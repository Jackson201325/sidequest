"""Executable terminal contract; all tmux commands use an injected runner."""
from pathlib import Path
import shlex
import tempfile
import unittest

from sidequest.terminal import ShellTerminal, TmuxTerminal


class TerminalSpecs(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='sidequest terminal ')
        self.addCleanup(self.folder.cleanup)
        self.path = str(Path(self.folder.name).resolve())
        self.calls = []
        self.panes = 'project\t@3\tEditor\t' + self.path + '\nother\t@9\tAPP-21\t/elsewhere\n'

    def command(self, args, **kwargs):
        self.calls.append(args)
        return self.panes if args[1] == 'list-panes' else ''

    def test_shell_returns_a_handoff_without_running_commands_or_changing_cwd(self):
        before = Path.cwd()
        result = ShellTerminal('/bin/sh').launch('APP-21', self.path)
        self.assertEqual(result.foreground['argv'], ['/bin/sh', '-i'])
        self.assertEqual(result.foreground['cwd'], self.path)
        self.assertEqual(Path.cwd(), before)

    def test_shell_reports_missing_worktree(self):
        for path in ('', self.path + '/missing'):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                ShellTerminal('/bin/sh').launch('APP-21', path)

    def test_tmux_only_selects_the_configured_session(self):
        result = TmuxTerminal(self.command, 'project', '/bin/sh').launch('APP-21', self.path)
        self.assertEqual(result.message, 'Switched to Editor')
        self.assertEqual(self.calls[1:], [['tmux', 'select-window', '-t', '@3'],
                                         ['tmux', 'switch-client', '-t', 'project']])

    def test_agent_argv_is_quoted_once_and_passed_to_the_matching_pane(self):
        argv = ['my-agent', '--flag', "APP-21: 'quotes' $(literal)"]
        TmuxTerminal(self.command, 'project', '/bin/sh').launch('APP-21', self.path, argv)
        command = self.calls[1]
        self.assertEqual(command[:7], ['tmux', 'split-window', '-h', '-t', '@3', '-c', self.path])
        self.assertEqual(shlex.split(command[-1]), argv)

    def test_independent_sessions_never_focus_each_others_window(self):
        first = TmuxTerminal(self.command, 'project', '/bin/sh')
        second = TmuxTerminal(self.command, 'other', '/bin/sh')
        first.launch('APP-21', self.path)
        second.launch('APP-21', '/elsewhere')
        self.assertEqual([command[-1] for command in self.calls if command[1] == 'select-window'], ['@3', '@9'])
        self.assertEqual([command[-1] for command in self.calls if command[1] == 'switch-client'], ['project', 'other'])

    def test_explicit_foreground_start_does_not_touch_tmux(self):
        result = TmuxTerminal(self.command, 'project', '/bin/sh').launch('APP-21', self.path, foreground=True)
        self.assertEqual(result.foreground['cwd'], self.path)
        self.assertEqual(self.calls, [])

    def test_existing_window_lookup_failure_is_not_silently_replaced_by_a_shell(self):
        def failed(*args, **kwargs):
            raise RuntimeError('tmux unavailable')
        with self.assertRaisesRegex(RuntimeError, 'tmux unavailable'):
            TmuxTerminal(failed, 'project', '/bin/sh').launch('APP-21', self.path)


if __name__ == '__main__':
    unittest.main()
