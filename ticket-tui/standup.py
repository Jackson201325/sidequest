"""Preview of your next standup, built only from data the queue already has."""

import os
import re
import shutil
from datetime import datetime, time, timedelta
from pathlib import Path

from core import TZ, parse_time
from sidequest.ticket_keys import mentions, without_leading_key
from sidequest.identity import is_my_author
from workflow import next_owner

DEFAULT_TIME = time(9, 0)
VAGUE = re.compile(r"^(small|minor|tiny)?\s*(fix|fixes|tweak|tweaks|changes?|cleanup|clean up.*)$|^smallfix(es)?$|^wip$", re.I)
MAX_SUBJECTS = 4


def _title(ticket):
    return without_leading_key(ticket.title) or ticket.title


def parse_standup_time(value):
    hours, minutes = (int(part) for part in str(value).split(":", 1))
    return time(hours, minutes)


def _skip_weekend(day, step):
    while day.weekday() >= 5:
        day += timedelta(days=step)
    return day


def window(clock, at=DEFAULT_TIME, today=False):
    """(next standup, start of the period it covers): from the business day before it until now.

    today=True: the standup of clock's own (business) day even after it has started; that is
    the meeting today's report is written for, so the report refresh uses it."""
    day = clock.date()
    if clock.weekday() >= 5 or (not today and clock.timetz().replace(tzinfo=None) >= at):
        day += timedelta(days=1)
    meeting_day = _skip_weekend(day, 1)
    covered = _skip_weekend(meeting_day - timedelta(days=1), -1)
    return datetime.combine(meeting_day, at, TZ), datetime.combine(covered, time(0, 0), TZ)


def _my_pr_commits(ticket):
    for pr in ticket.prs:
        for c in pr.get("commits", []):
            authors = c.get("authors") or []
            if isinstance(authors, dict):
                authors = authors.get("nodes", [])
            if is_my_author(authors):
                yield {"sha": c.get("oid", ""), "date": c.get("authoredDate"), "subject": c.get("messageHeadline", "")}


def _has_work(ticket, commits):
    """Any recorded work on the ticket: one of your commits (git or PR) or a linked PR."""
    return bool(ticket.prs) or any(c.get("sha") for c in commits) or any(True for _ in _my_pr_commits(ticket))


def _work_done(ticket, commits, start, clock):
    seen, subjects, vague = set(), [], 0
    for c in sorted(list(commits) + list(_my_pr_commits(ticket)), key=lambda c: c.get("date") or ""):
        stamp = parse_time(c.get("date"))
        sha, subject = c.get("sha"), (c.get("subject") or "").strip()
        if not stamp or not (start <= stamp <= clock) or not sha or sha in seen:
            continue
        seen.add(sha)
        if subject.lower().startswith("merge "):
            continue
        if VAGUE.match(subject):
            vague += 1
        elif subject not in subjects:
            subjects.append(subject)
    items = subjects
    if len(items) > MAX_SUBJECTS:
        items = items[:MAX_SUBJECTS] + [f"+{len(items) - MAX_SUBJECTS} more"]
    if vague:
        items.append("small fixes")
    return items, len(seen)


def preview(tickets, worklog, clock, at=DEFAULT_TIME, escalate_days=5, stale_days=2, today=False):
    """Sections for the next standup. Every line points at a ticket; nothing is invented."""
    meeting, start = window(clock, at, today)
    entries = (worklog or {}).get("entries", {})
    done, today, waiting, blockers = [], [], [], []
    active = [t for t in tickets if t.lane != "Done"]
    for t in sorted(active, key=lambda t: -t.score):
        items, count = _work_done(t, entries.get(t.key, []), start, clock)
        if items:
            done.append(f"{t.key} {_title(t)}: " + "; ".join(items))
        if t.lane == "Needs me" and not _has_work(t, entries.get(t.key, [])):
            pass                                   # nothing done on it yet: not a standup item
        elif t.lane == "Needs me" or (t.lane == "Waiting" and t.age >= stale_days):
            today.append(f"{t.key} {_title(t)}: {t.action}")
        elif t.lane == "Waiting":
            pr = " / ".join(f"#{p['number']}" for p in t.prs)
            waiting.append(f"{t.key} {_title(t)}: {t.action.lower()} ({next_owner(t)}{', PR ' + pr if pr else ''})")
        if t.lane == "Clarify":
            blockers.append(f"{t.key} {_title(t)}: {t.action.lower()}")
        elif t.lane == "Waiting" and t.age >= escalate_days:
            blockers.append(f"{t.key} {_title(t)}: waiting {t.wait_label} business time on {next_owner(t)}")
    return {"meeting": meeting, "start": start, "done": done, "today": today,
            "waiting": waiting, "blockers": blockers}


STANDUP_HEADING = re.compile(r"^#{1,6}\s+standup\b", re.I)
REFRESH_NOTE = "> Refreshed "
TODAY_TITLE = re.compile(r"^\W*today\b", re.I)


def _is_title(line):
    """A subsection title inside the Standup section ("**Today**", "Today", "Yesterday (Tue 11/03)")."""
    text = line.strip()
    return bool(text) and (re.match(r"^\*\*[^*]+\*\*:?$", text) is not None or not text.startswith(("-", "*", ">")))


def _merge_today(body, items):
    """Add draft Today items for tickets the written section's Today list doesn't mention yet.

    Everything already written stays exactly as it is (Yesterday is never touched). Returns
    (new body lines, number of items added)."""
    body = list(body)
    titles = [i for i, line in enumerate(body) if _is_title(line)]
    today = next((i for i in titles if TODAY_TITLE.match(body[i].strip().strip("*"))), None)
    if today is None:                       # no Today list: add one before Blockers (or at the end)
        at = next((i for i in titles if re.match(r"^\W*blockers?\b", body[i].strip().strip("*"), re.I)), len(body))
        block = ["**Today**"] + ([""] if at < len(body) else [])
        if at and body[at - 1].strip():
            block.insert(0, "")
        body[at:at] = block
        today = at + (1 if block[0] == "" else 0)
    stop = next((i for i in range(today + 1, len(body)) if _is_title(body[i])), len(body))
    seen = {key for line in body[today:stop] for key in mentions(line)}
    new = []
    for item in items:
        keys = set(mentions(item))
        if keys and not keys & seen:
            new.append(f"- {item}")
            seen |= keys
    last = max([today] + [i for i in range(today + 1, stop) if body[i].strip()])
    return body[:last + 1] + new + body[last + 1:], len(new)


def as_markdown(data):
    """The commit-based draft as a report section: bold titles, a blank line between sections."""
    out = []
    for line in as_text(dict(data, written=None)).splitlines():
        if line.startswith("- "):
            out.append(line)
        else:
            out += ([""] if out else []) + [f"**{line.rstrip(':')}**"]
    return "\n".join(out)


def update_report(reports, data, clock, sources="", backups=None):
    """Rewrite the Standup section of today's report with the draft (sidequest --update-report).

    Only today's report is changed, and only its Standup section; the rest of the saved report
    stays as written. The previous file is copied to `backups` first. A missing report for
    today is never created (the saved report owns that file); returns None then."""
    path = Path(reports) / f"{clock:%Y-%m-%d}.md"
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    backup = None
    if backups:
        Path(backups).mkdir(parents=True, exist_ok=True)
        backup = Path(backups) / f"{clock:%Y-%m-%d-%H%M%S}.md"
        shutil.copyfile(path, backup)
    lines = original.splitlines()
    start = next((i for i, line in enumerate(lines) if STANDUP_HEADING.match(line)), None)
    end = None if start is None else \
        next((i for i in range(start + 1, len(lines)) if re.match(r"^#{1,6}\s", lines[i])), len(lines))
    written_body = [] if start is None else [l for l in lines[start + 1:end] if not l.startswith(REFRESH_NOTE)]
    while written_body and not written_body[0].strip():
        written_body.pop(0)
    while written_body and not written_body[-1].strip():
        written_body.pop()
    if any(l.strip() and not _is_title(l) for l in written_body):
        # A standup is already written (the saved report, or an earlier refresh): keep every line of
        # it and only add Today items for tickets it doesn't mention yet.
        body, added = _merge_today(written_body, data["today"])
        what = f"added {added} item{'' if added == 1 else 's'} to Today" if added else "nothing new to add to Today"
    else:
        body, what = as_markdown(data).splitlines(), "wrote the draft"
    covered = f"{data['start']:%a %d %b} → {clock:%H:%M}"
    note = (f"{REFRESH_NOTE}{clock:%a %d %b %H:%M} with sidequest --update-report, for the "
            f"{data['meeting']:%a %d %b %H:%M} standup (covers {covered}), from your commits (git + PRs) and Jira: {what}."
            + (f" Sources: {sources}." if sources else "")
            + (f" Previous version: {backup}." if backup else ""))
    section = ["## Standup", note, ""] + body + [""]
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        new = lines + [""] + section
    else:
        new = lines[:start] + section + lines[end:]
    text = "\n".join(new).rstrip("\n") + "\n"
    temp = path.with_name(f".{path.name}.tmp")       # not *.md, so the report window never shows it
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)
    return {"path": str(path), "backup": str(backup) if backup else None}


def written(reports, meeting):
    """The Standup section of the saved report for this meeting's day, or None.

    The report (reports/YYYY-MM-DD.md) is written from
    your sessions, Jira and GitHub, so when it exists it is the standup; the preview below is
    only the fallback for days it hasn't been written yet."""
    path = Path(reports) / f"{meeting:%Y-%m-%d}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    lines, inside = [], False
    for line in text.splitlines():
        if re.match(r"^#{1,6}\s", line):
            if inside:
                break
            inside = STANDUP_HEADING.match(line) is not None
            continue
        if inside and not line.startswith(REFRESH_NOTE):
            lines.append(line.rstrip())
    body = "\n".join(lines).strip()
    return {"path": str(path), "date": meeting.date(), "text": body} if body else None


def as_text(data):
    """Plain text to paste into the standup thread."""
    if data.get("written"):
        return data["written"]["text"]
    def section(title, rows, empty):
        return [title] + [f"- {r}" for r in rows] + ([f"- {empty}"] if not rows else [])
    done_title = "Yesterday" if (data["meeting"].date() - data["start"].date()).days == 1 else \
        f"Since {data['start']:%A}"
    lines = section(done_title + ":", data["done"], "No commits or logged progress recorded")
    lines += section("Today:", data["today"], "Pick up the next ticket")
    if data["waiting"]:
        lines += section("Waiting on others:", data["waiting"], "")
    lines += section("Blockers:", data["blockers"], "None")
    return "\n".join(lines)


def view_lines(data, refreshed_at=""):
    """Lines for the TUI preview pane."""
    if data.get("written"):
        lines = ["STANDUP PREVIEW",
                 f"Next standup: {data['meeting']:%a %d %b, %H:%M} · from the {data['meeting']:%a %d %b} report (saved report)",
                 "y: copy as text · v: overview", ""]
        # Report headings ("Yesterday (date)", "Today") have no colon; add one here so the pane bolds them.
        def heading(line):
            if re.fullmatch(r"\*\*[^*]+\*\*", line.strip()):
                line = line.strip()[2:-2]
            return line if not line.strip() or line.lstrip().startswith(("-", "*")) or line.endswith(":") else line + ":"
        lines += [heading(line) for line in as_text(data).splitlines()]
        return lines + ["", "Source: " + data["written"]["path"]]
    covered = f"{data['start']:%a %d %b} → now"
    lines = ["STANDUP PREVIEW",
             f"Next standup: {data['meeting']:%a %d %b, %H:%M} · covers {covered}",
             "y: copy as text · v: overview · r: refresh sources", ""]
    lines += as_text(data).splitlines()
    lines += ["", f"Draft from your commits (git + PRs). The written standup arrives with the "
                  f"{data['meeting']:%a %d %b} saved report (saved report) and replaces this.",
              "Sources: " + (refreshed_at or "last refresh")]
    return lines
