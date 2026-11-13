#!/usr/bin/env python3
"""sidequest crew: a manager agent for every ticket, and one worker agent per ticket worktree.

  sidequest crew                    open the manager (crew.manager_command) in a pane below this
                                    one (40% of its height) in tmux or Herdr, else in this terminal
  sidequest crew APP-1 APP-2        start a worker (crew.worker_command) in each ticket's worktree
                                    window; it runs start, implement, qa-local and ship-check and
                                    stops when it needs you or is ready; after a ready ship-check it
                                    starts the challenger (crew.challenge_command, default Opus),
                                    which assumes the work is wrong and checks it before you ship
  sidequest crew --status           every worker's step and state, the ones waiting on you first
  sidequest crew APP-1 --after-stop the worker's Stop hook: starts the challenger only when ship-check
                                    is ready; always exits 0

A worker or challenger recorded as working or queued whose tmux pane is gone starts again without --again.

In tmux a ticket keeps one worker pane and one challenger pane; a later request for that ticket is
pasted into the open pane's agent session instead of a new split ("prompt sent to the open worker pane").
Workers report through `sidequest-data run`; the dashboard shows it on the card and in AI mode (6).
Tickets assigned to someone else, in a crew.skip_statuses Jira status (review, QA, Approved, Blocked, Done),
or whose Jira lookup failed are skipped unless --again; unassigned tickets start. Workers never commit, push, open PRs or post. Exit 0: done; 1: a ticket was skipped; 2: usage or settings.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest.project_flag import take

take(sys.argv)
try:
    from sidequest import config, crew, runs
except ValueError as exc:
    raise SystemExit('sidequest crew: ' + str(exc))
from sidequest.qa import tickets_dir
from sidequest.skills import DATA

SIDEQUEST = shlex.quote(str(ROOT / 'bin' / 'sidequest'))
MANAGER_WINDOW = 'Crew'
# Statuses where the ticket is with reviewers, QA or a blocker, not the person; crew.skip_statuses overrides.
SKIP_STATUSES = ('Ready for Code Review,In Code Review,Code Review,Ready for QA,In QA,Approved,Blocked,Done,'
                 'Closed,In Review,QA,Testing,In Testing,Ready for Production,Ready to Deploy,Resolved,'
                 'Ready for Stakeholder Review,In Stakeholder Review,Archived')


def jira_ticket(key):
    """Status and assignee from Jira (read-only), or None when the lookup fails."""
    try:
        out = subprocess.run([str(ROOT / 'bin' / 'sidequest-data'), 'ticket', key, '--json'],
                             capture_output=True, text=True, timeout=30, check=True).stdout
        return json.loads(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def waiting_reason(ticket, skip_statuses):
    if not ticket:
        return "could not read the ticket from Jira"
    if ticket.get('assignee_ok') is False and ticket.get('assignee') != 'Unassigned':
        return f"assigned to {ticket.get('assignee') or 'someone else'} in Jira"
    status = ticket.get('status') or ''
    if status.casefold() in {s.strip().casefold() for s in skip_statuses.split(',') if s.strip()}:
        return f"Jira status is {status}; it is with someone else"
    return None


def jira_tickets(keys):
    if not keys:
        return {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(keys, pool.map(jira_ticket, keys)))


def jira_statuses(keys):
    return {key: t.get('status') for key, t in jira_tickets(keys).items() if t and t.get('status')}


def read_quietly(key):
    try:
        return runs.read(tickets_dir() / key / 'run.json')
    except (OSError, ValueError):
        return None



def find_worktree(key):
    from sidequest.worktrees import lookup
    repository = config.workspace_repository()
    if not repository:
        return {'state': 'none'}

    def git(*args):
        return subprocess.run(['git', '-C', repository, *args], capture_output=True, text=True, check=True).stdout
    try:
        names = git('for-each-ref', '--format=%(refname:lstrip=2)', 'refs/heads')
        return lookup(key, git('worktree', 'list', '--porcelain'), names.splitlines())
    except (OSError, subprocess.CalledProcessError):
        return {'state': 'none'}


def workflow():
    from sidequest.application import build_workflow
    from sidequest.terminal import ShellTerminal
    flow = build_workflow(config.SETTINGS, os.environ)
    return flow, isinstance(flow.terminal, ShellTerminal)


def worker_launcher(flow, worker, data, agent='worker'):
    """Workers start in the background: the person stays in the window they are in. In tmux each
    ticket keeps one pane per agent: a later request goes to the open pane's session, and launch
    returns True so dispatch reports the prompt as sent, not a new start."""
    from sidequest import tmux
    from sidequest.terminal import TmuxTerminal, agent_argv, agent_display_name

    def launch(key, path, prompt):
        flow.agent_command = crew.worker_command(worker, key, data, SIDEQUEST)
        terminal = getattr(flow, 'terminal', None)
        if isinstance(terminal, TmuxTerminal):
            argv, role = agent_argv(prompt, flow.agent_command), f'crew-{agent}:{key}'
            reused = tmux.role_pane(terminal.run, terminal.session, role) is not None
            tmux.start_agent(terminal.run, key, path, argv, True, terminal.session,
                             agent_display_name(argv), focus=False, role=role)
            return reused
        return flow.agent(key, path, prompt, focus=False).message
    return launch


def pane_alive(flow):
    """alive(key, agent) for dispatch: tmux knows whether a crew pane is open; other terminals do not."""
    from sidequest import tmux
    from sidequest.terminal import TmuxTerminal
    terminal = getattr(flow, 'terminal', None)
    if not isinstance(terminal, TmuxTerminal):
        return None
    return lambda key, agent: tmux.role_pane(terminal.run, terminal.session, f'crew-{agent}:{key}') is not None



def open_manager(flow, in_shell, environ=os.environ):
    """The manager opens in a pane below the caller's pane (40% of its height) inside tmux or Herdr;
    a tmux pane that is already open is selected instead."""
    from sidequest import tmux
    from sidequest.terminal import TmuxTerminal, agent_argv, run_request
    folder = tickets_dir()
    folder.mkdir(parents=True, exist_ok=True)
    command = config.get('crew', 'manager_command') or crew.DEFAULT_MANAGER
    if config.PROJECT:
        command = 'env SIDEQUEST_PROJECT=' + shlex.quote(config.PROJECT) + ' ' + command
    flow.agent_command = command
    argv = agent_argv(crew.manager_prompt(DATA, SIDEQUEST), command)
    if isinstance(flow.terminal, TmuxTerminal) and environ.get('TMUX_PANE'):
        print(tmux.open_below(flow.terminal.run, environ['TMUX_PANE'], str(folder), argv, 'crew'))
        return 0
    if hasattr(flow.terminal, 'split_below'):
        print(flow.terminal.split_below(str(folder), argv).message)
        return 0
    session = getattr(flow.terminal, 'session', None)
    if session:
        for line in tmux.list_panes(flow.terminal.run).splitlines():
            parts = line.split('\t')
            if len(parts) == 4 and parts[0] == session and parts[2] == MANAGER_WINDOW:
                flow.terminal.run(['tmux', 'select-window', '-t', parts[1]], timeout=5)
                print('Switched to the ' + MANAGER_WINDOW + ' window')
                return 0
    result = flow.agent(MANAGER_WINDOW, str(folder), crew.manager_prompt(DATA, SIDEQUEST))
    if in_shell and result.foreground:
        return run_request(result.foreground)
    print(result.message)
    return 0


def main():
    parser = argparse.ArgumentParser(prog='sidequest crew', description=__doc__.split('\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument('keys', nargs='*', help='ticket keys such as APP-123, or only their numbers')
    parser.add_argument('--status', action='store_true', help='print every worker and exit')
    parser.add_argument('--again', action='store_true',
                        help='start a worker even when one is recorded as running, or the ticket is with someone else')
    parser.add_argument('--dry-run', action='store_true', help='show what would start; launch nothing')
    parser.add_argument('--after-stop', action='store_true',
                        help="worker Stop hook: start the challenger only after a ready ship-check; always exits 0")
    args = parser.parse_args()
    clock = datetime.now(timezone.utc)
    if args.status:
        records = runs.all_records(tickets_dir())
        print('\n'.join(runs.table(records, clock, jira_statuses([r['key'] for r in records]))))
        return 0
    from sidequest.start import full_key
    try:
        keys = [full_key(key, config.get('jira', 'projects', [])) for key in args.keys]
        if args.after_stop and not (keys and all(crew.challenge_due(read_quietly(key)) for key in keys)):
            return 0
        flow, in_shell = (None, False) if args.dry_run else workflow()
    except (RuntimeError, ValueError) as exc:
        print('sidequest crew: ' + str(exc), file=sys.stderr)
        return 0 if args.after_stop else 2
    if not keys:
        try:
            return open_manager(flow, in_shell)
        except RuntimeError as exc:
            print('sidequest crew: ' + str(exc), file=sys.stderr)
            return 1
    if in_shell:
        print('sidequest crew: workers need their own windows; run this inside tmux or Herdr (sidequest up)',
              file=sys.stderr)
        return 0 if args.after_stop else 2
    launch = worker_launcher(flow, config.get('crew', 'worker_command') or crew.DEFAULT_WORKER, DATA)
    challenger = worker_launcher(flow, config.get('crew', 'challenge_command') or crew.DEFAULT_CHALLENGER, DATA,
                                 'challenger')
    skip = config.get('crew', 'skip_statuses') or SKIP_STATUSES
    found = {} if args.again else jira_tickets(keys)
    try:
        lines, skipped = crew.dispatch(keys, find_worktree, tickets_dir(), launch, DATA,
                                       clock.isoformat(timespec='seconds'), args.again, args.dry_run,
                                       waiting=lambda key: waiting_reason(found.get(key), skip),
                                       challenger=challenger, alive=pane_alive(flow))
    except RuntimeError as exc:
        print('sidequest crew: ' + str(exc), file=sys.stderr)
        return 0 if args.after_stop else 1
    print('\n'.join(lines))
    return 1 if skipped and not args.after_stop else 0


if __name__ == '__main__':
    raise SystemExit(main())
