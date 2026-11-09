"""`sidequest start KEY`: the dashboard's Space n from a shell (move in Jira, worktree, window)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import start
from sidequest.workspace import GitWorkspace

GIT = ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid']


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), *GIT, *args], check=True, capture_output=True, text=True).stdout


class FakeJira:
    def __init__(self, message='MOVED APP-7 Ready for Dev → In Dev', code=0):
        self.message, self.code, self.moves = message, code, []

    def start_ticket(self, key, yes=False):
        self.moves.append((key, yes))
        return self.code, self.message

    def fetch_one(self, key):
        return {'key': key, 'summary': 'Reject empty input', 'issue_type': 'Bug'}


class StartTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='sidequest start ')
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name).resolve()
        origin, self.repo = self.home / 'origin.git', self.home / 'app'
        git(self.home, 'init', '-q', '--bare', '-b', 'main', str(origin))
        git(self.home, 'clone', '-q', str(origin), str(self.repo))
        git(self.repo, 'commit', '-q', '--allow-empty', '-m', 'Base')
        git(self.repo, 'push', '-q', 'origin', 'main')
        self.workspace = GitWorkspace(self.repo, self.home / 'trees', base_ref='origin/main')

    def test_a_number_takes_the_first_project_and_a_bad_key_is_refused(self):
        self.assertEqual(start.full_key('800', ['APP', 'OPS']), 'APP-800')
        self.assertEqual(start.full_key('ops-12', ['APP']), 'OPS-12')
        for bad, projects in (('800', []), ('not a key', ['APP'])):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                start.full_key(bad, projects)

    def test_the_ticket_moves_then_gets_its_worktree_and_a_second_start_reuses_it(self):
        jira = FakeJira()
        lines, made = start.start('APP-7', jira, self.workspace, yes=True)
        self.assertEqual(jira.moves, [('APP-7', True)])
        self.assertEqual(lines, ['MOVED APP-7 Ready for Dev → In Dev'])
        self.assertEqual(made['branch'], 'fix/APP-7-reject-empty-input')
        self.assertTrue(Path(made['path']).is_dir())
        _, again = start.start('APP-7', jira, self.workspace)
        self.assertEqual(again['path'], made['path'])
        self.assertFalse(again['created'])

    def test_no_move_leaves_jira_alone_and_a_refused_move_still_makes_the_worktree(self):
        jira = FakeJira()
        lines, _ = start.start('APP-7', jira, self.workspace, move=False, prefix='chore')
        self.assertEqual((jira.moves, lines), ([], []))
        refused = FakeJira("APP-8: can't move from QA to In Dev. Available: Done", code=3)
        lines, made = start.start('APP-8', refused, self.workspace)
        self.assertEqual(lines, ["note     APP-8: can't move from QA to In Dev. Available: Done"])
        self.assertTrue(Path(made['path']).is_dir())

    def test_the_command_refuses_a_bad_key_before_any_service_call(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
        settings = self.home / 'settings.json'
        settings.write_text(json.dumps({'workspace': {'repository': str(self.repo)}}))
        env.update(SIDEQUEST_CONFIG=str(settings), SIDEQUEST_STATE_DIR=str(self.home / 'state'))
        ran = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), 'start', 'nope'],
                             env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(ran.returncode, 2, ran.stdout + ran.stderr)
        self.assertIn('expected a Jira key such as APP-123', ran.stderr)


if __name__ == '__main__':
    unittest.main()
