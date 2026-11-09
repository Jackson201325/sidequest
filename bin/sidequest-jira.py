#!/usr/bin/env python3
"""Jira transport. Read-only, except the opt-in start move (jira.start_status) through the issue
transitions endpoint. Search uses Jira's documented POST search endpoint."""
import base64
import http.client
import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from sidequest import config, credentials, identity
from sidequest.access import CAUSES

SITE = config.get('jira', 'site').rstrip('/')
CLOUD_ID = config.get('jira', 'cloud_id')
BASES = ([SITE] if SITE else []) + (['https://api.atlassian.com/ex/jira/' + CLOUD_ID] if CLOUD_ID else [])
_base = [None]

STATUS_CAUSES = {301: 'not_found', 401: 'login', 403: 'denied', 404: 'not_found', 429: 'rate_limited'}


class JiraError(RuntimeError):
    service = 'Jira'

    def __init__(self, message, status=None, cause=None, note=None, permanent=False):
        super().__init__(message)
        self.note = note  # see sidequest.access.NOTES
        self.permanent = permanent  # retrying cannot help (bad input, configuration or a moved issue)
        self.status = status  # HTTP status when the error came from a Jira response
        # Jira raises every error itself, so its cause is always known: never guessed from wording.
        self.cause = cause or STATUS_CAUSES.get(status) or ('server' if status and status >= 500 else 'unknown')
        if self.cause not in CAUSES:
            raise ValueError('unknown Jira error cause: ' + self.cause)

def _auth():
    email, token = identity.JIRA_EMAIL, credentials.secret('jira')
    if not email or not token:
        raise JiraError('No Jira credentials: configure jira.email and credentials.jira (or set SIDEQUEST_JIRA_TOKEN)',
                        cause='credentials')
    return 'Basic ' + base64.b64encode((email + ':' + token).encode()).decode()

TRANSITION_PATH = re.compile(r'/rest/api/3/issue/[A-Z][A-Z0-9_]*-\d+/transitions')


def _write_allowed(method, path):
    """The only write: moving an issue through its transitions, and only once a start status is set."""
    return method == 'POST' and bool(TRANSITION_PATH.fullmatch(path)) and bool(config.get('jira', 'start_status'))


def jira(method, path, body=None):
    if method != 'GET' and not (method == 'POST' and path == '/rest/api/3/search/jql') and not _write_allowed(method, path):
        raise JiraError('Jira adapter is read-only', permanent=True)
    if not path.startswith('/rest/api/3/') or '..' in path or '\\' in path:
        raise JiraError('Unsupported Jira request path', permanent=True)
    if not BASES:
        raise JiraError('Configure jira.site before refreshing Jira', permanent=True)
    rejected = False
    for base in ([_base[0]] if _base[0] else BASES):
        request = urllib.request.Request(base + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'})
        # urllib repeats ordinary headers on every redirect, to any host; this one goes to `base` only.
        request.add_unredirected_header('Authorization', _auth())
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read()
            # A transition answers 204 with no body.
            data = json.loads(raw) if raw.strip() or method == 'GET' else {}
            if not isinstance(data, dict):
                raise JiraError('Invalid Jira response; previous data retained')
            _base[0] = base
            return data
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and not _base[0]:
                rejected = True
                continue
            # After the site refused the token, keep the gateway's answer and say both: a scoped
            # token only works on the gateway, but an expired one fails there too.
            raise JiraError('Jira HTTP %d; previous data retained' % exc.code, exc.code,
                            note='site_refused_token' if rejected else None) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            # URLError wraps the real error in .reason; errors while reading the body arrive bare.
            inner = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            cause = ('tls' if isinstance(inner, ssl.SSLError) else 'dns' if isinstance(inner, socket.gaierror)
                     else 'timeout' if isinstance(inner, (TimeoutError, socket.timeout)) else 'network')
            raise JiraError('Jira ' + {'tls': 'TLS failure', 'dns': 'DNS lookup failed', 'timeout': 'request timed out'}
                            .get(cause, 'network failure') + '; previous data retained', cause=cause,
                            note='site_refused_token' if rejected else None) from None
        except ValueError:
            raise JiraError('Jira invalid response; previous data retained',
                            note='site_refused_token' if rejected else None) from None
    raise JiraError('Jira HTTP 401; renew SIDEQUEST_JIRA_TOKEN', 401)

def workflow_dates(key, current_status, created=None, account_id=None, current_assignee=None, status_id=None):
    """Status entry and first personal assignment, from one complete changelog."""
    def timestamp(value):
        try:
            value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value.replace("Z", "+00:00"))
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo is None:
                raise ValueError("missing timezone")
            return stamp
        except (ValueError, TypeError, AttributeError):
            raise JiraError("invalid Jira status timestamp; retain the previous snapshot")

    start, changes, assignments, events = 0, [], [], []
    while True:
        page = jira("GET", "/rest/api/3/issue/%s/changelog?startAt=%d&maxResults=100" % (key, start))
        values = page.get("values") if isinstance(page, dict) else None
        if not isinstance(values, list) or not isinstance(page.get("isLast"), bool):
            raise JiraError("invalid Jira changelog; retain the previous snapshot")
        for change in values:
            for item in change.get("items", []):
                name = item.get("fieldId") or item.get("field")
                if name in ("status", "assignee"):
                    events.append({"at": timestamp(change.get("created")).isoformat(), "field": name,
                                   "from": item.get("fromString"), "to": item.get("toString"),
                                   "author": (change.get("author") or {}).get("displayName", "")})
                if name == "status":
                    stamp = timestamp(change.get("created"))
                    changes.append((stamp, (item.get("to"), item.get("toString")), stamp.isoformat()))
                elif account_id and name == "assignee":
                    assignments.append((timestamp(change.get("created")), item.get("from"), item.get("to")))
        start += len(values)
        if page["isLast"]:
            break
        if not values:
            raise JiraError("incomplete Jira changelog; retain the previous snapshot")
    if changes:
        # The changelog is chronological, so the last of simultaneous transitions is the newest.
        newest = max(row[0] for row in changes)
        _, (to_id, to_name), status_at = [row for row in changes if row[0] == newest][-1]
        # A rename keeps the id; an id migration keeps the name. Only both differing means the
        # status changed during collection, which the next refresh resolves.
        same = ((to_id and status_id and str(to_id) == str(status_id))
                or (to_name or '').casefold() == (current_status or '').casefold())
        if not same:
            raise JiraError("Jira status changed during collection; refresh again")
    else:
        status_at = timestamp(created).isoformat() if created else None
    first = min((at for at, _, to in assignments if to == account_id), default=None)
    # The first change's previous owner establishes who held the ticket at creation.
    initial_owner = min(assignments, key=lambda row: row[0])[1] if assignments else current_assignee
    if account_id and initial_owner == account_id and created:
        first = timestamp(created)
    return {"status_since": status_at, "first_assigned_at": first.isoformat() if first else None,
            "jira_changes": events}


def _names(setting):
    return [part.strip() for part in config.get('jira', setting).split(',') if part.strip()]


def start_ticket(key, yes=False, dry_run=False):
    """Move KEY to jira.start_status: (exit code, one-line result).

    jira.start_from statuses move without asking; jira.start_ask statuses need yes; any other
    status (later work such as review or QA) is left alone. The message starts with MOVED, ALREADY,
    ASK, SKIPPED or WOULD MOVE (exit 0); 1 means moving is off, 3 that no transition reaches it.
    """
    target = config.get('jira', 'start_status')
    if not target:
        return 1, 'Moving tickets is off; set SIDEQUEST_JIRA_START_STATUS (jira.start_status) to enable it'
    issue = jira('GET', '/rest/api/3/issue/%s?fields=status' % key)
    current = (((issue.get('fields') or {}).get('status')) or {}).get('name') or ''
    fold = current.casefold()
    if fold == target.casefold():
        return 0, 'ALREADY %s is %s' % (key, current)
    if fold in [name.casefold() for name in _names('start_ask')]:
        if not yes:
            return 0, 'ASK %s is in %s; confirm before moving it to %s (--yes)' % (key, current, target)
    elif fold not in [name.casefold() for name in _names('start_from')]:
        return 0, 'SKIPPED %s is in %s; not moved' % (key, current)
    options = jira('GET', '/rest/api/3/issue/%s/transitions' % key).get('transitions') or []
    match = [t for t in options if ((t.get('to') or {}).get('name') or '').casefold() == target.casefold()
             or (t.get('name') or '').casefold() == target.casefold()]
    if not match:
        available = ', '.join(sorted({(t.get('to') or {}).get('name') or '?' for t in options})) or 'none'
        return 3, "%s: can't move from %s to %s. Available: %s" % (key, current, target, available)
    destination = (match[0].get('to') or {}).get('name') or target
    if dry_run:
        return 0, 'WOULD MOVE %s %s → %s' % (key, current, destination)
    jira('POST', '/rest/api/3/issue/%s/transitions' % key, {'transition': {'id': str(match[0]['id'])}})
    return 0, 'MOVED %s %s → %s' % (key, current, destination)


def download_attachments(key, folder):
    """Save each attachment of KEY into folder: [{filename, path, size, mime}] or an error per file."""
    issue = jira('GET', '/rest/api/3/issue/%s?fields=attachment' % key)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rows, used = [], set()
    for item in (issue.get('fields') or {}).get('attachment') or []:
        base = re.sub(r'[^\w.\- ]', '_', os.path.basename(item.get('filename') or 'attachment')).strip() or 'attachment'
        if base.startswith('.'):
            base = '_' + base
        stem, ext = os.path.splitext(base)
        filename, number = base, 1
        while filename.lower() in used:  # Jira allows two attachments with one name
            number += 1
            filename = '%s (%d)%s' % (stem, number, ext)
        used.add(filename.lower())
        path = folder / filename
        row = {'filename': filename, 'path': str(path), 'size': item.get('size'), 'mime': item.get('mimeType')}
        if not re.fullmatch(r'\d+', str(item.get('id') or '')):
            rows.append(dict(row, error='invalid attachment id'))
            continue
        error = None
        for base_url in ([_base[0]] if _base[0] else BASES):
            request = urllib.request.Request(base_url + '/rest/api/3/attachment/content/%s' % item['id'])
            # Jira answers with a redirect to its media host, which must not receive the token.
            request.add_unredirected_header('Authorization', _auth())
            try:
                with urllib.request.urlopen(request, timeout=60) as response, open(str(path) + '.part', 'wb') as out:
                    while True:
                        chunk = response.read(1 << 16)
                        if not chunk:
                            break
                        out.write(chunk)
                os.replace(str(path) + '.part', path)
                _base[0], error = base_url, None
                break
            except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                error = 'download failed: %s' % (getattr(exc, 'code', None) or exc.__class__.__name__)
        rows.append(dict(row, error=error) if error else row)
    return rows


def status_since(key, current_status, created=None):
    """Compatibility entry point for callers needing only the status date."""
    return workflow_dates(key, current_status, created)["status_since"]


def search(jql, fields, max_results=50):
    issues, seen, token = [], set(), None
    while max_results is None or len(issues) < max_results:
        size = 100 if max_results is None else min(100, max_results - len(issues))
        body = {"jql": jql, "fields": fields, "maxResults": size}
        if token:
            body["nextPageToken"] = token
        result = jira("POST", "/rest/api/3/search/jql", body)
        if not isinstance(result, dict) or not isinstance(result.get("issues"), list):
            raise JiraError("invalid Jira search response; retain the previous snapshot")
        issues.extend(result["issues"])
        token = result.get("nextPageToken")
        if result.get("isLast") is True or (not token and result.get("isLast") is not False):
            return issues if max_results is None else issues[:max_results]
        if not token or token in seen:
            raise JiraError("incomplete Jira pagination; retain the previous snapshot")
        seen.add(token)
    return issues[:max_results]


def adf(node, depth=0):
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf(n, depth) for n in node)
    t, kids, attrs = node.get("type"), node.get("content") or [], node.get("attrs") or {}
    inner = lambda: "".join(adf(k, depth) for k in kids)
    if t == "text":
        s = node.get("text", "")
        for m in node.get("marks") or []:
            mt = m.get("type")
            if mt == "strong":
                s = "**%s**" % s
            elif mt == "em":
                s = "_%s_" % s
            elif mt == "code":
                s = "`%s`" % s
            elif mt == "link":
                href = (m.get("attrs") or {}).get("href", "")
                if href and href != s:
                    s = "[%s](%s)" % (s, href)
        return s
    if t == "hardBreak":
        return "\n"
    if t == "paragraph":
        return inner() + "\n\n"
    if t == "heading":
        return "#" * int(attrs.get("level", 2)) + " " + inner() + "\n\n"
    if t in ("bulletList", "orderedList"):
        out = []
        for i, item in enumerate(kids, 1):
            mark = "%d." % i if t == "orderedList" else "-"
            body = adf(item.get("content") or [], depth + 1).strip()
            body = body.replace("\n\n", "\n").replace("\n", "\n" + "  " * (depth + 1))
            out.append("  " * depth + mark + " " + body)
        return "\n".join(out) + ("\n\n" if depth == 0 else "\n")
    if t == "taskList":
        return "".join("- [%s] %s\n" % ("x" if (k.get("attrs") or {}).get("state") == "DONE" else " ",
                                          adf(k.get("content") or [], depth).strip()) for k in kids) + "\n"
    if t == "codeBlock":
        return "```%s\n%s\n```\n\n" % (attrs.get("language") or "", inner())
    if t == "blockquote":
        return "".join("> " + l + "\n" for l in inner().strip().splitlines()) + "\n"
    if t == "rule":
        return "---\n\n"
    if t == "mention":
        return "@" + (attrs.get("text") or "").lstrip("@")
    if t in ("inlineCard", "blockCard", "embedCard"):
        return attrs.get("url", "")
    if t == "emoji":
        return attrs.get("text") or attrs.get("shortName", "")
    if t == "status":
        return "[%s]" % attrs.get("text", "")
    if t == "date":
        return attrs.get("timestamp", "")
    if t in ("mediaSingle", "mediaGroup", "media", "mediaInline"):
        return "(attachment)\n" if t != "media" else ""
    if t == "table":
        rows = []
        for r in kids:
            cells = [adf(c.get("content") or [], depth).strip().replace("\n", " ") for c in r.get("content") or []]
            rows.append("| " + " | ".join(cells) + " |")
        if rows:
            rows.insert(1, "|" + "---|" * rows[0].count(" | ") + "---|")
        return "\n".join(rows) + "\n\n"
    if t == "panel":
        return "> **%s:** %s\n\n" % (attrs.get("panelType", "note"), inner().strip())
    if t == "expand":
        return "**%s**\n%s" % (attrs.get("title", ""), inner())
    return inner()


def text_of(v):
    if isinstance(v, dict) and v.get("type") == "doc":
        return re.sub(r"\n{3,}", "\n\n", adf(v)).strip()
    return (v or "").strip() if isinstance(v, str) else ""


def name(v):
    if isinstance(v, list):
        return ", ".join(filter(None, (name(x) for x in v)))
    if isinstance(v, dict):
        return v.get("displayName") or v.get("name") or v.get("value") or ""
    return "" if v is None else str(v)


def fetch_one(key, include_activity=False, account_id=None):
    if not re.fullmatch(r'[A-Z][A-Z0-9_]*-\d+', key):
        raise JiraError('Expected a Jira key such as APP-123', permanent=True)
    fields = 'summary,status,assignee,priority,issuetype,created,updated,description'
    issue = jira('GET', '/rest/api/3/issue/%s?fields=%s' % (key, fields))
    if isinstance(issue.get('key'), str) and issue['key'] != key:
        new = issue['key'] if re.fullmatch(r'[A-Z][A-Z0-9_]*-\d+', issue['key']) else 'another key'
        raise JiraError('Jira issue %s moved to %s; previous data retained' % (key, new), 301, permanent=True)
    if issue.get('key') != key or not isinstance(issue.get('fields'), dict):
        raise JiraError('Invalid Jira issue response; previous data retained')
    f = issue['fields']
    assignee = f.get('assignee') or {}
    account_id = account_id or identity.JIRA_ACCOUNT_ID
    result = {'key': key, 'summary': f.get('summary') or '', 'status': name(f.get('status')) or 'Unknown',
              'priority': name(f.get('priority')), 'issue_type': name(f.get('issuetype')),
              'assignee': name(assignee) or 'Unassigned',
              'assignee_ok': assignee.get('accountId') == account_id if account_id else None,
              'created': f.get('created'), 'updated': f.get('updated'), 'description': text_of(f.get('description'))}
    if include_activity:
        result.update(workflow_dates(key, result['status'], f.get('created'), account_id, assignee.get('accountId'),
                                     (f.get('status') or {}).get('id')))
        comments, start, total = [], 0, None
        while total is None or start < total:
            data = jira('GET', '/rest/api/3/issue/%s/comment?orderBy=created&maxResults=100&startAt=%d' % (key, start))
            rows, total = data.get('comments'), data.get('total')
            if not isinstance(rows, list) or not isinstance(total, int) or total < 0:
                raise JiraError('Invalid Jira comments response; previous data retained')
            comments.extend({'author': name(c.get('author')) or 'Unknown', 'update_author': name(c.get('updateAuthor')),
                             'body': text_of(c.get('body')), 'created_at': c.get('created'),
                             'updated_at': c.get('updated')} for c in rows)
            start += len(rows)
            if not rows and start < total:
                raise JiraError('Incomplete Jira comments; previous data retained')
        result.update(jira_comments=comments, jira_comment_total=total,
                      jira_comments_checked_at=datetime.now(identity.TZ).isoformat())
    return result
