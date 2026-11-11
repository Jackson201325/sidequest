"""Herdr 0.9.5 terminal adapter. Git lifecycle stays in GitWorkspace."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

from sidequest.terminal import LaunchResult, ShellTerminal


class HerdrTerminal:
    def __init__(self, run, environ, shell, launches_dir):
        self.run = run
        self.context = dict(environ)
        self.foreground = ShellTerminal(shell)
        self.launches_dir = Path(launches_dir)

    def require_context(self):
        if self.context.get('HERDR_ENV') != '1' or not all(
                self.context.get(key) for key in ('HERDR_WORKSPACE_ID', 'HERDR_PANE_ID', 'HERDR_TAB_ID')):
            raise RuntimeError('Run Sidequest inside a Herdr-managed pane to use workspace.terminal=herdr')

    def _call(self, args, expected, empty_ok=False):
        try:
            output = self.run(['herdr', *args], timeout=15)
            if empty_ok and isinstance(output, str) and not output.strip():
                return {'type': 'ok'}
            data = json.loads(output)
            result = data.get('result') if isinstance(data, dict) and 'error' not in data else None
            if not isinstance(result, dict) or result.get('type') != expected:
                raise ValueError('Unexpected response')
            return result
        except (OSError, RuntimeError, ValueError, TypeError, subprocess.SubprocessError):
            raise RuntimeError('Herdr control failed or returned an invalid response; inspect the session before retrying') from None

    def _pane(self, value):
        if (not isinstance(value, dict) or value.get('workspace_id') != self.context['HERDR_WORKSPACE_ID']
                or not all(isinstance(value.get(k), str) and value[k] for k in ('pane_id', 'tab_id'))):
            raise RuntimeError('Herdr returned an invalid or out-of-workspace pane; no further controls sent')
        return value

    def _match(self, path):
        result = self._call(['pane', 'list', '--workspace', self.context['HERDR_WORKSPACE_ID']], 'pane_list')
        panes = result.get('panes')
        if not isinstance(panes, list):
            raise RuntimeError('Herdr returned an invalid pane inventory')
        matches = []
        for value in panes:
            pane = self._pane(value)
            cwd = pane.get('foreground_cwd') or pane.get('cwd')
            if cwd is not None and not isinstance(cwd, str):
                raise RuntimeError('Herdr returned an invalid working directory')
            if pane['pane_id'] == self.context['HERDR_PANE_ID'] or not cwd:
                continue
            folder = str(Path(cwd).expanduser().resolve())
            if folder == path or folder.startswith(path + os.sep):
                matches.append((folder != path, pane['pane_id'], pane))
        return min(matches, key=lambda item: item[:2])[2] if matches else None

    def _create_tab(self, key, path):
        result = self._call(['tab', 'create', '--workspace', self.context['HERDR_WORKSPACE_ID'],
                             '--cwd', path, '--label', key, '--no-focus'], 'tab_created')
        pane = self._pane(result.get('root_pane'))
        tab = result.get('tab')
        if (not isinstance(tab, dict) or tab.get('tab_id') != pane['tab_id']
                or tab.get('workspace_id') != self.context['HERDR_WORKSPACE_ID']):
            raise RuntimeError('Herdr returned an invalid new tab; inspect it before retrying')
        return pane

    def _split(self, pane, path, focus=True):
        layout = self._call(['pane', 'layout', '--pane', pane['pane_id']], 'pane_layout').get('layout')
        if (not isinstance(layout, dict) or layout.get('workspace_id') != self.context['HERDR_WORKSPACE_ID']
                or layout.get('tab_id') != pane['tab_id'] or not isinstance(layout.get('panes'), list)):
            raise RuntimeError('Herdr returned an invalid layout')
        rect = next((row.get('rect') for row in layout['panes']
                     if isinstance(row, dict) and row.get('pane_id') == pane['pane_id']), None)
        if not isinstance(rect, dict) or not all(isinstance(rect.get(k), int) and rect[k] > 0 for k in ('width', 'height')):
            raise RuntimeError('Herdr did not report the target pane size')
        direction = 'right' if rect['width'] >= 120 and rect['width'] >= rect['height'] * 2 else 'down'
        result = self._call(['pane', 'split', '--pane', pane['pane_id'], '--direction', direction,
                             '--cwd', path, *(['--focus'] if focus else [])], 'pane_info')
        created = self._pane(result.get('pane'))
        if created['tab_id'] != pane['tab_id'] or created['pane_id'] == pane['pane_id']:
            raise RuntimeError('Herdr returned an invalid split target')
        return created

    def _agent_command(self, path, argv):
        # Herdr pane run enters text through the shell. Bundled skills can exceed
        # macOS canonical input limits, so submit only a short private launcher path.
        self.launches_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='agent-', suffix='.py', dir=str(self.launches_dir))
        with os.fdopen(fd, 'w') as script:
            script.write('import os\n'
                         'os.chdir(' + repr(path) + ')\n'
                         'os.unlink(__file__)\n'
                         'argv = ' + repr(list(argv)) + '\n'
                         'os.execvp(argv[0], argv)\n')
        return shlex.join([sys.executable, name])

    def split_below(self, path, argv, share=0.7):
        """Run argv in a new pane under the caller's pane; the new pane gets `share` of the height."""
        self.require_context()
        result = self._call(['pane', 'split', '--pane', self.context['HERDR_PANE_ID'], '--direction', 'down',
                             '--ratio', str(round(1 - share, 2)), '--cwd', path, '--focus'], 'pane_info')
        created = self._pane(result.get('pane'))
        if created['pane_id'] == self.context['HERDR_PANE_ID']:
            raise RuntimeError('Herdr returned an invalid split target')
        self._call(['pane', 'run', created['pane_id'], self._agent_command(path, argv)], 'ok', empty_ok=True)
        return LaunchResult(message='Opened in a pane below')

    def launch(self, key, path, argv=None, foreground=False, focus=True):
        self.require_context()
        if foreground:
            return self.foreground.launch(key, path, argv)
        if not path or not Path(path).expanduser().is_dir():
            raise RuntimeError('The worktree folder is unavailable; refresh local worktrees')
        path = str(Path(path).expanduser().resolve())
        pane = self._match(path)
        if pane is None:
            pane = self._create_tab(key, path)
        elif argv is not None:
            pane = self._split(pane, path, focus)
        if argv is not None:
            command = self._agent_command(path, argv)
            self._call(['pane', 'run', pane['pane_id'], command], 'ok', empty_ok=True)
            if not focus:
                return LaunchResult(message='Agent started in the background for ' + key + ' in Herdr')
        focused = self._call(['tab', 'focus', pane['tab_id']], 'tab_info').get('tab')
        if (not isinstance(focused, dict) or focused.get('tab_id') != pane['tab_id']
                or focused.get('workspace_id') != self.context['HERDR_WORKSPACE_ID']):
            raise RuntimeError('Herdr did not confirm the requested tab; inspect it before retrying')
        return LaunchResult(message=('Agent launch submitted for ' if argv is not None else 'Opened workspace for ')
                            + key + ' in Herdr')
