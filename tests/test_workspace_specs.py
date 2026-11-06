"""Workspace contract: real temporary Git repos, no network or terminal tools."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from sidequest.workspace import GitWorkspace


class WorkspaceSpecs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name).resolve()
        self.repo = self.folder / 'repo'
        self.repo.mkdir()
        self.git('init', '-q', '-b', 'main')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '--allow-empty', '-qm', 'Base')
        self.workspace = GitWorkspace(self.repo, base_ref='main')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True).strip()

    def test_preview_is_read_only_and_apply_creates_without_switching_main(self):
        plan = self.workspace.preview('APP-12', 'A workspace')
        self.assertEqual(plan.result()['state'], 'preview')
        self.assertFalse(Path(plan.path).exists())
        self.assertEqual(self.git('worktree', 'list', '--porcelain').count('worktree '), 1)
        applied = self.workspace.apply(plan)
        self.assertTrue(applied['created'])
        self.assertEqual(self.git('branch', '--show-current'), 'main')
        reused = self.workspace.apply(self.workspace.preview('APP-12', 'Changed title'))
        self.assertFalse(reused['created'])
        self.assertEqual((reused['path'], reused['branch']), (applied['path'], applied['branch']))

    def test_new_branch_does_not_track_its_base_but_remote_branch_does(self):
        origin = self.folder / 'origin.git'
        subprocess.check_call(['git', 'init', '-q', '--bare', str(origin)])
        self.git('remote', 'add', 'origin', str(origin))
        self.git('push', '-q', 'origin', 'main', 'main:feature/APP-13-existing')
        self.git('fetch', '-q', 'origin')
        workspace = GitWorkspace(self.repo, base_ref='origin/main')
        fresh = workspace.apply(workspace.preview('APP-12', 'A workspace'))
        upstream = subprocess.run(['git', '-C', fresh['path'], 'rev-parse', '--abbrev-ref', '@{u}'],
                                  text=True, capture_output=True)
        self.assertNotEqual(upstream.returncode, 0, 'a new branch must not track origin/main')
        existing = workspace.apply(workspace.preview('APP-13', 'Existing'))
        self.assertEqual(subprocess.check_output(['git', '-C', existing['path'], 'rev-parse', '--abbrev-ref', '@{u}'],
                                                 text=True).strip(), 'origin/feature/APP-13-existing')

    def test_git_failures_keep_the_reason(self):
        with self.assertRaises(RuntimeError) as failure:
            GitWorkspace(self.repo, base_ref='origin/missing').preview('APP-12', 'A workspace')
        self.assertIn('Git command failed:', str(failure.exception))

    def test_changed_base_requires_a_new_preview(self):
        plan = self.workspace.preview('APP-12', 'A workspace')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '--allow-empty', '-qm', 'New base')
        with self.assertRaisesRegex(RuntimeError, 'changed since preview'):
            self.workspace.apply(plan)
        self.assertFalse(Path(plan.path).exists())
        self.assertNotIn('feature/APP-12', self.git('branch', '--list'))

    def test_destination_created_after_preview_is_never_overwritten(self):
        plan = self.workspace.preview('APP-12', 'A workspace')
        path = Path(plan.path)
        path.mkdir()
        (path / 'keep.txt').write_text('User data')
        with self.assertRaisesRegex(RuntimeError, 'Destination already exists'):
            self.workspace.apply(plan)
        self.assertEqual((path / 'keep.txt').read_text(), 'User data')

    def test_dangling_destination_symlink_is_never_followed_or_overwritten(self):
        plan = self.workspace.preview('APP-12', 'A workspace')
        path = Path(plan.path)
        path.symlink_to(self.folder / 'missing-target')
        with self.assertRaisesRegex(RuntimeError, 'Destination already exists'):
            self.workspace.apply(plan)
        self.assertTrue(path.is_symlink())

    def test_a_plan_from_another_repository_is_refused(self):
        plan = self.workspace.preview('APP-12', 'A workspace')
        other = self.folder / 'other'
        subprocess.run(['git', 'clone', '-q', str(self.repo), str(other)], check=True)
        with self.assertRaisesRegex(RuntimeError, 'changed since preview'):
            GitWorkspace(other, base_ref='main').apply(plan)
        self.assertFalse(Path(plan.path).exists())

    def test_branch_checked_out_after_preview_is_rejected_without_another_creation(self):
        plan = self.workspace.preview('APP-12', 'A workspace')
        self.git('worktree', 'add', '-qb', plan.branch, str(self.folder / 'elsewhere'), 'main')
        with self.assertRaisesRegex(RuntimeError, 'changed since preview'):
            self.workspace.apply(plan)
        self.assertFalse(Path(plan.path).exists())
        self.assertEqual(self.git('worktree', 'list', '--porcelain').count('worktree '), 2)

    def test_existing_branch_is_reused_without_resetting_its_commit(self):
        self.git('branch', 'fix/APP-12-existing')
        original = self.git('rev-parse', 'fix/APP-12-existing')
        result = self.workspace.apply(self.workspace.preview('APP-12', 'Ignored new title'))
        self.assertEqual(result['branch'], 'fix/APP-12-existing')
        self.assertEqual(self.git('rev-parse', 'fix/APP-12-existing'), original)

    def test_invalid_key_cannot_reuse_an_unrelated_checkout(self):
        with self.assertRaises(ValueError):
            self.workspace.preview('main', 'Invalid ticket')

    def test_explicit_repository_and_destination_ignore_process_defaults(self):
        workspace = GitWorkspace(self.repo, self.folder / 'worktrees', base_ref='main')
        with patch.dict(os.environ, {'SIDEQUEST_REPO': '/missing/repo'}):
            result = workspace.apply(workspace.preview('APP-12', 'A workspace'))
        self.assertEqual(Path(result['path']).parent, self.folder / 'worktrees')


if __name__ == '__main__':
    unittest.main()
