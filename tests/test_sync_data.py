"""`sidequest up` phase 1: read-only sync data, collected only when asked, and the `sync` settings."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import collector, config, github
from sidequest.snapshots import SnapshotStore

SETTINGS = {'jira': {'site': 'https://example.atlassian.net', 'projects': ['APP']},
            'github': {'repository': 'example/app'}}
MERGED = [{'number': 7, 'headRefName': 'feature/APP-1-x', 'headRefOid': 'a' * 40, 'mergedAt': '2026-11-01T10:00:00Z'}]
ISSUES = [{'key': 'APP-1', 'fields': {'summary': 'Totals', 'issuetype': {'name': 'Bug'}, 'status': {'name': 'In Dev'}}}]


class SyncSettingsTests(unittest.TestCase):
    def test_sync_settings_are_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps({'sync': {'tickets_jql': 'sprint in openSprints()', 'cleanup': 'ask'}}))
            self.assertEqual(config.load(path, {'SIDEQUEST_SYNC_UPDATE': 'on'})['sync'],
                             {'tickets_jql': 'sprint in openSprints()', 'cleanup': 'ask', 'update': 'on'})
            for key, bad in (('cleanup', 'yes'), ('update', 'ask'), ('open_prs', 'maybe')):
                path.write_text(json.dumps({'sync': {key: bad}}))
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'sync.' + key):
                    config.load(path)


class MergedPrTests(unittest.TestCase):
    def test_merged_prs_are_listed_with_their_head_commit(self):
        with patch.object(github.tr, 'run_tool', return_value=json.dumps(MERGED)) as run:
            rows = github.list_merged_prs()
        self.assertEqual(rows, [{'number': 7, 'branch': 'feature/APP-1-x', 'head_oid': 'a' * 40,
                                 'merged_at': '2026-11-01T10:00:00Z'}])
        argv = run.call_args[0][0]
        self.assertEqual(argv[argv.index('--state') + 1], 'merged')
        self.assertIn('headRefOid', argv[argv.index('--json') + 1])
        # Every author: a worktree's branch may be merged through someone else's PR.
        self.assertNotIn('--author', argv)
        self.assertEqual(argv[argv.index('--limit') + 1], '300')
        for bad in ('{}', '[{"number": 7}]'):
            with patch.object(github.tr, 'run_tool', return_value=bad), self.assertRaises(RuntimeError):
                github.list_merged_prs()


class LivePrTests(unittest.TestCase):
    def test_a_pr_is_asked_about_now(self):
        with patch.object(github.tr, 'run_tool', return_value='{"state": "MERGED", "headRefOid": "abc"}') as run:
            self.assertEqual(github.pr_state(7), {'state': 'MERGED', 'head_oid': 'abc'})
        argv = run.call_args[0][0]
        self.assertEqual(argv[:4], ['gh', 'pr', 'view', '7'])
        for failure in (RuntimeError('offline'), SystemExit(1)):
            with patch.object(github.tr, 'run_tool', side_effect=failure):
                self.assertIsNone(github.pr_state(7))
        with patch.object(github.tr, 'run_tool', return_value='not json'):
            self.assertIsNone(github.pr_state(7))


class SyncCollectionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        for name, value in ((config, ('SETTINGS', SETTINGS)), (collector.identity, ('GITHUB_REPO', 'example/app')),
                            (collector.identity, ('JIRA_ACCOUNT_ID', 'me'))):
            patcher = patch.object(name, *value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in (('collect_prs', {'enabled': True, 'open_prs': []}),
                            ('collect_jira', {'enabled': True, 'jira_available': True, 'tickets': []})):
            patcher = patch.object(collector, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_sync_sources_are_collected_only_when_asked(self):
        with patch.object(collector.client, 'search', return_value=ISSUES) as search, \
                patch.object(github, 'list_merged_prs', return_value=[{'number': 7}]) as merged:
            collector.collect(self.folder)
            search.assert_not_called()
            merged.assert_not_called()
            data = collector.collect(self.folder, sync=True)
        jql = search.call_args[0][0]
        self.assertTrue(jql.startswith('assignee = currentUser() AND statusCategory != Done AND project IN ("APP")'), jql)
        self.assertEqual(data['sources']['sync_tickets']['tickets'],
                         [{'key': 'APP-1', 'summary': 'Totals', 'issue_type': 'Bug', 'status': 'In Dev'}])
        self.assertEqual(data['sources']['merged_prs']['prs'], [{'number': 7}])
        kept = collector.collect(self.folder)
        self.assertEqual(kept['sources']['sync_tickets'], data['sources']['sync_tickets'], 'a refresh keeps sync data')

    def test_the_configured_query_is_used_and_a_failed_source_keeps_its_data(self):
        with patch.object(config, 'SETTINGS', dict(SETTINGS, sync={'tickets_jql': 'sprint in openSprints()'})), \
                patch.object(collector.client, 'search', return_value=ISSUES) as search, \
                patch.object(github, 'list_merged_prs', return_value=[{'number': 7}]):
            first = collector.collect(self.folder, sync=True)
        self.assertEqual(search.call_args[0][0], 'sprint in openSprints() ORDER BY created ASC')
        with patch.object(collector.client, 'search', return_value=ISSUES), \
                patch.object(github, 'list_merged_prs', side_effect=RuntimeError('HTTP 401 fixture-token')):
            second = collector.collect(self.folder, sync=True)
        self.assertEqual(second['sources']['merged_prs'], first['sources']['merged_prs'])
        self.assertIn('merged_prs', second['failures'])
        self.assertNotIn('fixture-token', json.dumps(second))
        self.assertNotIn('sync_tickets', second['failures'])
        self.assertEqual(SnapshotStore(self.folder).read()['sources']['merged_prs']['generated_at'],
                         first['sources']['merged_prs']['generated_at'])


if __name__ == '__main__':
    unittest.main()
