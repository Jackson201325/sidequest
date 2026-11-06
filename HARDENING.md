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

2026-11-06: Code review of the review fixes.

Failing regressions first reproduced each finding. Git errors showed the
"Preparing worktree" progress line instead of the fatal reason; they now show the
fatal or error line, else the last line. Three ticket-key rules disagreed: the
GitHub reader upper-cased "python 3" into PYTHON-3, the collector fetched other
keys than the queue grouped, and worktree mapping accepted keys inside a slug.
sidequest/ticket_keys.py now owns one rule for the reader, collector and queue;
the collector derives PR keys after assigned keys are known, as the queue does.
Worktree mapping uses the lookup segment rule, so w and Space n agree. A moved
PR-derived Jira issue reports status 301 and drops out like a hidden one; assigned
issue errors still fail Jira. The header marks lower-case, unconfigured and
source-less refresh failures. Only a missing gh binary reads as "gh is not
installed". Rework statuses match after normalising, and one REWORK list in
workflow.py feeds ALIASES. Snapshots written before this change keep their stored
PR ticket until the next refresh replaces them.
Verification: bin/check passed 114 helper/service/spec tests and 146 UI tests
(two optional browser checks skipped). Tests use mocks and temporary repositories.

2026-11-06: One ticket key module.

Nine local key rules answered four questions differently. sidequest/ticket_keys.py
now answers all of them: is_key (workspace naming, lookup, plan-init, Jira links),
pr_ticket, branch_keys (lookup and the worktree map), branch_ticket (ship-check and
qa-shot) and mentions/without_leading_key (tmux titles, work log, standup). Guessing
rules (pr_ticket, branch_ticket) trust lower-case keys only for configured Jira
projects; mentions also accept "APP 12" because they only match known tickets.
Failing tests first showed ship-check warning on every non-DEMO branch and qa-shot
reading chore/python-3-bump as PYTHON-3. The unused extract_ticket and
commits_for_day helpers are removed. The Jira client keeps its own upper-case key
check at the transport.
Verification: bin/check passed 126 helper/service/spec tests and 146 UI tests
(two optional browser checks skipped). Tests use temporary repositories only.

2026-11-06: Helpers without DEMO keys.

Failing tests first showed three DEMO-only rules. review-app turned a bare number
into DEMO-###; it now uses the one project in jira.projects, or asks for the full
key. review_apps.find_pr only matched titles that start with the key; it now uses
the title or branch ticket (see the next entry). worktree printed only DEMO and OPS keys in
capitals; it now uses is_key. Tests use a temporary config and no gh binary.

2026-11-06: Review of the helper key change.

A code review found that find_pr trusted only the key's own project, missed PRs
beyond the newest 200, ignored the branch when the title named another ticket,
and failed on lower-case keys. Failing tests reproduced each case. find_pr now
searches open PR titles for the key first, so a PR of any age is found in one
call. Only when that misses does it list the newest 500 open PRs to match
branches, and it asks for --pr N when that list is full. A PR matches when its
title ticket or branch ticket is the key, using every configured project. Without
a key or --pr, review-app uses the current branch's ticket instead of whatever PR
the branch has. worktree capitalises a target only when it is a trusted key, so
release-2 stays as typed. qa-shot help no longer shows DEMO-only keys. Lookup of
a key-shaped branch name such as release-2 still uses the ticket-key segment rule.

2026-11-06: Queue evidence module.

App held the retain-last-good-data rule in four places, repeated the snapshot
checks, and found failed sources by reading error text. Module tests written first
failed until ticket-tui/queue_evidence.py existed. QueueEvidence now loads the
newest copy, runs the read-only collector, applies results and saves a failure set
({"jira"}, {"prs"} or {"all"}) beside the messages. Errors saved before this change
have no set and are read once with the previous text rule. SnapshotStore.publish
and the dashboard share sidequest.snapshots.source_problem. The unused "issue" and
"status" events were removed. Tests that set App fields now build QueueEvidence
and drive failures through collect and finish_refresh. CLI list and standup modes
still collect worktrees and the work log without saving them.
Verification: bin/check passed 135 helper/service/spec tests and 156 UI tests
(two optional browser checks skipped).

2026-11-06: Key handling and UI shims.

Eighteen key tests written first failed until App.press existed. The key chain
moved out of App.loop unchanged, except that prefix state is stored on App and
prompts use App.blocking. The tests cover movement, paging, gg/G, gl/gL lane
jumps, views, focus, Escape, detail tabs, search, the Space menu, resize, command
keys, sort order, standup copy, quit, unknown keys and action errors.
ticket-tui/launcher.py and ticket-tui/environments.py only forwarded calls; no
skill, script or document outside their tests imported them. Their tests moved
to tests/ against sidequest.tmux and sidequest.environments, and both files were
removed. The one real function, the browser opener, is sidequest.terminal.
open_browser. It takes the browser command as an argument, because a headless
spec forbids the workspace layer from reading global configuration.
Verification: bin/check passed 151 helper/service/spec tests and 160 UI tests
(two optional browser checks skipped), with no git re-init warnings.

2026-11-06: Review of the key and shim change.

A failing test showed that a resize during a waiting Space or g prefix never
cleared the screen; press now handles the resize first and keeps the prefix.
tests/test_environments.py failed outside the repository root; it now adds the
root to sys.path like the other tests. The moved tmux tests call sidequest.tmux
directly instead of copies of the removed shims, a duplicate split_command test
is removed, and the worktree window test reads the tmux session from the test
configuration. The docs no longer claim that the dashboard imports tmux.

2026-11-06: Detail views and viewport.

Tests written first failed until ticket-tui/detail_views.py existed. DetailViews
returns styled rows for every tab, marks the current workflow step from the stage
index instead of the "YOU ARE HERE" text, and takes Activity line kinds from
layout.timeline_rows. App.viewport and App.fit replace the page_size,
preview_page_size and offset updates that draw used to make; a resize reaches
fit through KEY_RESIZE, and one resize test now sends that key. Key and title
lines that the panel border already shows are no longer built, even when refresh
errors precede them. Wrapped continuations of headings are plain. A render of all
seven tabs at 145x40, 80x24 and 64x18 matched the previous commit in text and
paint attributes (595 lines, 1,852 paint calls).
Verification: bin/check passed 150 helper/service/spec tests and 172 UI tests
(two optional browser checks skipped).

2026-11-06: Access failures as data.

Every service error used to reach recovery text through one substring classifier,
so Jira's HTTP status and a missing gh binary were turned into text and guessed
back. Thirteen tests written first failed until sidequest.access.AccessFailure
existed. AccessFailure is a RuntimeError with a service and a cause (missing_tool,
credentials, login, denied, dns, tls, network, not_found, unknown); its message is
the same recovery text as before. JiraError now records a cause from the HTTP
status, missing credentials, TLS, DNS or network failure, and the collector uses
it directly. The gh runner reports a missing gh as missing_tool. Word matching
remains only for text-only tool output (gh stderr and dashboard helper runs), and
200 service/text pairs give the same text as before. Two Jira messages are more
precise: DNS failures now say "DNS lookup failed" instead of "network
unavailable", and invalid JSON says "request failed". Heroku already maps its own
HTTP statuses and is unchanged. The dashboard run() no longer special-cases the
ticket, my-tickets and pr-feedback commands or an old Keychain diagnostic. The
dashboard only runs collect; sidequest-data still offers ticket and pr-feedback
(my-tickets no longer exists).
Verification: bin/check passed 163 helper/service/spec tests and 172 UI tests
(two optional browser checks skipped).

2026-11-06: Review of access failures.

Failing tests reproduced five bugs. Jira TLS errors raised while reading the body
carry a text reason, so the cause is now taken from the error itself and they are
tls again. A connection dropped mid-body (http.client.IncompleteRead) is a network
failure instead of a traceback. JiraError without a known status keeps cause None,
so its text is still classified; unknown cause names are refused. A gh timeout is
a network failure, and the collector catches subprocess errors per source, so Jira
still collects and the snapshot is published. A failed sidequest-data run in the
dashboard reads "request failed" instead of guessing "login" from the helper's
generic sentence. review_apps uses the shared missing-tool message, the collector
keeps an AccessFailure as raised, and access_error is removed. README lists the new
error messages.

2026-11-06: Second review of access failures.

Failing tests first. AccessFailure gained timeout, server and rate_limited causes
and terminal_text, the same advice without "press r" or "Previous data retained"
for command-line helpers. services.run_tool runs gh and heroku for the collector
and review_apps alike: a missing program names its CLI, a timeout is "timeout"
(gh may wait for a prompt, so it is not called a network failure), and a failed
heroku command is a Heroku failure, not a GitHub one. JiraError always has a cause:
HTTP 429 is rate_limited, 5xx is server, a read timeout is timeout, and anything
else is unknown, so Jira text is never guessed. A 401 on the first Jira base is
reported even when a second base fails differently. sidequest-data prints
"sidequest-data: " plus the real cause (Jira advice for ticket, a neutral
"Collection failed (TypeName)" for collect), and the dashboard shows that one line
and never other helper output. The redundant AccessFailure branch in failure_for
and the unreachable subprocess handlers in the collector are removed.

2026-11-06: Third review of access failures.

Failing tests first. One advice table in sidequest/access.py now gives each cause a
problem, an action and whether pressing r helps; the dashboard text and
terminal_text are both built from it, and every service, cause and tool pair is
checked to give both forms. 408 of 432 messages are unchanged; the others are a
timeout without a tool (Jira now says the service did not answer in time instead
of asking to run a command) and a missing heroku (now "run heroku login").
run_tool is the only CLI runner, names the service from the program's basename,
and marks missing programs and timeouts with the tool. Jira treats Python 3.9's
socket.timeout as a timeout. After a 401 on the first base, only a 404 or an
unreachable second base is hidden; 403, 429 and 5xx from a base that accepted the
token are reported. sidequest-data prints terminal_text for people and a
failure line (now a JSON record); Jira's own messages are kept,
and other errors name only their type. The dashboard rebuilds its message from the
failure line and ignores argparse and other output.

2026-11-06: Fourth review of access failures.

Failing tests first. sidequest-data now prints one JSON failure record (service,
cause and tool, or only the error type); the dashboard rebuilds identical advice
from it, keeps "Collection failed (TypeName)" for other errors, and refuses
unknown services, causes, tools, type names or malformed records. "No such file or
directory" is a missing command only when it names a bare program, so missing
config files and paths are no longer called missing tools. After a 401 on the
first Jira base, only 403, 429 and 5xx from the second base replace it; a broken
second base that answers 5xx is reported as a server error. sidequest-data ticket
keeps "issue APP-1 moved to APP-9" and no longer doubles the Jira prefix. The
diagnostics guard in the dashboard has a test again, github.run_command is renamed
gh_output without its unused strict flag, and README lists the new messages.
