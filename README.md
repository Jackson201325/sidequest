# Sidequest

A keyboard-driven attention queue for Jira tickets and GitHub pull requests, with
optional Heroku review-app status and local Git evidence. It shows whose turn it
is, how long a handoff has waited, and which evidence supports the next action.

Python 3.9+ on macOS or Linux. Uses only Python's standard library and curses.
No company checkout, team scripts, shell aliases or background jobs are required.

```sh
git clone https://github.com/Jackson201325/sidequest.git
cd sidequest
```

```sh
./bin/sidequest --demo
./bin/sidequest --demo --list
```

The demo uses fictional tickets in memory and disables external actions. Run it
before configuring any accounts. The launcher is local to this project; it does
not install or replace commands elsewhere on your machine.

## Configure your services

Configuration is optional. Without it, the live queue starts empty and makes no
service requests. Copy the example outside the repository and replace its
placeholders. Remove any service section you do not use.

```sh
mkdir -p ~/.config/sidequest
cp config.example.json ~/.config/sidequest/config.json
```

Set `SIDEQUEST_CONFIG=/absolute/path/config.json` to use another configuration file.
XDG_CONFIG_HOME, XDG_DATA_HOME and XDG_STATE_HOME are supported. The namespace
`sidequest` keeps this project separate from other installations.

| Setting | Purpose |
| --- | --- |
| `identity.display_name` | Your display name |
| `identity.git_author` | Git author name used to select your local commits |
| `identity.timezone` | IANA timezone for dates and business time; default UTC |
| `jira.site` | Your Jira Cloud HTTPS origin |
| `jira.email` | Email for Jira API-token authentication |
| `jira.account_id` | Optional; otherwise read from Jira's `/myself` endpoint |
| `jira.cloud_id` | Optional cloud ID for scoped API tokens |
| `jira.projects` | Optional project keys; an empty list includes all your projects |
| `github.repository` | Repository in `owner/name` form |
| `github.username` | Your GitHub login; defaults to the authenticated gh user |
| `heroku.pipeline` | Optional review-app pipeline ID; blank disables Heroku |
| `workspace.repository` | Optional local Git repository to inspect; blank disables local scans |
| `workspace.plans_dir` | Optional folder containing `APP-123/plan.md` |
| `workspace.tmux_session` | Session used for explicit window jumps and agent launches |
| `workspace.browser` | Optional browser command; otherwise the OS default opener |

Jira reads the token from `SIDEQUEST_JIRA_TOKEN` in the process environment. Supply
it through your terminal or secret manager. Tokens are never configuration fields.
This project does not read macOS Keychain entries. GitHub uses `gh` and your own
`gh auth login`. Heroku uses `SIDEQUEST_HEROKU_TOKEN` or `heroku auth:token`, only
when a pipeline is configured. Login credentials and tokens are never copied,
saved in snapshots or included in this repository.

```sh
./bin/sidequest-data collect --json
./bin/sidequest
./bin/sidequest --refresh
./bin/sidequest --refresh --list
./bin/sidequest --standup
```

Jira and GitHub work independently. The queue includes assigned open Jira tickets
and your authored open PRs; linked PR tickets are also read from Jira. Arbitrary
project keys such as `APP-123` work. Existing status names are mapped to common
development, review, QA and release stages; unfamiliar statuses retain an honest
ownership/clarification fallback.

## Keys

| Key | Action |
| --- | --- |
| `j/k`, arrows | Move through tickets or scroll details |
| `h/l`, Enter | Switch between the ticket list and details |
| `1`–`4` | All, Needs me, Waiting, Clarify |
| `/` | Search |
| `a/p/v/s/f/u` | Activity, Plan, Overview, Work log, Flow, Standup |
| `o/O` | Pick or reverse a sort |
| `+/-`, `=` | Resize sections or reset the split |
| `r` | Refresh configured Jira and GitHub sources |
| `e` | Refresh optional Heroku review-app status |
| Space `j/o` | Open the Jira ticket or PR |
| `w` | Jump to an existing ticket window in the configured tmux session |
| Space `s` | Explicitly launch Claude Code in a local worktree with a selected prompt |
| `y` | Copy the standup with macOS pbcopy; `--standup` prints it on any platform |
| `?`, `q` | Help, quit |

The queue does not change tickets, create worktrees, push, deploy or post comments.
An agent launched explicitly with Space `s` is a separate program operating in the
selected repository. It does not load private company skills from this project.

WAIT uses Monday–Friday 09:00–17:00 in the configured timezone, excluding nights
and weekends. Holidays are not excluded. Jira status history and first assignment
set the clock; missing history uses a labeled observation fallback. Jira handoffs
take precedence over old PR feedback. Failed sources keep their previous data and
timestamps, while successful sources can advance.

## Local storage and reports

- Configuration: `~/.config/sidequest/config.json`.
- UI cache: `~/.local/share/sidequest/tickets.sqlite3`.
- Snapshots: `~/.local/state/sidequest/snapshots/`.
- Optional plans: `~/.local/state/sidequest/tickets/APP-123/plan.md`.

Snapshots can contain private ticket text and local paths. They stay outside the
source tree and must not be committed. `--data-dir` and `--snapshots` override
the storage locations. The demo writes no persistent state.

`--update-report` updates only the Standup section of a report you supply at
`reports/YYYY-MM-DD.md`, beside the snapshots directory. It keeps written text,
adds newly discovered Today items, and backs up the report. If today's report
does not exist, it prints the draft and exits 3. There is no report scheduler.

## Development

```sh
./bin/check
```

Checks use temporary storage, fictional identities, mocked services and a real
pseudo-terminal for curses input. No live account or company repository is needed.
See [DEVELOPMENT.md](DEVELOPMENT.md) and [HARDENING.md](HARDENING.md).

Limits: fewer than 100 authored open PRs per refresh; reaching the limit is an
explicit failure, preserving the previous PR source. GitHub discussion, review,
commit and unresolved-thread pages are collected separately; reaching the REST
API's 250-commit cap also fails explicitly. Local work-log
scans cover 90 days and use `origin/main` as their branch baseline. Native Windows
is not supported. Live service permissions and custom board workflows need
verification with each user's own accounts.
