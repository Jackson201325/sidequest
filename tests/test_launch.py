"""Plain `sidequest` in a terminal: workspace.launch session opens the tmux session instead of the dashboard."""
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
UP = 'sidequest up: set workspace.repository'


class LaunchTests(unittest.TestCase):
    def run_plain(self, workspace, **extra_env):
        """Output of `sidequest` with no arguments in a pseudo-terminal, and whether it was still running."""
        folder = tempfile.TemporaryDirectory(prefix='sidequest launch ')
        self.addCleanup(folder.cleanup)
        home = Path(folder.name).resolve()
        settings = home / 'config.json'
        settings.write_text(json.dumps({'workspace': workspace}))
        fake_bin = home / 'bin'
        fake_bin.mkdir()
        (fake_bin / 'tmux').write_text('#!/bin/sh\nexit 1\n')
        (fake_bin / 'tmux').chmod(0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('SIDEQUEST_', 'HERDR_')) and k != 'TMUX'}
        env.update(SIDEQUEST_CONFIG=str(settings), XDG_CONFIG_HOME=str(home / 'config'),
                   XDG_STATE_HOME=str(home / 'state'), XDG_DATA_HOME=str(home / 'data'),
                   PATH=str(fake_bin) + os.pathsep + env.get('PATH', ''), TERM='xterm-256color',
                   PYTHONDONTWRITEBYTECODE='1', **extra_env)
        master, slave = pty.openpty()
        process = subprocess.Popen([sys.executable, '-B', str(ROOT / 'bin/sidequest')], cwd=home, env=env,
                                   stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        received = bytearray()
        deadline = time.monotonic() + 3
        try:
            while time.monotonic() < deadline and process.poll() is None:
                if select.select([master], [], [], .05)[0]:
                    try:
                        received.extend(os.read(master, 65536))
                    except OSError:
                        break
            running = process.poll() is None
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            os.close(master)
        return received.decode(errors='replace'), running

    def test_launch_session_hands_plain_sidequest_to_sidequest_up(self):
        text, _ = self.run_plain({'launch': 'session', 'terminal': 'tmux'})
        self.assertIn(UP, text)

    def test_inside_tmux_plain_sidequest_stays_the_dashboard(self):
        text, running = self.run_plain({'launch': 'session', 'terminal': 'auto'}, TMUX='/tmp/fake,1,0')
        self.assertNotIn(UP, text)
        self.assertTrue(running, text[-400:])

    def test_without_the_setting_or_with_herdr_plain_sidequest_stays_the_dashboard(self):
        for workspace in ({}, {'launch': 'session', 'terminal': 'herdr'}, {'launch': 'dashboard'}):
            with self.subTest(workspace=workspace):
                text, running = self.run_plain(workspace)
                self.assertNotIn(UP, text)
                self.assertTrue(running, text[-400:])

    def test_an_unknown_launch_value_is_a_settings_error(self):
        folder = tempfile.TemporaryDirectory(prefix='sidequest launch ')
        self.addCleanup(folder.cleanup)
        settings = Path(folder.name) / 'config.json'
        settings.write_text(json.dumps({'workspace': {'launch': 'tmux'}}))
        env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
        env.update(SIDEQUEST_CONFIG=str(settings), XDG_CONFIG_HOME=folder.name + '/config')
        ran = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), '--list'], env=env,
                             capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(ran.returncode, 2)
        self.assertIn('workspace.launch must be dashboard or session', ran.stderr)


if __name__ == '__main__':
    unittest.main()
