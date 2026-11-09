# Workspace and integration specifications

Status: workspace coordination, shell/tmux/Herdr adapters and headless Heroku
lookup are implemented, and so is full startup orchestration (`sidequest up`, below) for tmux.
A Herdr layout and a second deployment provider remain planned contracts.

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

## Full workspace startup (`sidequest up`): implemented for tmux (Herdr layout planned), 2026-11-09

`sidequest up` prepares a project's workspace from its Jira tickets and GitHub PRs and opens
one terminal session for it, so the dashboard, Space n and the agent skills find each
ticket's worktree ready. It is the generic part of one project's `tw` script.

### Where it sits

| Part | New or changed |
| --- | --- |
| Entry points | `bin/sidequest up` (dispatches to `bin/sidequest-up.py`); `--project` as everywhere |
| Use cases | `sidequest/sync.py`: `discover()` → `SyncPlan` (immutable) → `apply(plan, ...)` |
| Local workspace (Git) | Reuses `GitWorkspace` for creation; new guarded update and removal helpers |
| Terminals | `open_layout(session, windows)` on the tmux and Herdr adapters |
| Data | Two read-only sources: `sync_tickets` (Jira, by `sync.tickets_jql`) and `merged_prs` (gh) |
| Settings | `sync` section (below); `workspace.windows`, `workspace.on_up` |
| Dashboard | Unchanged in phase 1-5; a later key may show the plan, never apply removal |

The dashboard refresh, the collector and tests never call `apply`. Removal and merging
happen only in `sidequest up`, a command the person runs.

### What one run does, in order

| Step | Changes | Default | Guards (checked live at apply time) |
| --- | --- | --- | --- |
| 1. Collect | Snapshots only | on | Failed sources keep their last data; a step that needs a failed source is skipped and reported |
| 2. Fetch | `git fetch origin` (read-only for local branches) | on; `--no-fetch` | A failed fetch skips steps 5 and 6 |
| 3. Create | A worktree for each sync ticket and each of your open PRs that has none; branch reuse (local, then origin), `fix/` for Bugs, `copy_files` | on | Same as Space n: existing destinations and checkouts are never overwritten; a ticket with a merged PR is skipped |
| 4. Order and open | One window per worktree, ordered by first assignment (PRs without a ticket: opened date), plus `workspace.windows`; then `workspace.on_up` | on | Existing windows are reused and moved, never closed by this step |
| 5. Update | Fast-forward a branch to its own origin branch; `main` follows `origin/main`; rebase a never-pushed branch onto the base | on | Skip and report when: a merge/rebase/cherry-pick is in progress, the app is booked for it, an agent process's cwd is inside it, the branch diverged from its origin. `--autostash`; on conflict abort and leave the worktree as it was |
| 6. Merge the base into pushed branches | `git merge origin/<base>` (the team's merge commit) | off; `--update` | Step 5's guards; abort on conflict; never push |
| 7. Remove merged | Remove the worktree, then delete its local branch; close its window | off; `--cleanup`, which asks per worktree (`--yes` for no questions) | Never the main checkout or the caller's cwd; skip when there are uncommitted or untracked changes, an agent or app booking holds it, or the branch has a commit that is not in the merged PR's head (`merge-base --is-ancestor branch head`). The PR's merged state and head are read from GitHub at apply time: a snapshot alone never authorizes removal. `git worktree remove` without `--force` |

`--dry-run` prints the plan (every action with its reason, every skip with its guard) and
changes nothing. Each applied action prints one line; the run ends with a summary and exit
status 0 (all done), 1 (something skipped or failed and reported) or 2 (usage or settings).

### Settings

```json
"sync": {
  "tickets_jql": "assignee = currentUser() AND statusCategory != Done",
  "open_prs": "on",
  "update": "off",
  "cleanup": "ask"
},
"workspace": {
  "windows": [{"name": "report", "command": "sidequest --report"}],
  "on_up": ["~/project/tools/sync-agent-rules -q"]
}
```

`update` (`off` | `on`) and `cleanup` (`off` | `ask` | `on`) set the defaults that `--update`,
`--cleanup` and `--yes` override for one run. `cleanup: on` matches a tool that removes merged
worktrees on every run; it keeps every guard.

### Tests (each written before its code, real temporary Git repositories, fake gh/Jira)

1. `--dry-run` lists create/update/remove/skip lines and leaves the repository byte-for-byte unchanged.
2. Create: sync tickets and open PRs get worktrees; branch reuse local then origin; `fix/` for a Bug;
   a ticket with a merged PR is skipped; an existing checkout is reused.
3. Order: windows follow first-assignment time; extra windows from settings; existing windows are moved, not closed.
4. Update: fast-forward; `main` follows `origin/main`; unpushed branch rebased; a diverged branch, an
   in-progress merge, a booked app and an agent cwd each skip with their reason; a conflict is aborted
   and the worktree matches its earlier state.
5. `--update`: a pushed branch gets the merge commit; a conflict aborts it; nothing is pushed.
6. Cleanup: dirty, untracked, extra commit, caller cwd, main checkout and booked app each keep the
   worktree; a PR that GitHub no longer reports as merged keeps it; `ask` removes only after yes.
7. A failed Jira or GitHub source skips the steps that need it and never removes anything.
8. The dashboard refresh and the collector never import `sync.apply` (codebase review test).

### Phases

1. Data: `sync_tickets` and `merged_prs` sources, read-only (tests 7). Done 2026-11-09: `collect(sync=True)`
   only; a normal refresh keeps them as they are; `sync` settings validated.
2. Plan and create with `--dry-run` (tests 1, 2). Done 2026-11-09: `sidequest up [--dry-run] [--offline]`;
   `GitWorkspace.preview_branch` reuses a PR's existing branch (never the base branch) and `apply` re-checks it.
3. Session: windows, order, `workspace.windows`, `on_up`; tmux first, Herdr after (test 3). Done 2026-11-09 for
   tmux: `tmux.open_layout`, `sync.layout`, assignment dates kept in the state folder (`window-order.json`),
   `workspace.windows` entries {name, command?, cwd?, at?, stay?, keys?}; Herdr still reports "not supported yet".
4. Update and `--update` (tests 4, 5). Done 2026-11-09: `sidequest/updates.py` (Git only; the app booking and
   agent checks come in as `busy(path)` from `sync.busy_check`); updates run only after a successful fetch.
5. Cleanup (tests 6, 8). Done 2026-11-09: `sidequest/cleanup.py`, `github.pr_state` (asked at removal time),
   `sync.confirm_removal`; the boundary test reads the dashboard's and collector's imports.
6. One project's `tw` becomes `sidequest up --project NAME`; its own extra windows and hooks move to its profile.
   Done 2026-11-09: that script is now a 79-line front (flags mapped, `start` built from Sidequest commands).

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
