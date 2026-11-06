# Workspace and integration specifications

Status: workspace coordination, shell/tmux/Herdr adapters and headless Heroku
lookup are implemented. Full startup orchestration and a second deployment
provider below remain planned contracts.

## Scope and shared workflow

GitHub and Jira remain the supported repository/ticket integrations. One Git
module owns workspace policy. Credentials and project application setup remain
external to the source tree. CLI and dashboard use `WorkspaceWorkflow`:

| Operation | Result and effects |
| --- | --- |
| `prepare(key, summary, ..., apply=False)` | Preview dictionary; local Git inspection only |
| `prepare(..., apply=True)` | Create/reuse from a freshly validated plan; no terminal launch |
| `start(key, summary, ...)` | Prepare and request a foreground shell; workspace evidence plus launch result |
| `open(key, path)` | Open/focus a selected checkout; no Git mutation |
| `agent(key, path, prompt)` | Run the configured agent in a selected checkout; no Git mutation |

Errors reach the caller. Failed preparation never launches a terminal. Refresh,
startup rendering and collector reads never invoke mutating workspace operations.

## Workspace acceptance scenarios: implemented

1. Preview reports branch, destination and base without creating files/branches.
2. Apply creates one checkout without switching the caller's branch. A subsequent
   start for that ticket reuses it, even if the summary changes.
3. Existing ticket branches keep their names/commits. Worktrees take precedence
   over branch-only matches. APP-12 never matches APP-123 or backup branches.
4. Changed source commit, selected branch/checkout or repository invalidates a
   plan. A destination appearing after preview is refused; user files and symlinks
   are not overwritten. Git remains the final concurrent-conflict guard.
5. A new ticket branch does not track its base (origin/main), so the first
   `git push` targets a same-named branch instead of failing with a suggestion to
   push to main. An existing remote ticket branch keeps tracking origin/<branch>.
   Invalid keys, absent bases and Git failures return errors (with Git's reason)
   without launching a shell.
6. Explicit repository/destination/base settings belong to the composed workflow;
   later environment/settings changes cannot redirect it.

Executable specs: `tests/test_workspace_specs.py`, `test_application_specs.py`,
existing worktree/naming tests and workspace CLI tests.

## Terminal interface: implemented

```python
launch(key, path, argv=None, foreground=False) -> LaunchResult
```

- The caller selects `path`. `argv=None` requests a shell/open action; otherwise
  the vector contains the executable and arguments, including one literal prompt.
- `foreground=True` requires a handoff in the current terminal. The adapter returns
  `LaunchResult.foreground` with `argv`, `cwd` and `label`. The caller executes it
  with `run_request` and reports the child exit status. A completed managed-terminal
  action returns a display message instead.
- Errors propagate without silent fallback or false success. Adapters never fetch
  refs, choose/create/delete worktrees, copy setup files, change Jira, publish PRs
  or start deployments.

Shell mode validates the directory without changing the parent cwd. It requests
the captured `$SHELL -i` (fallback `/bin/sh`) or configured agent. Exiting returns
to the dashboard. Agent commands are parsed once; prompts remain one argument.

Active `TMUX` context selects tmux; installation alone does not. Navigation prefers
the matching checkout path within the configured session, then the exact ticket
label. Agent launch splits a matching window or creates a window/session. The
command is quoted once. Explicit starts retain foreground shell behavior.

Executable specs: `tests/test_terminal_specs.py`, `test_application_specs.py`,
`tests/test_tmux_launch.py`, `ticket-tui/test_workspace_coordinator.py`, existing UI action
tests and real PTY handoff/navigation tests. An injected terminal demonstrates that
another adapter needs no changes to Git or the dashboard.

## Herdr 0.9.5 acceptance criteria: implemented

`workspace.terminal` and `SIDEQUEST_TERMINAL` select auto/shell/tmux/herdr. Auto
prefers active tmux, then active Herdr, then shell; explicit managed modes require
their context. Herdr requires HERDR_ENV=1 and inherited workspace/tab/pane IDs.
Herdr also requires zsh on PATH for foreground worktree shells; configure Herdr's
terminal.default_shell to zsh for managed tabs/panes. Absence fails before Git changes.
Installation alone never authorizes a control. The adapter stays in the inherited
local session; cross-machine or cross-server control is outside this interface.

- Discover live panes only in the caller's workspace. Validate response types,
  identifiers and workspace membership. Never guess IDs, reuse a same-label tab
  with a different directory, or target the dashboard's own pane.
- Open/focus a tab for the selected checkout; create it with explicit cwd when
  missing. An agent gets a new tab root or a split of the matching pane. Read its
  geometry first: split wide panes right and narrower panes down. All IDs come
  from discovery/creation responses. Confirm the tab focus response.
- Foreground requests retain the current shell handoff behavior. Herdr never
  calls Git worktree commands, ticket APIs, or deployment APIs.
- Preserve argv, multiline/large prompts and spaced paths. A short pane-run
  command executes a private mode-600 launcher in the external state directory;
  it removes itself before exec. Uncertain submissions leave the launcher intact
  and require inspection before retry. No automatic retry/fallback or pane cleanup.
- Herdr 0.9.5 tab focus returns tab_info; pane run acknowledges admission silently
  on exit 0. Submission is not evidence of agent readiness or completion.

Executable specs: tests/test_herdr.py covers context/selection, discovery, new and
existing tabs, geometry, literal large arguments, mode-600/self-removing launchers,
malformed/error/foreign responses, transport failures and timeout uncertainty.
A real isolated managed-pane smoke test passed on macOS with Herdr 0.9.5 and a
fixture agent. Other versions and agent-specific interactive UIs need separate
verification. Nothing installs agent integrations, changes keybindings or rewrites
the user's Herdr/tmux defaults.

## Full workspace startup: planned

A future portable `tw` equivalent calls the shared coordinator/Git interfaces.
Its specs must distinguish discovery, creation, fetching, branch updates and
cleanup. Each mutating operation needs a reviewable plan and live local guards.
Cached Jira/GitHub evidence never authorizes deletion. Dirty/untracked files,
unpushed/diverged commits and held branches need coverage before updates/removal
exist. Layout uses target-project commands; personal shell aliases, credentials,
Docker booking and company setup files must not become defaults.

## Deployment integration: current limit and second-provider criteria

`sidequest.environments.fetch_environments(numbers, run, pipeline)` reads Heroku
provisioning/runtime evidence through GET requests. It works headlessly without
UI imports or changes to `sys.path`. Tokens never enter results. Disabled
configuration requests no credentials; unavailable runtime evidence cannot claim
healthy application state.

Add a real second provider together with one normalized evidence contract:
provider identity, PR/commit association, deployment phase, observed URL/time and
explicit runtime health or unknown. Missing association, collection failure and
no deployment are distinct. GitHub deployment records alone never prove live
application health. Failures retain last-good data with its original timestamp.
UI cache keys/provider labels become neutral in that same change.

New review-app QA providers require their own allowed-host and redirect tests.
Explicit credentials and origin validation remain mandatory. This refactor does
not broaden the Heroku host allowlist or add a generic deployment registry.

Current executable specs: `tests/test_headless_integrations.py`, Heroku reader
tests, QA credential/host tests and source-retention tests. Planned provider
criteria require new failing executable specs before implementation.

## Document views: implemented

p opens Plan and d opens Updates; u remains Standup. Both views read the same
external ticket plan.md and never rewrite it. Explicit Updates/progress,
implementation notes/summary and QA/test/verification-result sections go to
Updates with their nested children. Peer planning sections return to Plan.
Unrecognized headings stay in Plan, and fenced Markdown examples never create
real sections. Missing updates are explicit; edits refresh both cached views.
Executable coverage: ticket-tui/test_plan_updates.py and real keyboard input in
ticket-tui/test_terminal.py.
