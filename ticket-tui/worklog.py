"""Dated evidence from git and PRs; not an estimate of hours or completion."""

import subprocess
from collections import defaultdict

from core import TZ, now, parse_time
from sidequest.identity import GIT_AUTHOR, is_my_author
from sidequest import config
from sidequest.evidence import parse_commits
from sidequest.ticket_keys import mentions



def collect_worklog(tickets, root, run):
    if not GIT_AUTHOR:
        return {"generated_at": now().isoformat(), "entries": {}, "errors": ["Configure identity.git_author to show your local commits"]}
    flags = ["--since=90 days ago", "--author=" + GIT_AUTHOR, "--no-merges", "-n", "2000",
             "--format=%H%x1f%aI%x1f%s%x1e"]
    raw = run(["git", "-C", str(root), "log", "--all", *flags], timeout=15)
    all_commits = parse_commits(raw)
    entries, errors = {}, []
    for ticket in tickets:
        related = {c["sha"]: c for c in all_commits if ticket["key"] in mentions(c["subject"])}
        if ticket.get("worktree"):
            try:
                branch = run(["git", "-C", ticket["worktree"], "log", config.base_ref() + "..HEAD", *flags], timeout=15)
                related.update({c["sha"]: c for c in parse_commits(branch)})
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                errors.append(ticket["key"] + ": branch history unavailable")
        entries[ticket["key"]] = sorted(related.values(), key=lambda c: c["date"], reverse=True)
    return {"generated_at": now().isoformat(), "entries": entries, "errors": errors}


def daily_summary(ticket, commits):
    """Group evidence by Asuncion date and deduplicate commits across sources."""
    days, seen = defaultdict(list), set()
    events = list(commits)
    for pr in ticket.prs:
        for c in pr.get("commits", []):
            authors = c.get("authors") or []
            if isinstance(authors, dict):
                authors = authors.get("nodes", [])
            if not is_my_author(authors):
                continue
            events.append({"sha": c.get("oid", ""), "date": c.get("authoredDate"),
                           "subject": c.get("messageHeadline", "Commit"), "source": "PR"})
    for event in events:
        stamp = parse_time(event.get("date"))
        sha = event.get("sha")
        if not stamp or not sha or sha in seen:
            continue
        seen.add(sha)
        local = stamp.astimezone(TZ)
        days[local.date().isoformat()].append((local, f"{local:%H:%M} · {event['subject']} ({sha[:7]}; {event['source']})"))
    lines = []
    for day in sorted(days, reverse=True):
        items = sorted(days[day], key=lambda item: item[0], reverse=True)
        lines += [f"{parse_time(day):%d %b %Y} · {len(items)} recorded update" + ("s" if len(items) != 1 else "")]
        lines += ["  " + text for _, text in items]
        lines += [""]
    return lines or ["No dated work evidence loaded for this ticket."]
