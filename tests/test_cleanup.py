"""`sidequest up` phase 5: removing worktrees whose PR merged, only when nothing can be lost."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import cleanup

GIT = ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid']


def git(path, *args, check=True):
    result = subprocess.run(['git', '-C', str(path), *GIT, *args], capture_output=True, text=True)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class CleanupTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='sidequest cleanup ')
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name).resolve()
        self.repo, self.trees = self.home / 'app', self.home / 'trees'
        git(self.home, 'init', '-q', '-b', 'main', str(self.repo))
        git(self.repo, 'commit', '-q', '--allow-empty', '-m', 'Base')
        self.merged, self.closed = [], []

    def merged_worktree(self, key, number):
        branch = 'feature/' + key + '-done'
        path = self.trees / (key + '-done')
        git(self.repo, 'worktree', 'add', '-q', str(path), '-b', branch)
        (path / (key + '.txt')).write_text('work\n')
        git(path, 'add', '.')
        git(path, 'commit', '-q', '-m', 'Work ' + key)
        self.merged.append({'number': number, 'branch': branch, 'head_oid': git(path, 'rev-parse', 'HEAD')})
        return path, branch

    def run_cleanup(self, cwd=None, busy=lambda path: '', live=None, confirm=lambda candidate: True, dry_run=False):
        live = live or (lambda number: {'state': 'MERGED', 'head_oid': next(pr['head_oid'] for pr in self.merged
                                                                            if pr['number'] == number)})
        return cleanup.clean(self.repo, self.merged, cwd=str(cwd or self.home), busy=busy, live_pr=live,
                             confirm=confirm, close_window=self.closed.append, dry_run=dry_run)

    def branches(self):
        return git(self.repo, 'branch', '--format=%(refname:short)').splitlines()

    def test_a_clean_merged_worktree_is_removed_with_its_branch_and_window(self):
        path, branch = self.merged_worktree('APP-1', 11)
        lines, problems = self.run_cleanup()
        self.assertIn('removed  APP-1    PR #11 merged; worktree and local branch removed', lines)
        self.assertFalse(path.exists())
        self.assertNotIn(branch, self.branches())
        self.assertEqual(self.closed, ['APP-1'])
        self.assertEqual(problems, 0)

    def test_a_branch_that_git_will_not_delete_is_reported_not_called_removed(self):
        path, branch = self.merged_worktree('APP-1', 11)
        real = cleanup._git

        def no_branch_delete(repository, *args):
            if args[:2] == ('branch', '-D'):
                return subprocess.CompletedProcess(args, 1, '', "error: cannot delete branch '" + branch + "'\n")
            return real(repository, *args)
        cleanup._git = no_branch_delete
        self.addCleanup(setattr, cleanup, '_git', real)
        lines, problems = self.run_cleanup()
        self.assertFalse(path.exists())
        self.assertIn(branch, self.branches())
        self.assertEqual(problems, 1)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith('removed  APP-1'), lines)
        self.assertIn('worktree removed; local branch kept (git branch -D: error: cannot delete branch', lines[0])
        self.assertNotIn('local branch removed', lines[0])

    def test_anything_that_could_be_lost_keeps_the_worktree(self):
        dirty, _ = self.merged_worktree('APP-2', 12)
        (dirty / 'APP-2.txt').write_text('unsaved\n')
        untracked, _ = self.merged_worktree('APP-3', 13)
        (untracked / 'new.txt').write_text('new\n')
        extra, _ = self.merged_worktree('APP-4', 14)
        (extra / 'later.txt').write_text('later\n')
        git(extra, 'add', '.')
        git(extra, 'commit', '-q', '-m', 'After the merge')
        here, _ = self.merged_worktree('APP-5', 15)
        booked, _ = self.merged_worktree('APP-6', 16)
        lines, _ = self.run_cleanup(cwd=here / 'sub', busy=lambda path: 'the app is booked for it' if path == str(booked) else '')
        self.assertIn('kept     APP-2    PR #12 merged, but it has uncommitted or untracked changes', lines)
        self.assertIn('kept     APP-3    PR #13 merged, but it has uncommitted or untracked changes', lines)
        self.assertIn("kept     APP-4    PR #14 merged, but feature/APP-4-done has commits that weren't in it", lines)
        self.assertIn('kept     APP-5    PR #15 merged, but you are in it', lines)
        self.assertIn('kept     APP-6    PR #16 merged, but the app is booked for it', lines)
        for path in (dirty, untracked, extra, booked):
            self.assertTrue(path.exists())
        self.assertEqual(self.closed, [])

    def test_github_decides_at_removal_time(self):
        path, branch = self.merged_worktree('APP-7', 17)
        for answer, reason in (({'state': 'OPEN', 'head_oid': self.merged[0]['head_oid']}, 'GitHub no longer reports PR #17 as merged'),
                               ({'state': 'MERGED', 'head_oid': 'f' * 40}, 'its head on GitHub is not the merged head we know'),
                               (None, 'GitHub could not be asked about PR #17')):
            with self.subTest(answer=answer):
                lines, _ = self.run_cleanup(live=lambda number: answer)
                self.assertTrue(any(line.startswith('kept     APP-7') and reason in line for line in lines), lines)
                self.assertTrue(path.exists())
        self.merged[0]['head_oid'] = 'e' * 40
        lines, _ = self.run_cleanup(live=lambda number: {'state': 'MERGED', 'head_oid': 'e' * 40})
        self.assertIn('kept     APP-7    PR #17 merged, but its head commit is not fetched here', lines)

    def test_the_main_checkout_is_never_a_candidate_and_ask_or_dry_run_change_nothing(self):
        git(self.repo, 'checkout', '-q', '-b', 'feature/APP-8-in-main')
        self.merged.append({'number': 18, 'branch': 'feature/APP-8-in-main', 'head_oid': git(self.repo, 'rev-parse', 'HEAD')})
        path, _ = self.merged_worktree('APP-9', 19)
        lines, _ = self.run_cleanup(dry_run=True)
        self.assertEqual([line for line in lines if 'APP-8' in line], [])
        self.assertIn('would    APP-9    remove (PR #19 merged)', lines)
        self.assertTrue(path.exists())
        lines, _ = self.run_cleanup(confirm=lambda candidate: False)
        self.assertIn('kept     APP-9    PR #19 merged; you chose to keep it', lines)
        self.assertTrue(path.exists())


    def up(self, *args):
        import json, os
        from sidequest.snapshots import SnapshotStore
        state = self.home / 'state'
        stamp = '2026-11-09T10:00:00+00:00'
        SnapshotStore(state / 'snapshots').publish({'merged_prs': {'prs': self.merged, 'generated_at': stamp},
                                                    'sync_tickets': {'tickets': [], 'generated_at': stamp},
                                                    'prs': {'open_prs': [], 'generated_at': stamp}})
        settings = self.home / 'settings.json'
        settings.write_text(json.dumps({'workspace': {'repository': str(self.repo), 'terminal': 'shell'}}))
        env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
        env.update(SIDEQUEST_CONFIG=str(settings), SIDEQUEST_STATE_DIR=str(state), SIDEQUEST_DATA_DIR=str(state / 'data'))
        return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), 'up', *args], cwd=self.home,
                              env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def test_up_previews_cleanup_and_never_removes_offline_or_without_an_answer(self):
        path, _ = self.merged_worktree('APP-1', 11)
        dry = self.up('--dry-run', '--offline')
        self.assertIn('would    APP-1    remove (PR #11 merged)', dry.stdout)
        offline = self.up('--offline', '--no-attach', '--yes')
        self.assertIn('cleanup  skipped with --offline: GitHub is asked before anything is removed', offline.stdout)
        self.assertTrue(path.exists())

    def test_without_a_terminal_cleanup_asks_nobody_and_keeps_everything(self):
        from sidequest import sync
        confirm = sync.confirm_removal(mode='ask', yes=False, interactive=False)
        self.assertFalse(confirm({'name': 'APP-1', 'number': 11, 'path': '/w'}))
        self.assertTrue(sync.confirm_removal(mode='ask', yes=True, interactive=False)({'name': 'APP-1'}))
        self.assertTrue(sync.confirm_removal(mode='on', yes=False, interactive=False)({'name': 'APP-1'}))
        answers = iter(['y', 'n'])
        asked = sync.confirm_removal(mode='ask', yes=False, interactive=True, ask=lambda prompt: next(answers))
        self.assertEqual([asked({'name': 'APP-1', 'number': 11, 'path': '/w'}), asked({'name': 'APP-2', 'number': 12, 'path': '/w'})],
                         [True, False])


if __name__ == '__main__':
    unittest.main()
