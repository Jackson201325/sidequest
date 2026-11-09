"""`sidequest up` phase 2: the sync plan and worktree creation, in real temporary Git repositories."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import sync, tmux
from sidequest.snapshots import SnapshotStore
from sidequest.workspace import GitWorkspace

GIT = ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid']


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), *GIT, *args], check=True, capture_output=True, text=True).stdout


class SyncPlanTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='sidequest sync ')
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name).resolve()
        origin, self.repo, self.worktrees = self.home / 'origin.git', self.home / 'app', self.home / 'worktrees'
        git(self.home, 'init', '-q', '--bare', '-b', 'main', str(origin))
        git(self.home, 'clone', '-q', str(origin), str(self.repo))
        git(self.repo, 'commit', '-q', '--allow-empty', '-m', 'Base')
        for branch in ('feature/APP-3-from-origin', 'hotfix/shared-fix', 'feature/APP-5-merged'):
            git(self.repo, 'branch', branch)
        git(self.repo, 'push', '-q', 'origin', 'main', 'feature/APP-3-from-origin', 'hotfix/shared-fix', 'feature/APP-5-merged')
        for branch in ('feature/APP-3-from-origin', 'hotfix/shared-fix', 'feature/APP-5-merged'):
            git(self.repo, 'branch', '-q', '-D', branch)
        git(self.repo, 'branch', 'feature/APP-2-local-work')
        git(self.repo, 'worktree', 'add', '-q', str(self.worktrees / 'APP-4-ready'), '-b', 'feature/APP-4-ready')
        self.workspace = GitWorkspace(self.repo, self.worktrees, base_ref='origin/main')
        tickets = [{'key': 'APP-1', 'summary': 'Reject empty input', 'issue_type': 'Bug', 'status': 'Ready'},
                   {'key': 'APP-2', 'summary': 'Local work', 'issue_type': 'Task', 'status': 'In Dev'},
                   {'key': 'APP-3', 'summary': 'From origin', 'issue_type': 'Task', 'status': 'In Dev'},
                   {'key': 'APP-4', 'summary': 'Ready', 'issue_type': 'Task', 'status': 'In Dev'},
                   {'key': 'APP-5', 'summary': 'Merged', 'issue_type': 'Task', 'status': 'In QA'}]
        prs = [{'number': 21, 'branch': 'hotfix/shared-fix', 'is_cross_repository': False},
               {'number': 22, 'branch': 'feature/APP-2-local-work', 'is_cross_repository': False},
               {'number': 23, 'branch': 'someone/fork-branch', 'is_cross_repository': True}]
        merged = [{'number': 9, 'branch': 'feature/APP-5-merged', 'head_oid': '0' * 40}]
        self.snapshot = {'sources': {'sync_tickets': {'tickets': tickets}, 'prs': {'open_prs': prs},
                                     'merged_prs': {'prs': merged}}, 'failures': {}}

    def state(self):
        return git(self.repo, 'for-each-ref', '--format=%(refname) %(objectname)'), git(self.repo, 'worktree', 'list', '--porcelain')

    def test_the_plan_lists_each_ticket_and_pr_and_changes_nothing(self):
        before = self.state()
        plan = sync.discover(self.snapshot, self.workspace)
        rows = {(action.kind, action.target): action for action in plan}
        self.assertEqual(rows[('create', 'APP-1')].branch, 'fix/APP-1-reject-empty-input')
        self.assertEqual(rows[('create', 'APP-2')].branch, 'feature/APP-2-local-work')
        self.assertEqual(rows[('create', 'APP-3')].branch, 'feature/APP-3-from-origin')
        self.assertEqual(rows[('exists', 'APP-4')].path, str(self.worktrees / 'APP-4-ready'))
        self.assertIn('PR #9', rows[('skip', 'APP-5')].reason)
        self.assertEqual(rows[('create', 'hotfix/shared-fix')].branch, 'hotfix/shared-fix')
        self.assertNotIn(('create', 'feature/APP-2-local-work'), rows, 'a PR on a ticket branch is not planned twice')
        self.assertFalse(any(action.target == 'someone/fork-branch' for action in plan), 'fork PRs are left out')
        with self.assertRaises(ValueError):
            self.workspace.preview_branch('main')
        self.assertEqual(self.state(), before)

    def test_apply_creates_the_planned_worktrees_and_a_second_run_finds_them(self):
        results = sync.apply(sync.discover(self.snapshot, self.workspace), self.workspace)
        self.assertTrue(all(result.ok for result in results), [result.line for result in results])
        listed = git(self.repo, 'worktree', 'list', '--porcelain')
        for branch in ('fix/APP-1-reject-empty-input', 'feature/APP-2-local-work', 'feature/APP-3-from-origin',
                       'hotfix/shared-fix'):
            self.assertIn('branch refs/heads/' + branch, listed)
        self.assertNotIn('APP-5', listed)
        self.assertEqual(git(self.repo, 'rev-parse', '--abbrev-ref', 'feature/APP-3-from-origin@{u}').strip(),
                         'origin/feature/APP-3-from-origin')
        again = sync.discover(self.snapshot, self.workspace)
        self.assertEqual({action.kind for action in again}, {'exists', 'skip'})

    def test_a_missing_source_skips_its_part_and_a_changed_repository_is_not_applied(self):
        snapshot = dict(self.snapshot, failures={'sync_tickets': 'Jira failed'})
        plan = sync.discover(snapshot, self.workspace)
        self.assertTrue(any(action.kind == 'blocked' and 'Jira failed' in action.reason for action in plan))
        self.assertFalse(any(action.target.startswith('APP-1') for action in plan))
        plan = sync.discover(self.snapshot, self.workspace)
        git(self.repo, 'branch', 'fix/APP-1-reject-empty-input')
        results = {result.target: result for result in sync.apply(plan, self.workspace)}
        self.assertFalse(results['APP-1'].ok)
        self.assertIn('preview again', results['APP-1'].line)

    def test_up_dry_run_prints_the_plan_without_changes(self):
        state = self.home / 'state'
        SnapshotStore(state / 'snapshots').publish({name: dict(data, generated_at='2026-11-09T10:00:00+00:00')
                                                    for name, data in self.snapshot['sources'].items()})
        settings = self.home / 'settings.json'
        settings.write_text(json.dumps({'workspace': {'repository': str(self.repo), 'worktrees_dir': str(self.worktrees),
                                                      'base_ref': 'origin/main'}}))
        env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
        env.update(SIDEQUEST_CONFIG=str(settings), SIDEQUEST_STATE_DIR=str(state), SIDEQUEST_DATA_DIR=str(self.home / 'data'))
        before = self.state()
        shown = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), 'up', '--dry-run', '--offline'],
                               cwd=self.repo, env=env, capture_output=True, text=True)
        self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
        self.assertIn('create   APP-1', shown.stdout)
        self.assertIn('fix/APP-1-reject-empty-input', shown.stdout)
        self.assertIn('exists   APP-4', shown.stdout)
        self.assertIn('skip     APP-5', shown.stdout)
        self.assertIn('Dry run: nothing changed', shown.stdout)
        self.assertEqual(self.state(), before)



class LayoutTests(unittest.TestCase):
    WORKTREES = [('/p/app', 'feature/APP-600-main-work'), ('/p/APP-3-c', 'feature/APP-3-c'),
                 ('/p/APP-1-a', 'fix/APP-1-a'), ('/p/APP-9-z', 'feature/APP-9-z'), ('/p/shared', 'hotfix/shared-fix'),
                 ('/p/APP-2-b', 'feature/APP-2-b')]
    SNAPSHOT = {'sources': {
        'jira': {'tickets': [{'key': 'APP-1', 'first_assigned_at': '2026-11-03T10:00:00+00:00'},
                             {'key': 'APP-2', 'first_assigned_at': '2026-11-01T10:00:00+00:00'},
                             {'key': 'APP-3', 'first_assigned_at': '2026-11-02T10:00:00+00:00'}]},
        'prs': {'open_prs': [{'branch': 'hotfix/shared-fix', 'created_at': '2026-11-02T12:00:00Z'}]}}}
    EXTRAS = [{'name': 'queue', 'command': 'sidequest', 'at': 'start', 'stay': True},
              {'name': 'report', 'command': 'sidequest --report', 'at': 'end'},
              {'name': 'notes', 'cwd': '/p/notes', 'at': 'end'}]

    def test_windows_follow_assignment_order_between_the_extra_windows(self):
        windows = sync.layout(self.SNAPSHOT, self.WORKTREES, self.EXTRAS, '/p')
        self.assertEqual([window.name for window in windows],
                         ['queue', 'Main APP-600', 'APP-2', 'APP-3', 'hotfix-shared-fix', 'APP-1', 'APP-9', 'report', 'notes'])
        by_name = {window.name: window for window in windows}
        self.assertEqual(by_name['APP-3'].path, '/p/APP-3-c')
        self.assertEqual(by_name['queue'].path, '/p')
        self.assertEqual((by_name['queue'].command, by_name['queue'].stay), ('sidequest', True))
        self.assertIn('exec', tmux.process(by_name['queue']), 'stay in tmux: a shell is left when the command ends')
        self.assertEqual(tmux.process(by_name['report']), 'sidequest --report')
        self.assertIsNone(by_name['notes'].command)

    def test_remembered_dates_keep_a_ticket_in_place_after_it_leaves_your_list(self):
        # 08:30 at -03:00 is 11:30 UTC: after APP-2 (10:00 UTC), before APP-3 (next day). Times, not text, decide.
        windows = sync.layout(self.SNAPSHOT, self.WORKTREES, [], '/p', remembered={'APP-9': '2026-11-01T08:30:00-03:00'})
        self.assertEqual([window.name for window in windows][:4], ['Main APP-600', 'APP-2', 'APP-9', 'APP-3'])
        late = sync.layout(self.SNAPSHOT, self.WORKTREES, [], '/p', remembered={'APP-9': '2026-11-01T09:30:00+00:00'})
        self.assertEqual([window.name for window in late][:3], ['Main APP-600', 'APP-9', 'APP-2'])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'window-order.json'
            path.write_text(json.dumps({'APP-9': '2026-11-01T12:00:00+00:00', 'APP-1': 'old'}))
            dates = sync.remember_order(path, self.SNAPSHOT)
            self.assertEqual(dates['APP-9'], '2026-11-01T12:00:00+00:00', 'kept after leaving the list')
            self.assertEqual(dates['APP-1'], '2026-11-03T10:00:00+00:00', 'the current date wins')
            self.assertEqual(json.loads(path.read_text()), dates)

    def test_tmux_layout_reuses_moves_and_never_closes_windows(self):
        from sidequest import tmux
        windows = sync.layout(self.SNAPSHOT, self.WORKTREES[:2], self.EXTRAS[:1], '/p')
        calls, listed = [], '0 @1 APP-3\n1 @2 Main\n2 @3 my-own\n'

        def run(args, timeout=5):
            calls.append(args)
            if args[1] == 'has-session':
                return ''
            if args[1] == 'list-windows':
                return listed
            if args[1] == 'new-window':
                return '@9\n'
            return ''
        tmux.open_layout(run, 'proj', windows)
        names = [c for c in calls if c[1] in ('new-window', 'new-session')]
        self.assertEqual([c[c.index('-n') + 1] for c in names], ['queue'], 'existing windows are reused')
        self.assertIn(['tmux', 'rename-window', '-t', '@2', 'Main APP-600'], calls)
        self.assertFalse(any(c[1] in ('kill-window', 'kill-session') for c in calls))
        moved = [c[c.index('-s') + 1] for c in calls if c[1] == 'move-window']
        final = moved[len(moved) // 2:]
        self.assertEqual(final, ['@9', '@2', '@1', '@3'], 'queue, Main, ticket, then windows of your own')

    def test_keys_are_typed_once_into_a_new_window(self):
        from sidequest import tmux
        calls = []

        def run(args, timeout=5):
            calls.append(args)
            if args[1] == 'list-windows':
                return '0 @1 Main\n'
            return '@5\n' if args[1] == 'new-window' else ''
        extras = [{'name': 'editor', 'keys': 'nvimc', 'at': 'end'}]
        tmux.open_layout(run, 'proj', sync.layout(self.SNAPSHOT, self.WORKTREES[:1], extras, '/p'))
        self.assertIn(['tmux', 'send-keys', '-t', '@5', 'nvimc', 'Enter'], calls)
        calls.clear()

        def again(args, timeout=5):
            calls.append(args)
            return '0 @1 Main APP-600\n1 @5 editor\n' if args[1] == 'list-windows' else ''
        tmux.open_layout(again, 'proj', sync.layout(self.SNAPSHOT, self.WORKTREES[:1], extras, '/p'))
        self.assertFalse(any(c[1] == 'send-keys' for c in calls), 'an existing window is not typed into again')

    def test_a_missing_session_is_created_with_the_first_window(self):
        from sidequest import tmux
        calls = []

        def run(args, timeout=5):
            calls.append(args)
            if args[1] == 'has-session':
                raise RuntimeError('no session')
            if args[1] == 'list-windows':
                return '0 @1 queue\n'
            return '@1\n'
        tmux.open_layout(run, 'proj', sync.layout(self.SNAPSHOT, self.WORKTREES[:1], self.EXTRAS[:1], '/p'))
        created = next(c for c in calls if c[1] == 'new-session')
        self.assertEqual(created[:8], ['tmux', 'new-session', '-d', '-s', 'proj', '-n', 'queue', '-c'])

    def test_up_runs_hooks_and_reports_a_failing_one(self):
        state, settings = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()) / 'settings.json'
        self.addCleanup(lambda: __import__('shutil').rmtree(state, ignore_errors=True))
        repo = state / 'repo'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(repo)], check=True)
        SnapshotStore(state / 'snapshots').publish({
            'sync_tickets': {'tickets': [], 'generated_at': '2026-11-09T10:00:00+00:00'},
            'merged_prs': {'prs': [], 'generated_at': '2026-11-09T10:00:00+00:00'},
            'prs': {'open_prs': [], 'generated_at': '2026-11-09T10:00:00+00:00'}})
        settings.write_text(json.dumps({'workspace': {
            'repository': str(repo), 'terminal': 'shell',
            'on_up': ['sh -c "echo first hook ran"', 'sh -c "echo broken >&2; exit 3"', '~/hook-from-home']}}))
        (state / 'hook-from-home').write_text('#!/bin/sh\necho home hook\n')
        (state / 'hook-from-home').chmod(0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
        env.update(SIDEQUEST_CONFIG=str(settings), SIDEQUEST_STATE_DIR=str(state), SIDEQUEST_DATA_DIR=str(state / 'data'),
                   HOME=str(state))
        ran = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), 'up', '--offline', '--no-attach'],
                             cwd=repo, env=env, capture_output=True, text=True)
        self.assertEqual(ran.returncode, 1, ran.stdout + ran.stderr)
        self.assertIn('hook     sh -c "echo first hook ran"', ran.stdout)
        self.assertIn('failed   sh -c "echo broken >&2; exit 3" (exit 3: broken)', ran.stdout)
        self.assertIn('windows  not opened: workspace.terminal is shell', ran.stdout)
        self.assertIn('hook     ~/hook-from-home', ran.stdout)
        dry = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), 'up', '--offline', '--dry-run'],
                             cwd=repo, env=env, capture_output=True, text=True)
        self.assertIn('would run sh -c "echo first hook ran"', dry.stdout)

    @unittest.skipUnless(__import__('shutil').which('tmux'), 'tmux is not installed')
    def test_short_flags_combine_and_rebuild_is_previewed(self):
        state, settings = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()) / 'settings.json'
        self.addCleanup(lambda: __import__('shutil').rmtree(state, ignore_errors=True))
        repo = state / 'repo'
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(repo)], check=True)
        settings.write_text(json.dumps({'workspace': {'repository': str(repo), 'terminal': 'tmux',
                                                      'tmux_session': 'sq-test-never-made'}}))
        env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
        env.update(SIDEQUEST_CONFIG=str(settings), SIDEQUEST_STATE_DIR=str(state), SIDEQUEST_DATA_DIR=str(state / 'data'))
        dry = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), 'up', '-rnu', '--dry-run'],
                             cwd=repo, env=env, capture_output=True, text=True)
        self.assertNotEqual(dry.returncode, 2, dry.stdout + dry.stderr)
        self.assertNotIn('Collecting', dry.stdout, '-n is --offline')
        self.assertIn('would close tmux session sq-test-never-made first; this stops what runs in its windows', dry.stdout)
        self.assertNotIn('first hook ran\n', dry.stdout.replace('would run sh -c "echo first hook ran"', ''))


if __name__ == '__main__':
    unittest.main()


class WhenDueTests(unittest.TestCase):
    SNAPSHOT = {'sources': {'sync_tickets': {'tickets': [], 'generated_at': '2026-11-09T10:00:00+00:00'}}}

    def test_a_recent_sync_is_fresh_and_an_old_or_missing_one_is_due(self):
        fresh = sync.fresh(self.SNAPSHOT, '120', now='2026-11-09T11:59:00+00:00', tz='UTC')
        self.assertEqual(fresh, 'fresh    last sync 10:00; next sync after 12:00 (sync.every_minutes 120)')
        self.assertEqual(sync.fresh(self.SNAPSHOT, '120', now='2026-11-09T12:00:00+00:00', tz='UTC'), '')
        self.assertEqual(sync.fresh({'sources': {}}, '120', now='2026-11-09T10:01:00+00:00', tz='UTC'), '')
        self.assertEqual(sync.fresh(self.SNAPSHOT, '', now='2026-11-09T10:01:00+00:00', tz='UTC'), '', 'no setting: always due')

    def test_up_when_due_skips_the_network_while_the_last_sync_is_fresh(self):
        from datetime import datetime, timezone
        state, settings = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()) / 'settings.json'
        self.addCleanup(lambda: __import__('shutil').rmtree(state, ignore_errors=True))
        repo = state / 'repo'
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(repo)], check=True)
        SnapshotStore(state / 'snapshots').publish({name: dict(data, generated_at=datetime.now(timezone.utc).isoformat())
                                                    for name, data in (('sync_tickets', {'tickets': []}),
                                                                       ('merged_prs', {'prs': []}),
                                                                       ('prs', {'open_prs': []}))})
        settings.write_text(json.dumps({'workspace': {'repository': str(repo), 'terminal': 'shell'},
                                        'sync': {'every_minutes': '120'}}))
        env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
        env.update(SIDEQUEST_CONFIG=str(settings), SIDEQUEST_STATE_DIR=str(state), SIDEQUEST_DATA_DIR=str(state / 'data'))
        ran = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), 'up', '--when-due', '--no-attach'],
                             cwd=repo, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assertIn('fresh    last sync', ran.stdout)
        self.assertNotIn('Collecting', ran.stdout)
