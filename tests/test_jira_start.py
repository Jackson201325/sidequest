"""The one Jira write: an opt-in move to the start status, with ready/ask/skip rules from settings."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import config
from sidequest.jira import client

SETTINGS = {'jira': {'site': 'https://example.atlassian.net', 'email': 'dev@example.com', 'start_status': 'In Dev',
                     'start_from': 'Ready for Dev, Fixing Revisions', 'start_ask': 'Backlog,Blocked'}}
TRANSITIONS = {'transitions': [{'id': '31', 'name': 'Start work', 'to': {'name': 'In Dev'}},
                               {'id': '41', 'name': 'Done', 'to': {'name': 'Done'}}]}


class JiraStartTests(unittest.TestCase):
    def start(self, status, settings=SETTINGS, transitions=TRANSITIONS, **options):
        calls = []

        def fake(method, path, body=None):
            calls.append((method, path, body))
            if path.endswith('?fields=status'):
                return {'fields': {'status': {'name': status}}}
            if path.endswith('/transitions') and method == 'GET':
                return transitions
            return {}
        with patch.object(config, 'SETTINGS', settings), patch.object(client, 'jira', side_effect=fake):
            code, message = client.start_ticket('APP-7', **options)
        return code, message, [call for call in calls if call[0] == 'POST']

    def test_a_ready_status_moves_without_asking(self):
        code, message, posts = self.start('Ready for Dev')
        self.assertEqual((code, message), (0, 'MOVED APP-7 Ready for Dev → In Dev'))
        self.assertEqual(posts, [('POST', '/rest/api/3/issue/APP-7/transitions', {'transition': {'id': '31'}})])

    def test_an_ask_status_needs_yes(self):
        code, message, posts = self.start('backlog')
        self.assertEqual((code, posts), (0, []))
        self.assertIn('ASK APP-7 is in backlog', message)
        code, message, posts = self.start('Backlog', yes=True)
        self.assertEqual((code, len(posts)), (0, 1))

    def test_later_statuses_and_the_start_status_are_left_alone(self):
        self.assertEqual(self.start('Code Review')[:2], (0, 'SKIPPED APP-7 is in Code Review; not moved'))
        self.assertEqual(self.start('Code Review', yes=True)[2], [])
        self.assertEqual(self.start('In Dev')[:2], (0, 'ALREADY APP-7 is In Dev'))

    def test_dry_run_and_missing_transitions_never_write(self):
        code, message, posts = self.start('Ready for Dev', dry_run=True)
        self.assertEqual((code, message, posts), (0, 'WOULD MOVE APP-7 Ready for Dev → In Dev', []))
        code, message, posts = self.start('Ready for Dev', transitions={'transitions': [TRANSITIONS['transitions'][1]]})
        self.assertEqual((code, posts), (3, []))
        self.assertIn('Available: Done', message)

    def test_moving_is_off_until_a_start_status_is_set(self):
        code, message, posts = self.start('Ready for Dev', settings={'jira': {'site': 'https://example.atlassian.net'}})
        self.assertEqual((code, posts), (1, []))
        self.assertIn('SIDEQUEST_JIRA_START_STATUS', message)

    def test_the_transport_allows_only_the_transition_write_and_only_when_enabled(self):
        sent = []

        def urlopen(request, timeout=0):
            sent.append((request.get_method(), request.full_url))
            return io.BytesIO(b'')
        with patch.dict('os.environ', {'SIDEQUEST_JIRA_TOKEN': 'fixture'}), \
                patch.object(client, 'BASES', ['https://example.atlassian.net']), \
                patch.object(client.identity, 'JIRA_EMAIL', 'dev@example.com'), \
                patch('urllib.request.urlopen', side_effect=urlopen):
            with patch.object(config, 'SETTINGS', SETTINGS):
                self.assertEqual(client.jira('POST', '/rest/api/3/issue/APP-7/transitions', {'transition': {'id': '31'}}), {})
                for method, path in (('POST', '/rest/api/3/issue/APP-7/comment'), ('PUT', '/rest/api/3/issue/APP-7'),
                                     ('POST', '/rest/api/3/issue/APP-7/transitions/../comment'),
                                     ('DELETE', '/rest/api/3/issue/APP-7/transitions')):
                    with self.subTest(method=method, path=path), self.assertRaises(client.JiraError):
                        client.jira(method, path, {})
            with patch.object(config, 'SETTINGS', {'jira': {}}), self.assertRaises(client.JiraError):
                client.jira('POST', '/rest/api/3/issue/APP-7/transitions', {'transition': {'id': '31'}})
        self.assertEqual(sent, [('POST', 'https://example.atlassian.net/rest/api/3/issue/APP-7/transitions')])


class AttachmentTests(unittest.TestCase):
    def test_a_failed_attachment_download_leaves_no_partial_file(self):
        issue = {'key': 'APP-7', 'fields': {'attachment': [{'id': '10', 'filename': 'screen.png'}]}}

        class Broken(io.BytesIO):
            def read(self, size=-1):
                data = super().read(2)
                if not data:
                    raise OSError('connection reset')
                return data
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'jira', return_value=issue), \
                patch.dict('os.environ', {'SIDEQUEST_JIRA_TOKEN': 'fixture'}), \
                patch.object(client, 'BASES', ['https://example.atlassian.net']), \
                patch.object(client, '_base', [None]), \
                patch.object(client.identity, 'JIRA_EMAIL', 'dev@example.com'), \
                patch('urllib.request.urlopen', side_effect=lambda request, timeout=0: Broken(b'half')):
            rows = client.download_attachments('APP-7', Path(folder))
            names = sorted(p.name for p in Path(folder).iterdir())
        self.assertEqual(rows[0]['error'], 'download failed: OSError')
        self.assertEqual(names, [])

    def test_attachments_download_into_the_folder_with_safe_unique_names(self):
        issue = {'key': 'APP-7', 'fields': {'attachment': [
            {'id': '10', 'filename': 'screen.png', 'size': 3, 'mimeType': 'image/png'},
            {'id': '11', 'filename': 'screen.png', 'size': 3, 'mimeType': 'image/png'},
            {'id': '12', 'filename': '../../evil.csv', 'size': 3, 'mimeType': 'text/csv'},
            {'id': '../x', 'filename': 'bad-id.txt'}]}}
        fetched = []

        def urlopen(request, timeout=0):
            fetched.append(request.full_url)
            return io.BytesIO(request.full_url.rsplit('/', 1)[1].encode())
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'jira', return_value=issue), \
                patch.dict('os.environ', {'SIDEQUEST_JIRA_TOKEN': 'fixture'}), \
                patch.object(client, 'BASES', ['https://example.atlassian.net']), \
                patch.object(client.identity, 'JIRA_EMAIL', 'dev@example.com'), \
                patch('urllib.request.urlopen', side_effect=urlopen):
            rows = client.download_attachments('APP-7', Path(folder))
            names = sorted(p.name for p in Path(folder).iterdir())
            contents = {p.name: p.read_text() for p in Path(folder).iterdir()}
        self.assertEqual(names, ['evil.csv', 'screen (2).png', 'screen.png'])
        self.assertEqual(contents['screen (2).png'], '11')
        self.assertEqual([r.get('error') for r in rows], [None, None, None, 'invalid attachment id'])
        self.assertEqual(len(fetched), 3)
        self.assertTrue(all(url.startswith('https://example.atlassian.net/rest/api/3/attachment/content/')
                            for url in fetched))


if __name__ == '__main__':
    unittest.main()
