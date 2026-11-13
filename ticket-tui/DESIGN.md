# Sidequest queue design

This is an attention queue and optional local launcher. It explains whose turn a
ticket is, how long it has waited and what evidence supports the next action.
It is read-only toward Jira, GitHub and Heroku. Explicit local workspace actions
use the shared WorkspaceWorkflow; refresh never mutates Git. Ticket changes,
shipping, application management and scheduled reporting belong to other tools.

Keep the ticket list above details at every width with at least 18 rows. Smaller
terminals show the focused pane. Keep readable focus borders, lane symbols and
NO_COLOR support. Preserve selection after refresh and sorting. Network I/O never
blocks input; only the UI thread updates UI state and SQLite.

Use Activity, Plan, Overview, Work log, Flow and Standup views. Activity contains
Jira/GitHub events; work logs contain dated commit evidence. Unknown ownership or
history remains explicitly unknown. Unresolved PR review threads take
precedence over Jira handoffs; once every thread is resolved, the Jira handoff
decides again, even while GitHub still shows changes requested. A failing check
alone does not override Jira. The table's status cell then reads "<status> (PR feedback)"; a narrow
column shortens the status and keeps the mark. Business time uses the configured timezone, weekdays 09:00–17:00, with
first-assignment and status-transition dates supplying the waiting clock.

2026-11-05: replaced account-specific defaults and PATH-based helper lookup with
external configuration and a bundled read-only collector. Removed company start
and shipping actions. Browser opening uses a configured command or the OS opener,
without loading a shell profile. Optional tmux and Claude actions use a separate
session name. Original queue rendering and keyboard navigation are retained.

2026-11-05: Sidequest names the application, CLI, help and header. Sample tickets
use fictional DEMO keys. The stacked layout, focus and keyboard controls remain.

2026-11-05: Space s also offers the six bundled project-neutral workflows.
The selected skill is rendered with this clone's helper paths, so a global
installation is optional. The queue's own collection remains read-only. Planning
and screenshot artifacts share the same external directory as the CLI helpers.

2026-11-05: tmux is no longer a prerequisite for workspace/agent actions. Outside
tmux, w opens a worktree shell and Space s runs the configured agent in place.
Space n explicitly creates/reuses a local ticket worktree and opens a shell.
With jira.start_status set, a ticket in a jira.start_ask status shows a picker
first: move and open, open only, or Esc to cancel (2026-11-09). In tmux, Space n selects or
creates the ticket's window and switches to it, and Bugs get fix/ branches (issue type is collected).
workspace.agent_tasks replaces the Space s presets; workspace.reports_dir moves the daily reports.
The dashboard restores its terminal state after the child exits; passive reads
stay read-only. Users already inside tmux retain existing window/pane navigation.

2026-11-05: workspace/agent actions now submit intent to WorkspaceWorkflow and
receive LaunchResult through the UI event queue. App no longer chooses a terminal
or constructs Git/tmux operations. It retains input, eligibility messages, worker
scheduling and curses handoff. The injected workflow factory supports isolated
tests and future terminal adapters. Headless deployment lookup lives in the Python
package. See ../ARCHITECTURE.md and ../specs/workspace-integrations.md.

2026-11-05: Herdr is another terminal adapter behind WorkspaceWorkflow. The UI
still receives LaunchResult and owns only its foreground curses handoff; provider
selection, tab/pane discovery and agent launch stay outside App. Auto preserves
active tmux priority; explicit Herdr selection requires a real managed pane.

2026-11-05: an unconfigured refresh retains existing queue evidence and reports
the missing service setting. Herdr foreground handoffs require zsh; no UI-specific
shell policy or credential bridge is added to App.

2026-11-05: Plan (p) shows planning sections; Updates (d) shows explicit Updates,
progress/implementation notes and recorded QA/test/verification results from the
same plan.md. Heading hierarchy keeps nested update entries together and returns
peer planning sections to Plan. Fenced examples stay literal. Unknown headings
stay in Plan so content is never silently discarded. The file is never rewritten;
both views share its mtime cache. Existing Standup (u) is unchanged.

2026-11-07: Questions (c) is a read-only view of the ticket folder's questions.md,
the decision record written only by `sidequest-data questions` (sidequest/questions.py).
Not asked yet comes first, then waiting, then answered with its evidence and decision.
Plan open-question sections move from Plan to Questions under FROM PLAN.MD. Meetings (m)
reads meetings.md, newest section first; recording meetings is outside Sidequest.
Overview shows the unanswered count and latest meeting. Both caches follow file changes.

2026-11-07: the card adds a Local line (branch_state.py, local Git only, collected in a
background job after worktrees load; not persisted) and a QA hint for my tickets with
missing or stale screenshots. Overview's WORKSPACE repeats it with the QA reason.
Activity shows Jira status moves (→) and assignee changes (⇄) from the changelog.

2026-11-07: when `app` is configured, the header ends with sqapp's booking (`App APP-12
· idle 2m` or `App free`), re-read at most every 10 seconds; demo and unconfigured
runs never read it. The dashboard never writes the booking.

2026-11-06: QueueEvidence owns the queue's data: the newest copy of each source,
refresh validation with the snapshot publisher's own check, merging, saving and
per-source failure sets, so the header never reads error text. DetailViews builds
every detail tab as rows of text and a style name (plain, heading, current, day,
event, dim); draw paints styles and never guesses them from text. App.press applies
one key and returns False to quit; App.loop reads keys, runs timers, draws and
performs handoffs, and waits 250 ms for a key when idle and 50 ms while something
loads. App.viewport derives panel and page sizes from the terminal size; App.fit
keeps selection and detail scroll in range after keys, list changes and resizes;
draw changes no navigation state. A resize clears the screen even while a Space or
g prefix waits. The UI reaches tmux only through WorkspaceWorkflow and imports
Heroku reading and browser opening from the package.

2026-11-10: menus are boxes over the dashboard. layout.menu_box builds the rows (heavy border, › for the
choice, ✓ for the current value, notes under a divider, the key hint in the bottom border or as a note
when it does not fit); App.draw_menu centres it with a blank margin. Sort, the agent picker and the start
picker share it. draw(overlay) paints the menu or prompt before its one refresh, so the dashboard stays
visible. / filters the list on each edit and shows "(N of M)" for the current lane; Enter keeps the
query and Esc restores the previous one. Keys and results of the menus are unchanged.

2026-11-11: Crew (t) lists every crew worker from the ticket folders' run.json, the person's turn first
(waiting, failed, ready, then working and queued); the card adds an `Agent step · state · age · note` line.
Both read only; run.json is written by `sidequest-data run` and the workers' hooks. Its file versions are
part of view_key, so a worker's change redraws without waiting for the minute tick.

2026-11-11: AI mode (6, ✦) replaces the Crew tab and board. It is a lane, not a ticket tab: the list
becomes one pipeline row per open ticket (plus workers on tickets outside the queue) with ✓━ done stages,
the current state's glyph and a moving ▶ while working, ordered waiting, failed, ready, working, queued,
then no worker. The details panel shows the selected ticket's agent story (step track, note, history,
unanswered questions) instead of the ticket tabs. 1–5 return to the ticket lanes.

Earlier the same day: Crew (t) was a full-screen board of every open ticket and every crew worker, grouped NEEDS YOU
(waiting, failed, ready), WORKING (working, queued) and NO WORKER YET (with the `sidequest crew KEY` command).
The ticket list hides while it is open; Esc returns to the tab used before. Working glyphs spin and waiting
glyphs blink only while such a worker is on screen.

2026-11-10: 5 In Dev (◆) filters by workflow stage, not ownership: tickets whose Jira status maps to
implementation or rework (workflow.stage_context index 1). It can overlap the ownership lanes; Done
tickets stay hidden. Header counts, search counts and the list share App.in_view.

2026-11-11: Space c starts the selected ticket's crew worker after a confirm box (a restart with --again when
one is recorded as working or queued); Space C opens the manager. Both run bin/sidequest-crew.py in a background
job, so its worktree, duplicate and terminal checks apply; outside tmux/Herdr Space C hands this terminal to the
manager. The status line shows only the command's last line. Demo mode disables both.
Workers start in the background (detached tmux pane or window, no Herdr focus), so Space c keeps the dashboard
in front; Space C opens the manager in a pane below the dashboard (40% of the height), or selects it. When a last
manager chat exists (crew-manager.json in the tickets folder), a choose box offers Continue the last manager
chat (--continue) or Start a new manager chat (--new) first.
Space c on a ticket without a worktree offers "Create the worktree, then start a worker": the job runs
WorkspaceWorkflow.prepare (no window, no Jira move), then sidequest crew, then reloads worktrees.
2026-11-11: When sidequest crew skips the ticket with "use --again to start it anyway" (Jira assignee or
status), the status line says to press Space c again, and that next confirm box offers "Start anyway",
which passes --again. The offer lasts for one open of the box.
2026-11-11: AI mode has a fifth pipeline column, QA-REVIEW (cells are 11 wide below 110 columns, so
SHIP-CHECK keeps a gap). A ready ship-check shows four ✓ and qa-review ahead.
2026-11-11: A sixth column, CHALLENGE, sits between SHIP-CHECK and QA-REVIEW. A ticket with an open PR
shows its row at QA-REVIEW (runs.after_ship), whatever step run.json last recorded.
2026-11-11: AI mode hides tickets whose Jira status is in AI_HIDDEN_STATUSES (now only Blocked), even
when they have a worker record. Lanes 1-5 still show them.
2026-11-11: A "waiting" worker is no longer "waiting on you" when the ticket is not the person's turn:
Jira done → "done in Jira"; court them → "with <owner>"; court unknown in a review, QA or Approved status →
"Jira: <status>". Court me keeps "waiting on you". Such rows keep a still ◌ (layout.shown_record), sort
after working and queued workers, and do not count in "need you". Working and failed are unchanged.
2026-11-13: Space M runs `sidequest meeting` for the selected ticket: meeting.command in a tmux pane below
the dashboard (role "meeting", reused when open), else in this terminal. Recording stays outside Sidequest;
the Meetings tab picks up the new meetings.md section through its file-change cache. The box first asks
"Ticket meeting: KEY" (the command gets the ticket's notes) or "General meeting" (no ticket context).
2026-11-13: AI mode rows say why a pipeline stopped: `→ <reason> · <title>` after AGENT (layout.stop_reason).
The reason is the worker's run.json note; with no note, "<state> without a note; open the worker (w)"; an open
PR that moved the row to qa-review shows "PR open; qa-review has not run" instead of the older step's note.
Working and queued rows show no reason. The details panel uses the same reason on the raw record.
