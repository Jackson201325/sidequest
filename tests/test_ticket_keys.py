"""The ticket key module answers every key question the queue, workspace and helpers ask."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'ticket-tui')]
from sidequest import ticket_keys, tmux, workspaces, worktrees


class TicketKeyModuleTests(unittest.TestCase):
    def test_is_key_accepts_any_case_but_only_a_whole_key(self):
        self.assertTrue(ticket_keys.is_key('APP-12'))
        self.assertTrue(ticket_keys.is_key('app-12'))
        for text in ('APP-12-slug', 'APP 12', 'APP-', '12-APP', '', 'feature/APP-12'):
            with self.subTest(text=text):
                self.assertFalse(ticket_keys.is_key(text))

    def test_branch_keys_reads_only_path_segments_and_skips_backups(self):
        self.assertEqual(ticket_keys.branch_keys('feature/APP-1-revert-APP-2'), ['APP-1'])
        self.assertEqual(ticket_keys.branch_keys('fix/app-3-utf-8'), ['APP-3'])
        self.assertEqual(ticket_keys.branch_keys('APP-4'), ['APP-4'])
        self.assertEqual(ticket_keys.branch_keys('backup/APP-5-old'), [])
        self.assertEqual(ticket_keys.branch_keys('feature/APP-61'), ['APP-61'])

    def test_branch_ticket_trusts_lowercase_keys_only_for_known_projects(self):
        self.assertIsNone(ticket_keys.branch_ticket('chore/python-3-bump'))
        self.assertEqual(ticket_keys.branch_ticket('fix/APP-7-totals'), 'APP-7')
        self.assertEqual(ticket_keys.branch_ticket('fix/app-7-totals', ['APP']), 'APP-7')
        self.assertIsNone(ticket_keys.branch_ticket('chore/python-3-bump', ['APP']))
        self.assertIsNone(ticket_keys.branch_ticket('backup/APP-7-old'))

    def test_mentions_accept_a_space_or_a_hyphen(self):
        self.assertEqual(ticket_keys.mentions('APP 12 and app-7, then APP-12 again'), ['APP-12', 'APP-7'])
        self.assertEqual(ticket_keys.mentions(''), [])

    def test_without_leading_key_removes_a_repeated_key_once(self):
        self.assertEqual(ticket_keys.without_leading_key('[DEMO 297] Remove emojis'), 'Remove emojis')
        self.assertEqual(ticket_keys.without_leading_key('APP-12: Fix totals'), 'Fix totals')
        self.assertEqual(ticket_keys.without_leading_key('Fix APP-12 totals'), 'Fix APP-12 totals')

    def test_pr_ticket_still_rejects_spaced_keys(self):
        self.assertIsNone(ticket_keys.pr_ticket({'title': 'Bump python 3.12'}))
        self.assertIsNone(ticket_keys.pr_ticket({'title': 'APP 12 totals'}))


class CallerTests(unittest.TestCase):
    def test_worktree_lookup_and_branch_naming_use_the_module(self):
        self.assertIs(worktrees.branch_keys, ticket_keys.branch_keys)
        with self.assertRaises(ValueError):
            workspaces.branch_name('APP 12', 'Totals')

    def test_tmux_finds_a_window_whose_title_spells_the_key_with_a_space(self):
        panes = 'sidequest\t@3\tAPP 12 totals\t/elsewhere\n'
        self.assertEqual(tmux.find_window(panes, 'APP-12', '/wt/app-12', 'sidequest'), ('@3', 'APP 12 totals'))

    def test_standup_treats_a_spaced_key_as_already_mentioned(self):
        import standup
        body, added = standup._merge_today(['**Today**', '- APP 12: finish totals'], ['APP-12 Fix totals'])
        self.assertEqual(added, 0)

    def test_old_unused_key_helpers_are_gone(self):
        from sidequest import evidence, services
        self.assertFalse(hasattr(services, 'extract_ticket'))
        self.assertFalse(hasattr(evidence, 'commits_for_day'))


class ShipCheckKeyTests(unittest.TestCase):
    def test_ship_check_reads_any_project_key_from_the_branch(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            git = lambda *args: subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', *args],
                                               cwd=repo, check=True, capture_output=True)
            git('init', '-q', '-b', 'main')
            (repo / 'app.rb').write_text('x = 1\n')
            git('add', '.')
            git('commit', '-qm', 'base')
            git('checkout', '-qb', 'fix/APP-7-totals')
            report = json.loads(subprocess.run(
                [sys.executable, str(ROOT / 'bin/sidequest-ship-check.py'), '--no-fetch', '--base', 'main', '--json'],
                cwd=repo, text=True, capture_output=True, check=True).stdout)
        self.assertEqual(report['ticket'], 'APP-7')
        self.assertFalse([w for w in report['warnings'] if 'key' in w])

    def test_qa_shot_reads_the_key_from_a_branch_segment_only(self):
        with tempfile.TemporaryDirectory() as folder:
            repo, tickets = Path(folder) / 'repo', Path(folder) / 'tickets'
            repo.mkdir()
            git = lambda *args: subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', *args],
                                               cwd=repo, check=True, capture_output=True)
            git('init', '-q', '-b', 'main')
            git('commit', '--allow-empty', '-qm', 'base')
            shot = lambda: subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest-qa-shot.py')], cwd=repo,
                                          env=dict(__import__('os').environ, SIDEQUEST_TICKETS_DIR=str(tickets)),
                                          text=True, capture_output=True, timeout=60)
            git('checkout', '-qb', 'chore/python-3-bump')
            self.assertIn('give the ticket key', shot().stderr)
            git('checkout', '-qb', 'fix/APP-7-totals')
            self.assertIn(str(tickets / 'APP-7/qa/shots.json'), shot().stderr)



class HelperKeyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def environment(self, projects):
        config = self.root / 'config.json'
        config.write_text(json.dumps({'jira': {'projects': projects}}))
        env = {k: v for k, v in __import__('os').environ.items() if not k.startswith('GIT_')}
        return dict(env, SIDEQUEST_CONFIG=str(config))

    def test_worktree_prints_any_project_key_in_capitals(self):
        repo = self.root / 'repo'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=repo, check=True)
        result = subprocess.run([sys.executable, str(ROOT / 'bin/sidequest-worktree.py'), 'app-9'], cwd=repo,
                                env=self.environment([]), text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.splitlines()[0], 'APP-9: none')

    def review_app(self, argument, projects):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest-review-app.py'), argument, '--json'],
                              env=dict(self.environment(projects), PATH='/nonexistent'), text=True, capture_output=True)

    def test_review_app_expands_a_bare_number_only_with_one_configured_project(self):
        self.assertIn('give the full ticket key', self.review_app('123', []).stderr)
        self.assertIn('give the full ticket key', self.review_app('123', ['APP', 'OPS']).stderr)
        self.assertIn('gh is not installed', self.review_app('123', ['APP']).stderr)
        self.assertIn('ticket key must look like APP-123', self.review_app('not a key', ['APP']).stderr)

    def test_review_app_finds_a_pr_by_the_queue_rule(self):
        from sidequest import review_apps
        def run(prs):
            return lambda args: json.dumps(prs)
        pr = lambda number, title, head='x': {'number': number, 'title': title, 'headRefName': head}
        self.assertEqual(review_apps.find_pr('APP-12', run=run([pr(1, '[APP-12] Totals'), pr(2, 'APP-120 Other')]))['number'], 1)
        self.assertEqual(review_apps.find_pr('APP-12', run=run([pr(3, 'Py fixes', 'fix/app-12-py')]))['number'], 3)
        with self.assertRaises(review_apps.ReviewAppError):
            review_apps.find_pr('APP-12', run=run([pr(2, 'APP-120 Other')]))
        calls = []
        review_apps.find_pr('APP-12', run=lambda args: calls.append(args) or json.dumps([pr(3, 'Py fixes', 'fix/APP-12-py')]))
        self.assertNotIn('--search', calls[0], 'GitHub search ignores branch names')


if __name__ == '__main__':
    unittest.main()
