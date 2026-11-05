# Sidequest queue design

This is an attention queue and optional local launcher. It explains whose turn a
ticket is, how long it has waited and what evidence supports the next action.
It is read-only toward Jira, GitHub and Heroku. Worktree creation, ticket changes,
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
