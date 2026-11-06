"""Regressions from the whole-codebase review (2026-11-06)."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'ticket-tui')]
from sidequest import identity
from sidequest.jira import client
from sidequest.snapshots import SnapshotStore


class AuthorTests(unittest.TestCase):
    def test_an_author_without_a_github_account_does_not_crash(self):
        with patch.object(identity, 'GITHUB_LOGIN', 'me'), patch.object(identity, 'GIT_AUTHOR', ''):
            self.assertFalse(identity.is_my_author([{'login': None, 'name': None}]))
            self.assertTrue(identity.is_my_author([{'login': None}, {'login': 'ME'}]))


class JiraStatusTests(unittest.TestCase):
    def dates(self, current, newest):
        change = {'created': '2026-11-01T10:00:00.000+0000', 'items': [{'field': 'status', 'toString': newest}]}
        with patch.object(client, 'jira', return_value={'values': [change], 'isLast': True}):
            return client.workflow_dates('APP-1', current, '2026-10-01T10:00:00.000+0000')

    def test_a_status_differing_only_in_case_keeps_its_date(self):
        self.assertIsNotNone(self.dates('In Dev', 'IN DEV')['status_since'])

    def test_a_renamed_status_is_unknown_instead_of_failing_jira(self):
        self.assertIsNone(self.dates('In Development', 'In Dev')['status_since'])


class SnapshotTests(unittest.TestCase):
    def test_a_snapshot_that_is_not_an_object_is_refused_like_other_bad_files(self):
        for content in ('[]', 'null', '"text"'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as folder:
                (Path(folder) / 'snapshot.json').write_text(content)
                with self.assertRaises(ValueError):
                    SnapshotStore(folder).read()


class RepositoryTests(unittest.TestCase):
    def test_the_dashboard_and_workspace_actions_use_the_same_repository(self):
        from sidequest.config import workspace_repository
        with patch.dict(os.environ, {'SIDEQUEST_REPO': '/repo-b'}), \
                patch('sidequest.config.SETTINGS', {'workspace': {'repository': '/repo-a'}}):
            self.assertEqual(workspace_repository(), '/repo-b')
        with patch.dict(os.environ, {}, clear=True), \
                patch('sidequest.config.SETTINGS', {'workspace': {'repository': '/repo-a'}}):
            self.assertEqual(workspace_repository(), '/repo-a')

    def test_the_base_ref_comes_from_configuration(self):
        from sidequest.config import base_ref
        with patch('sidequest.config.SETTINGS', {'workspace': {'base_ref': 'origin/develop'}}):
            self.assertEqual(base_ref(), 'origin/develop')
        with patch('sidequest.config.SETTINGS', {}):
            self.assertEqual(base_ref(), 'origin/main')

    def test_the_work_log_compares_branches_with_the_configured_base(self):
        import worklog
        calls = []

        def run(args, timeout=45):
            calls.append(args)
            return ''
        with patch.object(worklog, 'GIT_AUTHOR', 'Me'), patch('sidequest.config.SETTINGS', {'workspace': {'base_ref': 'origin/develop'}}):
            worklog.collect_worklog([{'key': 'APP-1', 'worktree': '/wt'}], Path('/repo'), run)
        self.assertIn('origin/develop..HEAD', calls[-1])


class ShipCheckTests(unittest.TestCase):
    def git(self, repo, *args):
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', *args], cwd=repo,
                       check=True, capture_output=True, env={k: v for k, v in os.environ.items() if not k.startswith('GIT_')})

    def ship_check(self, repo, config=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        if config:
            path = Path(repo).parent / 'config.json'
            path.write_text(json.dumps(config))
            env['SIDEQUEST_CONFIG'] = str(path)
        return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest-ship-check.py'), '--json'],
                              cwd=repo, text=True, capture_output=True, env=env)

    def test_a_non_migration_file_in_db_migrate_does_not_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder) / 'repo'
            (repo / 'db' / 'migrate').mkdir(parents=True)
            (repo / 'db' / 'schema.rb').write_text('ActiveRecord::Schema.define(version: 2026_01_01_000000) do\nend\n')
            self.git(repo, 'init', '-q', '-b', 'main')
            self.git(repo, 'add', '.')
            self.git(repo, 'commit', '-qm', 'base')
            self.git(repo, 'checkout', '-qb', 'fix/APP-1-x')
            (repo / 'db' / 'migrate' / '20260102000000_add.rb').write_text('class Add; def change; create_table :x; end; end\n')
            (repo / 'db' / 'migrate' / 'README.md').write_text('notes\n')
            (repo / 'db' / 'schema.rb').write_text('ActiveRecord::Schema.define(version: 2026_01_02_000000) do\n'
                                                   '  create_table "x" do |t|\n  end\nend\n')
            self.git(repo, 'add', '.')
            self.git(repo, 'commit', '-qm', 'migration')
            result = self.ship_check(repo, {'workspace': {'base_ref': 'main'}})
        self.assertEqual(result.returncode in (0, 1), True, result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_ship_check_compares_with_the_configured_base(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder) / 'repo'
            repo.mkdir()
            self.git(repo, 'init', '-q', '-b', 'develop')
            self.git(repo, 'commit', '--allow-empty', '-qm', 'base')
            self.git(repo, 'checkout', '-qb', 'fix/APP-1-x')
            self.git(repo, 'commit', '--allow-empty', '-qm', 'work')
            result = self.ship_check(repo, {'workspace': {'base_ref': 'develop'}})
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual([line.split(' ', 1)[1] for line in json.loads(result.stdout)['commits']], ['work'], result.stderr)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        from core import Store
        import tui
        self.tui = tui
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(':memory:')
        self.addCleanup(self.store.close)
        self.app = tui.App(self.store, Path(folder.name), demo=True)

    def test_a_bad_terminal_setting_is_a_status_message_not_an_exit(self):
        self.app.demo = False
        self.app.workflow_factory = lambda: (_ for _ in ()).throw(ValueError('Unsupported terminal kitty'))
        self.assertTrue(self.app.press('w'))
        self.assertIn('Unsupported terminal kitty', self.app.message)

    def test_spinner_frames_reuse_the_viewport(self):
        from test_responsive import Screen
        self.app.screen = Screen(40, 145)
        self.app.refreshing = True
        self.app.fit()
        with patch.object(self.app.views, 'rows', wraps=self.app.views.rows) as rows:
            for _ in range(5):
                self.app.draw()
        self.assertEqual(rows.call_count, 0)

    def test_list_mode_prints_cached_results_when_refresh_fails(self):
        from core import Store
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / 'data'
            stdout, stderr = io.StringIO(), io.StringIO()
            argv = ['sidequest', '--refresh', '--list', '--snapshots', folder, '--data-dir', str(data)]
            with patch.object(sys, 'argv', argv), patch('sys.stdout', stdout), patch('sys.stderr', stderr), \
                    patch.object(self.tui, 'run', side_effect=RuntimeError('Jira: no credentials yet.')):
                code = self.tui.main()
        self.assertEqual(code, 1)
        self.assertIn('Cached results; refresh incomplete', stderr.getvalue())
        self.assertIn('Jira: no credentials yet.', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
