"""Explicit ticket ordering; unknown activity never substitutes another source."""

import re

from core import parse_time
from activity import ticket_activity

SORT_MODES = ("Attention", "Last Jira update", "Last GitHub comment", "Last activity", "Last commit", "Priority", "Longest waiting", "Ticket")
DATE_SORTS = {"Last Jira update", "Last GitHub comment", "Last commit", "Last activity"}


def newest(values):
    stamps = [stamp for value in values if (stamp := parse_time(value))]
    return max(stamps).isoformat() if stamps else None


def activity_date(ticket, mode, worklog=None):
    if mode == "Last activity":
        return newest(e["at"] for e in ticket_activity(ticket))          # Jira + GitHub only
    if mode == "Last Jira update":
        return ticket.updated or None
    if mode == "Last GitHub comment":
        dates = []
        for pr in ticket.prs:
            dates += [c.get("createdAt") for c in pr.get("discussion", [])]
            # A bodyless approval is a review event, not a comment.
            dates += [c.get("submittedAt") for c in pr.get("reviews", []) if c.get("body")]
            for thread in pr.get("unresolved", []):
                dates += [c.get("created_at") for c in thread.get("comments", [])]
        return newest(dates)
    if mode == "Last commit":
        stamp = last_commit(ticket, worklog)
        return stamp.isoformat() if stamp else None
    return None


def last_commit(ticket, worklog=None):
    """Newest commit date for the ticket: your git commits on it, plus its PRs' commits."""
    dates = [c.get("date") for c in (worklog or {}).get("entries", {}).get(ticket.key, [])]
    dates += [commit.get("authoredDate") for pr in ticket.prs for commit in pr.get("commits", [])]
    stamps = [stamp for value in dates if (stamp := parse_time(value))]
    return max(stamps) if stamps else None


def ticket_number(ticket):
    match = re.fullmatch(r"(.*?)-(\d+)", ticket.key)
    return (match[1], int(match[2])) if match else (ticket.key, 0)


def ordered(tickets, mode, descending=True, worklog=None):
    if mode == "Ticket":
        return sorted(tickets, key=ticket_number, reverse=descending)

    def value(ticket):
        if mode in DATE_SORTS:
            stamp = parse_time(activity_date(ticket, mode, worklog))
            return stamp.timestamp() if stamp else None
        if mode == "Priority":
            return {"highest": 5, "critical": 5, "high": 4, "medium": 3, "low": 2, "lowest": 1}.get(ticket.priority.casefold())
        if mode == "Longest waiting":
            return ticket.wait_duration_seconds
        return ticket.score

    known = [(ticket, value(ticket)) for ticket in tickets]
    present = [(ticket, val) for ticket, val in known if val is not None]
    missing = [ticket for ticket, val in known if val is None]
    present.sort(key=lambda pair: (-pair[1] if descending else pair[1], ticket_number(pair[0])))
    result = [ticket for ticket, _ in present] + sorted(missing, key=ticket_number)
    if mode in ("Priority", "Attention"):
        # Ownership groups stay fixed even when the selected sort is reversed.
        result.sort(key=lambda ticket: {"Waiting": 1, "Done": 2}.get(ticket.lane, 0))
    return result
