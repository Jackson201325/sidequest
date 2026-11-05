"""Jumps and launches that start outside programs. `run` is injected so tests need no tmux."""

import shlex
import sys
from sidequest import config
from sidequest.terminal import agent_argv, agent_display_name

from core import KEY

SESSION = config.get('workspace', 'tmux_session', 'sidequest')
PANE_FORMAT = "#{session_name}\t#{window_id}\t#{window_name}\t#{pane_current_path}"


def find_tw_window(panes, ticket):
    """Prefer the ticket's worktree path, and never select another tmux session."""
    candidates = []
    for line in panes.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        session, wid, title, path = parts
        if session != SESSION:
            continue
        root = ticket.worktree.rstrip("/")
        path_match = bool(root and (path == root or path.startswith(root + "/")))
        name_match = ticket.key in [m.group().upper() for m in KEY.finditer(title)]
        if path_match or name_match:
            candidates.append((not path_match, wid, title))
    return min(candidates)[1:] if candidates else None


def agent_command(window_id, path, prompt):
    """tmux command that starts the configured agent in the ticket's worktree."""
    return ["tmux", "split-window", "-h", "-t", window_id, "-c", path, shlex.join(agent_argv(prompt))]


def new_window_command(key, path, prompt, session_exists=True):
    """No tmux window yet: open one named after the ticket in the configured session."""
    claude = shlex.join(agent_argv(prompt))
    if session_exists:
        return ["tmux", "new-window", "-t", SESSION + ":", "-n", key, "-c", path, claude]
    return ["tmux", "new-session", "-d", "-s", SESSION, "-n", key, "-c", path, claude]


def list_panes(run):
    return run(["tmux", "list-panes", "-a", "-F", PANE_FORMAT], timeout=5)


def switch_client(run, inside):
    """Inside tmux, switch now and return None. Outside, return the session for the caller to attach."""
    if inside:
        run(["tmux", "switch-client", "-t", SESSION], timeout=5)
        return None
    return SESSION


def jump_to_window(run, ticket, inside):
    target = find_tw_window(list_panes(run), ticket)
    if not target:
        raise RuntimeError("No existing tmux window for " + ticket.key + "; open a window in the configured session")
    wid, title = target
    run(["tmux", "select-window", "-t", wid], timeout=5)
    return switch_client(run, inside) or "Switched to " + title


def start_agent(run, ticket, prompt, inside):
    path = ticket.worktree
    try:
        panes = list_panes(run)
    except RuntimeError:
        panes = ""                               # no tmux server yet
    target = find_tw_window(panes, ticket)
    if target:
        wid, title = target
        run(agent_command(wid, path, prompt), timeout=5)
        run(["tmux", "select-window", "-t", wid], timeout=5)
    else:
        session_exists = any(line.startswith(SESSION + "\t") for line in panes.splitlines())
        run(new_window_command(ticket.key, path, prompt, session_exists), timeout=5)
        run(["tmux", "select-window", "-t", SESSION + ":" + ticket.key], timeout=5)
        title = ticket.key + " (new window)"
    return switch_client(run, inside) or f"{agent_display_name()} started in {title}: {prompt}"


def open_in_edge(run, url):
    """Open the configured browser or OS default without loading shell profiles."""
    browser = config.get('workspace', 'browser')
    command = shlex.split(browser) if browser else ['open' if sys.platform == 'darwin' else 'xdg-open']
    run(command + [url])
    return 'Opened in browser'
