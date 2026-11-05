"""Foreground terminal handoffs; each child owns its working directory."""
import os
from pathlib import Path
import shlex
import subprocess
from sidequest import config


def request(argv, path, label):
    folder = Path(path).expanduser().resolve()
    if not folder.is_dir():
        raise RuntimeError('The worktree folder is unavailable; refresh local worktrees')
    return {'argv': list(argv), 'cwd': str(folder), 'label': label}


def shell_request(path):
    return request([os.environ.get('SHELL') or '/bin/sh', '-i'], path, 'Workspace')


def agent_argv(prompt):
    command = shlex.split(config.get('workspace', 'agent_command', 'claude'))
    if not command:
        raise RuntimeError('Configure workspace.agent_command for your coding assistant')
    return command + [prompt]


def agent_request(path, prompt):
    return request(agent_argv(prompt), path, 'Agent')


def agent_display_name():
    name = Path(agent_argv('')[0]).name
    return {'claude': 'Claude Code', 'codex': 'Codex'}.get(name, name)


def run_request(action):
    """Inherit terminal I/O; let the child handle Ctrl-C and return on its exit."""
    process = subprocess.Popen(action['argv'], cwd=action['cwd'])
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            continue
