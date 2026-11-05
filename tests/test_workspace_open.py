import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceOpenTests(unittest.TestCase):
    def test_open_creates_then_reuses_worktree_in_a_plain_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            repo = base / 'repo';repo.mkdir()
            env = {key: value for key, value in os.environ.items() if not key.startswith(('GIT_', 'SIDEQUEST_')) and key != 'TMUX'}
            settings = base / 'config.json';settings.write_text('{}')
            shell = base / 'test-shell'
            recorded = base / 'cwd.txt'
            shell.write_text('#!' + sys.executable + '\nimport os\nfrom pathlib import Path\nPath(os.environ["WORKSPACE_TEST_CWD"]).write_text(os.getcwd())\nprint("WORKTREE_SHELL")\n')
            shell.chmod(0o755)
            env.update(SHELL=str(shell), SIDEQUEST_CONFIG=str(settings), WORKSPACE_TEST_CWD=str(recorded), PYTHONDONTWRITEBYTECODE='1')
            for args in (['init', '-q', '-b', 'main'], ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'Base']):
                subprocess.run(['git', *args], cwd=repo, env=env, check=True)
            command = [sys.executable, '-B', str(ROOT / 'bin/sidequest-data'), 'workspace', 'APP-21', '--summary', 'Plain terminal', '--base', 'main', '--open']
            for _ in range(2):
                result = subprocess.run(command, cwd=repo, env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('WORKTREE_SHELL', result.stdout)
                self.assertEqual(Path(recorded.read_text()), base / 'APP-21-plain-terminal')
            self.assertEqual(subprocess.check_output(['git', 'branch', '--show-current'], cwd=repo, env=env).decode().strip(), 'main')
            self.assertEqual(subprocess.check_output(['git', 'worktree', 'list', '--porcelain'], cwd=repo, env=env).decode().count('worktree '), 2)


if __name__ == '__main__':
    unittest.main()
