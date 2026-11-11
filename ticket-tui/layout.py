"""Pure layout pieces for the screen: glyphs, compact columns, relative times and panel borders.

Kept free of curses so they can be tested directly. Colour is applied by tui.py; every glyph
also differs by shape, so meaning survives without colour (NO_COLOR, monochrome terminals).
"""

from core import parse_time
from pathlib import Path
import re
import sys

from workflow import STAGE_LABELS, next_owner, stage_context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import runs

# Lane glyphs: filled = your move, empty = waiting, ? = unclear.
LANE_GLYPH = {"Needs me": "●", "Waiting": "○", "Clarify": "?", "Done": "✓"}
VIEW_GLYPH = {**LANE_GLYPH, "In Dev": "◆", "AI": "✦"}
CI_GLYPH = {"green": "✓", "failing": "✗", "pending": "…", "mixed": "~"}

# Colour tokens by meaning: token -> 8-colour name, or None for dim default text.
# Draw code names tokens (or lanes, via LANE_TOKEN); tui.setup_colors maps them to curses.
TOKENS = {"accent": "cyan", "you": "yellow", "unclear": "magenta", "waiting": None, "good": "green",
          "bad": "red", "info": "blue", "agent": "magenta", "aging": "red"}
LANE_TOKEN = {"Needs me": "you", "Waiting": "waiting", "Clarify": "unclear", "Done": "good",
              "In Dev": "info", "AI": "agent"}

# Focused panel: heavy border; other panel: light rounded border. Focus is visible by shape.
HEAVY = "┏━┓┃┗┛"
LIGHT = "╭─╮│╰╯"


SIDE_BY_SIDE_WIDTH = 120
SIDE_SHARE = (0.3, 0.6)


def side_by_side(height, width):
    return height >= 18 and width >= SIDE_BY_SIDE_WIDTH


def panel_rects(height, width, focus="list", list_fraction=0.3, side_fraction=0.45):
    """List/detail rectangles (y, x, height, width), preserving room to read details.

    Wide terminals put the list on the left (side_fraction of the width, 30-60%) and one divider column
    between them; the details rectangle also owns the closing rule above the footer, so it is one row taller.
    """
    usable, panel_height = width - 1, height - 3
    if side_by_side(height, width):
        low, high = (round(usable * share) for share in SIDE_SHARE)
        list_width = max(low, min(high, round(usable * side_fraction)))
        return (1, 0, panel_height - 1, list_width), (1, list_width + 1, panel_height, usable - list_width - 1)
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


def stage_label(ticket):
    """The ticket's Jira status as the board shows it (In Dev, Ready for QA, …)."""
    return ticket.status.strip() or "?"


def pr_label(ticket):
    """'#2059 ✓' for one PR, '#2059 +1' for several, '—' for none."""
    if not ticket.prs:
        return "—"
    pr = ticket.prs[0]
    extra = f" +{len(ticket.prs) - 1}" if len(ticket.prs) > 1 else ""
    return f"#{pr.get('number', '?')} {CI_GLYPH.get(pr.get('ci'), '·')}{extra}"


def cell(text, size, right=False):
    if size <= 0:
        return ""
    text = str(text)
    text = text if len(text) < size else text[:max(0, size - 2)] + "…"
    return (text.rjust(size - 1) + " ") if right else text.ljust(size)


# List groups in display order; one-lane views show no headings.
GROUPS = {"Needs me": "NEEDS YOU", "Clarify": "UNCLEAR", "Waiting": "WAITING ON OTHERS", "Done": "DONE"}
GROUP_RANK = {lane: i for i, lane in enumerate(GROUPS)}
GROUPED_VIEWS = ("All", "In Dev")
# Crew worker state in the list's last column: (glyph, token). Still glyphs, so rows do not animate.
AGENT_MARK = {"working": ("✦", "agent"), "queued": ("◌", "agent"), "waiting": ("⏸", "you"),
              "ready": ("✓", "you"), "failed": ("✗", "bad")}


def group_rows(tickets, grouped):
    """Display lines: ("heading", text, lane) and ("ticket", index into tickets).

    Tickets must already be in group order; a heading goes before each lane's first ticket.
    """
    lines, lane = [], None
    for i, ticket in enumerate(tickets):
        if grouped and ticket.lane != lane:
            lane = ticket.lane
            count = sum(t.lane == lane for t in tickets)
            lines.append(("heading", f"{GROUPS.get(lane, lane.upper())} {count}", lane))
        lines.append(("ticket", i))
    return lines


def list_offset(lines, index, offset, rows):
    """First display line to show so ticket `index` is visible, with its heading when it opens a group."""
    position = next((n for n, line in enumerate(lines) if line == ("ticket", index)), 0)
    top = position - 1 if position and lines[position - 1][0] == "heading" else position
    offset = min(offset, top)
    return position - rows + 1 if position >= offset + rows else offset


def inbox_columns(width, with_when=False):
    """Column widths for a list row: glyph, key, title, tag (or when), wait, agent. Narrow rows drop the tag."""
    cols = {"glyph": 2, "key": 10, "title": 0, "tag": 7 if with_when else 12, "age": 6, "agent": 2}
    if width - sum(cols.values()) < 16:
        cols["tag"] = 0
    cols["title"] = max(8, width - sum(cols.values()))
    return cols


def row_tag(ticket):
    """Short reason beside the title: the PR state on your tickets, the owner on theirs."""
    if ticket.lane == "Waiting":
        return turn_label(ticket), "waiting"
    if not ticket.prs:
        return "", ""
    pr = ticket.prs[0]
    decision = (pr.get("review_decision") or "").upper()
    if decision == "CHANGES_REQUESTED":
        return "✗ changes", "bad"
    if pr.get("ci") == "failing":
        return "✗ CI", "bad"
    if decision == "APPROVED":
        return "✓ approved", "good"
    if pr.get("ci") == "pending":
        return "… CI", "accent"
    if pr.get("ci") == "green":
        return "✓ CI", "good"
    return f"#{pr.get('number', '?')}", "waiting"


def inbox_row(ticket, cols, when="", agent="", stale_days=2):
    """One list row as (text, style) parts that together fill sum(cols). Styles are tokens, lanes or
    "key" / "title"; tui.py turns them into attributes."""
    theirs = ticket.lane == "Waiting"
    tag, tag_style = (when, "waiting") if when else row_tag(ticket)
    mark, mark_style = AGENT_MARK.get(agent, ("", ""))
    aging = ticket.lane != "Needs me" and ticket.age >= stale_days
    return [(cell(LANE_GLYPH.get(ticket.lane, " "), cols["glyph"]), ticket.lane),
            (cell(ticket.key, cols["key"]), "key"),
            (cell(ticket.title, cols["title"]), "waiting" if theirs else "title"),
            (cell(tag, cols["tag"]), tag_style),
            (cell(ticket.wait_label, cols["age"], True), "aging" if aging else "waiting"),
            (cell(mark, cols["agent"], True), mark_style)]


def title_rule(width, title, focused, label=""):
    """A pane's top line: '▸ Title ──── label ─' while it has the keys, two spaces instead of ▸ otherwise."""
    head = ("▸ " if focused else "  ") + title + " "
    tail = f" {label.strip()} ─" if label.strip() else ""
    return (head + "─" * max(0, width - len(head) - len(tail)) + tail)[:width]


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


def agent_track(record, frame):
    """'✓ start ━ ⠋ implement ━ · qa-local ━ · ship-check': done steps, the current state's glyph, steps ahead."""
    current = runs.STEPS.index(record["step"])
    marks = ["✓" if i < current or (i == current and record["state"] == "ready")
             else runs.glyph(record["state"], frame) if i == current else "·" for i in range(len(runs.STEPS))]
    return " ━ ".join(f"{mark} {step}" for mark, step in zip(marks, runs.STEPS))


def inspector_rows(ticket, clock, last_commit_at=None, environment="", stale_days=2, local=(), hint="",
                   record=None, frame=0, short=False):
    """The details pane's summary as (text, style) rows: the card's facts, then NEXT, hints and the crew
    worker. Styles: a lane name, "pr", "dim", "plain", "next" or "agent"; tui.py paints them."""
    facts = card(ticket, clock, last_commit_at, environment, stale_days, local)
    if ticket.action:
        facts = facts[:-1]
    rows = [(facts[0], ticket.lane)] + [(line, "pr" if line.startswith("PR ") else "dim") for line in facts[1:]]
    tail = ([("NEXT → " + ticket.action, "next")] if ticket.action else []) + \
           ([("→ " + hint, "plain")] if hint else [])
    if short:
        return rows[:1] + [row for row in tail if row[1] == "next"]
    if record:
        tail += [("Agent " + agent_track(record, frame), "agent"), ("      " + runs.summary(record, clock), "dim")]
    return rows + ([("", "plain")] + tail if tail else [])


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


PIPELINE_STAGES = ("START", "IMPLEMENT", "QA-LOCAL", "SHIP-CHECK")


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
    cell = 12 if width >= 110 else 10
    return 10, cell, 22


def pipeline_header(width):
    key, cell, state = pipeline_columns(width)
    return (f"{'TICKET':<{key}}" + "".join(f"{name:<{cell}}" for name in PIPELINE_STAGES)
            + f"{'AGENT':<{state}}TITLE")[:width]


def pipeline_row(ticket, record, frame, width, clock):
    """(glyph, rest) for one AI-mode row; the glyph is coloured by its state."""
    key, cell, state_width = pipeline_columns(width)
    if record:
        glyph = runs.glyph(record["state"], frame)
        state = f"{runs.LABELS[record['state']]} {runs.age(record.get('updated'), clock)}"
    else:
        glyph, state = " ", "no worker"
    rest = (f"{ticket.key:<{key - 1}}" + "".join(pipeline_cells(record, frame, cell))
            + f"{state:<{state_width}}{ticket.title}")
    return glyph, rest[:max(0, width - 1)]
