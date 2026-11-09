"""Whole-app review fixes: each test fails on the behavior the review reported."""
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'ticket-tui'))
from sidequest import cleanup, collector, config, github, sync, terminal_mode, tmux, updates
from sidequest.access import dashboard_text
from sidequest.jira import client
from sidequest.snapshots import SnapshotStore

GIT = ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', '-c', 'core.editor=true']


def git(path, *args, check=True):
    result = subprocess.run(['git', '-C', str(path), *GIT, *args], capture_output=True, text=True)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class JiraRedirectTests(unittest.TestCase):
    def requests(self, call):
        seen = []

        def urlopen(request, timeout=0):
            seen.append(request)
            return io.BytesIO(b'{}')
        with patch.dict('os.environ', {'SIDEQUEST_JIRA_TOKEN': 'fixture'}), \
                patch.object(client, 'BASES', ['https://example.atlassian.net']), \
                patch.object(client, '_base', [None]), \
                patch.object(client.identity, 'JIRA_EMAIL', 'dev@example.com'), \
                patch('urllib.request.urlopen', side_effect=urlopen):
            call()
        return seen

    def assert_token_stays_on_the_first_host(self, seen):
        self.assertTrue(seen)
        for request in seen:
            # urllib repeats `headers` on every redirect, to any host; unredirected headers go once.
            self.assertNotIn('Authorization', request.headers)
            self.assertTrue(request.unredirected_hdrs.get('Authorization', '').startswith('Basic '))

    def test_api_requests_do_not_repeat_the_token_on_a_redirect(self):
        self.assert_token_stays_on_the_first_host(self.requests(lambda: client.jira('GET', '/rest/api/3/myself')))

    def test_attachment_downloads_do_not_repeat_the_token_on_a_redirect(self):
        issue = {'fields': {'attachment': [{'id': '10', 'filename': 'screen.png'}]}}
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'jira', return_value=issue):
            seen = self.requests(lambda: client.download_attachments('APP-7', Path(folder)))
        self.assert_token_stays_on_the_first_host(seen)


class PushedUnderAnotherNameTests(unittest.TestCase):
    def test_a_branch_pushed_under_another_name_is_not_rebased(self):
        folder = tempfile.TemporaryDirectory(prefix='sidequest review ')
        self.addCleanup(folder.cleanup)
        home = Path(folder.name).resolve()
        origin, repo, mate = home / 'origin.git', home / 'app', home / 'mate'
        git(home, 'init', '-q', '--bare', '-b', 'main', str(origin))
        git(home, 'clone', '-q', str(origin), str(repo))
        git(repo, 'config', 'user.name', 'Test')
        git(repo, 'config', 'user.email', 'test@example.invalid')
        (repo / 'shared.txt').write_text('base\n')
        git(repo, 'add', '.')
        git(repo, 'commit', '-q', '-m', 'Base')
        git(repo, 'push', '-q', '-u', 'origin', 'main')
        path = home / 'trees' / 'APP-5-x'
        git(repo, 'worktree', 'add', '-q', str(path), '-b', 'feature/APP-5-x', 'origin/main')
        (path / 'work.txt').write_text('work\n')
        git(path, 'add', '.')
        git(path, 'commit', '-q', '-m', 'Work')
        git(path, 'push', '-q', '-u', 'origin', 'feature/APP-5-x:mine/APP-5')
        git(home, 'clone', '-q', str(origin), str(mate))
        (mate / 'other.txt').write_text('mate\n')
        git(mate, 'add', '.')
        git(mate, 'commit', '-q', '-m', 'Mate')
        git(mate, 'push', '-q', 'origin', 'main')
        git(repo, 'fetch', '-q', 'origin')
        before = git(path, 'rev-parse', 'HEAD')
        lines, _ = updates.update_all(repo, 'origin/main', busy=lambda path: '')
        self.assertEqual(git(path, 'rev-parse', 'HEAD'), before, lines)
        self.assertIn('behind   APP-5 (1); sidequest up --update merges origin/main in', lines)


class TmuxLayoutTests(unittest.TestCase):
    def test_the_session_is_looked_up_by_its_exact_name(self):
        calls = []

        def run(args, timeout=5):
            calls.append(args)
            return '0 @1 Main\n' if args[1] == 'list-windows' else '@1\n'
        tmux.open_layout(run, 'web', [sync.Window('Main', '/repo')])
        # A bare name also matches a session that only starts with it (web-admin).
        self.assertEqual(next(c for c in calls if c[1] == 'has-session'), ['tmux', 'has-session', '-t', '=web'])

    def test_the_first_window_of_a_new_session_gets_its_keys(self):
        calls = []

        def run(args, timeout=5):
            calls.append(args)
            if args[1] == 'has-session':
                raise RuntimeError('no session')
            if args[1] == 'list-windows':
                return '0 @4 editor\n'
            return '@4\n' if args[1] == 'new-session' else ''
        tmux.open_layout(run, 'proj', [sync.Window('editor', '/repo', keys='nvimc')])
        self.assertIn(['tmux', 'send-keys', '-t', '@4', 'nvimc', 'Enter'], calls)


class UpCommandTests(unittest.TestCase):
    """`sidequest up` with a stand-in tmux on PATH that records what it is asked."""

    def setUp(self):
        self.state = Path(tempfile.mkdtemp(prefix='sidequest up '))
        self.addCleanup(lambda: __import__('shutil').rmtree(self.state, ignore_errors=True))
        self.repo = self.state / 'repo'
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.repo)], check=True)
        SnapshotStore(self.state / 'snapshots').publish({
            name: dict(data, generated_at='2026-11-09T10:00:00+00:00')
            for name, data in (('sync_tickets', {'tickets': []}), ('merged_prs', {'prs': []}), ('prs', {'open_prs': []}))})
        settings = self.state / 'settings.json'
        settings.write_text(json.dumps({'workspace': {'repository': str(self.repo), 'terminal': 'tmux',
                                                      'tmux_session': 'proj'}}))
        tools = self.state / 'tools'
        tools.mkdir()
        self.log = self.state / 'tmux.log'
        (tools / 'tmux').write_text('#!/bin/sh\necho "$@" >> "%s"\n'
                                    'case "$1" in display-message) echo proj;; list-windows) echo "0 @1 Main";; '
                                    'new-window|new-session) echo @2;; esac\n' % self.log)
        (tools / 'tmux').chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
        self.env.update(SIDEQUEST_CONFIG=str(settings), SIDEQUEST_STATE_DIR=str(self.state),
                        SIDEQUEST_DATA_DIR=str(self.state / 'data'), HOME=str(self.state),
                        PATH=str(tools) + os.pathsep + self.env.get('PATH', ''), TMUX='/tmp/fake,1,0')

    def up(self, *args):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), 'up', *args], cwd=self.repo,
                              env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def test_rebuild_is_refused_inside_the_session_it_would_close(self):
        ran = self.up('--offline', '--no-attach', '-r')
        self.assertEqual(ran.returncode, 2, ran.stdout + ran.stderr)
        self.assertIn('-r closes tmux session proj, and this command runs inside it', ran.stderr)
        self.assertNotIn('kill-session', self.log.read_text() if self.log.exists() else '')

    def test_a_dry_run_writes_no_state(self):
        ran = self.up('--offline', '--dry-run')
        self.assertIn('Dry run: nothing changed.', ran.stdout, ran.stdout + ran.stderr)
        self.assertFalse((self.state / 'window-order.json').exists())


class TmuxInsideTests(unittest.TestCase):
    def test_inside_is_true_only_for_the_session_this_runs_in(self):
        answer = subprocess.CompletedProcess([], 0, 'proj\n', '')
        with patch.dict(os.environ, {'TMUX': '/tmp/fake,1,0'}), patch('subprocess.run', return_value=answer):
            self.assertTrue(terminal_mode.Tmux().inside('proj'))
            self.assertFalse(terminal_mode.Tmux().inside('pro'))
        with patch.dict(os.environ, {}, clear=True), patch('subprocess.run', return_value=answer) as run:
            self.assertFalse(terminal_mode.Tmux().inside('proj'))
            run.assert_not_called()


class CleanupTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='sidequest review cleanup ')
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name).resolve()
        self.repo, self.trees = self.home / 'app', self.home / 'trees'
        git(self.home, 'init', '-q', '-b', 'main', str(self.repo))
        (self.repo / '.gitignore').write_text('.env\n')
        (self.repo / '.env').write_text('KEY=shared\n')
        git(self.repo, 'add', '.gitignore')
        git(self.repo, 'commit', '-q', '-m', 'Base')
        self.merged = []

    def merged_worktree(self, key, number):
        branch, path = 'feature/' + key + '-done', self.trees / (key + '-done')
        git(self.repo, 'worktree', 'add', '-q', str(path), '-b', branch)
        (path / (key + '.txt')).write_text('work\n')
        git(path, 'add', '.')
        git(path, 'commit', '-q', '-m', 'Work ' + key)
        self.merged.append({'number': number, 'branch': branch, 'head_oid': git(path, 'rev-parse', 'HEAD')})
        return path

    def run_cleanup(self, **options):
        live = lambda number: {'state': 'MERGED', 'head_oid': next(pr['head_oid'] for pr in self.merged
                                                                   if pr['number'] == number)}
        return cleanup.clean(self.repo, self.merged, cwd=str(self.home), busy=lambda path: '', live_pr=live,
                             confirm=lambda candidate: True, close_window=lambda name: None, **options)

    def test_a_changed_local_file_keeps_the_worktree_and_an_unchanged_copy_does_not(self):
        changed, copied = self.merged_worktree('APP-1', 11), self.merged_worktree('APP-2', 12)
        (changed / '.env').write_text('KEY=only-here\n')
        (copied / '.env').write_text('KEY=shared\n')
        lines, problems = self.run_cleanup(local_files=['.env'])
        self.assertIn('kept     APP-1    PR #11 merged, but its .env differs from the main checkout', lines)
        self.assertIn('removed  APP-2    PR #12 merged; worktree and local branch removed', lines)
        self.assertTrue((changed / '.env').exists())
        self.assertEqual(problems, 0)

    def test_a_worktree_whose_state_cannot_be_read_is_kept(self):
        broken = self.merged_worktree('APP-3', 13)
        (broken / '.git').unlink()
        lines, problems = self.run_cleanup()
        self.assertIn('kept     APP-3    PR #13 merged, but its changes could not be read (git status failed)', lines)
        self.assertTrue(broken.exists())
        self.assertEqual(problems, 0)


class SyncFailureTests(unittest.TestCase):
    SETTINGS = {'jira': {'site': 'https://example.atlassian.net', 'projects': ['APP']},
                'github': {'repository': 'example/app'}}

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for target, name, value in ((config, 'SETTINGS', self.SETTINGS), (collector.identity, 'GITHUB_REPO', 'example/app'),
                                    (collector.identity, 'JIRA_ACCOUNT_ID', 'me'),
                                    (collector, 'collect_prs', lambda: {'enabled': True, 'open_prs': []}),
                                    (collector, 'collect_jira', lambda prs=(): {'enabled': True, 'jira_available': True,
                                                                                'tickets': []}),
                                    (collector.client, 'search', lambda *args: [])):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_dashboard_refresh_keeps_a_sync_failure_until_the_next_sync(self):
        with patch.object(github, 'list_merged_prs', return_value=[{'number': 7}]):
            collector.collect(self.folder, sync=True)
        with patch.object(github, 'list_merged_prs', side_effect=RuntimeError('offline')):
            failed = collector.collect(self.folder, sync=True)
        refreshed = collector.collect(self.folder)
        self.assertEqual(refreshed['failures'].get('merged_prs'), failed['failures']['merged_prs'])
        self.assertTrue(sync.source(refreshed, 'merged_prs', 'prs')[1], 'the plan still reports the failed source')
        cached = collector.collect(self.folder, max_age=3600)
        self.assertEqual(cached['generated_at'], refreshed['generated_at'], 'a sync failure does not defeat --max-age')
        with patch.object(github, 'list_merged_prs', return_value=[{'number': 8}]):
            self.assertNotIn('merged_prs', collector.collect(self.folder, sync=True)['failures'])

    def test_the_dashboard_reports_only_its_own_sources(self):
        from core import Store
        from queue_evidence import QueueEvidence
        store = Store(':memory:')
        self.addCleanup(store.close)
        snapshot = {'version': 1, 'generated_at': '2026-11-09T10:00:00+00:00', 'failures': {'merged_prs': 'GitHub: offline.'},
                    'sources': {'jira': {'jira_available': True, 'tickets': [], 'generated_at': '2026-11-09T10:00:00+00:00'},
                                'prs': {'open_prs': [], 'generated_at': '2026-11-09T10:00:00+00:00'}}}
        (self.folder / 'snapshot.json').write_text(json.dumps(snapshot))
        evidence = QueueEvidence(store, self.folder)
        self.assertEqual((evidence.refresh_errors, evidence.failed_sources), ([], set()))
        updates_, messages, failed = evidence.collect(lambda args, timeout: json.dumps(snapshot))
        self.assertEqual((sorted(updates_), messages, failed), (['jira', 'prs'], [], set()))


class JiraStartReasonTests(unittest.TestCase):
    def test_a_refused_move_reaches_the_dashboard_with_its_reason(self):
        main = runpy.run_path(str(ROOT / 'bin' / 'sidequest-data.py'), run_name='sidequest_data_test')['main']
        message = "APP-7: can't move from QA to In Dev. Available: Done"
        stderr = io.StringIO()
        with patch.object(sys, 'argv', ['sidequest-data', 'jira-start', 'APP-7']), patch('sys.stderr', stderr), \
                patch.object(client, 'start_ticket', return_value=(3, message)):
            code = main()
        lines = stderr.getvalue().splitlines()
        self.assertEqual((code, lines[0]), (3, message))
        record = next(line for line in lines if line.startswith('sidequest-data-failure: '))
        self.assertEqual(dashboard_text(record[len('sidequest-data-failure: '):]), message)


if __name__ == '__main__':
    unittest.main()
