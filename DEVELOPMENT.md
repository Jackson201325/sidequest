# Sidequest development context

This repository is an independent, account-neutral extraction of the queue UI.
It has its own source, Git history, configuration and runtime namespace. It does
not install into another workflow or import scripts from an adjacent checkout.

Read AGENTS.md, HARDENING.md and ticket-tui/DESIGN.md each iteration. Preserve
existing unrelated work. Use Python 3.9+ and the standard library only.

ARCHITECTURE.md owns module responsibilities and current migration limits.
specs/workspace-integrations.md defines implemented behavior and future Herdr,
startup and deployment acceptance criteria. Its executable specs run in bin/check.
WorkspaceWorkflow in sidequest/application.py is shared by CLI and TUI actions.
It receives GitWorkspace and a terminal adapter; build_workflow captures explicit
settings/environment once per workflow. The dashboard accepts a workflow factory
and schedules actions in background jobs. QueueEvidence (ticket-tui/queue_evidence.py)
owns queue data, retention and failed sources; DetailViews (ticket-tui/detail_views.py)
builds each detail tab as styled rows; App only draws them. App.viewport computes
page sizes from the terminal size, and App.fit keeps selection and scroll in range.
Only App's event loop changes UI state
and performs curses handoffs. Shell/tmux policy no longer lives in App.
GitWorkspace owns read-only preview and live revalidation before apply. A stale
plan is refused; Git still guards concurrent branch/path conflicts. No fetch,
reset or deletion is added. Terminal adapters only open selected directories or
launch argument vectors. The dashboard reaches tmux only through WorkspaceWorkflow
and calls sidequest.environments and sidequest.terminal.open_browser directly. Heroku reading lives in sidequest/environments.py;
headless QA lookup never imports the UI or changes sys.path. Provider-specific
UI cache keys, global configuration in older collection modules and the existing
CLI dispatcher remain; whole-application multi-profile support is not implemented.

Service errors are sidequest.access.AccessFailure (service + cause). Adapters that
know the cause report it (Jira from HTTP status and connection errors, run_tool from
missing programs and timeouts); failure_for guesses from words only for text-only
tool output. str() is the dashboard text; terminal_text is for command-line helpers.
Both come from one advice table (problem, action, whether r can help).
sidequest.access.describe_failure gives one failed command's terminal and dashboard
text. sidequest-data prints the terminal text, which may add the operating system's
own reason for an OSError, and a "sidequest-data-failure: {"text": ...}" line. The
dashboard shows that text only if it is one printable line of at most 300 characters
(describe_failure clips to that); otherwise it shows a generic failure. Dashboard text
comes only from Sidequest's templates and messages; a moved issue's new key is shown
only when it is a valid ticket key.

`bin/sidequest` launches curses or the list/standup modes; with workspace.launch session, a
plain run in a terminal outside tmux/Herdr hands off to `sidequest up --when-due`. The `sessions`
setting (sync.personal_sessions, built by `sidequest up` through tmux.open_layout) adds personal tmux
sessions beside the project's, with workspace.windows-style windows. sidequest/terminal_mode.py picks
tmux or Herdr for those sessions (auto: the terminal this runs in, else tmux) and gives `up`, `start`, the
overview and the launcher one interface; sidequest/herdr_session.py implements it with Herdr workspaces
and tabs over the server socket. Window holds the raw command and `stay`; only tmux wraps it. The bundled `bin/sidequest-data`
supports read-only `collect`, `snapshot` and `ticket` helpers, plus independent
workflow commands for naming, lookup, plans, PR feedback/checks, QA and skills.
TUI refresh calls
the bundled dispatcher by its absolute location, never a global personal command.
`sidequest/credentials.py` resolves secrets by reference (env var, else keychain:/env: from
the `credentials` setting); `sidequest/projects.py` writes (`project init`) and checks (`project check`) profiles.
`sidequest/config.py` picks a project profile (SIDEQUEST_PROJECT or --project via
sidequest/project_flag.py, else the profile whose repository/worktrees folder holds the cwd,
else the only one; terminal_mode.run_tmux drops SIDEQUEST_* so a tmux server never pins one project
for every pane), applies projects/NAME/config.json over the shared config.json, then
SIDEQUEST_<SECTION>_<KEY> environment variables on top (config.KEYS lists every
setting, including qa.browser and qa.email; unknown names fail; config.NOT_SETTINGS lists the
credential variables); SIDEQUEST_DATA_DIR/STATE_DIR move storage; all services are
disabled until configured. Identity defaults contain no account identifiers.
The default timezone is UTC and business hours are Mon–Fri 09:00–17:00.

`bin/sidequest-jira.py` owns Jira HTTP requests, search, history and comments. It rejects
writes, except the POST endpoint Jira uses for read-only searches. GitHub uses
the user's gh CLI with an explicit repository, paginated activity and unresolved
threads. Heroku needs an explicit pipeline and uses only GET requests. Credentials
stay in process memory or the user's CLI authentication store.

`sidequest/collector.py` publishes validated source updates through snapshots.py.
Healthy sources advance; failed sources preserve their previous data and source
timestamp. A bounded PR inventory fails explicitly when its limit is reached.
Optional local Git scans use the configured repository and never fetch or mutate it.

Ticket folders hold plan.md, questions.md (written only by `sidequest-data questions`,
sidequest/questions.py) and an optional meetings.md; the dashboard reads them and never
writes them. branch_state.py reads local Git per worktree for the card's Local line.
Confirmed PR/branch ticket links are config (github.pr_tickets, github.branch_tickets)
and live in ticket_keys.linked_ticket, so every key rule stays in one place.
bin/sqapp (sidequest-data app) books an optional shared local app for one worktree at
a time; sidequest/app_booking.py owns its lock format, expiry and label. The project's
own commands (app.switch_command, current_command, running_command) do the switching.

The queue's original sorting, business-hour clocks, ownership rules, stacked panes,
keyboard navigation and saved divider remain. Company ticket-start actions and
company-specific agent assumptions are excluded. Seven reusable `sidequest-*` skills
are bundled under agents/skills/<name>/SKILL.md. The dashboard's agent menu renders
the selected canonical skill; the optional installer binds absolute helper paths
for Codex/Claude, checks drift and preserves user edits. `agents/RULES.md` supplies
shared workflow rules. Explicit tmux/Claude/browser actions remain optional.
Outside tmux, workspace and agent actions hand the current terminal to a child
shell or the configured agent, then restore the dashboard on exit. tmux is not
required. `workspace.agent_command` selects the agent CLI (default claude).
No scheduler, check-in tool or application/database management is included.

Use ./bin/check for all checks. It runs both suites with an external test-only
configuration, temporary HOME/XDG folders and no service credentials. Test fixtures
are fictional. CLI portability tests also run without that fixture configuration.
Record new evidence and limits in HARDENING.md. Live service access has not been
certified by offline tests; no publishing or remote service writes are part of them.

The public project is named Sidequest. Its commands are `bin/sidequest` and
`bin/sidequest-data`; the Python package is `sidequest`. Configuration variables
use `SIDEQUEST_`, and configuration, caches and snapshots use the `sidequest`
namespace. Example ticket keys use DEMO or APP; code never assumes a project.
Key rules live in sidequest/ticket_keys.py. The personal workflow is a
separate installation and is never modified when developing or publishing this one.

`workspace` previews local worktree creation; --apply explicitly creates it after
live lookup. --open creates/reuses it and opens the user's shell there. Space n
delegates to the same helper and opens a shell; w opens an existing worktree.
The base ref is configurable with workspace.base_ref. The helper never removes
worktrees, switches an existing checkout, fetches
or copies credentials. `plan-init` never overwrites a plan. Artifact paths are
shared with the dashboard and remain outside repositories. QA login has no default
account or Keychain fallback; credentials come from explicit environment variables.
The browser's actual host is checked before login after redirects. Review-app QA
is restricted to the HTTPS Heroku host discovered for the PR.

The README owns adopter onboarding: demo, direct service connections, credentials,
first refresh, component dependencies, skill installation and supported commands.
Its Minimum requirements section explicitly separates the GitHub/Jira dashboard
from action-specific tools. Personal editor/report aliases, tmux and macOS-only
credential/clipboard setup are not installation requirements. Browser links use
the OS opener or configured browser; screenshots and agent workflows need their
respective tools only when invoked.
Project Docker booking, automatic cleanup, attachment download, Jira custom fields
and status transitions are not copied. Skills use the target project's commands
and require remote-action authorization from that user.

2026-11-05: Herdr terminal adapter. sidequest/herdr.py implements the existing
launch interface against verified Herdr 0.9.5 CLI responses. Configuration/env
select auto/shell/tmux/herdr; auto preserves active tmux priority. Herdr requires
managed context and confines discovery/controls to the inherited workspace. It
uses private self-removing launch scripts for large agent prompts. No Git policy
or native-session bootstrap is embedded in the dashboard. The offline gate
strips HERDR_* so tests cannot inherit a live control socket. Full startup/sync,
cross-server routing and other deployment providers remain separate work.

2026-11-05: disabled-source retention and zsh. Refresh no longer replaces active
cached Jira/PR data when configuration disappears; it retains the source and its
timestamp, marks the missing setting, and bypasses max-age reuse for that state.
First-use disabled services remain optional without credential access; successful
configured empty results still clear old rows. Herdr requires zsh on PATH and uses
it for foreground shells. Managed tabs follow Herdr's terminal.default_shell; set
that to zsh. Local account/Keychain bridging belongs outside this public repository.

2026-11-05: separate Plan and Updates tabs. ticket-tui/plan_document.py owns the
read-only Markdown section partition and readable rendering. App caches both
views together and rereads them on file edits. p selects planning; d selects
explicit update/progress/result sections and their children; u remains Standup.
Fenced code is not parsed as headings, and unrecognized sections stay in Plan.
Tests exercise rendered views, no document writes, reload behavior and real PTY
keyboard navigation at the approved TUI interface.
