"""Read-only Heroku lookup and explicit environment-only QA credentials."""
import json
import os
import re
import urllib.parse
from sidequest import config, credentials
from sidequest.access import AccessFailure
from sidequest.services import run_tool
from sidequest.environments import fetch_environments
from sidequest.ticket_keys import branch_ticket, ticket_key

BRANCH_SCAN_LIMIT = 500
REVIEW_HOST = re.compile(r"^[a-z0-9][a-z0-9-]*\.herokuapp\.com$")


class ReviewAppError(RuntimeError):
    pass


def _run(args, timeout=45):
    args = list(args)
    if args[:2] == ["gh", "pr"] and config.get("github", "repository"):
        args += ["--repo", config.get("github", "repository")]
    try:
        return run_tool(args, timeout)
    except AccessFailure as exc:
        raise ReviewAppError(exc.terminal_text) from None


def find_pr(key=None, number=None, run=_run):
    """The open PR for a ticket key, a PR number, or the current branch: {number, url, title, head}."""
    fields = "number,url,title,headRefName,state"
    if number:
        pr = json.loads(run(["gh", "pr", "view", str(number), "--json", fields]))
    elif key:
        key = key.upper()
        known = set(config.get("jira", "projects", [])) | {key.rsplit("-", 1)[0]}

        def mine(p):
            return key in (ticket_key(p.get("title") or "", known), branch_ticket(p.get("headRefName") or "", known))
        # Search finds title matches of any age; GitHub search ignores branch names, so only then list branches.
        prs = [p for p in json.loads(run(["gh", "pr", "list", "--state", "open", "--search", key,
                                          "--json", fields])) if mine(p)]
        if not prs:
            listed = json.loads(run(["gh", "pr", "list", "--state", "open", "--limit", str(BRANCH_SCAN_LIMIT),
                                     "--json", fields]))
            prs = [p for p in listed if mine(p)]
            if not prs and len(listed) >= BRANCH_SCAN_LIMIT:
                raise ReviewAppError("no open PR for %s in its title or the newest %d branches: pass --pr N"
                                     % (key, BRANCH_SCAN_LIMIT))
        if not prs:
            raise ReviewAppError("no open PR for %s: open it first (sidequest-ship)" % key)
        if len(prs) > 1:
            raise ReviewAppError("several open PRs for %s (%s): pass --pr N" % (key, ", ".join("#%d" % p["number"] for p in prs)))
        pr = prs[0]
    else:
        pr = json.loads(run(["gh", "pr", "view", "--json", fields]))
    return {"number": pr["number"], "url": pr.get("url", ""), "title": pr.get("title", ""),
            "head": pr.get("headRefName", ""), "state": pr.get("state", "")}


def review_app(number, run=_run, fetch=None):
    """Heroku's view of the PR's review app: {status, phase, app, url, warning}."""
    if fetch is None:
        fetch = fetch_environments
    try:
        data = fetch([number], run, config.get('heroku', 'pipeline'))
    except RuntimeError as exc:
        raise ReviewAppError(str(exc)) from None
    entry = dict(data.get("entries", {}).get(str(number)) or {"status": "Not provisioned"})
    entry["pr"] = number
    return entry


def review_host(url):
    """The hostname if the URL is a Heroku review-app address, otherwise None."""
    parsed = urllib.parse.urlparse(url or "")
    host = (parsed.hostname or "").lower()
    return host if parsed.scheme == "https" and REVIEW_HOST.match(host) else None


def login(run=None):
    """Review-app credentials must be supplied explicitly; no shared account defaults."""
    email, password = credentials.login('review')
    if email and password:
        return email, password
    raise ReviewAppError('Set credentials.review (or SIDEQUEST_REVIEW_EMAIL and SIDEQUEST_REVIEW_PASSWORD) for the review-app QA login')
