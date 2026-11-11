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

Eight skills share project-neutral rules and use the bundled helper. Browser QA
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

2026-11-07: parity with the personal queue.

Ported the general features the personal queue gained after the extraction. Questions
(c): sidequest/questions.py and `sidequest-data questions` keep an append-only decision
record in the ticket folder's questions.md; the tab reads it, plan open-question
sections move there. Meetings (m) reads meetings.md, newest first; Sidequest does not
record meetings. Jira changelog status and assignee changes become Activity events and
survive a comment-only refresh like comments. The card's Local line (branch_state.py)
reports unpushed, uncommitted, behind-base and QA screenshot state from local Git
only, with a QA hint on my tickets. Confirmed links (github.pr_tickets,
github.branch_tickets) attach unnamed PRs and branches to a ticket through
ticket_keys.linked_ticket, so collector, queue, worktrees and helpers agree; config
validates them. The QA skills add the screen sweep, and sidequest-start logs
questions and reads meetings.md.

sqapp generalizes the personal app booking: the same lock line, 30-minute expiry,
--wait/--release/--status/--force and exit 75, with the project's switch, current and
running commands from the new `app` config section instead of fixed Docker names.
Bookings use an fcntl lock on a mutex file and atomic replacement of the lock line.
Tests run real git checkouts and fictional switch commands. A read-only --status run against
the real Docker app showed Docker Desktop reports mounts under /host_mnt; such a folder
still counts as this worktree. switch_command was not run against Docker.

Settings from the environment: every documented setting can come from
SIDEQUEST_<SECTION>_<KEY>, applied over the file and validated by the same rules;
unknown names and bad values fail without echoing the value; SIDEQUEST_JIRA_TOKEN is
never a setting. SIDEQUEST_DATA_DIR/STATE_DIR separate projects without changing XDG
variables that child tools such as gh also read. A read-only live run with only
environment settings listed the same 11 tickets, lanes, waits and actions as the
personal queue; only the saved sort order differed.

Ticket start parity (approved by the user on 2026-11-07, a new boundary). The Jira transport
stays read-only except POST /rest/api/3/issue/KEY/transitions, allowed only while
jira.start_status is set; `jira-start` applies start_from (move), start_ask (needs --yes)
and leaves later statuses alone. Space n runs it before opening the worktree when it is
set; on a start_ask status it asks first (move with --yes, worktree only, or cancel). Attachments download into the ticket folder with sanitized, unique names and
numeric ids only. workspace.copy_files copies listed regular files into a new worktree
only, never over existing files or through symlinks. sidequest-start now follows the
personal start workflow: attachments first, start move, reuse, copy, numbered markers,
plan sections and logged questions.

Left in the personal workflow: the meeting recorder, the
report window's glow width, rubocop lint-changed and company identity/Keychain.
Verification: bin/check passed 266 helper/service/spec tests and 196 UI tests (two
optional browser checks skipped). Live Jira, GitHub and tmux were not exercised.

2026-11-09: Space n asks first and QA settings. With jira.start_status set, Space n on a ticket in
a jira.start_ask status shows a picker (move with --yes, worktree only, Esc cancels); the snapshot
status chooses the picker and jira-start still checks Jira live. New `qa` section: qa.browser and
qa.email are settings (SIDEQUEST_QA_BROWSER/EMAIL still work as variables); SIDEQUEST_QA_PASSWORD
is a credential and never a setting. A shots.json without base_url uses app.url, else
http://localhost:3000 (it was one project's port). Help examples no longer name one project's
make target. Verification: bin/check passed 268 helper/service/spec tests and 197 UI tests (two
optional browser checks skipped).

2026-11-09: tmux Space n, configurable presets and reports folder. Space n passes the Jira issue
type (now collected as issue_type) so Bugs get fix/ branches, and in tmux mode it selects or creates
the ticket's window and switches to it; shell and Herdr keep the foreground shell, and CLI --open is
unchanged. workspace.agent_tasks ([{label, prompt, optional skill}], validated, also as JSON in
SIDEQUEST_WORKSPACE_AGENT_TASKS) replaces the bundled Space s presets; a skill is a file the prompt
names, not inlined. workspace.reports_dir moves the daily reports read by the standup and written by
--update-report; the "no report" message names the folder. Snapshots from before this change have no
issue_type until the next refresh. Verification: bin/check passed 271 helper/service/spec tests and
200 UI tests (two optional browser checks skipped).

2026-11-09: project profiles. ~/.config/sidequest/projects/NAME/config.json is applied over the shared
config.json section by section. The project comes from --project / SIDEQUEST_PROJECT, else the profile
whose workspace.repository or worktrees_dir holds the current folder (deepest match), else the only
profile; an unknown name fails and lists the known ones. A selected project is exported as
SIDEQUEST_PROJECT so child commands stay in it, and gets its own data/state folders under
sidequest/projects/NAME (the app lock included). SIDEQUEST_CONFIG still means one file and no
profiles, so existing single-file setups and bin/check are unchanged. `sidequest-data project` prints
the choice. Profile matching reads only workspace paths before validation; the merged result is then
validated as before. Fixed: bin/sidequest-data failed when run through a symlink such as
~/.local/bin/sidequest-data (it looked for its helper beside the link). Verification: bin/check passed
278 helper/service/spec tests and 200 UI tests (two optional browser checks skipped).

2026-11-09: skills with project additions. `sidequest-data skill NAME` (ship or sidequest-ship) prints
the rendered skill without its front matter, then projects/PROJECT/skills/NAME.md as "Project
additions" that win where they differ; unknown names fail with the list. Installed skills are now stubs
(the canonical name and description, a pointer to `skill NAME`, and the canonical file as fallback), so
installed copies no longer carry the steps and cannot drift from the clone; the drift/user-edit guard is
unchanged. Space s bundled presets use the same merged text. Verification: bin/check passed 279
helper/service/spec tests and 201 UI tests (two optional browser checks skipped).

2026-11-09: skill replace mode. projects/PROJECT/skills/NAME.replace.md replaces the generic skill and
wins over NAME.md additions; it is printed without front matter, with the {{SIDEQUEST_*}} templates
filled, after an HTML comment naming the project and file. Links are followed, so a project can keep its
skills in its own repository. Reason: drafting additions from one project's six skills produced files as
long as the originals that mostly said "instead of the steps above", which doubles prompts and invites
conflicts.

2026-11-09: checks as settings. New `checks` section (test, lint; also SIDEQUEST_CHECKS_*). The generic
and additions forms of `sidequest-data skill NAME` start with "Project commands: PROJECT" listing the
configured test and lint commands and, when `app` is configured, the sqapp booking; the generic skills
point at that block. Replace versions print unchanged. Project additions can therefore drop command
lines. Verification: bin/check passed 281 helper/service/spec tests and 201 UI tests (two optional
browser checks skipped).

2026-11-09: report view with a project replace. `sidequest --report` pages the newest YYYY-MM-DD.md in
the reports folder (a note when it is not today's; exit 1 when there is none). workspace.report_command
replaces that view, as a skill's replace version replaces the skill: the command is exec'd with the
other arguments, so a project's own report window keeps the terminal and its exit status.

2026-11-09: adopting a project. `credentials` (jira, review, qa) holds only references: keychain:SERVICE,
keychain:SERVICE/ACCOUNT or env:NAME; any other value is refused without being echoed. sidequest/credentials.py
resolves them where secrets are used (the Jira transport, the review-app login, the local QA password); the
documented environment variables still win; the Keychain is read only on macOS and only for a configured
reference. `sidequest-data project init NAME --repo PATH` writes projects/NAME/config.json (0600) from
config.example.json with keychain:sidequest-NAME-* references and prints the `security add-generic-password`
commands the person runs; it refuses an existing profile or a bad name. `project check` reports OK / MISSING /
FAIL / OFF per part, runs `gh auth status` and `git rev-parse`, and never prints a secret. The README's "Adopt a
project" section lists where the app, the person's settings, secrets and data live. Verification: bin/check
passed 288 helper/service/spec tests and 203 UI tests (two optional browser checks skipped).

2026-11-09: `sidequest up` phase 1, read-only sync data. New sources, collected only by collect(sync=True):
sync_tickets (a Jira search with sync.tickets_jql, default "assigned to me and not Done" in jira.projects;
key, summary, issue type, status) and merged_prs (gh pr list --state merged, every author, as a worktree's branch may be merged through someone
else's PR: number, branch, head commit, merge time; 300 most recent). A normal refresh neither calls nor clears them. Each keeps its last
good copy and timestamp on failure, with the failure in the snapshot like the others (the dashboard shows
it until the next refresh). New `sync` settings (tickets_jql, open_prs on/off, update on/off, cleanup
off/ask/on) are validated; nothing reads update/cleanup yet. No Git or terminal changes in this phase.
Verification: bin/check passed 292 helper/service/spec tests and 203 UI tests (two optional browser checks skipped).
Live read-only check on one project: collect(sync=True) had no failures; its sync tickets and its 270 merged
branches with head commits matched that project's existing tool exactly.

2026-11-09: `sidequest up` phase 2, plan and create. sidequest/sync.py: discover(snapshot, workspace) returns
create / exists / skip / blocked actions (a sync ticket with a merged PR is skipped; fork PRs and PRs on an
already planned branch are left out; a failed or missing source blocks its part with the reason); apply()
creates through GitWorkspace.apply, which inspects again and refuses a plan the repository moved past. New
GitWorkspace.preview_branch(branch) gives a PR's existing branch a worktree (reuse only; the base branch is
refused), so preview(key) keeps refusing non-ticket keys. `sidequest up [--dry-run] [--offline]` collects
(sync=True), fetches origin (not in a dry run), then applies; exit 0 / 1 (blocked or failed, listed) / 2.
Nothing is removed, updated or pushed. Verification: bin/check passed 296 helper/service/spec tests and 203
UI tests (two optional browser checks skipped); tests use real temporary repositories with a bare origin.

2026-11-09: `sidequest up` phase 3, the tmux session. sync.layout() orders windows: `at: start` extras, the main
checkout ("Main KEY"), worktrees by first-assignment time (compared as times: snapshot and remembered dates carry
different offsets), PR-only branches by opened time, unknown dates by ticket number, then `at: end` extras.
Dates are kept in STATE_DIR/window-order.json so a ticket handed on keeps its place. tmux.open_layout() reuses
windows by name, renames the main checkout's window when its ticket changes, creates missing ones (typing `keys`
once into a new window), parks and re-places windows with renumbering paused, and never closes a window; the
person's own windows go after the worktrees. workspace.on_up commands run after the layout (argv, no shell;
a leading ~ is expanded); a failing one is listed and makes the exit status 1. workspace.terminal shell or herdr
skips the layout with a note. Checked: on one project the dry-run order matched the existing tool's live session,
and a real run into a throwaway session made the same 18 windows and ran both hooks. Verification: bin/check
passed 303 helper/service/spec tests and 203 UI tests (two optional browser checks skipped).

2026-11-09: `sidequest up` phase 4, branch updates. sidequest/updates.py follows the existing tool's rules: local
main is fast-forwarded with update-ref (old value checked) when no worktree has it and it holds no commits of its
own; each worktree takes new commits from its own origin branch with merge --ff-only --autostash; a branch never
pushed is rebased onto the base; a pushed branch behind the base is listed, or with --update / sync.update on gets
merge --no-edit --autostash. A failed rebase or merge is aborted, so the worktree is left as it was; nothing is
pushed. Skipped with the reason: a merge/rebase/cherry-pick in progress, the app booked for it, an agent process's
cwd inside it (lsof), or a branch that diverged from its origin branch (counted as needing attention). A branch
tracking the base itself (Git's default for a branch started from origin/main) is not treated as having its own
origin branch. Updates run only after a successful fetch; a dry run shows them as "would". Verification: bin/check
passed 311 helper/service/spec tests and 203 UI tests (two optional browser checks skipped).

2026-11-09: `sidequest up` phase 5, removing merged worktrees. sidequest/cleanup.py removes a worktree (never the
main checkout) on a merged PR's branch only when the caller is not in it, busy() gives no reason, `git status
--porcelain --untracked-files=all` is empty, the merged head commit exists locally and contains the branch
(merge-base --is-ancestor), the person confirmed, and github.pr_state(number), asked at that moment, still says
MERGED with the same head. It closes the window, runs `git worktree remove` without --force, and deletes the local
branch only after that succeeded. sync.cleanup ask (default) asks per worktree in a terminal and keeps everything
without one unless --yes; on removes; off skips (--cleanup considers it). --offline never removes; a failed or
missing merged_prs source skips cleanup. Cleanup runs before creation, as the existing tool does. A boundary test
parses the dashboard's, collector's and sidequest-data's imports and fails if any reaches cleanup, updates or sync.
Verification: bin/check passed 319 helper/service/spec tests and 203 UI tests (two optional browser checks skipped).

2026-11-09: `sidequest up` phase 6. One project's own workspace script now only maps its flags to `sidequest up`
(and keeps a `start` command built from sidequest-data); its tests check what it hands over. Checked on that
project: `--dry-run` changed nothing, and an offline run into a throwaway tmux session made the same 18 windows
in the same order and ran both hooks. Its live session was not touched.

2026-11-09: `sidequest up` short options and `sidequest start`. `-n` is --offline, `-u` is --update, and `-r`
(--rebuild) closes the tmux session (`kill-session -t =NAME`) just before the layout and builds it again; a dry
run only says it would. `sidequest start KEY` (bin/sidequest-start.py, sidequest/start.py) moves the ticket with
the same jira.start_* rules, creates or reuses the worktree with the same naming, runs `sidequest up -n
--no-attach`, selects the window and prints `DIR <path>`. A refused move is noted and the worktree is still made;
a bad key exits 2 before any service call. Attaching is shared in tmux.attach. One project's workspace script was
removed; its skills, rules and old queue now call `sidequest up` and `sidequest start`. Verification: bin/check
passed 324 helper/service/spec tests and 203 UI tests (two optional browser checks skipped).

2026-11-09: project overview. With several profiles and none selected, `sidequest up` and `sidequest start` exit 2
and name the projects instead of guessing; before, they reported a missing workspace.repository. In a terminal,
`sidequest` and `sidequest up` with no options open the overview; `sidequest projects` opens it anywhere and
prints it without a terminal. sidequest/overview.py reads each profile's settings, snapshot time, app booking,
`git worktree list` and `tmux list-windows -t =SESSION` (read-only), draws text lines and maps keys to commands;
bin/sidequest-projects.py owns curses and runs the chosen command with SIDEQUEST_PROJECT set. `r` asks before
`up -r`. Checked in a throwaway tmux session with two temporary profiles: the list, `d`, the `r` question and
Esc. Verification: bin/check passed 329 helper/service/spec tests and 203 UI tests (two optional browser checks
skipped).

2026-11-09: `sidequest up --all`. It runs `sidequest up … --no-attach` once per profile, in name order, with
SIDEQUEST_PROJECT set, so each project gets its own tmux session; then it attaches to the first. It refuses
--project (exit 2) and returns the worst exit code. tmux.attach now waits for `tmux attach-session` instead of
replacing the process, so detaching returns to the caller. Checked with a private tmux server and two temporary
profiles, through a terminal start command: the first open made both sessions and attached; detaching gave a
shell; a second open attached without syncing. Verification: bin/check passed 330 helper/service/spec tests and
203 UI tests (two optional browser checks skipped).

2026-11-09: `sidequest up --when-due` and sync.every_minutes (a whole number of minutes as text; empty means
always due). sync.fresh compares the sync_tickets snapshot time with now. While it is fresh, an open tmux session
is only attached (no collection, fetch, cleanup, updates or hooks) and a missing one is built as with --offline.
`sidequest up` without the option always syncs. Checked with a private tmux server, two temporary profiles and
`sidequest up --all --when-due` as the terminal start command: the fresh project was built offline, then only
attached; the project without the setting synced both times.

2026-11-09: `sidequest-data project wiring`. projects.wiring lists every outside connection of the selected
project: each command setting (checks, app, report_command, agent_command, workspace.browser), each on_up hook and
window command with a check that its program is on PATH or executable; window keys as TYPED; qa.browser as a file;
each skill with the file that wins (replace, generic + addition, generic), links resolved, and the installed stubs
for Claude Code and Codex; secrets as references only. It only reads and exits 1 on a missing command or file. On
the real profile the first run reported workspace.browser as a missing file; it is a command line (terminal.
open_browser splits it), so it is now checked as a command, with a test that failed first.

2026-11-09: `workspace.launch` (`dashboard` default, or `session`). With `session`, `sidequest` without arguments,
in a terminal, outside tmux ($TMUX) and Herdr (HERDR_ENV=1), with workspace.terminal auto or tmux and tmux on
PATH, runs `sidequest up --when-due` (`--all` when no project is selected). Every other case opens the dashboard,
so the session's own Sidequest window cannot loop. Herdr sessions are not opened. A pseudo-terminal test first
failed at bin/sidequest: the session setting still opened the dashboard; inside tmux, with herdr, and without the
setting the dashboard stays. An unknown value is a settings error (exit 2).

2026-11-09: `sessions`, personal tmux sessions (for example dotfiles) built by every `sidequest up` without
network, with workspace.windows-style windows validated by the same check. Tests first failed at `sidequest up`:
--dry-run lists each session and its windows; a real run on a private tmux server (TMUX_TMPDIR) builds the
session and a second run adds no duplicate windows; a name the project's tmux_session uses is skipped; a bad
name or window is a settings error. `sidequest up` now exits 2 on a settings error, as its help says (it was 1).

2026-11-09: Herdr layouts. `sidequest up` (with --when-due, --all, -r and cleanup), personal sessions,
`sidequest start`, the overview and `workspace.launch` session now work with workspace.terminal herdr: one
workspace per session in the default Herdr session, one tab per window. Herdr 0.9.5 facts checked on
throwaway named sessions: the CLI has no `tab move`, but the socket API's tab.move works (one JSON request
per line); a server outlives the hidden client that started it; panes get HERDR_SOCKET_PATH; `herdr status`
lists the socket even when stopped; socket paths over about 104 bytes fail on macOS. Tests first failed:
fake-server layout, reuse, Main rename, start-and-adopt, controls and attach; the launcher with herdr; the
overview's tab count; and a real server in a temporary XDG_CONFIG_HOME built both workspaces once over two
runs (stopped afterwards only when its socket is inside that folder). Auto now prefers Herdr inside Herdr
for `up`, as the dashboard already did. A Herdr window's command is typed into its shell, which stays.

2026-11-09: sidequest-implement skill. Fills the gap between sidequest-start (plan written) and
sidequest-ship (work finished). It reads the plan with the user's edits, meetings.md, logged questions,
attachments, ticket activity made after the plan, the code markers and existing branch work; records
differences under the plan's Updates; builds unblocked criteria test-first and asks about blocking open
questions; then runs the project's checks. It never commits, pushes or changes Jira. Space s lists it as
"Implement ticket". Test first failed: `sidequest-data skill implement` was unknown.

2026-11-09: sidequest-where skill ("where am I"). Resumes a ticket from the sources behind the
dashboard's tabs: Jira activity and status history, the worktree and branch (status, commits, ship-check,
plan markers), the PR with its reviews, checks and review app, plan.md with its Updates, logged questions,
meetings.md and QA evidence. It orders them into one timeline, picks the furthest stage the evidence
supports, reports conflicts between sources, and prints state, last activity, done/left, blockers, unknown
sources and one next step with its skill. It only reads: no edits, no plan or worktree creation, no Jira
or GitHub change. A failed source is reported as unknown, never as empty; it asks the user only for facts
no source holds. Space s lists it as "Where am I". Test first failed: `sidequest-data skill where` was
unknown.

2026-11-09: tmux sessions no longer keep one project's selection. A tmux server passes the environment
it starts with to every pane of every session. `sidequest up --all` started it with SIDEQUEST_PROJECT set
to the first project, so `sidequest` in any pane (another project's folder included) opened that project.
tmux commands from `sidequest up` now run without SIDEQUEST_* variables, as Herdr's server start already
did, so a pane picks its project by folder. A server that is already running keeps its old environment:
`tmux set-environment -g -u SIDEQUEST_PROJECT` clears it for new panes. Test first failed: `tmux
new-session` received the full environment.

2026-11-09: `bin/sidequest-map.py`, a read-only code map (calls, imports, file writes, config and environment
reads, external programs) as one offline HTML page outside the checkout. Tests first failed at the scanner and
the command: cross-module and method calls, writes such as write_text and os.replace, config reads through
config.get, settings[section] and a held section, unknown and undeclared settings, programs run through
subprocess but not Herdr subcommands, tests left out unless --tests, and data embedded without `</`. Limits:
static analysis only; dynamic calls, settings read in loops or helpers (jira.start_from, app ttl/wait/running,
credentials) and calls through variables are not resolved.

2026-11-09: `sidequest map` runs `bin/sidequest-map.py`, and `--open` opens the written page with
`workspace.browser` or the OS default, as ticket links do. The test first failed at `bin/sidequest map --open`
with a fake browser from SIDEQUEST_CONFIG. The page stays outside the checkout; nothing is fetched or written
elsewhere.

2026-11-09: whole-app review fixes (tests/test_app_review_fixes.py; each test failed first). The Jira token is an
unredirected header, so a redirect (the attachment media host, a moved site) never receives it. A branch with its
own upstream under another name counts as pushed and is not rebased. tmux looks the session up by exact name
(`=NAME`), and the first window of a new session gets its `keys`. `sidequest up -r` is refused (exit 2) from inside
the session it would close; `--dry-run` no longer writes window-order.json. Cleanup keeps a worktree when `git status`
fails or when a workspace.copy_files copy differs from the main checkout; other ignored files still go with the
worktree. A refresh without sync keeps the recorded sync_tickets/merged_prs failures (the dashboard reports only
jira and prs), and they do not defeat --max-age. A refused jira-start (exit 3) writes a failure record, so Space n
shows its reason. Not changed: a ticket with a merged PR is still skipped by `sidequest up` when it returns for
rework; that needs a decision on the branch for the second round and on cleanup of the first.

2026-11-10: menu and search display only. Menus no longer clear the screen, and / filters while typing.
No data, refresh, network or Git behaviour changed; Esc on / restores the previous query and selection.

2026-11-11: agent crew. tests/test_runs.py, tests/test_crew.py and ticket-tui/test_crew_tab.py failed first (no
`run` helper, no crew module, no `t` tab). run.json is written atomically and only by `sidequest-data run`;
unknown steps and states are refused without a write. Hooks always exit 0, write nothing without a record and
keep ready, failed and waiting states the worker set. Dispatch skips tickets without their own worktree
(including the main checkout) and does not start a second worker while one is recorded as working or queued.
Worker prompts forbid commits, pushes, PRs, comments and Jira changes except the start workflow's start move.
Limits: workers' stop points rely on the prompt and the skills; a worker that dies without a hook stays
"working" until `--again`. Live Claude Code hooks and tmux/Herdr launches are not exercised offline.

2026-11-11: tmux window choice. A live crew run split the worker into a newer launcher window in the same folder,
because find_window compared window ids as text (@12 before @5). tests/test_tmux_launch.py failed first. A window in
the worktree folder still wins over one that only names the ticket; among those, the window that also names the
ticket wins, then the oldest by numeric id.

2026-11-11: crew workers start without focus. tests/test_tmux_launch.py, tests/test_herdr.py and tests/test_crew.py
failed first. WorkspaceWorkflow.agent takes focus (default True, so Space s and the manager are unchanged); workers
pass False. tmux then uses split-window -d / new-window -d and runs no select-window or switch-client; Herdr splits
without --focus and skips tab focus. Not verified live in Herdr.

2026-11-11: `sidequest-data update-branch`. tests/test_updates.py failed first (no command). In real repositories
with a bare origin: a branch never pushed is rebased with its uncommitted work kept; a pushed branch gets a merge
commit and its origin branch is unchanged; a conflict is aborted with HEAD and the tree unchanged, or left open with
--keep-conflicts (exit 3, files listed); a branch that diverged from its origin branch is refused. Only `git fetch`
reaches the remote. Crew workers run it at ship-check and may finish that rebase or merge; they never push.
2026-11-11: The crew manager opens in a pane below the caller's pane (40% of its height), not in a Crew window.
tests/test_tmux_launch.py, tests/test_herdr.py and tests/test_crew.py failed first. tmux splits $TMUX_PANE with
`split-window -v -l 40%` and tags the pane @sidequest_role=crew; an open crew pane in the session is selected.
Herdr splits HERDR_PANE_ID down with --ratio 0.6 (the ratio is assumed to be the top pane's share; not checked
live). Herdr has no reuse check, so a second open adds a second pane.
2026-11-11: Space c on a ticket without a worktree skipped it with only a status line (TRD-817).
ticket-tui/test_crew_tab.py failed first. Space c now creates the worktree with WorkspaceWorkflow.prepare
(apply=True: no window, no Jira move) in the background job, then starts the worker.
2026-11-11: Crew step qa-review after ship-check. tests/test_crew.py, tests/test_runs.py and
ticket-tui/test_crew_tab.py failed first. A ready ship-check restarts at qa-review; the worker checks
`review-app KEY --json` and waits when no PR or review app exists, and never updates PR screenshots or
asks for passwords in chat. Qa-local must end with qa-shot screenshots and qa/report.md.
