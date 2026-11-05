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
