"""GitHub PRs and complete unresolved review threads, using the user's gh login."""
from __future__ import annotations
import json
from sidequest import config
from sidequest import services as tr
from sidequest.ticket_keys import pr_ticket
from sidequest.reviews import ci_summary
GITHUB_REPO = tr.GITHUB_REPO
GITHUB_OWNER, GITHUB_NAME = (GITHUB_REPO.split('/', 1) if '/' in GITHUB_REPO else ('', ''))

def gh_output(args):
    raw = tr.run_tool(args)
    if not raw:
        raise RuntimeError('GitHub returned no data; previous data retained')
    return raw


def list_open_prs(limit=100, *, include_activity=False):
    fields = ('number,title,url,isDraft,reviewDecision,statusCheckRollup,updatedAt,headRefName,'
              'headRefOid,createdAt,isCrossRepository,reviewRequests')
    raw = gh_output(['gh', 'pr', 'list', '--repo', GITHUB_REPO, '--author',
                       tr.configured_author(), '--state', 'open', '--json', fields, '--limit', str(limit)])
    try:
        rows = json.loads(raw)
    except ValueError:
        raise RuntimeError('Invalid GitHub PR response; previous data retained') from None
    if not isinstance(rows, list) or not all(isinstance(row, dict) and isinstance(row.get('number'), int) for row in rows):
        raise RuntimeError('Invalid GitHub PR inventory; previous data retained')
    if len(rows) >= limit:
        raise RuntimeError('GitHub PR limit reached; collection may be incomplete, previous data retained')
    return rows


def list_merged_prs(limit=300):
    """The repository's most recently merged PRs, every author (a worktree's branch may be merged through
    someone else's PR): number, branch, head commit and merge time (read-only)."""
    raw = gh_output(['gh', 'pr', 'list', '--repo', GITHUB_REPO, '--state', 'merged',
                     '--json', 'number,headRefName,headRefOid,mergedAt', '--limit', str(limit)])
    try:
        rows = json.loads(raw)
    except ValueError:
        raise RuntimeError('Invalid GitHub merged PR response; previous data retained') from None
    if not isinstance(rows, list) or not all(
            isinstance(row, dict) and isinstance(row.get('number'), int) and isinstance(row.get('headRefName'), str)
            and isinstance(row.get('headRefOid'), str) for row in rows):
        raise RuntimeError('Invalid GitHub merged PR list; previous data retained')
    return [{'number': row['number'], 'branch': row['headRefName'], 'head_oid': row['headRefOid'],
             'merged_at': row.get('mergedAt')} for row in rows]


def pr_state(number):
    """{state, head_oid} of one PR, asked now; None when GitHub cannot be asked or answers oddly."""
    try:
        data = json.loads(tr.run_tool(['gh', 'pr', 'view', str(number), '--repo', GITHUB_REPO, '--json',
                                       'state,headRefOid']) or '')
    except (RuntimeError, OSError, ValueError, SystemExit):
        return None
    if not isinstance(data, dict) or not isinstance(data.get('state'), str):
        return None
    return {'state': data['state'], 'head_oid': data.get('headRefOid') or ''}


def rest_pages(path):
    rows, page = [], 1
    while True:
        try:
            chunk = json.loads(gh_output(['gh', 'api', path + '?per_page=100&page=' + str(page)]))
        except ValueError:
            raise RuntimeError('Invalid GitHub activity response; previous data retained') from None
        if not isinstance(chunk, list) or not all(isinstance(row, dict) for row in chunk):
            raise RuntimeError('Invalid GitHub activity page; previous data retained')
        rows.extend(chunk)
        if len(chunk) < 100:
            return rows
        page += 1
        if page > 100:
            raise RuntimeError('GitHub activity limit reached; previous data retained')


def activity_for_pr(number):
    base = 'repos/' + GITHUB_REPO
    comments = rest_pages(base + '/issues/%d/comments' % number)
    reviews = rest_pages(base + '/pulls/%d/reviews' % number)
    commits = rest_pages(base + '/pulls/%d/commits' % number)
    if len(commits) >= 250:
        raise RuntimeError('GitHub commit API limit reached; previous data retained')
    return {
        'discussion': [{'author': {'login': (row.get('user') or {}).get('login')}, 'body': row.get('body'),
                        'createdAt': row.get('created_at'), 'updatedAt': row.get('updated_at')} for row in comments],
        'reviews': [{'author': {'login': (row.get('user') or {}).get('login')}, 'body': row.get('body'),
                     'state': row.get('state'), 'submittedAt': row.get('submitted_at')} for row in reviews],
        'commits': [{'oid': row.get('sha'), 'messageHeadline': ((row.get('commit') or {}).get('message') or '').split('\n', 1)[0],
                     'authoredDate': ((row.get('commit') or {}).get('author') or {}).get('date'),
                     'authors': [{'login': (row.get('author') or {}).get('login'),
                                  'name': ((row.get('commit') or {}).get('author') or {}).get('name')}]} for row in commits],
    }

def first_line(text: str, limit: int = 180) -> str:
    line = (text or "").strip().splitlines()[0] if text else ""
    line = " ".join(line.split())
    if len(line) > limit:
        return line[: limit - 1] + "…"
    return line


def unresolved_threads_for_pr(number: int, *, strict: bool = False) -> list[dict]:
    """Read all review-thread and reply pages, then reduce resolved threads."""
    fields = "databaseId author { login } body createdAt"
    def graph(query, variables):
        args = ["gh", "api", "graphql", "-f", "query=" + query]
        for key, value in variables.items():
            args += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
        try:
            result = json.loads(gh_output(args))
        except json.JSONDecodeError:
            raise SystemExit("Invalid GitHub review response; retain the previous snapshot")
        if result.get("errors") or not isinstance(result.get("data"), dict):
            raise SystemExit("GitHub review request failed; retain the previous snapshot")
        return result["data"]
    def next_cursor(connection, seen):
        info = connection.get("pageInfo") or {}
        if not isinstance(info.get('hasNextPage'), bool):
            raise RuntimeError('Missing GitHub pagination metadata; previous data retained')
        if not info.get("hasNextPage"):
            return None
        cursor = info.get("endCursor")
        if not cursor or cursor in seen:
            raise SystemExit("Incomplete GitHub review pagination; retain the previous snapshot")
        seen.add(cursor)
        return cursor
    cursor, seen, out = None, set(), []
    while True:
        query = """query($owner:String!, $name:String!, $number:Int!, $cursor:String) {
          repository(owner:$owner,name:$name) { pullRequest(number:$number) {
            reviewThreads(first:50,after:$cursor) {
              pageInfo { hasNextPage endCursor }
              nodes { id isResolved path line comments(first:100) {
                pageInfo { hasNextPage endCursor } nodes { FIELDS }
              } }
            }
          } }
        }""".replace("FIELDS", fields)
        variables = {"owner": GITHUB_OWNER, "name": GITHUB_NAME, "number": number}
        if cursor:
            variables["cursor"] = cursor
        data = graph(query, variables)
        pr = (data.get("repository") or {}).get("pullRequest")
        if not isinstance(pr, dict):
            raise SystemExit("GitHub PR unavailable; retain the previous snapshot")
        connection = pr.get("reviewThreads") or {}
        if not isinstance(connection.get("nodes"), list):
            raise SystemExit("Invalid review threads; retain the previous snapshot")
        for node in connection["nodes"]:
            if node.get("isResolved"):
                continue
            comments_connection = node.get("comments") or {}
            raw = list(comments_connection.get("nodes") or [])
            reply_seen = set()
            reply_cursor = next_cursor(comments_connection, reply_seen)
            while reply_cursor:
                query = """query($id:ID!, $cursor:String) { node(id:$id) {
                  ... on PullRequestReviewThread { comments(first:100,after:$cursor) {
                    pageInfo { hasNextPage endCursor } nodes { FIELDS }
                  } }
                } }""".replace("FIELDS", fields)
                more = (graph(query, {"id": node["id"], "cursor": reply_cursor}).get("node") or {}).get("comments") or {}
                if not isinstance(more.get("nodes"), list):
                    raise SystemExit("Invalid review replies; retain the previous snapshot")
                raw.extend(more["nodes"])
                reply_cursor = next_cursor(more, reply_seen)
            comments = [{"database_id": c.get("databaseId"), "author": (c.get("author") or {}).get("login") or "?",
                         "summary": first_line(c.get("body") or ""), "created_at": c.get("createdAt"),
                         **({"body": c.get("body") or ""} if strict else {})} for c in raw]
            first = comments[0] if comments else {}
            out.append({"thread_id": node.get("id"), "path": node.get("path"), "line": node.get("line"),
                        "author": first.get("author") or "?", "summary": first.get("summary") or "",
                        "comment_database_id": first.get("database_id"), "comments": comments})
        cursor = next_cursor(connection, seen)
        if not cursor:
            return out


def reviewers_from(pr: dict) -> list[str]:
    out: list[str] = []
    for req in pr.get("reviewRequests") or []:
        if not isinstance(req, dict):
            continue
        login = req.get("login") or req.get("slug")
        if login:
            out.append(login)
    return out


def enrich_pr(pr: dict, *, include_threads: bool, include_activity: bool = False) -> dict:
    number = pr.get("number")
    title = pr.get("title") or ""
    threads = unresolved_threads_for_pr(number, strict=include_activity) if include_threads and number else []
    result = {
        "number": number,
        "title": title,
        "url": pr.get("url"),
        "branch": pr.get("headRefName"),
        "head_oid": pr.get("headRefOid"), "created_at": pr.get("createdAt"),
        "is_cross_repository": pr.get("isCrossRepository", False),
        "wip": title.startswith("[WIP]") or bool(pr.get("isDraft")),
        "review_decision": pr.get("reviewDecision") or "",
        "ci": ci_summary(pr.get("statusCheckRollup")),
        "requested_reviewers": reviewers_from(pr),
        "ticket": pr_ticket({"title": title, "branch": pr.get("headRefName")}, config.get("jira", "projects", [])),
        "updated_at": pr.get("updatedAt"),
        "unresolved_count": len(threads),
        "unresolved": threads if include_threads else [],
    }
    if include_activity:
        result.update(activity_for_pr(number))
    return result
