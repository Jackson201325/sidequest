"""Regressions from the whole-codebase review (2026-11-06)."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from time import time as time_now
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
    def dates(self, current, newest, current_id=None, newest_id=None):
        change = {'created': '2026-11-01T10:00:00.000+0000',
                  'items': [{'field': 'status', 'toString': newest, 'to': newest_id}]}
        with patch.object(client, 'jira', return_value={'values': [change], 'isLast': True}):
            return client.workflow_dates('APP-1', current, '2026-10-01T10:00:00.000+0000', status_id=current_id)

    def test_a_renamed_status_keeps_its_date_through_its_id(self):
        self.assertEqual(self.dates('In Development', 'In Dev', '10001', '10001')['status_since'][:10], '2026-11-01')

    def test_a_status_differing_only_in_case_keeps_its_date(self):
        self.assertIsNotNone(self.dates('In Dev', 'IN DEV')['status_since'])

    def test_a_status_matching_by_name_after_an_id_migration_keeps_its_date(self):
        self.assertIsNotNone(self.dates('QA', 'QA', '20003', '10003')['status_since'])

    def test_simultaneous_transitions_use_the_last_one_in_the_changelog(self):
        changes = [{'created': '2026-11-01T10:00:00.000+0000', 'items': [{'field': 'status', 'toString': 'Review', 'to': '2'}]},
                   {'created': '2026-11-01T10:00:00.000+0000', 'items': [{'field': 'status', 'toString': 'QA', 'to': '3'}]}]
        with patch.object(client, 'jira', return_value={'values': changes, 'isLast': True}):
            dates = client.workflow_dates('APP-1', 'QA', '2026-10-01T10:00:00.000+0000', status_id='3')
        self.assertIsNotNone(dates['status_since'])

    def test_a_status_change_during_collection_keeps_the_previous_data(self):
        with self.assertRaises(client.JiraError):
            self.dates('QA', 'In Dev', '10003', '10001')
        with self.assertRaises(client.JiraError):
            self.dates('QA', 'In Dev')


class JiraChangeEventTests(unittest.TestCase):
    def test_workflow_dates_returns_status_and_assignee_changes_with_names(self):
        page = {'isLast': True, 'values': [
            {'created': '2026-10-28T10:00:00.000-0300', 'author': {'displayName': 'Example Developer'},
             'items': [{'field': 'status', 'fromString': 'In Dev', 'toString': 'In Code Review'},
                       {'field': 'assignee', 'from': 'me', 'fromString': 'Example Developer', 'to': 'rev', 'toString': 'Rae'},
                       {'field': 'summary', 'fromString': 'Old', 'toString': 'New'}]}]}
        with patch.object(client, 'jira', return_value=page):
            dates = client.workflow_dates('APP-42', 'In Code Review', account_id='me')
        self.assertEqual(dates['jira_changes'], [
            {'at': '2026-10-28T10:00:00-03:00', 'field': 'status', 'from': 'In Dev', 'to': 'In Code Review',
             'author': 'Example Developer'},
            {'at': '2026-10-28T10:00:00-03:00', 'field': 'assignee', 'from': 'Example Developer', 'to': 'Rae',
             'author': 'Example Developer'}])


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
        with tempfile.TemporaryDirectory() as repo_b:
            with patch.dict(os.environ, {'SIDEQUEST_REPO': repo_b}), \
                    patch('sidequest.config.SETTINGS', {'workspace': {'repository': '/repo-a'}}):
                self.assertEqual(workspace_repository(), repo_b)
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



class ReviewFollowUpTests(unittest.TestCase):
    def test_update_report_says_when_the_refresh_failed(self):
        import tui
        from core import Store
        with tempfile.TemporaryDirectory() as folder:
            stdout, stderr = io.StringIO(), io.StringIO()
            argv = ['sidequest', '--refresh', '--update-report', '--snapshots', folder + '/snapshots',
                    '--data-dir', folder + '/data']
            with patch.object(sys, 'argv', argv), patch('sys.stdout', stdout), patch('sys.stderr', stderr), \
                    patch.object(tui, 'run', side_effect=RuntimeError('Jira: no credentials yet.')), \
                    patch.object(tui.standup, 'update_report', return_value={'path': 'r.md', 'backup': 'b.md'}):
                code = tui.main()
        self.assertEqual(code, 1)
        self.assertIn('refresh incomplete', stderr.getvalue())

    def test_a_stale_sidequest_repo_is_ignored_everywhere(self):
        from sidequest.repository import repository_from
        with tempfile.TemporaryDirectory() as folder:
            settings = {'workspace': {'repository': folder}}
            self.assertEqual(repository_from({'SIDEQUEST_REPO': '/nonexistent/old'}, settings), folder)
            self.assertEqual(repository_from({'SIDEQUEST_REPO': folder}, {}), folder)
            self.assertEqual(repository_from({}, {}), '')
        from sidequest.application import build_workflow
        with tempfile.TemporaryDirectory() as folder:
            workflow = build_workflow({'workspace': {'repository': folder}}, {'SIDEQUEST_REPO': '/nonexistent/old', 'SHELL': '/bin/sh'})
            self.assertEqual(str(workflow.workspace.repository), str(Path(folder).resolve()))

    def test_helper_runs_use_the_repository_folder_again(self):
        import tui
        seen = {}

        def fake(args, **kwargs):
            seen['cwd'] = kwargs.get('cwd')
            return subprocess.CompletedProcess(args, 0, '{}', '')
        with patch.object(tui, 'ROOT', Path('/repo-a')), patch('subprocess.run', side_effect=fake):
            tui.run(['git', 'worktree', 'list', '--porcelain'])
        self.assertEqual(seen['cwd'], Path('/repo-a'))

    def test_ship_check_fetches_the_remote_of_its_base(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            upstream = root / 'upstream.git'
            subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(upstream)], check=True)
            repo = root / 'repo'
            repo.mkdir()
            git = lambda *args: subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', *args],
                                               cwd=repo, check=True, capture_output=True,
                                               env={k: v for k, v in os.environ.items() if not k.startswith('GIT_')})
            git('init', '-q', '-b', 'main')
            git('commit', '--allow-empty', '-qm', 'base')
            git('remote', 'add', 'upstream', str(upstream))
            git('push', '-q', 'upstream', 'main')
            git('fetch', '-q', 'upstream')
            git('checkout', '-qb', 'fix/APP-1-x')
            env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest-ship-check.py'), '--fetch',
                                     '--base', 'upstream/main', '--json'], cwd=repo, text=True, capture_output=True, env=env)
        warnings = json.loads(result.stdout)['warnings']
        self.assertFalse([w for w in warnings if 'fetch failed' in w], warnings)

    def test_ship_check_help_names_the_configured_base(self):
        text = (ROOT / 'bin/sidequest-ship-check.py').read_text().split('"""')[1]
        self.assertNotIn('origin/main', text)
        self.assertNotIn('refresh origin', (ROOT / 'bin/sidequest-ship-check.py').read_text())
        self.assertIn('workspace.base_ref', text)

    def test_helpers_use_the_shared_repository_and_base_settings(self):
        for name in ('sidequest-worktree.py', 'sidequest-workspace-create.py'):
            with self.subTest(name=name):
                source = (ROOT / 'bin' / name).read_text()
                self.assertNotIn("os.environ.get(\"SIDEQUEST_REPO\")", source)
                self.assertNotIn("'base_ref') or 'origin/main'", source)

    def update_report(self, refresh, report):
        import tui
        with tempfile.TemporaryDirectory() as folder:
            stdout, stderr = io.StringIO(), io.StringIO()
            argv = ['sidequest', '--update-report', '--snapshots', folder + '/snapshots', '--data-dir', folder + '/data']
            argv += ['--refresh'] if refresh else []
            from core import Store
            store = Store(Path(folder) / 'seed.sqlite3')
            store.source('refresh_errors', {'messages': ['old failure from yesterday'], 'sources': ['prs']})
            store.close()
            with patch.object(sys, 'argv', argv), patch('sys.stdout', stdout), patch('sys.stderr', stderr), \
                    patch.object(tui, 'Store', lambda path: Store(Path(folder) / 'seed.sqlite3')), \
                    patch.object(tui, 'run', side_effect=RuntimeError('Jira: no credentials yet.')), \
                    patch.object(tui.standup, 'update_report', return_value=report):
                try:
                    code = tui.main()
                except SystemExit as exit:
                    code = exit.code
        return code, stderr.getvalue()

    def test_update_report_ignores_failures_from_earlier_sessions(self):
        code, stderr = self.update_report(False, {'path': 'r.md', 'backup': 'b.md'})
        self.assertIn(code, (0, None))
        self.assertNotIn('refresh incomplete', stderr)

    def test_the_draft_also_says_when_the_refresh_failed(self):
        code, stderr = self.update_report(True, None)
        self.assertEqual(code, 3)
        self.assertIn('refresh incomplete', stderr)

    def test_a_rebuild_refreshes_the_cached_view(self):
        import tui
        from core import Store
        from test_responsive import Screen
        store = Store(':memory:')
        self.addCleanup(store.close)
        app = tui.App(store, Path(tempfile.mkdtemp()), demo=True)
        app.screen = Screen(40, 145)
        app.fit()
        with patch.object(app.views, 'rows', wraps=app.views.rows) as rows:
            app.rebuild()
        self.assertEqual(rows.call_count, 1)

    def test_the_viewport_cache_follows_fallback_data_and_the_clock(self):
        import tui
        from core import Store
        from test_responsive import Screen
        store = Store(':memory:')
        self.addCleanup(store.close)
        app = tui.App(store, Path(tempfile.mkdtemp()), demo=True)
        app.screen = Screen(40, 145)
        key = app.view_key()
        with patch.object(tui.time, 'time', return_value=time_now() + 120):
            self.assertNotEqual(key, app.view_key())

    def test_no_worktree_advice_mentions_both_repository_settings(self):
        source = (ROOT / 'ticket-tui' / 'tui.py').read_text()
        self.assertNotIn('configure workspace.repository and create', source)


class WorkspaceChangeBoundaryTests(unittest.TestCase):
    def test_refresh_and_the_dashboard_never_reach_removal_updates_or_sync(self):
        import ast
        files = [path for path in (ROOT / 'ticket-tui').glob('*.py') if not path.name.startswith('test_')]
        files += [ROOT / 'sidequest/collector.py', ROOT / 'sidequest/snapshots.py', ROOT / 'bin/sidequest-data.py']
        for path in files:
            tree = ast.parse(path.read_text())
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    names.update((node.module or '') + '.' + alias.name for alias in node.names)
                    names.add(node.module or '')
            with self.subTest(file=path.name):
                self.assertFalse({name for name in names if any(part in ('cleanup', 'updates', 'sync')
                                                                 for part in name.split('.'))}, sorted(names))



class OneRuleTests(unittest.TestCase):
    """2026-11-13 review: the same question had different answers in different commands."""

    def test_dashboard_actions_use_the_session_name_sidequest_up_builds(self):
        from sidequest.application import build_workflow
        tmux = {'TMUX': '/tmp/tmux,1,0', 'SHELL': '/bin/sh'}
        for workspace, project, expected in (({}, 'acme', 'acme'), ({'tmux_session': ''}, 'acme', 'acme'),
                                             ({'tmux_session': 'work'}, 'acme', 'work'), ({}, '', 'sidequest')):
            environ = dict(tmux, SIDEQUEST_PROJECT=project) if project else tmux
            with self.subTest(workspace=workspace, project=project):
                flow = build_workflow({'workspace': workspace}, environ, run=lambda *a, **k: '')
                self.assertEqual(flow.terminal.session, expected)

    def test_one_function_names_the_session(self):
        from sidequest import terminal_mode
        self.assertEqual(terminal_mode.session_name({'tmux_session': 'work'}, 'acme'), 'work')
        self.assertEqual(terminal_mode.session_name({'tmux_session': ''}, 'acme'), 'acme')
        self.assertEqual(terminal_mode.session_name({}, ''), 'sidequest')
        self.assertEqual(terminal_mode.session_name(None, None), 'sidequest')
        for path in ('bin/sidequest-up.py', 'bin/sidequest-start.py', 'sidequest/application.py', 'sidequest/overview.py'):
            with self.subTest(path=path):
                self.assertNotIn("get('tmux_session')", (ROOT / path).read_text())

    def test_one_rule_names_the_remote_to_fetch_for_a_base(self):
        from sidequest import gitutil
        self.assertEqual(gitutil.base_remote('upstream/main', ['origin', 'upstream']), 'upstream')
        self.assertEqual(gitutil.base_remote('origin/main', ['origin']), 'origin')
        self.assertEqual(gitutil.base_remote('main', ['origin', 'upstream']), 'origin')
        self.assertEqual(gitutil.base_remote('feature/x', ['origin']), 'origin')
        for path in ('bin/sidequest-up.py', 'bin/sidequest-update-branch.py', 'bin/sidequest-ship-check.py'):
            with self.subTest(path=path):
                self.assertIn('base_remote(', (ROOT / path).read_text())

    def test_one_rule_says_which_terminal_an_action_uses(self):
        from sidequest import terminal_mode
        from sidequest.application import build_workflow
        from sidequest.terminal import ShellTerminal, TmuxTerminal
        tmux = {'TMUX': '/tmp/tmux,1,0', 'SHELL': '/bin/sh'}
        shell = {'workspace': {'terminal': 'shell'}}
        self.assertEqual(terminal_mode.action_mode(tmux, shell), 'shell')
        self.assertEqual(terminal_mode.action_mode(tmux, {}), 'tmux')
        self.assertEqual(terminal_mode.action_mode({'HERDR_ENV': '1'}, {}), 'herdr')
        self.assertEqual(terminal_mode.action_mode({}, {}), 'shell')
        self.assertEqual(terminal_mode.action_mode(dict(tmux, SIDEQUEST_TERMINAL='shell'), {}), 'shell')
        self.assertIsInstance(build_workflow(shell, tmux).terminal, ShellTerminal)
        self.assertIsInstance(build_workflow({}, tmux, run=lambda *a, **k: '').terminal, TmuxTerminal)

    def test_sidequest_meeting_runs_in_place_inside_tmux_when_the_terminal_is_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {k: v for k, v in os.environ.items() if not k.startswith(('SIDEQUEST_', 'TMUX', 'HERDR_'))}
            env.update(HOME=folder, XDG_STATE_HOME=folder + '/state', XDG_DATA_HOME=folder + '/data',
                       XDG_CONFIG_HOME=folder + '/config', SIDEQUEST_CONFIG=str(ROOT / 'tests/fixture-config.json'),
                       SIDEQUEST_TICKETS_DIR=folder + '/tickets', SIDEQUEST_MEETING_COMMAND='echo ran-in-place',
                       SIDEQUEST_TERMINAL='shell', TMUX=folder + '/no-server,1,0', TMUX_PANE='%1')
            done = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest-meeting.py')], capture_output=True,
                                  text=True, env=env, stdin=subprocess.DEVNULL, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('ran-in-place', done.stdout)



class SmallBugTests(unittest.TestCase):
    """2026-11-13 review: bugs that needed no decision."""

    def run_bin(self, name, *args, **extra):
        with tempfile.TemporaryDirectory() as folder:
            env = {k: v for k, v in os.environ.items() if not k.startswith(('SIDEQUEST_', 'TMUX', 'HERDR_'))}
            env.update(HOME=folder, XDG_STATE_HOME=folder + '/state', XDG_DATA_HOME=folder + '/data',
                       XDG_CONFIG_HOME=folder + '/config', SIDEQUEST_CONFIG=str(ROOT / 'tests/fixture-config.json'),
                       PYTHONDONTWRITEBYTECODE='1', **extra)
            return subprocess.run([sys.executable, '-B', str(ROOT / 'bin' / name), *args], capture_output=True,
                                  text=True, env=env, stdin=subprocess.DEVNULL, timeout=60)

    def test_a_comment_of_only_spaces_has_an_empty_first_line(self):
        from sidequest.github import first_line
        for text in ('  \n ', '\n', '', None):
            with self.subTest(text=text):
                self.assertEqual(first_line(text), '')
        self.assertEqual(first_line('\n  Looks   good\nmore'), 'Looks good')

    def test_a_rejected_setting_exits_2_with_one_line_in_every_command(self):
        for name, args in (('sidequest-start.py', ['APP-1']), ('sidequest-meeting.py', []), ('sidequest-data', ['project']),
                           ('sidequest-projects.py', []), ('sqapp', ['--status']), ('sidequest', ['--list'])):
            with self.subTest(name=name):
                done = self.run_bin(name, *args, SIDEQUEST_JIRA_SITEE='https://x.atlassian.net')
                self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
                self.assertIn('SIDEQUEST_JIRA_SITEE is not a Sidequest setting', done.stderr)
                self.assertNotIn('Traceback', done.stderr)
                self.assertEqual(len(done.stderr.strip().splitlines()), 1, done.stderr)

    def test_help_says_which_flags_are_kept_only_for_old_callers(self):
        import re
        for args, flag in ((['collect'], '--json'), (['snapshot'], '--json'), (['snapshot'], '--max-age MAX_AGE'),
                           (['ticket'], '--json'), (['pr-feedback'], '--json'), (['ship-check'], '--no-fetch')):
            with self.subTest(args=args, flag=flag):
                done = self.run_bin('sidequest-data', *args, '--help')
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertRegex(done.stdout, re.escape(flag) + r'\s+[^\n]*no effect')

    def test_help_names_the_subcommands_and_projects_has_help(self):
        done = self.run_bin('sidequest', '--help')
        self.assertEqual(done.returncode, 0, done.stderr)
        for name in ('sidequest up', 'sidequest start', 'sidequest crew', 'sidequest meeting', 'sidequest map',
                     'sidequest projects'):
            self.assertIn(name, done.stdout)
        done = self.run_bin('sidequest', 'projects', '--help')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('sidequest projects: every project profile', done.stdout)
        self.assertNotIn('No projects yet', done.stdout)


if __name__ == '__main__':
    unittest.main()
