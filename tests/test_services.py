import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'ticket-tui')]
from sidequest.jira import client
from sidequest import collector, github
from sidequest.snapshots import SnapshotStore


class ServiceTests(unittest.TestCase):
    def test_jira_search_collects_all_pages(self):
        replies = [{'issues': [{'key': 'APP-1'}], 'nextPageToken': 'next', 'isLast': False},
                   {'issues': [{'key': 'APP-2'}], 'isLast': True}]
        with patch.object(client, 'jira', side_effect=replies) as request:
            self.assertEqual(len(client.search('assignee = currentUser()', ['summary'], None)), 2)
        self.assertEqual(request.call_args[0][2]['nextPageToken'], 'next')

    def test_incomplete_jira_search_is_a_failure(self):
        with patch.object(client, 'jira', return_value={'issues': [], 'isLast': False}):
            with self.assertRaises(client.JiraError):
                client.search('assignee = currentUser()', ['summary'], None)

    def test_jira_transport_refuses_write_before_loading_credentials(self):
        with patch.object(client, '_auth', side_effect=AssertionError('credentials accessed')):
            with self.assertRaisesRegex(client.JiraError, 'read-only'):
                client.jira('POST', '/rest/api/3/issue/APP-1/transitions', {})

    def test_recent_comments_use_public_jira_adapter(self):
        issue = {'key': 'APP-42', 'fields': {'summary': 'Check totals', 'status': {'name': 'In QA'}}}
        comment = {'total': 1, 'comments': [{'id': '1', 'author': {'displayName': 'Reviewer'},
                   'body': {'type': 'doc', 'content': [{'type': 'text', 'text': 'Check quantities'}]},
                   'created': '2026-10-27T12:00:00Z', 'updated': '2026-10-27T12:00:00Z'}]}
        def response(method, path, *args):
            return comment if '/comment?' in path else {'values': [], 'isLast': True} if '/changelog?' in path else issue
        with patch.object(client, 'jira', side_effect=response):
            result = client.fetch_one('APP-42', include_activity=True)
        self.assertEqual(result['jira_comments'][0]['body'], 'Check quantities')
        self.assertEqual(result['jira_comment_total'], 1)

    def test_failed_source_retains_data_and_original_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            source = {'generated_at': '2026-01-01T10:00:00+00:00', 'open_prs': [{'number': 1}]}
            SnapshotStore(folder).publish({'prs': source})
            with patch.object(collector, 'collect_jira', return_value={'jira_available': True, 'tickets': []}), \
                 patch.object(collector, 'collect_prs', side_effect=RuntimeError('HTTP 401 fixture-token')):
                data = collector.collect(Path(folder))
            self.assertEqual(data['sources']['prs'], source)
            self.assertIn('prs', data['failures'])
            self.assertNotIn('fixture-token', json.dumps(data))

    def test_invalid_pr_list_cannot_be_successful_empty_result(self):
        with patch.object(github.tr, 'run_tool', return_value='{}'):
            with self.assertRaises((RuntimeError, SystemExit)):
                github.list_open_prs(include_activity=True)

    def test_pr_limit_is_reported_as_incomplete(self):
        with patch.object(github.tr, 'run_tool', return_value='[{"number":1}]'):
            with self.assertRaisesRegex((RuntimeError, SystemExit), 'limit'):
                github.list_open_prs(limit=1, include_activity=True)

    def test_pr_discussion_pages_are_not_silently_truncated(self):
        comments = [{'user': {'login': 'reviewer'}, 'body': str(i), 'created_at': '2026-01-01T10:00:00Z'} for i in range(100)]
        pages = [comments, [{'user': {'login': 'reviewer'}, 'body': 'last', 'created_at': '2026-01-01T11:00:00Z'}], [], []]
        with patch.object(github.tr, 'run_tool', side_effect=[json.dumps(page) for page in pages]):
            activity = github.activity_for_pr(42)
        self.assertEqual(len(activity['discussion']), 101)
        self.assertEqual(activity['discussion'][-1]['body'], 'last')

    def test_github_commit_endpoint_cap_is_an_explicit_failure(self):
        with patch.object(github, 'rest_pages', side_effect=[[], [], [{}] * 250]):
            with self.assertRaisesRegex(RuntimeError, 'commit.*limit'):
                github.activity_for_pr(42)

    def test_missing_review_pagination_metadata_is_not_successful_empty_data(self):
        response = {'data': {'repository': {'pullRequest': {'reviewThreads': {'nodes': []}}}}}
        with patch.object(github.tr, 'run_tool', return_value=json.dumps(response)):
            with self.assertRaisesRegex((RuntimeError, SystemExit), 'pagination'):
                github.unresolved_threads_for_pr(42)


    def test_pr_derived_jira_keys_cannot_fail_the_whole_collection(self):
        def fetch(key, include_activity=False, account_id=None):
            if key == 'APP-404':
                raise client.JiraError('Jira HTTP 404; previous data retained', 404)
            return {'key': key}
        settings = {'jira': {'site': 'https://example.atlassian.net', 'projects': ['APP']}}
        with patch.object(collector.config, 'SETTINGS', settings), patch.object(collector.identity, 'JIRA_ACCOUNT_ID', 'me'), \
                patch.object(client, 'search', return_value=[{'key': 'APP-1'}]), \
                patch.object(client, 'fetch_one', side_effect=fetch) as fetch_one:
            prs = [{'title': t} for t in ('APP-1 a', 'APP-2 b', 'APP-404 c', 'Bump PYTHON-3 image')]
            result = collector.collect_jira(prs)
        self.assertEqual([t['key'] for t in result['tickets']], ['APP-1', 'APP-2'])
        self.assertNotIn('PYTHON-3', [call.args[0] for call in fetch_one.call_args_list])

    def test_assigned_jira_ticket_errors_still_fail_collection(self):
        settings = {'jira': {'site': 'https://example.atlassian.net'}}
        with patch.object(collector.config, 'SETTINGS', settings), patch.object(collector.identity, 'JIRA_ACCOUNT_ID', 'me'), \
                patch.object(client, 'search', return_value=[{'key': 'APP-1'}]), \
                patch.object(client, 'fetch_one', side_effect=client.JiraError('Jira HTTP 404', 404)):
            with self.assertRaises(client.JiraError):
                collector.collect_jira([])

    def jira_keys_fetched_for(self, prs, settings):
        with patch.object(collector.config, 'SETTINGS', settings), patch.object(collector.identity, 'JIRA_ACCOUNT_ID', 'me'), \
                patch.object(client, 'search', return_value=[{'key': 'APP-1'}]), \
                patch.object(client, 'fetch_one', side_effect=lambda key, **_: {'key': key}) as fetch_one:
            collector.collect_jira(prs)
        return [call.args[0] for call in fetch_one.call_args_list]

    def test_collector_and_queue_agree_on_pr_ticket_keys(self):
        import core
        settings = {'jira': {'site': 'https://example.atlassian.net'}}
        prs = [{'number': 1, 'title': 'Fix python 3.12 for APP-5', 'branch': 'fix/py'},
               {'number': 2, 'title': 'Py3 fixes', 'branch': 'fix/app-9-py3'},
               {'number': 3, 'title': 'Bump python 3.12 image', 'branch': 'chore/python-3-bump'}]
        fetched = self.jira_keys_fetched_for(prs, settings)
        self.assertEqual(sorted(fetched), ['APP-1', 'APP-5', 'APP-9'])
        jira = {'tickets': [{'key': key} for key in fetched]}
        queue_keys = sorted(t.key for t in core.tickets_from(jira, {'open_prs': prs}))
        self.assertEqual(queue_keys, ['APP-1', 'APP-5', 'APP-9', 'PR-3'])

    def test_moved_pr_derived_jira_issue_does_not_fail_collection(self):
        def fetch(key, include_activity=False, account_id=None):
            if key == 'APP-5':
                raise client.JiraError('Jira issue APP-5 moved to NEW-7; previous data retained', 301)
            return {'key': key}
        settings = {'jira': {'site': 'https://example.atlassian.net'}}
        with patch.object(collector.config, 'SETTINGS', settings), patch.object(collector.identity, 'JIRA_ACCOUNT_ID', 'me'), \
                patch.object(client, 'search', return_value=[{'key': 'APP-1'}]), \
                patch.object(client, 'fetch_one', side_effect=fetch):
            result = collector.collect_jira([{'title': 'APP-5 old work'}])
        self.assertEqual([t['key'] for t in result['tickets']], ['APP-1'])

    def test_jira_client_reports_a_moved_issue_with_its_own_status(self):
        with patch.object(client, 'jira', return_value={'key': 'NEW-7', 'fields': {}}):
            with self.assertRaises(client.JiraError) as failure:
                client.fetch_one('APP-5')
        self.assertEqual(failure.exception.status, 301)
        self.assertIn('NEW-7', str(failure.exception))

    def test_github_pr_ticket_uses_the_shared_key_rule(self):
        row = {'number': 3, 'title': 'Bump python 3.12 image', 'headRefName': 'chore/python-3-bump'}
        with patch.object(github, 'unresolved_threads_for_pr', return_value=[]):
            self.assertIsNone(github.enrich_pr(row, include_threads=False)['ticket'])
            row['headRefName'] = 'fix/APP-9-py3'
            self.assertEqual(github.enrich_pr(row, include_threads=False)['ticket'], 'APP-9')

    def test_missing_file_errors_only_blame_gh_when_gh_is_missing(self):
        from sidequest.access import failure_for
        self.assertIn('GitHub CLI (gh) is not installed', str(failure_for('GitHub', "[Errno 2] No such file or directory: 'gh'")))
        other = str(failure_for('fetch', "fatal: cannot open '.git/FETCH_HEAD': No such file or directory"))
        self.assertNotIn('GitHub CLI (gh) is not installed', other)


if __name__ == '__main__':
    unittest.main()
