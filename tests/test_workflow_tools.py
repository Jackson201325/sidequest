import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkflowToolTests(unittest.TestCase):
    def invoke(self, folder, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith('SIDEQUEST_')}
        env.update(HOME=folder, XDG_CONFIG_HOME=folder + '/config', XDG_DATA_HOME=folder + '/data',
                   XDG_STATE_HOME=folder + '/state', SIDEQUEST_TICKETS_DIR=str(Path(folder) / 'tickets'),
                   PYTHONDONTWRITEBYTECODE='1')
        env.pop('TMUX', None)
        env.pop('HERDR_ENV', None)
        return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest-data'), *args],
                              cwd=folder, env=env, capture_output=True, text=True)

    def test_jira_start_is_off_until_configured_and_keys_are_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            off = self.invoke(folder, 'jira-start', 'APP-12')
            self.assertEqual(off.returncode, 1)
            self.assertIn('SIDEQUEST_JIRA_START_STATUS', off.stderr)
            bad = self.invoke(folder, 'jira-start', 'not-a-key')
            self.assertEqual(bad.returncode, 2)

    def test_portable_branch_and_plan_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            named = self.invoke(folder, 'branch-name', 'APP-12', '--summary', 'Reject empty input', '--type', 'Bug')
            self.assertEqual(named.returncode, 0, named.stderr)
            self.assertEqual(named.stdout.strip(), 'fix/APP-12-reject-empty-input')
            plan = self.invoke(folder, 'plan-init', 'APP-12', '--summary', 'Reject empty input')
            self.assertEqual(plan.returncode, 0, plan.stderr)
            path = Path(folder) / 'tickets/APP-12/plan.md'
            self.assertIn('Acceptance criteria', path.read_text())
            path.write_text('Keep my plan')
            self.invoke(folder, 'plan-init', 'APP-12')
            self.assertEqual(path.read_text(), 'Keep my plan')

    def test_skills_installation_and_drift_check_are_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / 'skills'
            preview = self.invoke(folder, 'skills', '--dest', str(dest))
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertFalse(dest.exists())
            installed = self.invoke(folder, 'skills', '--dest', str(dest), '--apply')
            self.assertEqual(installed.returncode, 0, installed.stderr)
            copies = sorted(dest.glob('sidequest-*/SKILL.md'))
            self.assertEqual(len(copies), 9)
            self.assertTrue(all('{{SIDEQUEST_' not in path.read_text() for path in copies))
            ship = (dest / 'sidequest-ship/SKILL.md').read_text()
            self.assertTrue(ship.startswith('---\nname: sidequest-ship\ndescription: '))
            self.assertIn(str(ROOT / 'bin/sidequest-data') + ' skill ship', ship)
            self.assertNotIn('Identify what', ship, 'the steps come from the command, not a copy')
            self.assertEqual(self.invoke(folder, 'skills', '--dest', str(dest), '--check').returncode, 0)
            copies[0].write_text('User edit')
            self.assertEqual(self.invoke(folder, 'skills', '--dest', str(dest), '--check').returncode, 1)
            self.assertNotEqual(self.invoke(folder, 'skills', '--dest', str(dest), '--apply').returncode, 0)
            self.assertEqual(copies[0].read_text(), 'User edit')

    def test_workspace_preview_does_not_create_a_worktree(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder) / 'repo';repo.mkdir()
            for args in (['init', '-q', '-b', 'main'], ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'Base']):
                subprocess.run(['git', *args], cwd=repo, check=True)
            result = self.invoke(str(repo), 'workspace', 'APP-12', '--summary', 'Reject empty input', '--base', 'main')
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = subprocess.check_output(['git', 'worktree', 'list', '--porcelain'], cwd=repo).decode()
            self.assertEqual(rows.count('worktree '), 1)
            applied = self.invoke(str(repo), 'workspace', 'APP-12', '--summary', 'Reject empty input', '--base', 'main', '--apply')
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(subprocess.check_output(['git', 'worktree', 'list', '--porcelain'], cwd=repo).decode().count('worktree '), 2)


if __name__ == '__main__':
    unittest.main()
