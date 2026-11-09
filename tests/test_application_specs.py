"""The same workflow interface is available to a headless CLI and the dashboard."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from sidequest.application import WorkspaceWorkflow, build_workflow
from sidequest.terminal import LaunchResult, ShellTerminal, TmuxTerminal
from sidequest.workspace import GitWorkspace


class RecordingTerminal:
    def __init__(self):
        self.calls = []

    def launch(self, key, path, argv=None, foreground=False):
        self.calls.append((key, path, argv, foreground))
        return LaunchResult(message='Opened by another terminal adapter')


class ApplicationSpecs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name).resolve()
        self.repo = self.folder / 'repo'
        self.repo.mkdir()
        for args in (['init', '-q', '-b', 'main'],
                     ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                      'commit', '--allow-empty', '-qm', 'Base']):
            subprocess.run(['git', '-C', str(self.repo), *args], check=True)
        self.terminal = RecordingTerminal()
        self.workflow = WorkspaceWorkflow(GitWorkspace(self.repo, base_ref='main'), self.terminal,
                                          agent_command='codex --sandbox workspace-write')

    def test_preview_and_apply_never_launch_a_terminal(self):
        self.assertEqual(self.workflow.prepare('APP-21', 'An example')['state'], 'preview')
        self.assertTrue(self.workflow.prepare('APP-21', 'An example', apply=True)['created'])
        self.assertEqual(self.terminal.calls, [])

    def test_start_prepares_before_calling_the_injected_terminal(self):
        result = self.workflow.start('APP-21', 'An example')
        key, path, argv, foreground = self.terminal.calls[0]
        self.assertEqual(key, 'APP-21')
        self.assertTrue((Path(path) / '.git').is_file())
        self.assertIsNone(argv)
        self.assertTrue(foreground)  # Preserve today's Space n / CLI --open behavior.
        self.assertEqual(result.key, 'APP-21')
        self.assertEqual(result.workspace['path'], path)
        self.assertEqual(result.message, 'Opened by another terminal adapter')

    def test_window_start_uses_the_terminal_window_and_falls_back_to_a_shell(self):
        windows = []
        self.terminal.start_window = lambda key, path: windows.append((key, path)) or LaunchResult(message='Window')
        result = self.workflow.start('APP-21', 'An example', 'Bug', window=True)
        self.assertEqual(result.message, 'Window')
        self.assertEqual(windows[0][0], 'APP-21')
        self.assertTrue(result.workspace['branch'].startswith('fix/APP-21'))
        self.assertEqual(self.terminal.calls, [])
        del self.terminal.start_window
        self.workflow.start('APP-21', 'An example', window=True)
        self.assertTrue(self.terminal.calls[0][3], 'terminals without windows keep the foreground shell')

    def test_failed_preparation_does_not_launch_any_terminal(self):
        with self.assertRaises(RuntimeError):
            self.workflow.start('APP-21', 'An example', base='missing-base')
        self.assertEqual(self.terminal.calls, [])

    def test_open_and_agent_do_not_create_worktrees(self):
        self.workflow.open('APP-21', str(self.repo))
        prompt = "APP-21: spaces, 'quotes', $(touch must-not-exist)"
        self.workflow.agent('APP-21', str(self.repo), prompt)
        self.assertEqual(self.terminal.calls[1][2], ['codex', '--sandbox', 'workspace-write', prompt])
        rows = subprocess.check_output(['git', '-C', str(self.repo), 'worktree', 'list', '--porcelain'], text=True)
        self.assertEqual(rows.count('worktree '), 1)
        self.assertFalse((self.repo / 'must-not-exist').exists())

    def test_settings_are_captured_per_workflow_and_terminal_selection_uses_session_context(self):
        settings = {'workspace': {'repository': str(self.repo), 'base_ref': 'main', 'agent_command': 'codex'}}
        environment = {'SHELL': '/bin/sh', 'TMUX': ''}
        first = build_workflow(settings, environment, run=lambda *a, **k: '')
        settings['workspace']['agent_command'] = 'another-agent'
        environment['TMUX'] = '/tmp/managed-session'
        second = build_workflow(settings, environment, run=lambda *a, **k: '')
        self.assertIsInstance(first.terminal, ShellTerminal)
        self.assertIsInstance(second.terminal, TmuxTerminal)
        result = first.agent('APP-21', str(self.repo), 'Review APP-21')
        self.assertEqual(result.foreground['argv'], ['codex', 'Review APP-21'])


if __name__ == '__main__':
    unittest.main()
