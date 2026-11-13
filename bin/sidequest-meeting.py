#!/usr/bin/env python3
"""sidequest meeting: run your meeting companion beside the dashboard, then show what it wrote.

  sidequest meeting                 a general meeting: no ticket context
  sidequest meeting KEY             a ticket meeting: the command also gets the ticket's notes
                                    Inside tmux both open a pane below this one (40% of its height)
                                    that runs meeting.command; an open meeting pane is selected
                                    instead. Outside tmux they run in this terminal.
  sidequest meeting --here [KEY]    run meeting.command in this terminal

meeting.command is your own transcriber or notes tool, run with /bin/sh in workspace.repository
(else the tickets folder). It gets SIDEQUEST_TICKETS_DIR. With a KEY it also gets SIDEQUEST_TICKET and
SIDEQUEST_TICKET_CONTEXT: a private temporary file with the ticket's plan.md, questions.md and earlier
meetings.md, removed when the command exits. It also gets JIRA_URL, JIRA_EMAIL and JIRA_API_TOKEN from
the project (jira.site, jira.email, credentials.jira) when they are set, and SIDEQUEST_WORKTREES_DIR
(workspace.worktrees_dir, else the repository's parent folder). The command is
expected to append `## <date> · <scope>` sections to <tickets>/<KEY>/meetings.md. When it exits,
the newest section of every meetings.md it changed is printed as the meeting summary; the
dashboard's Meetings tab (m) shows the same file. Sidequest itself records nothing.
Exit 0: done; 2: usage or settings; otherwise the command's own exit status.
"""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest.project_flag import take

take(sys.argv)
try:
    from sidequest import config, meeting
except ValueError as exc:
    print('sidequest meeting: ' + str(exc), file=sys.stderr)
    raise SystemExit(2)
from sidequest.qa import tickets_dir


def folder():
    path = Path(config.workspace_repository() or tickets_dir()).expanduser()
    return path if path.is_dir() else tickets_dir()


def run_here(command, key):
    tickets = tickets_dir()
    tickets.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ('SIDEQUEST_TICKET', 'SIDEQUEST_TICKET_CONTEXT')}
    env['SIDEQUEST_TICKETS_DIR'] = str(tickets)
    repository = config.workspace_repository()
    trees = config.get('workspace', 'worktrees_dir') or (Path(repository).expanduser().parent if repository else '')
    if trees:
        env['SIDEQUEST_WORKTREES_DIR'] = str(Path(trees).expanduser())
    from sidequest import credentials
    for name, value in (('JIRA_URL', config.get('jira', 'site').rstrip('/')), ('JIRA_EMAIL', config.get('jira', 'email')),
                        ('JIRA_API_TOKEN', credentials.secret('jira') if config.get('jira', 'site') else None)):
        if value:
            env[name] = value
    brief = None
    if key:
        env['SIDEQUEST_TICKET'] = key
        handle, brief = tempfile.mkstemp(prefix='sidequest-meeting-' + key + '-', suffix='.md')
        with os.fdopen(handle, 'w') as out:
            out.write(meeting.context(key, tickets / key))
        env['SIDEQUEST_TICKET_CONTEXT'] = brief
    since = time.time() - 1
    # Ctrl-C belongs to the companion (it may write its summary on it); this script still prints after.
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        status = subprocess.run(['/bin/sh', '-c', command], cwd=str(folder()), env=env,
                                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL)).returncode
    finally:
        signal.signal(signal.SIGINT, previous)
        if brief:
            Path(brief).unlink(missing_ok=True)
    print('\n── Meeting summary ──\n' + meeting.summary(meeting.changed_since(tickets, since)))
    if sys.stdin.isatty():
        try:
            input('\nPress Enter to close.')
        except EOFError:
            pass
    return status


def main():
    parser = argparse.ArgumentParser(prog='sidequest meeting', description=__doc__.split('\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument('key', nargs='?', default='', help='the ticket the meeting is about, such as APP-123')
    parser.add_argument('--here', action='store_true', help='run in this terminal, not in a new pane')
    args = parser.parse_args()
    command = config.get('meeting', 'command')
    if not command:
        print('sidequest meeting: set meeting.command (or SIDEQUEST_MEETING_COMMAND) to your meeting '
              'companion, for example "meeting"', file=sys.stderr)
        return 2
    key = ''
    if args.key:
        from sidequest.start import full_key
        try:
            key = full_key(args.key, config.get('jira', 'projects', []))
        except ValueError as exc:
            print('sidequest meeting: ' + str(exc), file=sys.stderr)
            return 2
    if not args.here and os.environ.get('TMUX') and os.environ.get('TMUX_PANE'):
        from sidequest.terminal_mode import run_tmux
        argv = meeting.pane_argv(sys.executable, Path(__file__).resolve(), key, config.PROJECT or '')
        try:
            print(meeting.open_pane(run_tmux, os.environ['TMUX_PANE'], str(folder()), argv))
        except RuntimeError as exc:
            print('sidequest meeting: ' + str(exc), file=sys.stderr)
            return 1
        return 0
    return run_here(command, key)


if __name__ == '__main__':
    raise SystemExit(main())
