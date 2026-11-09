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
history remains explicitly unknown. Jira handoffs take precedence over old PR
feedback. Business time uses the configured timezone, weekdays 09:00–17:00, with
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
