"""tmux operations on already-selected checkouts; no Git or UI imports."""
import shlex

from sidequest.worktrees import KEY

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
        name_match = key.upper() in [m.group().upper() for m in KEY.finditer(title)]
        if path_match or name_match:
            candidates.append((not path_match, wid, title))
    return min(candidates)[1:] if candidates else None


def split_command(window_id, path, argv):
    return ['tmux', 'split-window', '-h', '-t', window_id, '-c', path, shlex.join(argv)]


def window_command(key, path, argv, session, session_exists=True):
    command = shlex.join(argv)
    if session_exists:
        return ['tmux', 'new-window', '-t', session + ':', '-n', key, '-c', path, command]
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


def start_agent(run, key, path, argv, inside, session, display_name):
    try:
        panes = list_panes(run)
    except RuntimeError:
        panes = ''  # A new session can be created when no server is running.
    target = find_window(panes, key, path, session)
    if target:
        wid, title = target
        run(split_command(wid, path, argv), timeout=5)
        run(['tmux', 'select-window', '-t', wid], timeout=5)
    else:
        session_exists = any(line.startswith(session + '\t') for line in panes.splitlines())
        run(window_command(key, path, argv, session, session_exists), timeout=5)
        run(['tmux', 'select-window', '-t', session + ':' + key], timeout=5)
        title = key + ' (new window)'
    return switch_client(run, inside, session) or f'{display_name} started in {title}: {argv[-1]}'
