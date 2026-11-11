# Queue redesign: inbox + inspector

Status: implemented (2026-11-11). Phases 1–4 are done; open question 1 was accepted in phase 4.

## Why

The current screen gives every element the same weight. Two heavy boxes fill the
terminal, most of their rows are empty, and the most important line ("→ next
action") looks like the lines around it. The footer lists about 15 keys.

The app answers one question: **whose turn is each ticket, and what do I do
next?** The redesign makes that answer the first thing the eye lands on.

## Principles

1. Group by whose turn it is. The list is an inbox, not a table.
2. One call to action per screen: the selected ticket's NEXT line.
3. Fewer borders. Rules and spacing separate regions; only focus is decorated.
4. Colors have names by meaning (tokens), not by hue. Every meaning also has a
   glyph, so NO_COLOR and 8-colour terminals keep working.
5. Bold for focus and headings. Dim for metadata. Plain text for everything else.
6. The footer shows at most 5 keys. `?` shows the rest.
7. Panels never move unless the terminal size or the user changes them.

## Layout

### Wide (≥ 120 columns, ≥ 18 rows): side by side

```
 ◆ sidequest   1 All 4   2 ● 2   3 ○ 2   4 ? 1   5 ◆ 1   6 ✦ 2          Attention ↓ · synced 2m
 ─────────────────────────────────────────────────────────────────────────────────────────────
 ▸ NEEDS YOU 2                                    │ DEMO-901
 ● DEMO-901  Validate bulk request quantit…  <1h ✦│ Validate bulk request quantities
 ? DEMO-904  Clarify export acceptance cri…  <1h  │
                                                  │ ● your turn · implementation · <1h
   WAITING ON OTHERS 2                            │ PR #901  ✓ CI  ✗ changes requested · 2
 ○ DEMO-902  Keep inventory totals c…  reviewer 6d│ Jira In Progress · Heroku ◐ building
 ○ DEMO-903  Check tracking status d…        qa 6d│
                                                  │ NEXT → Address requested changes
                                                  │ ✦ plan ✓━ build ✓━ ▶ test ── ship · 4m
                                                  │
                                                  │ a Activity  p Plan  d Updates  c Questions¹ …
                                                  │ ── today ─────────────────────────────────
                                                  │ 10:42 GH ✗ changes requested on #901
                                                  │ 10:15 GH ✓ CI passed
 ─────────────────────────────────────────────────────────────────────────────────────────────
 j/k move   ⏎ inspect   Space actions   / search   ? help
```

- List takes `list_fraction` of the width (default 0.45, range 0.3–0.6).
  `+`/`-` resize it horizontally in this mode.
- One vertical rule `│` separates the panes. No other panel borders.

### Medium (64–119 columns, ≥ 18 rows): stacked

Same regions, list above inspector, separated by one horizontal rule. This is the
current stacked rule, kept below 120 columns. `+`/`-` resize vertically as today.

### Small (< 18 rows): focused pane only

Unchanged from today.

**Rule change.** DESIGN.md says "Keep the ticket list above details at every
width". This spec changes it to "at widths below 120 columns". See open question 1.

## Header (row 0)

`◆ sidequest` (accent, bold), then the lane tabs, then status on the right.

- Lane tabs keep keys 1–6. They double as the attention counts. Inactive tabs
  show `N glyph count` only; the active tab shows its name and is reversed.
- Right side: sort and freshness as today (`header_status`). Errors and STALE
  keep their current wording and bold/colour.
- Row 1 is a dim `─` rule.

## List pane

### Groups

In lanes All, In Dev and AI the list is split into groups, in this order:

| Group             | Lane       | Heading style |
| ----------------- | ---------- | ------------- |
| NEEDS YOU         | Needs me   | `you` token, bold |
| UNCLEAR           | Clarify    | `unclear` token, bold |
| WAITING ON OTHERS | Waiting    | dim, bold |

Lanes 2–4 already hold one group, so they show no group heading.

- Headings are not selectable. `j`/`k`, `gg`/`G` and `gl`/`gL` skip them and land on tickets.
- No blank rows between groups: in the stacked layout every row counts, and the
  coloured headings already separate the groups.
- The sort mode orders tickets inside each group. Group order is fixed.
- The focused pane's first heading (or the first row) starts with `▸`. That is
  the focus marker when there are no heavy borders.

### Row

```
G KEY       TITLE…                     TAG        WAIT A
● DEMO-901  Validate bulk request qu…  ✗ chg      <1h  ✦
```

| Cell  | Width | Content |
| ----- | ----- | ------- |
| G     | 2 | lane glyph, lane token |
| KEY   | 10 | ticket key, bold when selected |
| TITLE | rest | plain for Needs me / Clarify, dim for Waiting |
| TAG   | 0–10 | Needs me: PR state (`✓ CI`, `✗ chg`, `◌ review`). Waiting: `turn_label` (reviewer, qa). Dropped first when narrow. |
| WAIT  | 5 | `wait_label`, right aligned. `aging` token when `age >= stale_days` and the ticket waits on others. |
| A     | 2 | agent glyph from run.json (`✦` working, `⏸` waiting on you, `✗` failed), `agent` token. Empty when there is no worker. |

STATUS, TURN and PR columns move to the inspector. With a date sort, WHEN
replaces TAG.

Selection: reversed row while the list has focus, underlined while the
inspector has focus (as today).

## Inspector pane

Top to bottom:

1. (Dropped in phase 3: the title rule already shows `KEY · title`.)
2. (Dropped with item 1.)
3. Status: `● your turn · implementation · <1h` (lane token on the glyph and turn).
4. PR lines from `card()`: CI glyph in `good`/`bad`, decision text, unresolved count.
5. Jira status (`info` token), Heroku environment, Local line.
6. Blank row.
7. `NEXT → action` — `NEXT` in accent bold, the action in bold. This is the only
   bold sentence in the inspector. Hint lines (`→ QA …`) follow, plain.
8. Agent track when a run.json exists: reuse `pipeline_cells` in one line, then
   `step · state · age · note` dim.
9. Blank row, tab strip (`a Activity  p Plan …`), active tab reversed, others dim.
10. Tab body, scrolled as today.

With fewer than 16 rows, items 4–5 collapse to one line (as `summary[:2]` today).

The Standup tab and AI mode keep their current bodies; only the frame changes.

## Footer

One line, at most 5 keys: `j/k move  ⏎ inspect  Space actions  / search  ? help`.

- `⏎` and `l` already move focus to the inspector; `h` and `Esc` return (Esc
  also clears the search). These keys do not change; the footer only names `⏎`.
- `?` help lists every key, grouped MOVE / DO / VIEW. Nothing is removed, only hidden.
- The message line under the footer is unchanged.

## Colour tokens

One table in `layout.py` (pure, testable). `tui.setup_colors` maps tokens to
curses pairs. Draw code asks for tokens, never for curses colours.

| Token     | Meaning                         | 8-colour | Glyph backup |
| --------- | ------------------------------- | -------- | ------------ |
| `accent`  | app name, focus, NEXT, keys     | cyan     | `▸`, bold |
| `you`     | your turn                       | yellow   | `●` |
| `unclear` | owner or criteria unknown       | magenta  | `?` |
| `waiting` | someone else's turn             | default + dim | `○` |
| `good`    | CI green, approved, done steps  | green    | `✓` |
| `bad`     | CI failing, changes requested, failed worker | red | `✗` |
| `info`    | Jira status, stage names        | blue     | none needed |
| `agent`   | crew worker activity            | magenta  | `✦` `⏸` |
| `aging`   | waiting past `stale_days`       | red      | wait text |

Changes from today: Needs me goes from red to yellow (red now means only
"something failed"), Waiting goes from green to dim default.

NO_COLOR: no pairs. Bold, dim, reverse, underline and glyphs carry all meaning,
as today.

## Code map

Keep rendering, domain rules and snapshot publication separate (AGENTS.md).

- `layout.py` (pure)
  - `TOKENS` table and `LANE_TOKEN`.
  - `panel_rects(height, width, focus, fraction)` gains the side-by-side mode
    at ≥ 120 columns and returns which split it chose.
  - `group_rows(tickets, view)` → list of `("heading", text, token)` and
    `("ticket", ticket)` items. Selection indexes only ticket items.
  - `inbox_columns(width, with_when)` and `inbox_row(ticket, record, cols, when)`
    replace `columns` / `table_row` for the list.
  - `inspector_summary(...)` builds on `card()` and returns styled rows
    (text, style name), like `DetailViews` rows.
- `tui.py`
  - `draw` splits into `draw_header`, `draw_list`, `draw_inspector`, `draw_footer`.
  - `viewport` / `fit` count heading rows when they page the list.
  - `FOOTER` shrinks to 5 keys; the help overlay gets the full list.
  - `draw_box` and `border` stay for menus only.

## Tests (red first, per AGENTS.md)

- `test_layout.py`: `panel_rects` side by side at 120×30, stacked at 119×30,
  focused-only at 100×17; `group_rows` order and heading omission in lanes 2–4;
  `inbox_row` tag and agent cells; WHEN with date sorts.
- `test_keys.py`: `j`/`k`/`gg`/`G`/`gl` skip headings; focus keys unchanged;
  `+`/`-` change the horizontal fraction in wide mode.
- `test_responsive.py`: selection survives resizes across the 120-column line.
- `test_plain_terminal.py`: NO_COLOR shows `▸` focus and all glyphs.
- `test_app_header.py`: compact lane tabs and right-side status.

## Phases

Each phase ships on its own and keeps `bin/check` green.

1. **Tokens and footer.** Token table, new lane colours, 5-key footer, full help.
   Low risk; no layout change.
2. **Grouped, borderless list.** `group_rows`, new row, rules instead of boxes,
   `▸` focus marker. Still stacked.
3. **Inspector.** New summary order with the NEXT line and agent track; tabs
   under the summary.
4. **Side by side.** Wide mode in `panel_rects`, horizontal resize, rule change
   in DESIGN.md.

Every phase updates help, README, DEVELOPMENT.md, HARDENING.md and a dated
DESIGN.md entry together.

## Open questions

1. Accept side by side at ≥ 120 columns? This changes the "list above details at
   every width" rule.
2. Keep cyan as the accent, or use magenta and move `agent` to blue?
3. Should All show an AGENTS group for workers on tickets outside the queue, or
   leave that to lane 6?
