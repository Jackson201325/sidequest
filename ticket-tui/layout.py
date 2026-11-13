"""Pure layout pieces for the screen: glyphs, compact columns, relative times and panel borders.

Kept free of curses so they can be tested directly. Colour is applied by tui.py; every glyph
also differs by shape, so meaning survives without colour (NO_COLOR, monochrome terminals).
"""

from core import parse_time
from pathlib import Path
import re
import sys

from workflow import ALIASES, STAGE_LABELS, next_owner, stage_context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import runs

# Lane glyphs: filled = your move, empty = waiting, ? = unclear.
LANE_GLYPH = {"Needs me": "●", "Waiting": "○", "Clarify": "?", "Done": "✓"}
VIEW_GLYPH = {**LANE_GLYPH, "In Dev": "◆", "AI": "✦"}
CI_GLYPH = {"green": "✓", "failing": "✗", "pending": "…", "mixed": "~"}

# Focused panel: heavy border; other panel: light rounded border. Focus is visible by shape.
HEAVY = "┏━┓┃┗┛"
LIGHT = "╭─╮│╰╯"


def panel_rects(height, width, focus="list", list_fraction=0.3):
    """List/detail rectangles (y, x, height, width), preserving room to read details."""
    usable, panel_height = width - 1, height - 3
    if height >= 18:
        available = panel_height - 1  # One blank row separates stacked borders.
        list_height = max(5, min(available - 8, round(available * list_fraction)))
        return (1, 0, list_height, usable), (list_height + 2, 0, available - list_height, usable)
    rectangle = (1, 0, panel_height, usable)
    return (rectangle, None) if focus == "list" else (None, rectangle)


def relative(value, clock):
    """Short age for lists: now, 5m, 3h, 2d, 3w, 4mo."""
    stamp = parse_time(value) if isinstance(value, str) else value
    if not stamp:
        return ""
    seconds = max(0, (clock - stamp).total_seconds())
    for limit, size, unit in ((60, 1, None), (3600, 60, "m"), (86400, 3600, "h"),
                              (86400 * 14, 86400, "d"), (86400 * 60, 86400 * 7, "w")):
        if seconds < limit:
            return "now" if unit is None else f"{int(seconds // size)}{unit}"
    return f"{int(seconds // (86400 * 30))}mo"


def turn_label(ticket):
    """Whose turn, as short as possible: you, a login (+N), a first name, or ?."""
    owner = next_owner(ticket)
    if owner == "You":
        return "you"
    if owner in ("Needs clarification", "Someone else (name unknown)"):
        return "?"
    if owner == "No next owner":
        return "done"
    names = [n.strip() for n in owner.split(",") if n.strip()]
    first = names[0].split()[0] if " " in names[0] and not names[0].islower() else names[0]
    return first + (f" +{len(names) - 1}" if len(names) > 1 else "")


FEEDBACK_MARK = "(PR feedback)"


def stage_label(ticket, size=0):
    """The ticket's Jira status as the board shows it (In Dev, Ready for QA, …).
    Unresolved PR review threads add "(PR feedback)"; a narrow column shortens the status, not the mark."""
    status = ticket.status.strip() or "?"
    if not any(p.get("unresolved_count", 0) for p in ticket.prs):
        return status
    label = f"{status} {FEEDBACK_MARK}"
    if not size or len(label) < size:
        return label
    room = size - len(FEEDBACK_MARK) - 3
    return f"{status[:room]}… {FEEDBACK_MARK}" if room > 0 else FEEDBACK_MARK


def pr_label(ticket):
    """'#2059 ✓' for one PR, '#2059 +1' for several, '—' for none."""
    if not ticket.prs:
        return "—"
    pr = ticket.prs[0]
    extra = f" +{len(ticket.prs) - 1}" if len(ticket.prs) > 1 else ""
    return f"#{pr.get('number', '?')} {CI_GLYPH.get(pr.get('ci'), '·')}{extra}"


def columns(width, with_when=False):
    """Column widths for the ticket table: KEY TITLE STATUS TURN PR WAIT [WHEN].

    KEY and WAIT stay compact, STATUS/TURN/PR widen a little on roomy panels (so "example-org +1"
    fits), and every remaining column goes to the title so the row fills the panel.
    Narrower terminals drop Status, then Turn.
    """
    cols = {"glyph": 2, "key": 10, "stage": 14, "turn": 12, "pr": 9, "age": 7, "when": 6 if with_when else 0}
    for drop in ("stage", "turn"):
        if width - sum(cols.values()) >= 24:
            break
        cols[drop] = 0
    roomy = {"stage": 22, "turn": 16, "pr": 11}
    extra = sum(size - cols[k] for k, size in roomy.items() if cols[k])
    if width - sum(cols.values()) - extra >= 60:
        cols.update({k: size for k, size in roomy.items() if cols[k]})
    cols["title"] = max(8, width - sum(cols.values()))
    return cols


def cell(text, size, right=False):
    if size <= 0:
        return ""
    text = str(text)
    text = text if len(text) < size else text[:max(0, size - 2)] + "…"
    return (text.rjust(size - 1) + " ") if right else text.ljust(size)


def table_header(cols):
    return "".join([cell("", cols["glyph"]), cell("KEY", cols["key"]), cell("TITLE", cols["title"]),
                    cell("STATUS", cols["stage"]), cell("TURN", cols["turn"]), cell("PR", cols["pr"]),
                    cell("WAIT", cols["age"], True), cell("WHEN", cols["when"], True)])


def table_row(ticket, cols, when=""):
    """(glyph, rest): key and title first, then the workflow fields."""
    glyph = cell(LANE_GLYPH.get(ticket.lane, " "), cols["glyph"])
    rest = "".join([cell(ticket.key, cols["key"]), cell(ticket.title, cols["title"]),
                    cell(stage_label(ticket, cols["stage"]), cols["stage"]), cell(turn_label(ticket), cols["turn"]),
                    cell(pr_label(ticket), cols["pr"]), cell(ticket.wait_label, cols["age"], True),
                    cell(when, cols["when"], True)])
    return glyph, rest

def border(width, title, focused, top=True, label=""):
    """Top line (with an embedded title) or bottom line (with an optional right-hand label)."""
    tl, h, tr, v, bl, br = HEAVY if focused else LIGHT
    if not top:
        label = label[:max(0, width - 4)]
        return bl + h * max(0, width - 3 - len(label)) + label + h + br
    label = f" {title} " if title else ""
    label = label[:max(0, width - 4)]
    return tl + h + label + h * max(0, width - 3 - len(label)) + tr


def menu_box(title, options, selected, max_width, current=None, notes=(), hint=""):
    """A focused menu box as (text, style) rows: border, option, selected or note.

    The selected option starts with › and the current value ends with ✓, so both survive NO_COLOR.
    """
    content = max([len(title) + 4, len(hint) + 4] + [len(o) + 6 for o in options] + [len(n) + 1 for n in notes])
    width = max(12, min(max_width, content + 4))
    inner = width - 4
    tl, h, tr, v, bl, br = HEAVY
    if len(hint) + 6 > width:
        # A long hint is easier to read as a note than cut off in the border.
        notes, hint = [*notes, hint], ""
    rows = [(border(width, title, True), "border")]
    for i, option in enumerate(options):
        mark = " ✓" if i == current else "  "
        text = ("› " if i == selected else "  ") + cell(option, inner - 4) + mark
        rows.append((f"{v} {text} {v}", "selected" if i == selected else "option"))
    if notes:
        rows.append(("┣" + h * (width - 2) + "┫", "border"))
        rows += [(f"{v} {cell(note, inner)} {v}", "note") for note in notes]
    label = f" {hint} " if hint else ""
    rows.append((border(width, title, True, top=False, label=label), "border"))
    return rows


def card(ticket, clock, last_commit_at=None, environment="", stale_days=2, local=(), hint=""):
    """The summary at the top of the right panel: where it stands, the PR, the dates, what's next.

    The first line starts with the lane glyph so tui.py can colour it.
    """
    index = stage_context(ticket)["index"]
    stage = STAGE_LABELS[index] if index is not None else "Stage unclear"
    label = ("since assignment" if ticket.wait_source == "First Jira assignment to you" else
             "in status" if ticket.wait_source == "Jira status transition" else "observed wait" if ticket.wait_source else "waiting")
    waiting = f"{label} {ticket.wait_label}"
    if ticket.lane != "Needs me" and ticket.age >= stale_days:
        waiting += " · chase it"
    lines = [f"{LANE_GLYPH.get(ticket.lane, ' ')} {ticket.lane} · {stage} · turn: {turn_label(ticket)} · {waiting}"]
    for pr in ticket.prs[:2]:
        decision = (pr.get("review_decision") or "awaiting review").replace("_", " ").lower()
        unresolved = pr.get("unresolved_count", 0)
        parts = [f"#{pr.get('number', '?')} {CI_GLYPH.get(pr.get('ci'), '·')} CI {pr.get('ci', 'unknown')}", decision]
        if unresolved:
            parts.append(f"{unresolved} unresolved")
        if pr.get("wip"):
            parts.append("draft")
        lines.append("PR " + " · ".join(parts))
    if len(ticket.prs) > 2:
        lines.append(f"PR +{len(ticket.prs) - 2} more (see v Overview)")
    if not ticket.prs:
        lines.append("PR none yet")
    dates = [f"Jira {ticket.status}"]
    if relative(ticket.updated, clock):
        dates.append(f"updated {relative(ticket.updated, clock)}")
    if last_commit_at:
        dates.append(f"last commit {relative(last_commit_at, clock)}")
    if environment and ticket.prs:
        dates.append(f"Heroku {environment}")
    lines.append(" · ".join(dates))
    lines += list(local)
    if ticket.action:
        lines.append("→ " + ticket.action)
    if hint:
        lines.append("→ " + hint)
    return lines


EVENT_MARK = (("approved", "✓"), ("changes requested", "✗"), ("commit", "•"), ("comment", "✎"),
              ("updated", "↻"), ("dismissed", "−"), ("moved", "→"), ("assigned", "⇄"))
DAY_RULE = "── "
EVENT_INDENT = 13                       # "HH:MM Jira ✎ " — snippets and wrapped titles line up under the title


def event_mark(title):
    lowered = title.lower()
    return next((mark for word, mark in EVENT_MARK if word in lowered), "·")


def day_label(local, today):
    days = (today - local.date()).days
    return "Today" if days == 0 else "Yesterday" if days == 1 else local.strftime("%a %d %b" if days < 300 else "%d %b %Y")


def snippet(body, limit=160):
    text = re.sub(r"\s+", " ", body or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def timeline_rows(events, clock):
    """Activity grouped by day as (kind, text): a "day" rule, one "event" line per event, then a
    "snippet" of its text indented under the title. "" kinds are blank separators."""
    rows, current = [], None
    for event in events:
        local = parse_time(event["at"]).astimezone(clock.tzinfo)
        label = day_label(local, clock.date())
        if label != current:
            if current is not None:
                rows.append(("", ""))
            rows.append(("day", DAY_RULE + label))
            current = label
        source = "Jira" if event["source"] == "Jira" else "GH"
        who = f" · {event['author']}" if event.get("author") else ""
        rows.append(("event", f"{local:%H:%M} {source:<4} {event_mark(event['title'])} {event['title']}{who}"))
        if event.get("body"):
            rows.append(("snippet", " " * EVENT_INDENT + snippet(event["body"])))
    return rows


def timeline(events, clock):
    return [text for _, text in timeline_rows(events, clock)]


# Which glyphs get the good / bad colour. Shapes already differ, so colour only reinforces.
TONE = {"✓": "good", "✗": "bad", "…": "accent"}


def scroll_label(offset, shown, total):
    """' 4–20 of 31 ' when there is more than fits, else ''."""
    if total <= shown:
        return ""
    return f" {offset + 1}–{min(offset + shown, total)} of {total} "


def lane_tab(index, view, count, active, compact):
    """Header tab. When space is short, only the active lane keeps its name."""
    glyph = "" if view == "All" else VIEW_GLYPH[view] + " "
    if compact and not active and view != "All":
        return f" {index} {glyph}{count} "
    return f" {index} {glyph}{view} {count} "


def pr_glyph_offset(cols):
    """Column of the CI glyph inside a table row's `rest` part (after the lane glyph)."""
    return cols["key"] + cols["title"] + cols["stage"] + cols["turn"]


PIPELINE_STAGES = ("START", "IMPLEMENT", "QA-LOCAL", "SHIP-CHECK", "CHALLENGE", "QA-REVIEW")


def pipeline_cells(record, frame, width):
    """One cell per crew step: ✓━━ done, the current state's glyph (with a moving ▶ while working), · ahead."""
    current = runs.STEPS.index(record["step"]) if record else None
    cells = []
    for index in range(len(runs.STEPS)):
        if record is None or index > current:
            cell = "·"
        elif index < current or record["state"] == "ready":
            cell = "✓" + "━" * (width - 2)
        elif record["state"] == "working":
            cell = runs.glyph("working", frame) + "━" * (frame % max(1, width - 3)) + "▶"
        else:
            cell = runs.glyph(record["state"], frame)
        cells.append(cell[:width].ljust(width))
    return cells


def pipeline_columns(width):
    """(key, cell, state) widths; the title takes what is left."""
    cell = 12 if width >= 110 else 11
    return 10, cell, 22


PIPELINE_NARROW = 100  # below this width a row names only the current step
PIPELINE_STEP = 32


def pipeline_header(width):
    key, cell, state = pipeline_columns(width)
    if width < PIPELINE_NARROW:
        return (f"{'TICKET':<{key - 1}}{'STEP · AGENT':<{PIPELINE_STEP}}REASON · TITLE")[:width]
    return (f"{'TICKET':<{key - 1}}" + "".join(f"{name:<{cell}}" for name in PIPELINE_STAGES)
            + f"{'AGENT':<{state}}REASON · TITLE")[:width]


def handed_off(ticket, record):
    """Who has a "waiting" or "ready" ticket when Jira or the PR says it is not the person's turn, else None.
    The worker's run.json only knows its own steps; review, QA and other assignees live in the ticket."""
    if not record or record["state"] not in ("waiting", "ready") or ticket.court == "me":
        return None
    if ticket.court == "done":
        return "done in Jira"
    if ticket.court == "them":
        return "with " + next_owner(ticket)
    if ALIASES.get(" ".join(ticket.status.casefold().replace("_", " ").split())) in (2, 3, 4):
        return "Jira: " + ticket.status
    return None


def crew_label(ticket, record):
    return handed_off(ticket, record) or runs.LABELS[record["state"]]


def shown_record(ticket, record):
    """The record AI mode shows: past ship-check with an open PR; a handed-off wait does not blink."""
    return quiet(ticket, runs.after_ship(record) if ticket.prs else record)


def quiet(ticket, record):
    if record and record["state"] == "waiting" and handed_off(ticket, record):
        return dict(record, state="queued", handed_off=True)
    return record


def stop_reason(record, shipped=False, theirs=False):
    """Why the worker's pipeline is not moving, or None while it works or waits in the queue.
    shipped: an open PR moves the shown pipeline to qa-review (runs.after_ship).
    theirs: the ticket is with someone else (handed_off), so only the worker's own note is a reason;
    the hook's "waits for you" and the hint to open the worker would be wrong."""
    if not record:
        return None
    shown = runs.after_ship(record) if shipped else record
    if shown["state"] in ("working", "queued"):
        return None
    if shown["step"] != record["step"]:
        return "PR open; qa-review has not run"
    note = record.get("note")
    if theirs:
        return note if note and note not in runs.HOOK_NOTES.values() else None
    return note or f"{shown['state']} without a note; open the worker (w)"


def pipeline_row(ticket, record, frame, width, clock):
    """(glyph, rest) for one AI-mode row; the glyph is coloured by its state."""
    key, cell, state_width = pipeline_columns(width)
    after = runs.after_ship(record) if record and ticket.prs else record
    reason = stop_reason(record, bool(ticket.prs), bool(handed_off(ticket, after)))
    label = crew_label(ticket, after) if after else ""
    record = quiet(ticket, after)
    if record:
        glyph = runs.glyph(record["state"], frame)
        state = f"{label} {runs.age(record.get('updated'), clock)}"
    else:
        glyph, state = " ", "no worker"
    tail = (f"→ {reason} · " if reason else "") + ticket.title
    if width < PIPELINE_NARROW:
        step = f"{after['step']} · {state}" if after else state
        return glyph, (f"{ticket.key:<{key - 1}}{step[:PIPELINE_STEP - 1]:<{PIPELINE_STEP}}" + tail)[:max(0, width - 1)]
    rest = (f"{ticket.key:<{key - 1}}" + "".join(pipeline_cells(record, frame, cell))
            + f"{state:<{state_width}}" + tail)
    return glyph, rest[:max(0, width - 1)]
