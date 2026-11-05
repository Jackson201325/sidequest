"""Compatibility launch helpers; terminal implementations live in sidequest.tmux."""
import shlex
import sys
from sidequest import config, tmux
from sidequest.terminal import agent_argv, agent_display_name

SESSION = config.get('workspace', 'tmux_session', 'sidequest')
PANE_FORMAT = tmux.PANE_FORMAT


def find_tw_window(panes, ticket):
    return tmux.find_window(panes, ticket.key, ticket.worktree, SESSION)


def agent_command(window_id, path, prompt):
    return tmux.split_command(window_id, path, agent_argv(prompt))


def new_window_command(key, path, prompt, session_exists=True):
    return tmux.window_command(key, path, agent_argv(prompt), SESSION, session_exists)


def list_panes(run):
    return tmux.list_panes(run)


def switch_client(run, inside):
    return tmux.switch_client(run, inside, SESSION)


def jump_to_window(run, ticket, inside):
    return tmux.jump(run, ticket.key, ticket.worktree, inside, SESSION)


def start_agent(run, ticket, prompt, inside):
    argv = agent_argv(prompt)
    return tmux.start_agent(run, ticket.key, ticket.worktree, argv, inside, SESSION, agent_display_name(argv))


def open_in_edge(run, url):
    """Open the configured browser or OS default without loading shell profiles."""
    browser = config.get('workspace', 'browser')
    command = shlex.split(browser) if browser else ['open' if sys.platform == 'darwin' else 'xdg-open']
    run(command + [url])
    return 'Opened in browser'
