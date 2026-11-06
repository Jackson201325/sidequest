# Verification and limits

2026-11-05: standalone extraction.

Four regressions first failed at public boundaries: arbitrary Jira keys produced
duplicate PR tickets; UI refresh selected a PATH-based personal helper; default
storage reused another installation's database namespace; and unconfigured Heroku
requested credentials. The extraction now uses generic Jira keys, a bundled helper,
separate storage and explicit opt-in service configuration.

Additional failing checks reproduced an ignored --refresh in --list mode and an
unhelpful exit for credentials placed in a configuration file. The CLI now performs
that refresh before printing, and reports a safe configuration error with exit 2.
GitHub discussion pagination was added after a missing-adapter test failed.
Generic project-key matching also exposed PR-only rows being offered a fictional
Jira link. A failing UI regression now requires Jira evidence before offering it.
Failing service-response regressions also require an explicit error when GitHub
omits review pagination metadata or reaches its 250-commit REST endpoint cap.

Checks cover paginated Jira searches and comments, incomplete-response rejection,
read-only transport restrictions, safe errors, per-source snapshot retention,
paginated GitHub activity, a bounded PR inventory, disabled Heroku, and a fresh-directory
CLI flow using a fixture gh executable. Existing UI regression tests were ported
to independent adapters, fictional identities and optional launchers. Real curses
navigation, view switching, resizing and persisted layout run in a pseudo-terminal.

The source export excludes previous Git history, credentials, runtime reports,
snapshots, caches, local agent state, personal agent skills and all scheduled jobs.
No live Jira, GitHub or Heroku writes are used for verification. No company checkout
or shared database is needed. Live API permissions, uncommon board statuses and
native browser/tmux/Claude actions need checking in the adopter's environment.

Verification: bin/check passed 17 standalone/service tests and 118 UI tests
(135 total) on macOS with system Python 3.9. The original personal workflow's
checks also passed independently, and its source file hashes stayed unchanged.

2026-11-05: Sidequest branding and publication preparation.

Four command-boundary tests failed before the renamed entry point existed. They
now cover Sidequest help, fictional demo keys, the configuration environment
variable and separate default storage. The executable names, bundled dispatcher,
Python imports, environment variables, tmux namespace, docs and test fixtures
were renamed together. Company-specific ticket prefixes and real teammate names
were removed from fixtures. Publication uses a fresh initial Git history.
Verification: bin/check passed 21 standalone/service/branding tests and 118 UI
tests (139 total), including real terminal input and fixture-only service calls.

2026-11-05: portable workflows and README onboarding.

Command tests first failed for the missing workflow commands. The package now
includes branch naming, live worktree lookup, preview/apply worktree creation,
non-overwriting plans, pre-PR checks, paginated PR feedback, local/review-app QA
capture, and explicit skill installation. Ported helper checks use temporary Git
repositories and process/service fixtures. Skills are installed to temporary
folders in tests; drift is detected and user edits are never overwritten.

Six skills share project-neutral rules and use the bundled helper. Browser QA
has no shared login defaults or Keychain dependency, and checks the current host
after redirects before supplying credentials. Both dashboard plans and CLI evidence
use the same external folder. The README explains setup, data flow, daily use,
credentials, optional workflows and remaining project-specific responsibilities.

bin/check passed 55 helper/service/branding tests and 118 UI tests (173 total;
two browser fixture tests skipped by default). No real service writes, personal
skill installation, shared Docker operations or production access are used.
The five QA-helper checks also passed separately with Microsoft Edge against
temporary localhost pages, including successful login/capture and failure evidence.
All six rendered skill packages passed skill-creator's quick_validate validator.

The initial GitHub Actions run failed before tests: ubuntu-latest resolved to
Ubuntu 26.04, where setup-python has no Python 3.9 build. CI now pins Ubuntu 22.04
so the minimum supported Python version can be tested on an available image.

2026-11-05: plain-terminal workspaces.

Four public-boundary regressions failed first: workspace --open was missing,
workspace/agent actions still called tmux outside a session, and the local-start
action did not create/reuse a worktree. The CLI and dashboard now open a shell
in the selected checkout and return on exit, with no tmux requirement. The agent
CLI is configurable and receives the same terminal handoff. Existing in-tmux
navigation remains. A real pseudo-terminal test creates a worktree, enters the
shell, accepts input and restores a working dashboard after exit. CLI tests prove
reuse and that the caller's main checkout stays on its original branch. All
fixtures use temporary Git repositories; no service writes or personal shell
configuration changes are made.
Verification: bin/check passed 56 helper/service tests and 122 UI tests (178
total, including two optional browser checks skipped in the offline gate).

2026-11-05: minimum requirements documentation.

The README now states the basic Python/Git/gh/Jira setup explicitly. It clarifies
that tmux, personal editor/browser aliases, Neovim, glow and macOS credential or
clipboard setup are not dashboard requirements. Screenshot browsers, agent CLIs,
Heroku authentication and application runtimes are described per action. This is
a documentation-only clarification; no commands, credentials or runtime behavior
changed. The normal bin/check gate still applies before committing and pushing.

2026-11-05: workspace integration foundations and specifications.

New executable specs first failed because the shared workflow, Git plan/executor
and terminal adapters did not exist. Further failing checks exposed an empty
workspace path opening the current directory, and headless review-app lookup
loading UI modules through sys.path. These now fail explicitly or use a headless
package reader. The dashboard and CLI share WorkspaceWorkflow; shell/tmux use one
launch interface. Legacy helper interfaces delegate to the same implementations.

Temporary-Git specs cover read-only preview, create/reuse, unchanged caller branch,
existing branch commits, stale source commits, concurrent checkout/destination
changes, dangling symlinks, foreign-repository plans and normal upstream tracking.
An extraction regression initially dropped upstream setup by passing a commit ID;
the failing spec caught it and symbolic-base behavior was restored. Terminal specs
cover literal argv, configured-session isolation, explicit foreground behavior,
missing folders and surfaced failures. A dashboard spec exercises an injected
workflow, and subprocess specs verify headless imports and explicit settings
independent of process-global configuration. Existing CLI/PTY tests remain.

ARCHITECTURE.md records current ownership and limits. The integration spec
distinguishes implemented behavior from planned Herdr, startup and deployment
criteria. Revalidation is not an atomic lock against all Git processes. No fetch,
reset, removal, automatic sync, Herdr control or new deployment provider is added.
Other collection modules retain global configuration and Heroku-specific UI cache
labels; whole-application multi-profile support is not claimed. No live service
writes, private workflow changes or production access are used for verification.
Verification: bin/check passed 80 helper/service/spec tests and 123 UI tests
(203 total; two optional browser checks skipped). Existing real PTY handoffs and
navigation passed. All 111 recorded original-workflow source hashes were unchanged.
No native Herdr/tmux or live service integration was exercised.

2026-11-05: Herdr 0.9.5 support.

Failing specs first reproduced the missing adapter and managed-terminal selection.
Further failing checks cover native response contracts and timeout uncertainty.
The adapter guards managed context, validates response types and discovered IDs,
scopes controls to the caller workspace, creates/reuses tabs and splits agents
according to pane geometry. Agent prompts use mode-600 external launch scripts
which remove themselves before exec. Failed/uncertain submissions are never
retried automatically; unconsumed scripts remain for inspection.

An isolated native named-session smoke test ran its controller inside an actual
Herdr pane. It created/focused a worktree tab, split a pane, and delivered a large
multiline quoted prompt to a fixture agent with unchanged argv/cwd. Native testing
caught tab focus returning tab_info and pane run succeeding with empty stdout;
fixtures and parsing now follow those observed 0.9.5 contracts. Both test sessions
were stopped from their own managed shells. No existing user session was touched.
No real coding assistant, Jira/GitHub/Heroku writes or production operations were
used. Native validation covers macOS Herdr 0.9.5 only. Auto keeps tmux priority;
explicit selection overrides it for an invocation.
Verification: bin/check passed 99 helper/service/spec tests and 123 UI tests
(222 total; two optional browser tests skipped). The native smoke delivered a
14,000-character prompt with 500 newlines unchanged. A separate local preview uses
fictional tickets, a disposable Git repository and isolated configuration; no
credentials or runtime data enter the source tree. Its macOS runtime path is kept
short enough for Unix sockets. All 111 original-workflow source hashes remain
unchanged. Desktop inspection was unavailable; startup was verified by the actual
managed dashboard process and the native adapter smoke test.

2026-11-05: empty queue after unconfigured refresh; Herdr zsh requirement.

A command-boundary reproduction returned an empty preview queue. Four new specs
then reproduced active Jira/PR snapshots being replaced by disabled empty sources,
including the max-age shortcut. Refresh now retains active evidence and source
timestamps while identifying missing configuration. Fresh unused integrations do
not fail, and real successful empty responses still replace data. The CLI test
requires the ticket to remain visible after refresh with an incomplete exit status.
Two Herdr specs also failed because foreground shells used inherited sh and absent
zsh was accepted. Composition now requires zsh before any workspace action and
selects it for Herdr foreground shells. Local tabs must also configure zsh in
Herdr's own settings. Tests use fixtures and temporary repositories only.
Verification: bin/check passed 105 helper/service/spec tests and 123 UI tests
(228 total; two optional browser checks skipped). Separately authorized local setup
reused existing authentication through a private external launcher and completed a
read-only live Jira/GitHub refresh. The real queue rendered through both CLI and
a native Herdr client. Collapsing the local sidebar supplied enough width at 80
columns. Local Herdr panes use zsh and the requested Ctrl+Space prefix. No credentials
or real snapshots enter this repository; the original workflow remains unchanged.

2026-11-05: Plan/Updates separation.

A failing rendered-view regression first showed recorded progress mixed into the
plan. Further failures reproduced implementation/QA sections remaining in Plan
and code examples being interpreted as live update headings. p and d now show
separate read-only views of the same document; hierarchy, fenced examples, empty
states, source bytes and edit-driven reloads are covered. The real PTY navigation
script switches between both tabs and observes their distinct content. No ticket
documents, services, worktrees or shared databases are modified by these checks.

2026-11-06: Reviews, refactors and fixes (PRs #3-#19).

Every change started with a failing test at a public boundary. Code reviews and
architecture reviews ran in a loop; the loop stopped when each fix round began to
add about as much risk as it removed. This entry states the final result; it
replaces 21 entries written during the day.

Ticket keys. sidequest/ticket_keys.py owns every key rule: is_key, pr_ticket,
branch_keys, branch_ticket, mentions and without_leading_key. Guessing rules
(pr_ticket, branch_ticket) trust a lower-case key only for a configured
jira.projects prefix, so "python 3.12" or chore/python-3-bump never becomes
PYTHON-3. The collector, GitHub reader, queue, worktree map, tmux, work log,
standup, ship-check, qa-shot, review-app and worktree helpers all use it; no helper
assumes DEMO keys. review-app expands a bare number only with exactly one
configured project; find_pr searches open PR titles first, then the newest 500
open PR branches, and matches a PR whose title or branch ticket is the key.

Dashboard structure. ticket-tui/queue_evidence.py (QueueEvidence) owns queue
data: the newest copy at startup, refresh validation through the shared
sidequest.snapshots.source_problem, merging, saving and per-source failure sets
({"jira"}, {"prs"} or {"all"}). ticket-tui/detail_views.py (DetailViews) builds
every detail tab as rows of text and a style name, so draw never guesses styles
from text. App.press applies one key; App.loop only reads keys, runs timers,
draws and hands off the terminal. App.viewport derives page sizes from the
terminal size, and App.fit keeps selection and scroll in range; draw changes no
navigation state. The pass-through ticket-tui/launcher.py and environments.py are
removed; the browser opener is sidequest.terminal.open_browser and takes the
browser command as an argument, because a headless spec forbids the workspace
layer from reading global configuration.

Service errors (frozen; change only for a clear user-facing bug).
sidequest.access.AccessFailure carries a service and a cause (missing_tool,
credentials, login, denied, dns, tls, network, timeout, server, rate_limited,
not_found, unknown). One advice table gives each cause a problem, an action and
whether pressing r helps; str() is the dashboard text and terminal_text the
command-line text. services.run_tool is the only gh/heroku runner and names the
service from the program. JiraError records its cause from the HTTP status (429
rate_limited, 5xx server) or connection error (TLS, DNS, timeout including Python
3.9's socket.timeout, network), and a permanent flag for errors a retry cannot
fix (bad key, unsupported path, read-only refusal, missing jira.site, moved
issue). Word matching remains only for text-only tool output: a missing file is
never a missing tool or another cause, a traceback is classified only by tool
names, and gh, heroku or a missing interpreter is a missing tool. When jira.site
refuses the token and the cloud gateway answers differently, the gateway's cause
is kept with the note "The Jira site refused the token; if it is not a scoped
token, renew SIDEQUEST_JIRA_TOKEN" (user decision: one request cannot tell a
scoped token from an expired one). sidequest-data prints terminal text and a
"sidequest-data-failure: {"text": ...}" line; the dashboard shows that text only
when it is one printable line of at most 300 characters (describe_failure clips
to that), and otherwise a generic failure (user decision, after six review rounds
of mismatches from rebuilding messages). Dashboard text comes only from
Sidequest's templates and its own Jira messages; a moved issue names its new key
only when the response gives a valid key. The terminal adds only an OSError's own
reason, never other exception text.

Repository, base and Jira dates. sidequest/repository.py (no configuration
import) uses SIDEQUEST_REPO only when it names an existing folder, else
workspace.repository; the dashboard, workspace actions and helpers share it. The
work log and ship-check use workspace.base_ref, and ship-check --fetch fetches the
remote of its base. Jira status dates match when the changelog's target status id
or name matches the current status, so a renamed status keeps its date; the last
of simultaneous transitions is the newest; only both differing fails the source,
which keeps previous data and the next refresh resolves.

Other fixes. Git errors show Git's fatal line, not progress output. The header
marks every kind of refresh failure. Rework statuses match after normalising, and
one REWORK list in workflow.py feeds ALIASES. A PR commit by an author without a
GitHub account no longer crashes the Work log and Standup tabs. A snapshot.json
that is not a JSON object is refused like other bad files. ship-check no longer
crashes on a non-migration file in db/migrate. A bad SIDEQUEST_TERMINAL is a
status message, not an exit. A resize during a Space or g prefix clears the screen.
--refresh with --list, --standup or --update-report prints cached results marked
incomplete when collection fails, and --update-report reports only that run's
failure.

Efficiency. Measured with the real loop on demo data: App.wait_ms waits 250 ms for
a key when nothing is loading or waiting, and 50 ms otherwise (keys still end the
wait at once), so idle wake-ups fell from 19 to 4 a second (0.23% to 0.06% of one
core). cached_viewport builds the detail tab once per key instead of twice and
reuses it across spinner frames; drain() and rebuild() clear it.

Known limits. The dashboard raises a plain RuntimeError for a failed sidequest-data
run; no caller branches on its type. With both jira.site and jira.cloud_id set, a
broken gateway that answers 5xx after the site refused the token reads as a server
error with the note above. Local runs used Python 3.11; CI covers Python 3.9.
Verification: bin/check passed 233 helper/service/spec tests and 176 UI tests (two
optional browser checks skipped), on every PR and on main after each merge.
