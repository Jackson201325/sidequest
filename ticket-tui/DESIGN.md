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

2026-11-06: QueueEvidence owns the queue's data. It loads the newest copy of each
source, validates refresh output with the snapshot publisher's own check, merges
and saves updates, and records which sources failed as data. App keeps input,
drawing, background scheduling and curses handoff; the header no longer reads
error text to decide which source failed.

2026-11-06: App.loop reads keys, runs timers, draws and performs handoffs; App.press
applies one key and returns False to quit. Prefix state (Space, g) lives on App, and
prompts or menus run through App.blocking, which skips screen timeouts without a
screen. Key rules are tested by pressing keys on a demo App. The UI reaches tmux
only through WorkspaceWorkflow and imports Heroku reading and browser opening
from the package; its pass-through shims are removed. A resize clears the screen
even while a Space or g prefix waits, and the prefix keeps waiting.

2026-11-06: DetailViews builds every detail tab as rows of text and a style name
(plain, heading, current, day, event, dim). draw paints styles and no longer
guesses headings, the current step or Activity lines from their text; the hidden
Plan heading marker never leaves the module. App.viewport derives panel and page
sizes from the terminal size, App.fit keeps the selection and detail scroll in
range after keys, list changes and resizes, and draw changes no navigation state.
