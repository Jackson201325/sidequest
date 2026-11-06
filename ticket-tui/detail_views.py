"""Detail tabs as styled rows: what each tab says about a ticket, and how each row is styled.

Rows carry a style name ("plain", "heading", "current", "day", "event", "dim"); the dashboard
only wraps and paints them, so it never guesses a style from the text.
"""
import textwrap
from dataclasses import dataclass
from datetime import datetime

from core import now, parse_time
from activity import ticket_activity
from layout import EVENT_INDENT, relative, timeline_rows
from plan_document import document_views
from sorting import last_commit
from workflow import next_owner, ownership, stage_context, workflow_path, workflow_strip
from worklog import daily_summary

HEADING_MARK = "\x00"  # plan_document's heading marker; never shown


@dataclass(frozen=True)
class Row:
    text: str
    style: str = "plain"


def readable_date(value):
    stamp = parse_time(value)
    if not stamp:
        return "Not recorded"
    local = stamp.astimezone(now().tzinfo)
    days = (now().date() - local.date()).days
    day = "Today" if days == 0 else "Yesterday" if days == 1 else local.strftime("%d %b %Y")
    return f"{day}, {local:%H:%M}"


def source_age(value):
    stamp = parse_time(value)
    if not stamp:
        return "not loaded"
    minutes = max(0, int((now() - stamp).total_seconds() // 60))
    return "just now" if minutes < 1 else f"{minutes}m ago" if minutes < 60 else f"{minutes // 60}h ago" if minutes < 1440 else f"{minutes // 1440}d ago"


def plain(*texts):
    return [Row(text) for text in texts]


def wrap(rows, width):
    """Wrap rows to `width`. Continuations keep the indent; an event's continuation lines up
    under its title and is dimmed like its snippet."""
    result = []
    for row in rows:
        indent = " " * (len(row.text) - len(row.text.lstrip(" ")))
        if row.style == "event":
            indent = " " * EVENT_INDENT
        pieces = textwrap.wrap(row.text, max(10, width), subsequent_indent=indent) or [""]
        follow = "dim" if row.style in ("event", "dim") else "plain"
        result += [Row(pieces[0], row.style)] + [Row(piece, follow) for piece in pieces[1:]]
    return result


class DetailViews:
    def __init__(self, evidence, stale_days=2):
        self.evidence, self.stale_days = evidence, stale_days
        self.plan_cache = {}

    def rows(self, tab, ticket, plans, loading=False, standup=None):
        """Every row of a detail tab, refresh errors first. `standup` returns the Standup tab's lines."""
        errors = self.evidence.refresh_errors
        rows = plain("REFRESH ERROR (cached data)", *errors, "") if errors else []
        if tab == "Standup":
            return rows + self.standup_rows(standup() if standup else [])
        if not ticket:
            return rows + plain("No tickets in this view.", "Press r to refresh, / to search, or 1 for All.")
        if tab in ("Plan", "Updates"):
            return rows + self.plan_rows(ticket, tab, plans)
        builder = {"Activity": self.activity_rows, "Workflow": self.flow_rows,
                   "Work log": self.worklog_rows}.get(tab, lambda t: self.overview_rows(t, loading))
        return rows + builder(ticket)

    def environment(self, ticket, loading):
        """Heroku review-app status for a ticket's PRs, with how fresh it is."""
        entries = self.evidence.environments.get("entries", {})
        checked = [entries[str(p["number"])] for p in ticket.prs if str(p["number"]) in entries]
        if checked:
            stale = self.evidence.environment_error or any(
                not parse_time(entry.get("checked_at")) or
                (now() - parse_time(entry.get("checked_at"))).total_seconds() > 300 for entry in checked)
            suffix = " (refreshing)" if loading else " (cached)" if stale else ""
            return " / ".join(dict.fromkeys(entry.get("status", "Unknown") for entry in checked)) + suffix
        return ("Loading" if loading else "Unavailable" if self.evidence.environment_error else
                "Not checked" if ticket.prs else "No linked PR")

    def current_step(self, ticket):
        strip = [Row(text, "current" if stage_context(ticket)["index"] is not None else "plain")
                 for text in workflow_strip(ticket)]
        return strip + plain("Turn: " + next_owner(ticket) + " (" + ownership(ticket)[1] + ")")

    def overview_rows(self, ticket, loading):
        stage, worklog = stage_context(ticket), self.evidence.worklog
        rows = [Row("STATUS", "heading"), *self.current_step(ticket),
                *plain("To move forward: " + stage["next"],
                       f"Priority: {ticket.priority or 'unknown'} · Jira status: {ticket.status}", ""),
                Row("DATES", "heading"),
                *plain(f"Last commit: {readable_date(last_commit(ticket, worklog))}",
                       f"Last Jira update: {readable_date(ticket.updated)}",
                       f"First assigned to you: {readable_date(ticket.first_assigned_at)}",
                       f"Jira status since: {readable_date(ticket.status_since)}",
                       f"Clock source: {ticket.wait_source}",
                       f"Since: {readable_date(ticket.wait_since)} · {ticket.wait_label} business time"
                       f" (follow up after {self.stale_days} business days)", ""),
                Row("HEROKU ENVIRONMENT", "heading"), Row(self.environment(ticket, loading))]
        for pr in ticket.prs:
            env = self.evidence.environments.get("entries", {}).get(str(pr["number"]), {})
            if env:
                rows += plain(f"PR #{pr['number']}: {env.get('status', 'Unknown')} · {source_age(env.get('checked_at'))}",
                              env.get("app", ""), env.get("url", ""))
                if env.get("warning"):
                    rows += plain(env["warning"])
        if self.evidence.environment_error:
            rows += plain("Last refresh failed; cached results may be stale.", self.evidence.environment_error)
        rows += plain("Web up means a web dyno is up; HTTP readiness is not checked.", "")
        for pr in ticket.prs:
            decision = (pr.get("review_decision") or "Awaiting review").replace("_", " ").lower()
            rows += [Row("GITHUB PR", "heading"), *plain(
                f"PR #{pr['number']}: {pr.get('title') or ticket.title}",
                f"{decision} · CI: {pr.get('ci', 'unknown')}",
                "Reviewers: " + (", ".join(pr.get("requested_reviewers", [])) or "none requested") +
                f" · {pr.get('unresolved_count', 0)} unresolved threads",
                pr.get("url") or "No PR URL in this snapshot",
                f"Branch: {pr.get('branch') or 'unknown'}" + (" · Draft" if pr.get("wip") else ""),
                f"Source activity: {readable_date(pr.get('updated_at'))}")]
        return rows + [Row(""), Row("WORKSPACE", "heading"),
                       *plain("Worktree: " + (ticket.worktree or "not found"),
                              "w / gw: open the existing tmux ticket window")]

    def flow_rows(self, ticket):
        stage = stage_context(ticket)
        path = [Row(text, "current" if i == stage["index"] else "plain")
                for i, text in enumerate(workflow_path(ticket))]
        return [*self.current_step(ticket), *plain("Your next action: " + ticket.action, ""),
                Row("WORKFLOW", "heading"), *path,
                *plain("", "To move forward: " + stage["next"], f"Jira status: {ticket.status}",
                       "", "Clock source: " + ticket.wait_source,
                       "Since: " + readable_date(ticket.wait_since),
                       "First assigned to you: " + readable_date(ticket.first_assigned_at),
                       "Jira status since: " + readable_date(ticket.status_since),
                       "Configure thresholds with --stale-days N and --escalate-days N.",
                       "Earlier/later indicate position, not verified completion. Review or QA can return work to implementation.")]

    def worklog_rows(self, ticket):
        worklog = self.evidence.worklog
        return plain("Your commits (git + PR), grouped by local date.",
                     "Commit timestamps are evidence, not hours worked or ticket completion.",
                     "Git coverage: latest 2,000 authored commits from the past 90 days.", "",
                     *daily_summary(ticket, worklog.get("entries", {}).get(ticket.key, [])),
                     "", "Source checked: " + readable_date(worklog.get("generated_at")),
                     *worklog.get("errors", []), "a: activity · v: overview")

    def activity_rows(self, ticket):
        events = ticket_activity(ticket)
        comments = ("Jira comments not loaded yet (r)" if ticket.jira_comment_total is None else
                    f"Jira comments {len(ticket.jira_comments)} of {ticket.jira_comment_total}, "
                    f"checked {source_age(ticket.jira_comments_checked_at)}")
        styles = {"day": "day", "event": "event", "snippet": "dim", "": "plain"}
        body = ([Row(text, styles[kind]) for kind, text in timeline_rows(events, now())] if events
                else plain("No dated activity loaded."))
        return plain(f"{len(events)} events, newest first · {comments}", "") + body

    def plan_rows(self, ticket, view, plans):
        """The ticket's plan.md split into Plan and Updates; cached until the file changes."""
        path = plans / ticket.key / "plan.md"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            if view == "Updates":
                return plain(f"No updates recorded yet for {ticket.key}.", "", str(path))
            return plain(f"No plan yet for {ticket.key}.", "",
                         f'Space s → Custom: "start {ticket.key} and write the plan" asks your agent to write it to',
                         str(path))
        cached = self.plan_cache.get(ticket.key)
        if not cached or cached[0] != mtime:
            try:
                text = path.read_text(errors="replace")
            except OSError as exc:
                return plain(f"Couldn't read {path}: {exc.strerror}")
            cached = (mtime, document_views(text, HEADING_MARK))
            self.plan_cache[ticket.key] = cached
        age = relative(datetime.fromtimestamp(cached[0], tz=now().tzinfo).isoformat(), now())
        edited = "edited just now" if age == "now" else f"edited {age} ago"
        lines = cached[1][view] or [f"No {view.lower()} recorded yet for {ticket.key}."]
        return plain(f"{path.parent.parent.name}/{path.parent.name}/{path.name} · {edited}", "") + [
            Row(line[len(HEADING_MARK):], "heading") if line.startswith(HEADING_MARK) else Row(line) for line in lines]

    @staticmethod
    def standup_rows(lines):
        return [Row(line, "heading" if line == "STANDUP PREVIEW" or (line.endswith(":") and not line.startswith("-"))
                    else "plain") for line in lines]
