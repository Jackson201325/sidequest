"""Workspace use cases shared by CLI and TUI; no curses or UI model dependency."""
from dataclasses import replace
from pathlib import Path
import shlex
import shutil

from sidequest.repository import repository_from
from sidequest.terminal import ShellTerminal, TmuxTerminal, agent_argv, run_command
from sidequest.workspace import GitWorkspace
from sidequest.herdr import HerdrTerminal


class WorkspaceWorkflow:
    def __init__(self, workspace, terminal, agent_command='claude'):
        self.workspace, self.terminal = workspace, terminal
        self.agent_command = agent_command

    def prepare(self, key, summary, issue_type='', prefix=None, base=None, apply=False):
        plan = self.workspace.preview(key, summary, issue_type, prefix, base)
        return self.workspace.apply(plan) if apply else plan.result()

    def start(self, key, summary, issue_type='', prefix=None, base=None, window=False):
        """Create/reuse the worktree, then open it: its own window when asked and the terminal has
        windows (tmux), else a foreground shell (the CLI --open contract)."""
        ready = self.prepare(key, summary, issue_type, prefix, base, apply=True)
        opener = getattr(self.terminal, 'start_window', None) if window else None
        launched = opener(key, ready['path']) if opener else self.terminal.launch(key, ready['path'], foreground=True)
        return replace(launched, key=key, workspace=ready)

    def open(self, key, path):
        return self.terminal.launch(key, path)

    def agent(self, key, path, prompt, focus=True):
        return self.terminal.launch(key, path, agent_argv(prompt, self.agent_command), focus=focus)


def build_workflow(settings, environ, run=run_command):
    """Capture explicit settings once; select only managed terminals with caller context."""
    values = dict(settings.get('workspace', {}))
    workspace = GitWorkspace(repository_from(environ, settings) or '.',
                             values.get('worktrees_dir'), values.get('base_ref') or 'origin/main',
                             shlex.split(values.get('copy_files') or ''))
    shell = environ.get('SHELL') or '/bin/sh'
    mode = environ.get('SIDEQUEST_TERMINAL') or values.get('terminal', 'auto')
    if mode not in ('auto', 'shell', 'tmux', 'herdr'):
        raise ValueError('workspace.terminal must be auto, shell, tmux or herdr')
    if mode == 'auto':
        mode = 'tmux' if environ.get('TMUX') else 'herdr' if environ.get('HERDR_ENV') == '1' else 'shell'
    if mode == 'tmux':
        if not environ.get('TMUX'):
            raise RuntimeError('Run Sidequest inside tmux to use workspace.terminal=tmux')
        terminal = TmuxTerminal(run, values.get('tmux_session', 'sidequest'), shell)
    elif mode == 'herdr':
        shell = shutil.which('zsh', path=environ.get('PATH'))
        if not shell:
            raise RuntimeError('Herdr requires zsh; install zsh and configure Herdr terminal.default_shell to use it')
        home = Path(environ.get('HOME') or Path.home())
        state = Path(environ.get('XDG_STATE_HOME') or home / '.local/state') / 'sidequest' / 'launches'
        terminal = HerdrTerminal(run, environ, shell, state)
        terminal.require_context()
    else:
        terminal = ShellTerminal(shell)
    return WorkspaceWorkflow(workspace, terminal, values.get('agent_command', 'claude'))
