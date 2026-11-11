"""Detail tabs as styled rows: what each tab says about a ticket, and how each row is styled.

Rows carry a style name ("plain", "heading", "current", "day", "event", "dim"); the dashboard
only wraps and paints them, so it never guesses a style from the text.
"""
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core import now, parse_time
from activity import ticket_activity
import branch_state
from layout import EVENT_INDENT, relative, timeline_rows
from plan_document import document_views, meeting_sections
from sorting import last_commit
from workflow import next_owner, ownership, stage_context, workflow_path, workflow_strip
from worklog import daily_summary

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import questions, runs

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


def marked(lines):
    """Rows from document lines; a line starting with HEADING_MARK becomes a heading row."""
    return [Row(line[len(HEADING_MARK):], "heading") if line.startswith(HEADING_MARK) else Row(line) for line in lines]


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
        self.questions_cache = {}
        self.branch_states = {}          # per-ticket local branch state from branch_state (not persisted)
        self.meetings_cache = {}
        self.runs_cache = {}
        self.frame = 0                   # animation frame for crew glyphs, set by the dashboard

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
        if tab == "Questions":
            return rows + self.question_rows(ticket, plans)
        if tab == "Meetings":
            return rows + self.meeting_rows(ticket, plans)
        builder = {"Activity": self.activity_rows, "Workflow": self.flow_rows,
                   "Work log": self.worklog_rows}.get(tab, lambda t: self.overview_rows(t, loading, plans))
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

    def overview_rows(self, ticket, loading, plans=None):
        stage, worklog = stage_context(ticket), self.evidence.worklog
        rows = [Row("STATUS", "heading"), *self.current_step(ticket),
                *plain("To move forward: " + stage["next"],
                       f"Priority: {ticket.priority or 'unknown'} · Jira status: {ticket.status}"),
                *(plain(f"Unanswered questions: {self.open_question_count(ticket, plans)} (c)",
                        f"Meetings: {self.meeting_summary(ticket, plans)} (m)") if plans else []),
                Row(""), Row("DATES", "heading"),
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
        rows += [Row(""), Row("WORKSPACE", "heading"), Row("Worktree: " + (ticket.worktree or "not found"))]
        state = self.branch_states.get(ticket.key)
        if ticket.worktree and state:
            rows.append(Row(branch_state.summary(state)))
            if state.get("qa_reason"):
                rows.append(Row(f"QA screenshots: {state['qa']} ({state['qa_reason']})"))
            if state.get("ui_files"):
                rows.append(Row(f"UI files changed: {len(state['ui_files'])}"))
        return rows + plain("w / gw: open the existing tmux ticket window")

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
        return plain(f"{path.parent.parent.name}/{path.parent.name}/{path.name} · {edited}", "") + marked(lines)

    def plan_view(self, ticket, view, plans):
        """The named plan.md view's lines, or None when there is no readable plan."""
        path = plans / ticket.key / "plan.md"
        try:
            mtime = path.stat().st_mtime
            cached = self.plan_cache.get(ticket.key)
            if not cached or cached[0] != mtime:
                cached = (mtime, document_views(path.read_text(errors="replace"), HEADING_MARK))
                self.plan_cache[ticket.key] = cached
        except OSError:
            return None
        return cached[1][view]

    def question_items(self, ticket, plans):
        """(path, mtime in ns or None, parsed questions); cached until the file changes."""
        path = plans / ticket.key / "questions.md"
        try:
            info = path.stat()
        except OSError:
            return path, None, []
        version = (info.st_mtime_ns, info.st_size)
        cached = self.questions_cache.get(ticket.key)
        if not cached or cached[0] != version:
            try:
                cached = (version, questions.parse(path.read_text(errors="replace")))
            except OSError:
                return path, None, []
            self.questions_cache[ticket.key] = cached
        return path, info.st_mtime_ns, cached[1]

    def run_paths(self, plans):
        return sorted(plans.glob("*/run.json")) if plans.is_dir() else []

    @staticmethod
    def run_version(paths):
        """File versions of the given run.json files, so a worker's change redraws the dashboard."""
        versions = []
        for path in paths:
            try:
                info = path.stat()
                versions.append((str(path), info.st_mtime_ns, info.st_size))
            except OSError:
                versions.append((str(path), None, None))
        return tuple(versions)

    def run_record(self, key, plans):
        """The ticket's crew worker record, or None; cached until the file changes."""
        path = plans / key / "run.json"
        version = self.run_version([path])[0][1:]
        cached = self.runs_cache.get(key)
        if not cached or cached[0] != version:
            try:
                cached = (version, runs.read(path) if version[0] is not None else None)
            except (OSError, ValueError):
                cached = (version, None)
            self.runs_cache[key] = cached
        return cached[1]

    def agent_line(self, ticket, plans):
        record = self.run_record(ticket.key, plans)
        return ["Agent " + runs.glyph(record["state"], self.frame) + " " + runs.summary(record, now())] if record else []

    def crew_records(self, plans):
        return [r for r in (self.run_record(p.parent.name, plans) for p in self.run_paths(plans)) if r]

    def agent_rows(self, ticket, plans):
        """AI mode: one ticket's whole crew story, newest change first."""
        if not ticket:
            return plain("No tickets in this view.")
        record = self.run_record(ticket.key, plans)
        questions_line = f"Unanswered questions: {self.open_question_count(ticket, plans)}"
        if not record:
            return plain(f"No worker for {ticket.key} yet.", "", f"Start one:  sidequest crew {ticket.key}",
                         f"It needs the ticket's own worktree first:  sidequest start {ticket.key}", "", questions_line)
        clock = now()
        rows = [Row("PIPELINE", "heading"), Row(runs.track(record["step"], record["state"], self.frame)),
                Row(f"{record['step']} · {runs.LABELS[record['state']]} · {runs.age(record.get('updated'), clock)}",
                    "current" if record["state"] in ("waiting", "failed", "ready") else "plain")]
        if record.get("note"):
            rows.append(Row("→ " + record["note"]))
        rows += plain("", questions_line,
                      "Answer the worker in its window (w).  Restart it: sidequest crew " + ticket.key + " --again",
                      "Ask the manager about every ticket: sidequest crew")
        rows += [Row(""), Row("HISTORY", "heading")]
        for entry in reversed(record.get("history") or []):
            line = f"{readable_date(entry.get('at')):<18} {entry.get('step')} · {runs.LABELS.get(entry.get('state'), '?')}"
            rows.append(Row(line + (f"  {entry['note']}" if entry.get("note") else "")))
        return rows

    def open_question_count(self, ticket, plans):
        """Questions without an answer yet (not asked, or asked and waiting)."""
        return sum(q["status"] != "answered" for q in self.question_items(ticket, plans)[2])

    def question_rows(self, ticket, plans):
        path, mtime, items = self.question_items(ticket, plans)
        from_plan = [line for line in (self.plan_view(ticket, "Questions", plans) or []) if line.strip()]
        if mtime is None and not from_plan:
            return plain(f"No questions logged yet for {ticket.key}.", "",
                         "Questions raised while starting the ticket, when they were asked, the answers",
                         "and the decisions they led to are logged here with `sidequest-data questions`.",
                         "", str(path))
        if mtime is None:
            stamp = "not created yet"
        else:
            age = relative(datetime.fromtimestamp(mtime / 1e9, tz=now().tzinfo).isoformat(), now())
            stamp = "edited just now" if age == "now" else f"edited {age} ago"
        where = f"{path.parent.parent.name}/{path.parent.name}/{path.name}"
        return plain(f"{where} · {stamp} · decision record (read-only here)", "") + marked(
            questions.view_lines(items, from_plan, HEADING_MARK))

    def meeting_notes(self, ticket, plans):
        """(path, sections newest first) from the ticket's meetings.md; cached until it changes."""
        path = plans / ticket.key / "meetings.md"
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return path, []
        cached = self.meetings_cache.get(ticket.key)
        if not cached or cached[0] != mtime:
            try:
                cached = (mtime, meeting_sections(path.read_text(errors="replace")))
            except OSError:
                return path, []
            self.meetings_cache[ticket.key] = cached
        return path, cached[1]

    def meeting_summary(self, ticket, plans):
        sections = self.meeting_notes(ticket, plans)[1]
        return f"{len(sections)}, latest {sections[0][0].split(' · ')[0]}" if sections else "none recorded"

    def meeting_rows(self, ticket, plans):
        """What was said about the ticket in meetings, newest first; the file is never rewritten."""
        path, sections = self.meeting_notes(ticket, plans)
        if not sections:
            return plain(f"No meeting notes for {ticket.key} yet.", "",
                         "A meeting-notes tool can append what was said about the ticket to", str(path))
        count = f"{len(sections)} meeting{'s' if len(sections) != 1 else ''}"
        rows = plain(f"{path.parent.parent.name}/{path.parent.name}/{path.name} · {count}, newest first", "")
        for heading, body in sections:
            rows += [Row(heading, "heading"), *plain(*body, "")]
        return rows[:-1]

    @staticmethod
    def standup_rows(lines):
        return [Row(line, "heading" if line == "STANDUP PREVIEW" or (line.endswith(":") and not line.startswith("-"))
                    else "plain") for line in lines]
