"""`sessions` in the settings: personal tmux sessions (dotfiles, notes) that `sidequest up` builds beside the project's."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PersonalSessionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='sq-sessions-')
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name).resolve()
        self.repo = self.home / 'repo'
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.repo)], check=True)
        (self.home / 'dots').mkdir()
        (self.home / 'nvim').mkdir()
        self.settings = self.home / 'settings.json'
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('SIDEQUEST_', 'TMUX'))}
        self.env.update(SIDEQUEST_CONFIG=str(self.settings), SIDEQUEST_STATE_DIR=str(self.home / 'state'),
                        SIDEQUEST_DATA_DIR=str(self.home / 'data'), HOME=str(self.home),
                        TMUX_TMPDIR=str(self.home / 'tmux'), SHELL='/bin/sh')
        (self.home / 'tmux').mkdir()

    def write(self, sessions, session='proj'):
        self.settings.write_text(json.dumps({
            'workspace': {'repository': str(self.repo), 'terminal': 'tmux', 'tmux_session': session},
            'sessions': sessions}))

    def up(self, *args):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), 'up', '-n', *args],
                              cwd=self.repo, env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def stop_tmux(self):
        # kill-server returns before the server and its panes exit; deleting the folder sooner races them.
        subprocess.run(['tmux', 'kill-server'], env=self.env, capture_output=True)
        deadline = time.monotonic() + 5
        while any((self.home / 'tmux').glob('tmux-*/*')) and time.monotonic() < deadline:
            time.sleep(0.05)

    DOTFILES = {'dotfiles': [{'name': 'nvim-config', 'cwd': '~/nvim', 'command': 'nvim', 'stay': True},
                             {'name': 'dots', 'cwd': '~/dots'}]}

    @unittest.skipUnless(shutil.which('tmux'), 'tmux is not installed')
    def test_dry_run_lists_each_personal_session_and_its_windows(self):
        self.write(self.DOTFILES)
        ran = self.up('--dry-run')
        self.assertNotEqual(ran.returncode, 2, ran.stdout + ran.stderr)
        self.assertIn('session  dotfiles', ran.stdout)
        self.assertIn('window   nvim-config  ' + str(self.home / 'nvim') + '  $ trap : INT; nvim; exec', ran.stdout)
        self.assertIn('window   dots         ' + str(self.home / 'dots'), ran.stdout)

    @unittest.skipUnless(shutil.which('tmux'), 'tmux is not installed')
    def test_up_builds_the_personal_session_once_on_a_private_tmux_server(self):
        self.write({'dotfiles': [{'name': 'nvim-config', 'cwd': '~/nvim'}, {'name': 'dots', 'cwd': '~/dots'}]})
        self.addCleanup(self.stop_tmux)
        for _ in range(2):
            ran = self.up('--no-attach')
            self.assertNotEqual(ran.returncode, 2, ran.stdout + ran.stderr)
            self.assertIn('session  dotfiles: 2 windows', ran.stdout)
        listed = subprocess.run(['tmux', 'list-windows', '-t', '=dotfiles', '-F', '#{window_name} #{pane_current_path}'],
                                env=self.env, capture_output=True, text=True).stdout.splitlines()
        self.assertEqual([line.split(' ', 1)[0] for line in listed], ['nvim-config', 'dots'])
        self.assertTrue(listed[1].endswith('/dots'), listed)

    def test_with_herdr_the_dry_run_lists_the_same_layout_without_the_old_unsupported_note(self):
        self.settings.write_text(json.dumps({
            'workspace': {'repository': str(self.repo), 'terminal': 'herdr', 'tmux_session': 'proj'},
            'sessions': self.DOTFILES}))
        fake = self.home / 'bin'
        fake.mkdir()
        (fake / 'herdr').write_text('#!/bin/sh\nexit 1\n')
        (fake / 'herdr').chmod(0o755)
        self.env['PATH'] = str(fake) + os.pathsep + self.env.get('PATH', '')
        ran = self.up('--dry-run')
        self.assertNotIn('not supported', ran.stdout)
        self.assertIn('window   Main', ran.stdout)
        self.assertIn('session  dotfiles', ran.stdout)
        self.assertIn('window   nvim-config  ' + str(self.home / 'nvim') + '  $ nvim', ran.stdout)

    def test_a_session_named_like_the_project_session_is_skipped(self):
        self.write(self.DOTFILES, session='dotfiles')
        ran = self.up('--dry-run')
        self.assertIn('session  dotfiles skipped: this project already uses that tmux session', ran.stdout)

    def test_bad_sessions_are_settings_errors(self):
        for sessions, message in ((
                {'Bad Name': []}, 'sessions names use lowercase letters, digits, - and _'), (
                {'dotfiles': [{'cwd': '~/dots'}]}, 'sessions.dotfiles must be a list of {name, command?')):
            with self.subTest(sessions=sessions):
                self.write(sessions)
                ran = self.up('--dry-run')
                self.assertEqual(ran.returncode, 2, ran.stdout + ran.stderr)
                self.assertIn(message, ran.stderr)


if __name__ == '__main__':
    unittest.main()
