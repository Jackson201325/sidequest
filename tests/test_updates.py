"""`sidequest up` phase 4: guarded branch updates, in real repositories with a bare origin and a teammate."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import updates

GIT = ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', '-c', 'core.editor=true']


def git(path, *args, check=True):
    result = subprocess.run(['git', '-C', str(path), *GIT, *args], capture_output=True, text=True)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class UpdateTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='sidequest updates ')
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name).resolve()
        self.origin, self.repo, self.mate = self.home / 'origin.git', self.home / 'app', self.home / 'mate'
        git(self.home, 'init', '-q', '--bare', '-b', 'main', str(self.origin))
        git(self.home, 'clone', '-q', str(self.origin), str(self.repo))
        # updates.py runs rebase/merge without GIT's -c identity; CI runners have no global one.
        git(self.repo, 'config', 'user.name', 'Test')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        (self.repo / 'shared.txt').write_text('base\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-q', '-m', 'Base')
        git(self.repo, 'push', '-q', '-u', 'origin', 'main')
        git(self.home, 'clone', '-q', str(self.origin), str(self.mate))
        self.trees = self.home / 'trees'

    def worktree(self, branch, push=False):
        path = self.trees / branch.split('/')[-1]
        git(self.repo, 'worktree', 'add', '-q', str(path), '-b', branch, 'origin/main')
        (path / (branch.split('/')[-1] + '.txt')).write_text('work\n')
        git(path, 'add', '.')
        git(path, 'commit', '-q', '-m', 'Work on ' + branch)
        if push:
            git(path, 'push', '-q', '-u', 'origin', branch)
        return path

    def mate_commit(self, branch, name='mate.txt', text='mate\n'):
        git(self.mate, 'fetch', '-q', 'origin')
        git(self.mate, 'checkout', '-q', '-B', branch, 'origin/' + branch)
        (self.mate / name).write_text(text)
        git(self.mate, 'add', '.')
        git(self.mate, 'commit', '-q', '-m', 'Mate on ' + branch)
        git(self.mate, 'push', '-q', 'origin', branch)
        git(self.repo, 'fetch', '-q', 'origin')

    def run_updates(self, **options):
        options.setdefault('busy', lambda path: '')
        return updates.update_all(self.repo, 'origin/main', **options)

    def test_a_pushed_branch_takes_its_origin_commits_and_keeps_uncommitted_work(self):
        path = self.worktree('feature/APP-1-x', push=True)
        self.mate_commit('feature/APP-1-x')
        (path / 'APP-1-x.txt').write_text('my unsaved edit\n')
        lines, problems = self.run_updates()
        self.assertIn('updated  APP-1    pulled 1 from origin/feature/APP-1-x', lines)
        self.assertEqual((path / 'mate.txt').read_text(), 'mate\n')
        self.assertEqual((path / 'APP-1-x.txt').read_text(), 'my unsaved edit\n')
        self.assertEqual(problems, 0)

    def test_main_follows_origin_main_and_a_main_with_its_own_commits_is_left(self):
        self.worktree('feature/APP-2-y')
        git(self.repo, 'checkout', '-q', '-b', 'feature/APP-9-main-checkout')
        self.mate_commit('main')
        lines, _ = self.run_updates()
        self.assertEqual(git(self.repo, 'rev-parse', 'main'), git(self.repo, 'rev-parse', 'origin/main'))
        self.assertIn('updated  main     fast-forwarded to origin/main (+1)', lines)
        git(self.repo, 'branch', '-f', 'main', 'origin/main~1')
        git(self.repo, 'checkout', '-q', 'main')
        (self.repo / 'local.txt').write_text('mine\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-q', '-m', 'Local main commit')
        git(self.repo, 'checkout', '-q', 'feature/APP-9-main-checkout')
        lines, _ = self.run_updates()
        self.assertIn("skipped  main     local main has commits that aren't on origin/main", lines)

    def test_an_unpushed_branch_is_rebased_and_a_conflict_is_aborted(self):
        path = self.worktree('feature/APP-3-z')
        self.mate_commit('main', name='other.txt')
        lines, _ = self.run_updates()
        self.assertIn('rebased  APP-3    onto origin/main (+1; not pushed yet)', lines)
        self.assertEqual(git(path, 'merge-base', 'HEAD', 'origin/main'), git(self.repo, 'rev-parse', 'origin/main'))
        before = git(path, 'rev-parse', 'HEAD')
        (path / 'shared.txt').write_text('mine\n')
        git(path, 'commit', '-q', '-am', 'Change shared')
        before = git(path, 'rev-parse', 'HEAD')
        self.mate_commit('main', name='shared.txt', text='theirs\n')
        lines, problems = self.run_updates()
        self.assertTrue(any(line.startswith('failed   APP-3') and 'conflicts in shared.txt' in line and 'left as it was' in line
                            for line in lines), lines)
        self.assertEqual(git(path, 'rev-parse', 'HEAD'), before)
        self.assertEqual(git(path, 'status', '--porcelain'), '')
        self.assertEqual(problems, 1)

    def test_a_pushed_branch_is_only_listed_unless_merging_is_asked(self):
        path = self.worktree('feature/APP-4-w', push=True)
        self.mate_commit('main', name='other.txt')
        before = git(path, 'rev-parse', 'HEAD')
        lines, _ = self.run_updates()
        self.assertIn('behind   APP-4 (1); sidequest up --update merges origin/main in', lines)
        self.assertEqual(git(path, 'rev-parse', 'HEAD'), before)
        lines, _ = self.run_updates(merge_base=True)
        self.assertIn('merged   APP-4    origin/main (+1); not pushed: git push when ready', lines)
        self.assertEqual(git(path, 'rev-list', '--count', 'origin/main..HEAD'), '2', 'the work and the merge commit')
        self.assertEqual(git(path, 'rev-parse', 'HEAD^2'), git(self.repo, 'rev-parse', 'origin/main'))
        self.assertEqual(git(self.repo, 'rev-parse', 'origin/feature/APP-4-w'), before, 'nothing is pushed')

    def test_guards_skip_with_their_reason(self):
        diverged = self.worktree('feature/APP-5-d', push=True)
        self.mate_commit('feature/APP-5-d')
        (diverged / 'local.txt').write_text('local\n')
        git(diverged, 'add', '.')
        git(diverged, 'commit', '-q', '-m', 'Local')
        busy = self.worktree('feature/APP-7-b')
        self.mate_commit('main', name='other.txt')
        before = {path: git(path, 'rev-parse', 'HEAD') for path in (diverged, busy)}
        lines, problems = self.run_updates(busy=lambda path: 'the app is booked for it' if path == str(busy) else '')
        self.assertTrue(any(line.startswith('skipped  APP-5') and 'diverged' in line for line in lines), lines)
        self.assertIn('skipped  APP-7    the app is booked for it', lines)
        self.assertEqual({path: git(path, 'rev-parse', 'HEAD') for path in (diverged, busy)}, before)
        self.assertGreaterEqual(problems, 1, 'a diverged branch needs attention')

    def test_a_merge_in_progress_is_never_touched(self):
        path = self.worktree('feature/APP-8-p')
        self.mate_commit('main', name='shared.txt', text='theirs\n')
        (path / 'shared.txt').write_text('mine\n')
        git(path, 'commit', '-q', '-am', 'Mine')
        git(path, 'merge', 'origin/main', check=False)
        lines, _ = self.run_updates()
        self.assertIn('skipped  APP-8    a merge/rebase is in progress', lines)

    def test_dry_run_says_what_would_happen_and_changes_nothing(self):
        self.worktree('feature/APP-1-x', push=True)
        unpushed = self.worktree('feature/APP-3-z')
        self.mate_commit('feature/APP-1-x')
        self.mate_commit('main', name='other.txt')
        refs = git(self.repo, 'for-each-ref', '--format=%(refname) %(objectname)')
        lines, _ = self.run_updates(dry_run=True)
        self.assertIn('would    APP-1    pull 1 from origin/feature/APP-1-x', lines)
        self.assertIn('would    APP-3    rebase onto origin/main (+1)', lines)
        self.assertEqual(git(self.repo, 'for-each-ref', '--format=%(refname) %(objectname)'), refs)
        self.assertEqual(git(unpushed, 'status', '--porcelain'), '')



class BusyTests(unittest.TestCase):
    def test_an_app_booking_or_an_agent_inside_keeps_a_worktree_still(self):
        from sidequest import sync
        booking = {'state': 'booked', 'path': '/w/APP-1'}
        busy = sync.busy_check(booking, ['/w/APP-2/src', '/elsewhere'])
        self.assertEqual(busy('/w/APP-1'), 'the app is booked for it (tests running?)')
        self.assertEqual(busy('/w/APP-2'), 'an agent is working in it')
        self.assertEqual(busy('/w/APP-3'), '')
        self.assertEqual(sync.busy_check({'state': 'free'}, [])('/w/APP-1'), '')


if __name__ == '__main__':
    unittest.main()
