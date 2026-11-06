"""Local ticket state and explainable attention rules. No remote writes."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest.identity import TZ
from sidequest.evidence import parse_time
from sidequest.ticket_keys import KEY, pr_ticket, ticket_key  # noqa: F401
from workflow import ALIASES, REWORK


def now():
    return datetime.now(TZ)

def business_seconds(start, end):
    """Time inside Mon–Fri 09:00–17:00 in the configured zone; holidays are not excluded."""
    if not start or end <= start:
        return 0
    start, end = start.astimezone(TZ), end.astimezone(TZ)
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds = 0
    while day.date() <= end.date():
        if day.weekday() < 5:
            opening, closing = day.replace(hour=9), day.replace(hour=17)
            seconds += max(0, (min(end, closing) - max(start, opening)).total_seconds())
        day += timedelta(days=1)
    return seconds


def business_days(start, end):
    """Completed eight-hour business days."""
    return int(business_seconds(start, end) // (8 * 3600))


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS local (key TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sources (name TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, key TEXT, at TEXT, message TEXT);
        """)
        self.db.commit()

    def get(self, key):
        row = self.db.execute("SELECT data FROM local WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save(self, key, updates, message=None, clock=None):
        data = self.get(key)
        data.update(updates)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO local VALUES (?,?)", (key, json.dumps(data)))
            if message:
                self.db.execute("INSERT INTO events(key,at,message) VALUES (?,?,?)",
                                (key, (clock or now()).isoformat(), message))

    def source(self, name, data=None):
        if data is not None:
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO sources VALUES (?,?)", (name, json.dumps(data)))
        row = self.db.execute("SELECT data FROM sources WHERE name=?", (name,)).fetchone()
        return json.loads(row[0]) if row else {}

    def history(self, key):
        return self.db.execute("SELECT at,message FROM events WHERE key=? ORDER BY id DESC LIMIT 40",
                               (key,)).fetchall()

    def close(self):
        self.db.close()


@dataclass
class Ticket:
    key: str
    title: str = ""
    status: str = "Unknown"
    priority: str = ""
    assignee: str = "Unknown"
    assigned_me: bool | None = None
    prs: list = field(default_factory=list)
    updated: str = ""
    worktree: str = ""
    court: str = "unknown"
    action: str = "Clarify who has the next action"
    evidence: str = "No reliable ownership evidence"
    lane: str = "Clarify"
    score: int = 0
    age: int = 0
    reason: str = ""
    local: dict = field(default_factory=dict)
    jira_comments: list = field(default_factory=list)
    jira_comment_total: int | None = None
    jira_comments_checked_at: str = ""
    status_since: str = ""
    first_assigned_at: str = ""
    wait_since: str = ""
    wait_source: str = ""
    wait_seconds: float | None = None

    @property
    def wait_duration_seconds(self):
        return self.wait_seconds if self.wait_seconds is not None else self.age * 8 * 3600

    @property
    def wait_label(self):
        days, hours = divmod(int(self.wait_duration_seconds // 3600), 8)
        if days:
            return f"{days}d {hours}h" if hours else f"{days}d"
        return f"{hours}h" if hours else "<1h"



def tickets_from(jira, prs, fallback=None, worktrees=None, projects=()):
    result = {}
    # Fresh Jira is authoritative, including an empty list. Fallback is startup-only.
    issues = (jira.get("tickets", []) if jira else
              (fallback or {}).get("jira_assigned", []) + (fallback or {}).get("jira_code_review", []))
    for issue in issues:
        key = issue.get("key")
        if not key:
            continue
        result[key] = Ticket(key, issue.get("summary", ""), issue.get("status", "Unknown"),
                             issue.get("priority", ""), issue.get("assignee", "Unknown"),
                             issue.get("assignee_ok"), updated=issue.get("updated", ""))
        result[key].status_since = issue.get("status_since") or ""
        result[key].first_assigned_at = issue.get("first_assigned_at") or ""
        result[key].jira_comments = issue.get("jira_comments", [])
        result[key].jira_comment_total = issue.get("jira_comment_total")
        result[key].jira_comments_checked_at = issue.get("jira_comments_checked_at", "")
    pr_list = prs.get("open_prs", []) if prs else (fallback or {}).get("open_prs", [])
    known = {p.upper() for p in projects} | {key.rsplit("-", 1)[0].upper() for key in result}
    for pr in pr_list:
        key = pr_ticket(pr, known) or f"PR-{pr.get('number')}"
        ticket = result.setdefault(key, Ticket(key, pr.get("title", "")))
        ticket.prs.append(pr)
    for key, path in (worktrees or {}).items():
        # Do not resurrect completed tickets just because a worktree still exists.
        if key in result:
            result[key].worktree = path
    return list(result.values())


def infer(ticket):
    status = ticket.status.casefold()
    prs = ticket.prs
    if status in ("done", "closed", "cancelled", "canceled", "archived", "resolved"):
        return "done", "No action", "Jira reports a completed status"
    # Jira owns the handoff; old GitHub feedback stays visible without taking it back.
    review = status in ("ready for code review", "code review", "in code review", "in review")
    # One status map with the Flow view: "QA Failed" is rework, not QA still testing.
    normalised = " ".join(status.replace("_", " ").split())
    stage = ALIASES.get(normalised)
    if normalised in REWORK and ticket.assigned_me is True:
        return "me", "Address returned work", f"Jira status {ticket.status} returns this to implementation"
    if stage == 3 or (stage is None and ("qa" in status or "testing" in status)):
        if ticket.assigned_me is True:
            return "unknown", "Check whether QA returned work to you", "QA status and your assignment need clarification"
        return "them", "Waiting for QA result", f"Jira status: {ticket.status}; confirm the QA owner"
    if status in ("approved", "ready for production", "ready to deploy", "ready for stakeholder review", "in stakeholder review"):
        if ticket.assigned_me is False and ticket.assignee not in ("Unknown", "Unassigned", ""):
            return "them", "Awaiting merge/release handoff", f"Jira says {ticket.status} and assigns this to {ticket.assignee}; next ownership is inferred from the assignment"
        if ticket.assigned_me is True:
            return "me", "Confirm the merge/release handoff", f"Jira says {ticket.status} and assigns this to you"
        return "unknown", "Clarify the release or closure handoff", f"Jira says {ticket.status}; this does not establish the next owner"
    if review:
        if ticket.assigned_me is False and ticket.assignee not in ("Unknown", "Unassigned", ""):
            return "them", "Waiting for review", f"Jira hands review to {ticket.assignee} ({ticket.status})"
        if ticket.assigned_me is True:
            return "unknown", "Confirm the review handoff", "Jira says review but still assigns this to you"
        reviewers = sorted({r for p in prs for r in p.get("requested_reviewers", [])})
        if reviewers:
            return "them", "Waiting for review", "Requested reviewers (inferred): " + ", ".join(reviewers)
        return "unknown", "Clarify the review owner", "Jira says review; no owner is established"
    if ticket.assigned_me is False and ticket.assignee not in ("Unknown", "Unassigned", ""):
        return "them", "Waiting for Jira assignee", f"Jira assigns this to {ticket.assignee} ({ticket.status})"
    if any(p.get("review_decision") == "CHANGES_REQUESTED" for p in prs):
        return "me", "Address requested changes", "A PR review requests changes"
    if any(p.get("ci") == "failing" for p in prs):
        return "me", "Investigate failed checks", "A PR has failing CI"
    if any(p.get("unresolved_count", 0) for p in prs):
        return "me", "Triage unresolved review threads", "Unresolved threads may need a fix or a reply"
    if any(p.get("wip") for p in prs):
        return "me", "Finish draft work", "An authored PR is a draft"
    if prs and all(p.get("review_decision") == "APPROVED" for p in prs):
        return "unknown", "Check the next QA or merge handoff", "PRs are approved; approval alone does not identify the next owner"
    if prs:
        reviewers = sorted({r for p in prs for r in p.get("requested_reviewers", [])})
        if reviewers:
            return "them", "Waiting for review", "Requested reviewers: " + ", ".join(reviewers)
        return "me", "Arrange a reviewer", "Open PR with no requested reviewer"
    if ticket.assigned_me is True:
        return "me", "Continue implementation", f"Jira assigns this ticket to you ({ticket.status})"
    return "unknown", "Clarify who has the next action", "Missing assignment or handoff evidence"


SIGNAL_FIELDS = ("turn", "action", "status", "assignee", "PRs")
FLIP_BACK_SECONDS = 15 * 60


def signal_diff(before, after):
    """': status Unknown → In Dev; PRs [] → [[2040, "", false]]' — what reset the WAIT clock."""
    try:
        old, new = json.loads(before), json.loads(after)
        parts = [f"{name} {json.dumps(a) if name == 'PRs' else a} → {json.dumps(b) if name == 'PRs' else b}"
                 for name, a, b in zip(SIGNAL_FIELDS, old, new) if a != b]
    except (ValueError, TypeError):
        return ""
    return (": " + "; ".join(parts)) if parts else ""


def rank(ticket, store, clock=None, stale_days=2, escalate_days=5):
    clock = clock or now()
    court, action, evidence = infer(ticket)
    local = store.get(ticket.key)
    # Only observed workflow transitions reset this clock. updatedAt is NOT progress.
    signal = json.dumps([court, action, ticket.status, ticket.assignee,
                         sorted((p.get("number"), p.get("review_decision"), bool(p.get("wip")))
                                for p in ticket.prs)], sort_keys=True)
    changed = local.get("signal") != signal
    if changed and local.get("signal"):
        try:
            previous, current = json.loads(local["signal"]), json.loads(signal)
            # Renaming a suggested action must not erase the observation clock.
            if previous[0] == current[0] and previous[2:] == current[2:]:
                store.save(ticket.key, {"signal": signal})
                changed = False
        except (ValueError, TypeError, IndexError):
            pass
    if changed and local.get("signal") and signal == local.get("prior_signal"):
        # A flip and a flip back within minutes is the data wobbling (two PR loads disagreeing,
        # a second sidequest on the same database), not real progress: keep the original clock.
        flipped_at = parse_time(local.get("observed_since"))
        if flipped_at and (clock - flipped_at).total_seconds() < FLIP_BACK_SECONDS:
            store.save(ticket.key, {"signal": signal, "observed_since": local.get("prior_since"),
                                    "prior_signal": local["signal"], "prior_since": local.get("observed_since")},
                       "Flip back ignored, clock kept" + signal_diff(local["signal"], signal), clock)
            local = store.get(ticket.key)
            changed = False
    if changed:
        message = "First observed state" if not local.get("signal") else "Observed workflow change"
        if local.get("signal"):
            message += signal_diff(local["signal"], signal)
        store.save(ticket.key, {"signal": signal, "observed_since": clock.isoformat(),
                                "prior_signal": local.get("signal"), "prior_since": local.get("observed_since")},
                   message, clock)
        local = store.get(ticket.key)
    ticket.court = court
    ticket.action = action
    ticket.evidence = evidence
    ticket.local = local
    transition = parse_time(ticket.status_since)
    ticket.wait_since = ticket.status_since if transition and transition <= clock else local.get("observed_since", "")
    ticket.wait_source = "Jira status transition" if transition and transition <= clock else "First observation (Jira history unavailable)"
    first_assignment = parse_time(ticket.first_assigned_at)
    start = parse_time(ticket.wait_since) or clock
    if first_assignment and start < first_assignment <= clock:
        ticket.wait_since = ticket.first_assigned_at
        ticket.wait_source = "First Jira assignment to you"
    ticket.wait_seconds = business_seconds(parse_time(ticket.wait_since) or clock, clock)
    ticket.age = int(ticket.wait_seconds // (8 * 3600))
    waiting = ticket.court == "them"
    ticket.lane = ("Done" if court == "done" else "Needs me" if ticket.court == "me" else
                   "Waiting" if waiting else "Clarify")
    follow_up_due = waiting and ticket.age >= stale_days
    if follow_up_due:
        ticket.action = {"Waiting for review": "Follow up on review", "Waiting for QA result": "Follow up on QA"}.get(action, "Follow up with the next owner")
    base = 45 if follow_up_due else {"Needs me": 60, "Clarify": 25, "Waiting": 5, "Done": -100}[ticket.lane]
    priority = {"highest": 20, "critical": 20, "high": 12, "medium": 5, "low": 0, "lowest": 0}
    urgency = 20 if court == "me" and action != "Continue implementation" else 0
    ticket.score = base + priority.get(ticket.priority.casefold(), 0) + min(ticket.age, 10) * 2 + urgency
    reasons = [evidence]
    if ticket.age >= stale_days:
        label = ("since first assigned to you" if ticket.wait_source == "First Jira assignment to you" else
                 "in the current Jira status" if transition and transition <= clock else "since the observed workflow change")
        reasons.append(f"{ticket.wait_label} of business time {label}")
    if ticket.age >= escalate_days:
        reasons.append("long wait: consider escalating")
    ticket.reason = "; ".join(reasons)
    return ticket
