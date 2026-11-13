#!/usr/bin/env python3
"""sidequest projects: every project profile, with quick actions.

In a terminal: j/k choose a project; Enter or a attaches its tmux session (or builds it with
`sidequest up -n` when there is none); u runs `sidequest up`; r `sidequest up -r` (asks first: it
stops what runs in the windows); d a dry run; s asks for a ticket and runs `sidequest start`;
q opens its dashboard; c checks its settings; Esc quits. Without a terminal it prints the list.
Sidequest also opens this from `sidequest` or `sidequest up` outside every project folder when
there are several projects.
"""
import curses
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from sidequest import overview, terminal_mode
except ValueError as exc:
    print('sidequest projects: ' + str(exc), file=sys.stderr)
    raise SystemExit(2)

BIN = Path(__file__).resolve().parent
TITLE = 'Sidequest projects'


def ask(screen, prompt):
    height, width = screen.getmaxyx()
    screen.move(height - 1, 0)
    screen.clrtoeol()
    screen.addnstr(height - 1, 0, prompt, width - 1, curses.A_BOLD)
    curses.echo()
    curses.curs_set(1)
    try:
        text = screen.getstr(height - 1, min(len(prompt), width - 2), 40).decode(errors='replace').strip()
    finally:
        curses.noecho()
        curses.curs_set(0)
    return text


def choose(screen, rows):
    """(row, (kind, value)) for the chosen action, or None."""
    curses.curs_set(0)
    selected = 0
    while True:
        screen.erase()
        height, width = screen.getmaxyx()
        screen.addnstr(0, 1, TITLE, width - 2, curses.A_BOLD)
        for index, line in enumerate(overview.render(rows, selected, width - 2)[:max(height - 5, 0)]):
            screen.addnstr(2 + index, 1, line, width - 2, curses.A_REVERSE if line.startswith('> ') else 0)
        for index, line in enumerate(overview.HELP):
            if height - 2 + index > 2:
                screen.addnstr(height - 2 + index, 1, line, width - 2, curses.A_DIM)
        key = screen.get_wch()
        if key in ('\x1b',) or key == 27:
            return None
        if key in ('j', curses.KEY_DOWN):
            selected = min(selected + 1, len(rows) - 1)
            continue
        if key in ('k', curses.KEY_UP):
            selected = max(selected - 1, 0)
            continue
        if key == curses.KEY_ENTER:
            key = '\n'
        chosen = overview.action(key, rows[selected]) if isinstance(key, str) else None
        if not chosen:
            continue
        kind, value = chosen
        if kind == 'confirm':
            answer = ask(screen, 'Close ' + rows[selected]['terminal'] + ' session ' + rows[selected]['session'] +
                         ' and stop what runs in its windows? y/N ')
            if answer.lower() != 'y':
                continue
            kind = 'sidequest'
        if kind == 'ask_key':
            key_text = ask(screen, 'Ticket to start (APP-123 or a number): ')
            if not key_text:
                continue
            kind, value = 'sidequest', value + [key_text]
        return rows[selected], (kind, value)


def launch(row, chosen):
    kind, value = chosen
    os.environ['SIDEQUEST_PROJECT'] = row['name']
    if kind == 'attach':
        terminal_mode.sessions(row['terminal']).attach(value)
        return 0
    command = BIN / ('sidequest-data' if kind == 'data' else 'sidequest')
    sys.stdout.flush()
    os.execv(sys.executable, [sys.executable, str(command), *value])


def main():
    if set(sys.argv[1:]) & {'-h', '--help'}:
        print(__doc__.strip())
        return 0
    rows = overview.project_rows()
    if not rows:
        print('No projects yet. Adopt one: sidequest-data project init NAME --repo PATH')
        return 0
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print('\n'.join(overview.render(rows, None, 200)))
        return 0
    picked = curses.wrapper(choose, rows)
    return launch(*picked) if picked else 0


if __name__ == '__main__':
    raise SystemExit(main())
