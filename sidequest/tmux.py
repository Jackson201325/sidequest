"""tmux operations on already-selected checkouts; no Git or UI imports."""
import os
import shlex
import subprocess
import sys

from sidequest.ticket_keys import mentions

PANE_FORMAT = '#{session_name}\t#{window_id}\t#{window_name}\t#{pane_current_path}'


def find_window(panes, key, path, session):
    candidates = []
    root = path.rstrip('/')
    for line in panes.splitlines():
        parts = line.split('\t', 3)
        if len(parts) != 4:
            continue
        current_session, wid, title, current_path = parts
        if current_session != session:
            continue
        path_match = bool(root and (current_path == root or current_path.startswith(root + '/')))
        name_match = key.upper() in mentions(title)
        if path_match or name_match:
            # The worktree folder first, then the ticket's own name, then the oldest window (ids are @N).
            number = int(wid[1:]) if wid[1:].isdigit() else float('inf')
            candidates.append((not path_match, not name_match, number, wid, title))
    return min(candidates)[3:] if candidates else None


def split_command(window_id, path, argv, detached=False):
    return ['tmux', 'split-window', *(['-d'] if detached else []), '-h', '-t', window_id, '-c', path, shlex.join(argv)]


def window_command(key, path, argv, session, session_exists=True, detached=False):
    command = shlex.join(argv)
    if session_exists:
        return ['tmux', 'new-window', *(['-d'] if detached else []), '-t', session + ':', '-n', key, '-c', path, command]
    return ['tmux', 'new-session', '-d', '-s', session, '-n', key, '-c', path, command]


def list_panes(run):
    return run(['tmux', 'list-panes', '-a', '-F', PANE_FORMAT], timeout=5)


def switch_client(run, inside, session):
    if inside:
        run(['tmux', 'switch-client', '-t', session], timeout=5)
        return None
    return session


def jump(run, key, path, inside, session):
    target = find_window(list_panes(run), key, path, session)
    if not target:
        raise RuntimeError('No existing tmux window for ' + key + '; open a window in the configured session')
    wid, title = target
    run(['tmux', 'select-window', '-t', wid], timeout=5)
    return switch_client(run, inside, session) or 'Switched to ' + title


def start_window(run, key, path, inside, session):
    """Select the ticket's window, or create one named KEY at path; then switch to the session."""
    panes = list_panes(run)
    target = find_window(panes, key, path, session)
    if target:
        wid, title = target
        run(['tmux', 'select-window', '-t', wid], timeout=5)
    else:
        session_exists = any(line.startswith(session + '\t') for line in panes.splitlines())
        run(['tmux', 'new-window' if session_exists else 'new-session', *(['-t', session + ':'] if session_exists
             else ['-d', '-s', session]), '-n', key, '-c', path], timeout=5)
        run(['tmux', 'select-window', '-t', session + ':' + key], timeout=5)
        title = key + ' (new window)'
    return switch_client(run, inside, session) or 'Switched to ' + title


def start_agent(run, key, path, argv, inside, session, display_name, focus=True):
    """Run argv beside the ticket's window, or in a new window named KEY. Without focus the person
    stays where they are: the pane or window is created detached and nothing is selected."""
    try:
        panes = list_panes(run)
    except RuntimeError:
        panes = ''  # A new session can be created when no server is running.
    target = find_window(panes, key, path, session)
    if target:
        wid, title = target
        run(split_command(wid, path, argv, detached=not focus), timeout=5)
        if focus:
            run(['tmux', 'select-window', '-t', wid], timeout=5)
    else:
        session_exists = any(line.startswith(session + '\t') for line in panes.splitlines())
        run(window_command(key, path, argv, session, session_exists, detached=not focus), timeout=5)
        if focus:
            run(['tmux', 'select-window', '-t', session + ':' + key], timeout=5)
        title = key + ' (new window)'
    if not focus:
        return f'{display_name} started in the background in {title}'
    return switch_client(run, inside, session) or f'{display_name} started in {title}: {argv[-1]}'


ROLE_OPTION = '@sidequest_role'


def open_below(run, pane, path, argv, role, percent=40):
    """Show the pane tagged `role` in pane's session, or split pane with a new pane below it that
    takes `percent` of its height and runs argv."""
    for line in run(['tmux', 'list-panes', '-s', '-t', pane, '-F',
                     '#{pane_id}\t#{window_id}\t#{' + ROLE_OPTION + '}'], timeout=5).splitlines():
        parts = line.split('\t')
        if len(parts) == 3 and parts[2] == role:
            run(['tmux', 'select-window', '-t', parts[1]], timeout=5)
            run(['tmux', 'select-pane', '-t', parts[0]], timeout=5)
            return 'Switched to the open ' + role + ' pane'
    created = run(['tmux', 'split-window', '-v', '-l', f'{percent}%', '-t', pane, '-c', path,
                   '-P', '-F', '#{pane_id}', shlex.join(argv)], timeout=5).strip()
    if created:
        run(['tmux', 'set-option', '-p', '-t', created, ROLE_OPTION, role], timeout=5)
    return 'Opened ' + role + ' in a pane below'


def open_layout(run, session, windows):
    """Make the session hold `windows` in order: reuse windows by name (the main checkout's is
    renamed when its ticket changes), create the missing ones, and move the person's own windows
    after the worktrees and before the end windows. Nothing is closed."""
    try:
        # '=' asks for the exact name: a bare name also matches a session that starts with it.
        run(['tmux', 'has-session', '-t', '=' + session], timeout=5)
    except RuntimeError:
        first = windows[0]
        made = run(['tmux', 'new-session', '-d', '-s', session, '-n', first.name, '-c', first.path,
                    '-P', '-F', '#{window_id}'] + ([process(first)] if first.command else []), timeout=5)
        if getattr(first, 'keys', ''):
            run(['tmux', 'send-keys', '-t', made.strip(), first.keys, 'Enter'], timeout=5)
    rows = [line.split(' ', 2) for line in run(['tmux', 'list-windows', '-t', session, '-F',
                                                 '#{window_index} #{window_id} #{window_name}'], timeout=5).splitlines()
            if line.count(' ') >= 2]
    ids = {name: wid for _, wid, name in rows}
    main = next((window for window in windows if window.name == 'Main' or window.name.startswith('Main ')), None)
    if main and main.name not in ids:
        old = next((name for name in ids if name in ('Main', 'main') or name.startswith('Main ')), None)
        if old:
            run(['tmux', 'rename-window', '-t', ids[old], main.name], timeout=5)
            ids[main.name] = ids.pop(old)
    for window in windows:
        if window.name not in ids:
            made = run(['tmux', 'new-window', '-d', '-P', '-F', '#{window_id}', '-t', session + ':', '-n', window.name,
                        '-c', window.path] + ([process(window)] if window.command else []), timeout=5)
            ids[window.name] = made.strip()
            if getattr(window, 'keys', ''):
                # Typed into the new window's shell, so its aliases and functions work.
                run(['tmux', 'send-keys', '-t', ids[window.name], window.keys, 'Enter'], timeout=5)
    wanted = [ids[window.name] for window in windows if not window.end]
    tail = [ids[window.name] for window in windows if window.end]
    own = [wid for _, wid, _ in rows if wid not in wanted and wid not in tail]
    order = wanted + own + tail
    try:
        base = int(run(['tmux', 'show-options', '-gv', 'base-index'], timeout=5).strip() or 0)
    except (RuntimeError, ValueError):
        base = 0
    # Park every window out of the way, then put them back in order (renumbering paused meanwhile).
    run(['tmux', 'set-option', '-t', session, 'renumber-windows', 'off'], timeout=5)
    for offset, wid in enumerate(order):
        run(['tmux', 'move-window', '-s', wid, '-t', session + ':' + str(1000 + offset)], timeout=5)
    for offset, wid in enumerate(order):
        run(['tmux', 'move-window', '-s', wid, '-t', session + ':' + str(base + offset)], timeout=5)
    run(['tmux', 'set-option', '-u', '-t', session, 'renumber-windows'], timeout=5)
    return len(order)


def process(window):
    """The command a window runs as its process; with stay, a shell is left when it ends."""
    if window.command and window.stay:
        return 'trap : INT; ' + window.command + '; exec "${SHELL:-/bin/sh}"'
    return window.command


def attach(session):
    """Switch to the session inside tmux, attach in a terminal, else print how to attach."""
    if os.environ.get('TMUX'):
        subprocess.run(['tmux', 'switch-client', '-t', session])
    elif sys.stdin.isatty() and sys.stdout.isatty():
        sys.stdout.flush()
        subprocess.run(['tmux', 'attach-session', '-t', session])
    else:
        print('attach   tmux attach -t ' + session)
