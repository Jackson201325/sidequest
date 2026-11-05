"""Foreground terminal handoffs; each child owns its working directory."""
import os
from pathlib import Path
import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional
from sidequest import tmux


def request(argv, path, label):
    if not path:
        raise RuntimeError('No local worktree yet; create or select a local worktree')
    folder = Path(path).expanduser().resolve()
    if not folder.is_dir():
        raise RuntimeError('The worktree folder is unavailable; refresh local worktrees')
    return {'argv': list(argv), 'cwd': str(folder), 'label': label}


def shell_request(path, shell=None):
    return request([shell or os.environ.get('SHELL') or '/bin/sh', '-i'], path, 'Workspace')


def agent_argv(prompt, command=None):
    if command is None:
        from sidequest import config
        command = config.get('workspace', 'agent_command', 'claude')
    argv = shlex.split(command)
    if not argv:
        raise RuntimeError('Configure workspace.agent_command for your coding assistant')
    return argv + [prompt]


def agent_request(path, prompt):
    return request(agent_argv(prompt), path, 'Agent')


def agent_display_name(argv=None):
    name = Path((agent_argv('') if argv is None else argv)[0]).name
    return {'claude': 'Claude Code', 'codex': 'Codex'}.get(name, name)


@dataclass(frozen=True)
class LaunchResult:
    """The caller owns foreground terminal handoff and presenting messages."""
    foreground: Optional[dict] = None
    message: str = ''
    key: str = ''
    workspace: Optional[dict] = None


class ShellTerminal:
    def __init__(self, shell):
        self.shell = shell

    def launch(self, key, path, argv=None, foreground=False):
        action = request(argv, path, 'Agent') if argv is not None else shell_request(path, self.shell)
        return LaunchResult(foreground=action)


class TmuxTerminal:
    def __init__(self, run, session, shell):
        self.run, self.session = run, session
        self.foreground = ShellTerminal(shell)

    def launch(self, key, path, argv=None, foreground=False):
        if foreground:
            return self.foreground.launch(key, path, argv)
        if argv is None:
            message = tmux.jump(self.run, key, path, True, self.session)
        else:
            message = tmux.start_agent(self.run, key, path, argv, True, self.session, agent_display_name(argv))
        return LaunchResult(message=message)


def run_command(args, timeout=45):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Terminal command failed; check your terminal session')
    return result.stdout


def run_request(action):
    """Inherit terminal I/O; let the child handle Ctrl-C and return on its exit."""
    process = subprocess.Popen(action['argv'], cwd=action['cwd'])
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            continue
