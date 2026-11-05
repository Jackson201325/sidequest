# Sidequest development context

This repository is an independent, account-neutral extraction of the queue UI.
It has its own source, Git history, configuration and runtime namespace. It does
not install into another workflow or import scripts from an adjacent checkout.

Read AGENTS.md, HARDENING.md and ticket-tui/DESIGN.md each iteration. Preserve
existing unrelated work. Use Python 3.9+ and the standard library only.

`bin/sidequest` launches curses or the list/standup modes. The bundled `bin/sidequest-data`
supports read-only `collect`, `snapshot` and `ticket` helpers. TUI refresh calls
the bundled dispatcher by its absolute location, never a global personal command.
`sidequest/config.py` reads optional external JSON configuration; all services are
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

The queue's original sorting, business-hour clocks, ownership rules, stacked panes,
keyboard navigation and saved divider remain. Company ticket-start actions and
company agent skills are excluded. Explicit tmux/Claude/browser actions remain
optional. No scheduler, check-in tool or application/database management is included.

Use ./bin/check for all checks. It runs both suites with an external test-only
configuration, temporary HOME/XDG folders and no service credentials. Test fixtures
are fictional. CLI portability tests also run without that fixture configuration.
Record new evidence and limits in HARDENING.md. Live service access has not been
certified by offline tests; no publishing or remote service writes are part of them.

The public project is named Sidequest. Its commands are `bin/sidequest` and
`bin/sidequest-data`; the Python package is `sidequest`. Configuration variables
use `SIDEQUEST_`, and configuration, caches and snapshots use the `sidequest`
namespace. Example ticket keys use DEMO or APP. The personal workflow is a
separate installation and is never modified when developing or publishing this one.
