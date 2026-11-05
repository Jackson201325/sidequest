"""A real terminal handoff to a worktree shell and back, without tmux."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest


class PlainTerminalHandoffTests(unittest.TestCase):
    def test_worktree_shell_uses_terminal_input_and_returns_to_dashboard(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            repo = folder / 'repo';repo.mkdir()
            env = {key: value for key, value in os.environ.items() if not key.startswith(('GIT_', 'SIDEQUEST_')) and key != 'TMUX'}
            for args in (['init', '-q', '-b', 'main'], ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'Base']):
                subprocess.run(['git', *args], cwd=repo, env=env, check=True)
            settings = folder / 'config.json';settings.write_text(json.dumps({'workspace': {'repository': str(repo), 'base_ref': 'main'}}))
            snapshots = folder / 'snapshots';snapshots.mkdir()
            (snapshots / 'standup.json').write_text(json.dumps({'jira_assigned': [{'key': 'APP-21', 'summary': 'Plain terminal', 'status': 'In Progress', 'assignee_ok': True}]}))
            shell = folder / 'test-shell'
            shell.write_text('#!' + sys.executable + '\nimport os,sys\nprint("WORKTREE_SHELL " + os.getcwd(), flush=True)\nfor line in sys.stdin:\n if line.strip()=="exit": break\n')
            shell.chmod(0o755)
            env.update(SHELL=str(shell), SIDEQUEST_CONFIG=str(settings), PYTHONDONTWRITEBYTECODE='1', TERM='xterm-256color')
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 145, 0, 0))
            process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).with_name('tui.py')), '--data-dir', str(folder / 'data'), '--snapshots', str(snapshots)], stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True)
            os.close(slave)
            received = bytearray()
            def until(expected):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if select.select([master], [], [], .05)[0]:
                        try: received.extend(os.read(master, 65536))
                        except OSError: break
                    if expected.encode() in received: return
                self.fail('Missing terminal text ' + expected + '; tail: ' + repr(received[-800:]))
            try:
                until('APP-21')
                os.write(master, b' n')
                until('WORKTREE_SHELL ' + str(folder / 'APP-21-plain-terminal'))
                received.clear()
                os.write(master, b'exit\n')
                until('back in Sidequest')
                os.write(master, b'q')
                deadline = time.monotonic() + 5
                while process.poll() is None and time.monotonic() < deadline:
                    if select.select([master], [], [], .05)[0]:
                        try: received.extend(os.read(master, 65536))
                        except OSError: break
                process.wait(timeout=1)
                self.assertEqual(process.returncode, 0)
                self.assertEqual(subprocess.check_output(['git', 'worktree', 'list', '--porcelain'], cwd=repo, env=env).decode().count('worktree '), 2)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                os.close(master)


if __name__ == '__main__':
    unittest.main()
