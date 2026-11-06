#!/usr/bin/env python3
"""Read-only Jira transport. Search uses Jira's documented POST search endpoint."""
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
from sidequest import config, identity
from sidequest.access import CAUSES

SITE = config.get('jira', 'site').rstrip('/')
CLOUD_ID = config.get('jira', 'cloud_id')
BASES = ([SITE] if SITE else []) + (['https://api.atlassian.com/ex/jira/' + CLOUD_ID] if CLOUD_ID else [])
_base = [None]

STATUS_CAUSES = {301: 'not_found', 401: 'login', 403: 'denied', 404: 'not_found', 429: 'rate_limited'}


class JiraError(RuntimeError):
    def __init__(self, message, status=None, cause=None, note=None):
        super().__init__(message)
        self.note = note  # see sidequest.access.NOTES
        self.status = status  # HTTP status when the error came from a Jira response
        # Jira raises every error itself, so its cause is always known: never guessed from wording.
        self.cause = cause or STATUS_CAUSES.get(status) or ('server' if status and status >= 500 else 'unknown')
        if self.cause not in CAUSES:
            raise ValueError('unknown Jira error cause: ' + self.cause)

def _auth():
    email, token = identity.JIRA_EMAIL, os.environ.get('SIDEQUEST_JIRA_TOKEN')
    if not email or not token:
        raise JiraError('No Jira credentials: configure jira.email and set SIDEQUEST_JIRA_TOKEN in your terminal',
                        cause='credentials')
    return 'Basic ' + base64.b64encode((email + ':' + token).encode()).decode()

def jira(method, path, body=None):
    if method != 'GET' and not (method == 'POST' and path == '/rest/api/3/search/jql'):
        raise JiraError('Jira adapter is read-only')
    if not path.startswith('/rest/api/3/') or '..' in path or '\\' in path:
        raise JiraError('Unsupported Jira request path')
    if not BASES:
        raise JiraError('Configure jira.site before refreshing Jira')
    rejected = False
    for base in ([_base[0]] if _base[0] else BASES):
        request = urllib.request.Request(base + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Authorization': _auth(), 'Accept': 'application/json', 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.load(response)
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
            raise JiraError('Jira invalid response; previous data retained') from None
    raise JiraError('Jira HTTP 401; renew SIDEQUEST_JIRA_TOKEN', 401)

def workflow_dates(key, current_status, created=None, account_id=None, current_assignee=None):
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

    start, changes, assignments = 0, [], []
    while True:
        page = jira("GET", "/rest/api/3/issue/%s/changelog?startAt=%d&maxResults=100" % (key, start))
        values = page.get("values") if isinstance(page, dict) else None
        if not isinstance(values, list) or not isinstance(page.get("isLast"), bool):
            raise JiraError("invalid Jira changelog; retain the previous snapshot")
        for change in values:
            for item in change.get("items", []):
                if (item.get("fieldId") or item.get("field")) == "status":
                    stamp = timestamp(change.get("created"))
                    changes.append((stamp, item.get("toString"), stamp.isoformat()))
                elif account_id and (item.get("fieldId") or item.get("field")) == "assignee":
                    assignments.append((timestamp(change.get("created")), item.get("from"), item.get("to")))
        start += len(values)
        if page["isLast"]:
            break
        if not values:
            raise JiraError("incomplete Jira changelog; retain the previous snapshot")
    if changes:
        _, status, status_at = max(changes, key=lambda row: row[0])
        if status != current_status:
            raise JiraError("Jira status changed during collection; refresh again")
    else:
        status_at = timestamp(created).isoformat() if created else None
    first = min((at for at, _, to in assignments if to == account_id), default=None)
    # The first change's previous owner establishes who held the ticket at creation.
    initial_owner = min(assignments, key=lambda row: row[0])[1] if assignments else current_assignee
    if account_id and initial_owner == account_id and created:
        first = timestamp(created)
    return {"status_since": status_at, "first_assigned_at": first.isoformat() if first else None}


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
        raise JiraError('Expected a Jira key such as APP-123')
    fields = 'summary,status,assignee,priority,created,updated,description'
    issue = jira('GET', '/rest/api/3/issue/%s?fields=%s' % (key, fields))
    if isinstance(issue.get('key'), str) and issue['key'] != key:
        raise JiraError('Jira issue %s moved to %s; previous data retained' % (key, issue['key']), 301)
    if issue.get('key') != key or not isinstance(issue.get('fields'), dict):
        raise JiraError('Invalid Jira issue response; previous data retained')
    f = issue['fields']
    assignee = f.get('assignee') or {}
    account_id = account_id or identity.JIRA_ACCOUNT_ID
    result = {'key': key, 'summary': f.get('summary') or '', 'status': name(f.get('status')) or 'Unknown',
              'priority': name(f.get('priority')), 'assignee': name(assignee) or 'Unassigned',
              'assignee_ok': assignee.get('accountId') == account_id if account_id else None,
              'created': f.get('created'), 'updated': f.get('updated'), 'description': text_of(f.get('description'))}
    if include_activity:
        result.update(workflow_dates(key, result['status'], f.get('created'), account_id, assignee.get('accountId')))
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
