"""`sidequest up`: plan a project's worktrees from its snapshot, then apply the plan.

discover() reads the snapshot and local Git only and returns an immutable plan; apply() creates
the planned worktrees through GitWorkspace.apply, which inspects again and refuses a plan the
repository has moved past. The dashboard refresh and the collector never call apply().
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from sidequest.ticket_keys import branch_keys
from sidequest.workspace import GitWorkspace, WorkspacePlan

KINDS = ('create', 'exists', 'skip', 'blocked')  # blocked: something is wrong and is reported (exit 1)


@dataclass(frozen=True)
class Action:
    kind: str
    target: str
    reason: str = ''
    branch: str = ''
    path: str = ''
    plan: Optional[WorkspacePlan] = None

    @property
    def line(self):
        detail = ' '.join(filter(None, (self.branch, ('→ ' + self.path) if self.path else '', self.reason)))
        return (self.kind.ljust(8) + ' ' + self.target.ljust(12) + ' ' + detail).rstrip()


@dataclass(frozen=True)
class Result:
    target: str
    ok: bool
    line: str


def source(snapshot, name, key):
    """(rows, problem): a source's rows, or why it cannot be used."""
    failure = (snapshot.get('failures') or {}).get(name)
    if failure:
        return [], failure
    data = (snapshot.get('sources') or {}).get(name)
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        return [], 'no ' + name + ' data yet; run sidequest up without --offline'
    return data[key], ''


def _planned(workspace, target, summary='', issue_type='', reason='', branch=False):
    try:
        plan = workspace.preview_branch(target) if branch else workspace.preview(target, summary, issue_type)
    except (RuntimeError, ValueError) as exc:
        return Action('blocked', target, str(exc))
    if plan.state in ('worktree', 'main-checkout'):
        return Action('exists', target, reason, plan.branch, plan.path)
    return Action('create', target, reason, plan.branch, plan.path, plan)


def discover(snapshot, workspace: GitWorkspace, open_prs=True):
    """The plan: one action per sync ticket and per open PR of yours (forks left out)."""
    actions, planned_branches = [], set()
    merged, problem = source(snapshot, 'merged_prs', 'prs')
    if problem:
        actions.append(Action('blocked', 'merged PRs', problem + ' (tickets with a merged PR cannot be told apart)'))
        return actions
    merged_by_key = {}
    for pr in merged:
        for key in branch_keys(pr.get('branch') or ''):
            merged_by_key.setdefault(key, pr)
    tickets, problem = source(snapshot, 'sync_tickets', 'tickets')
    if problem:
        actions.append(Action('blocked', 'tickets', problem))
    for ticket in tickets:
        key = ticket['key']
        if key in merged_by_key:
            actions.append(Action('skip', key, 'already merged in PR #' + str(merged_by_key[key].get('number'))))
            continue
        action = _planned(workspace, key, ticket.get('summary') or '', ticket.get('issue_type') or '')
        planned_branches.add(action.branch)
        actions.append(action)
    if open_prs:
        prs, problem = source(snapshot, 'prs', 'open_prs')
        if problem:
            actions.append(Action('blocked', 'open PRs', problem))
        for pr in prs:
            branch = pr.get('branch') or ''
            if not branch or pr.get('is_cross_repository') or branch in planned_branches:
                continue
            action = _planned(workspace, branch, reason='PR #' + str(pr.get('number')), branch=True)
            planned_branches.add(action.branch)
            actions.append(action)
    return actions


@dataclass(frozen=True)
class Window:
    name: str
    path: str
    command: Optional[str] = None
    end: bool = False
    keys: str = ''
    stay: bool = False


def _window_name(branch, path):
    keys = branch_keys(branch or '')
    if keys:
        return keys[0]
    return (branch or '').replace('/', '-') or Path(path).name


def remember_order(path, snapshot, save=True):
    """Assignment dates by ticket key, kept in `path` across runs so a ticket that leaves your list
    (handed to review or QA) keeps its window's place; today's snapshot wins for keys it has.
    save=False (a dry run) returns the same dates and writes nothing."""
    try:
        dates = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        dates = {}
    if not isinstance(dates, dict):
        dates = {}
    for row in (((snapshot or {}).get('sources') or {}).get('jira') or {}).get('tickets') or []:
        if row.get('key') and row.get('first_assigned_at'):
            dates[row['key']] = row['first_assigned_at']
    if save:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(dates, indent=2, sort_keys=True) + '\n')
    return dates


def _moment(value):
    """Seconds since the epoch for an ISO time with an offset, or None."""
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment.timestamp() if moment.tzinfo else None


def fresh(snapshot, every_minutes, now=None, tz='UTC'):
    """A line saying the last sync is newer than every_minutes, or '' when a sync is due."""
    if not str(every_minutes or '').isdigit() or not int(every_minutes):
        return ''
    stamp = ((snapshot.get('sources') or {}).get('sync_tickets') or {}).get('generated_at')
    last, current = _moment(stamp), _moment(now) if now else datetime.now(timezone.utc).timestamp()
    if last is None or current - last >= int(every_minutes) * 60:
        return ''
    zone = ZoneInfo(tz)
    at = datetime.fromtimestamp(last, zone)
    return ('fresh    last sync ' + at.strftime('%H:%M') + '; next sync after ' +
            (at + timedelta(minutes=int(every_minutes))).strftime('%H:%M') + ' (sync.every_minutes ' + str(every_minutes) + ')')


def extra_window(entry, root):
    """A Window from one {name, command?, cwd?, at?, stay?, keys?} entry; cwd defaults to `root`."""
    return Window(entry['name'], str(Path(entry.get('cwd') or root).expanduser()), entry.get('command'),
                  entry.get('at') == 'end', entry.get('keys') or '', bool(entry.get('stay')))


def personal_sessions(sessions, project_session, home):
    """[(name, windows or None, note)] for the `sessions` setting, in order; a name the project's own
    session uses is skipped (windows None) so the two never mix."""
    rows = []
    for name, entries in (sessions or {}).items():
        if name == project_session:
            rows.append((name, None, 'skipped: this project already uses that tmux session'))
            continue
        windows = [extra_window(entry, home) for entry in entries if entry.get('at') != 'end'] + \
                  [extra_window(entry, home) for entry in entries if entry.get('at') == 'end']
        rows.append((name, windows, ''))
    return rows


def layout(snapshot, worktrees, extras, root, remembered=None):
    """The session's windows in order: extras at the start, the main checkout, then one window per
    worktree by the date the ticket was first assigned to you (a PR without a ticket: when it was
    opened; unknown dates after, by ticket number), then extras at the end.

    worktrees: [(path, branch)] from `git worktree list`, the main checkout first.
    extras: workspace.windows entries {name, command?, cwd?, at? (start|end), stay?, keys?}."""
    sources = (snapshot or {}).get('sources') or {}
    assigned = {row.get('key'): row.get('first_assigned_at') for row in (sources.get('jira') or {}).get('tickets') or []}
    opened = {row.get('branch'): row.get('created_at') for row in (sources.get('prs') or {}).get('open_prs') or []}

    start = [extra_window(entry, root) for entry in extras if entry.get('at') != 'end']
    end = [extra_window(entry, root) for entry in extras if entry.get('at') == 'end']
    windows = []
    if worktrees:
        path, branch = worktrees[0]
        keys = branch_keys(branch or '')
        windows.append(Window('Main ' + keys[0] if keys else 'Main', path))
    ranked = []
    for index, (path, branch) in enumerate(worktrees[1:]):
        name = _window_name(branch, path)
        date = _moment(assigned.get(name) or (remembered or {}).get(name) or opened.get(branch))
        number = int(name.rsplit('-', 1)[1]) if branch_keys(branch or '') else 0
        rank = (0, date, number) if date else (1, 0, number) if number else (2, 0, index)
        ranked.append((rank, Window(name, path)))
    return start + windows + [window for _, window in sorted(ranked, key=lambda row: row[0])] + end


def busy_check(booking, agent_dirs):
    """busy(path) for the branch updates: why updating that worktree now could get in someone's way."""
    def busy(path):
        root = str(Path(path))
        if booking.get('state') == 'booked' and str(Path(booking.get('path') or '')) == root:
            return 'the app is booked for it (tests running?)'
        if any(folder == root or folder.startswith(root + '/') for folder in agent_dirs):
            return 'an agent is working in it'
        return ''
    return busy


def agent_dirs():
    """Working folders of running coding agents (claude, codex, opencode); [] when lsof is missing."""
    import subprocess
    try:
        listed = subprocess.run(['lsof', '-a', '-d', 'cwd', '-c', 'claude', '-c', 'codex', '-c', 'opencode', '-Fn'],
                                capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line[1:] for line in listed.splitlines() if line.startswith('n')]


def confirm_removal(mode, yes, interactive, ask=input):
    """confirm(candidate) for cleanup: `on` or --yes removes; `ask` asks in a terminal and keeps
    everything when there is no terminal to ask in."""
    def confirm(candidate):
        if yes or mode == 'on':
            return True
        if not interactive:
            return False
        answer = ask('Remove ' + candidate['name'] + ' (PR #' + str(candidate.get('number')) + ' merged, ' +
                     str(candidate.get('path')) + ')? [y/N] ')
        return answer.strip().lower() in ('y', 'yes')
    return confirm


def apply(actions, workspace: GitWorkspace):
    """Create each planned worktree; every action is checked again first. Nothing is removed."""
    results = []
    for action in actions:
        if action.kind != 'create':
            results.append(Result(action.target, action.kind != 'blocked', action.line))
            continue
        try:
            made = workspace.apply(action.plan)
        except (RuntimeError, ValueError, OSError) as exc:
            results.append(Result(action.target, False, 'failed   ' + action.target.ljust(12) + ' ' + str(exc)))
            continue
        copied = ', '.join(made.get('copied') or [])
        results.append(Result(action.target, True, 'created  ' + action.target.ljust(12) + ' ' + made['branch'] +
                              ' → ' + made['path'] + (' (copied ' + copied + ')' if copied else '')))
    return results
