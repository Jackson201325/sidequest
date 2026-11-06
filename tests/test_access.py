"""Access failures carry their cause as data; text is guessed only for text-only tools."""
import io
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'ticket-tui')]
from sidequest import collector, services
from sidequest.access import AccessFailure, access_error, failure_for
from sidequest.jira import client


def http_error(code):
    return urllib.error.HTTPError('https://example.atlassian.net', code, 'error', {}, io.BytesIO(b''))


class AccessFailureTests(unittest.TestCase):
    def test_a_failure_is_a_runtime_error_with_the_same_message_users_see(self):
        failure = failure_for('GitHub', 'HTTP 401 Bad credentials')
        self.assertIsInstance(failure, RuntimeError)
        self.assertEqual((failure.service, failure.cause), ('GitHub', 'login'))
        self.assertEqual(str(failure), access_error('GitHub', 'HTTP 401 Bad credentials'))
        self.assertEqual(str(failure), 'GitHub: login unavailable or expired. Run gh auth login in your terminal, '
                                       'then press r. Previous data retained.')

    def test_text_guessing_still_covers_text_only_tools(self):
        cases = {'getaddrinfo ENOTFOUND api.github.com': 'dns', 'SSL: CERTIFICATE_VERIFY_FAILED': 'tls',
                 'HTTP 403 forbidden': 'denied', 'connection timed out': 'network', 'repo not found': 'not_found',
                 "[Errno 2] No such file or directory: 'gh'": 'missing_tool', 'something odd': 'unknown'}
        for text, cause in cases.items():
            with self.subTest(text=text):
                self.assertEqual(failure_for('GitHub', text).cause, cause)

    def test_only_a_missing_gh_is_reported_as_gh(self):
        self.assertIn('GitHub CLI (gh) is not installed', str(failure_for('GitHub', "No such file or directory: 'gh'")))
        other = str(failure_for('fetch', "fatal: cannot open '.git/FETCH_HEAD': No such file or directory"))
        self.assertNotIn('GitHub CLI (gh)', other)
        self.assertIn('a required command is not installed', other)

    def test_a_known_cause_wins_over_misleading_text(self):
        error = client.JiraError('Jira says: please login again', cause='network')
        self.assertEqual(failure_for('Jira', error).cause, 'network')


class JiraCauseTests(unittest.TestCase):
    def request(self, side_effect):
        with patch.object(client, 'BASES', ['https://example.atlassian.net']), \
                patch.object(client, '_base', ['https://example.atlassian.net']), \
                patch.object(client, '_auth', return_value='Basic fixture'), \
                patch('urllib.request.urlopen', side_effect=side_effect):
            with self.assertRaises(client.JiraError) as failure:
                client.jira('GET', '/rest/api/3/myself')
        return failure.exception

    def test_http_statuses_become_causes(self):
        for code, cause in ((401, 'login'), (403, 'denied'), (404, 'not_found'), (500, 'unknown')):
            with self.subTest(code=code):
                error = self.request(http_error(code))
                self.assertEqual((error.status, error.cause), (code, cause))

    def test_network_dns_and_tls_failures_become_causes(self):
        cases = ((urllib.error.URLError(socket.gaierror(8, 'nodename nor servname provided')), 'dns'),
                 (urllib.error.URLError(ssl.SSLCertVerificationError('certificate verify failed')), 'tls'),
                 (urllib.error.URLError(ConnectionRefusedError('refused')), 'network'))
        for exc, cause in cases:
            with self.subTest(cause=cause):
                self.assertEqual(self.request(exc).cause, cause)

    def test_missing_credentials_is_its_own_cause(self):
        with patch.object(client.identity, 'JIRA_EMAIL', ''), patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(client.JiraError) as failure:
                client._auth()
        self.assertEqual(failure.exception.cause, 'credentials')

    def test_a_moved_issue_is_not_found(self):
        with patch.object(client, 'jira', return_value={'key': 'NEW-7', 'fields': {}}):
            with self.assertRaises(client.JiraError) as failure:
                client.fetch_one('APP-5')
        self.assertEqual((failure.exception.status, failure.exception.cause), (301, 'not_found'))


class CallerTests(unittest.TestCase):
    def test_gh_runner_reports_a_missing_gh_as_a_cause(self):
        with patch('subprocess.run', side_effect=FileNotFoundError(2, 'No such file or directory', 'gh')):
            with self.assertRaises(AccessFailure) as failure:
                services.run_command(['gh', 'pr', 'list'])
        self.assertEqual((failure.exception.service, failure.exception.cause), ('GitHub', 'missing_tool'))
        self.assertIn('GitHub CLI (gh) is not installed', str(failure.exception))

    def test_gh_runner_failures_are_access_failures(self):
        result = subprocess.CompletedProcess([], 1, '', 'HTTP 401 Bad credentials')
        with patch('subprocess.run', return_value=result):
            with self.assertRaises(AccessFailure) as failure:
                services.run_command(['gh', 'pr', 'list'])
        self.assertEqual(failure.exception.cause, 'login')

    def test_collector_uses_the_jira_cause_not_the_text(self):
        settings = {'jira': {'site': 'https://example.atlassian.net'}}
        error = client.JiraError('Jira says: please login again', cause='network')
        with patch.object(collector.config, 'SETTINGS', settings), patch.object(collector.identity, 'GITHUB_REPO', ''), \
                patch.object(collector.identity, 'JIRA_ACCOUNT_ID', 'me'), patch.object(client, 'search', side_effect=error), \
                patch.object(collector, 'SnapshotStore') as store, tempfile.TemporaryDirectory() as folder:
            store.return_value.read.return_value = {'sources': {}, 'failures': {}}
            collector.collect(folder)
        failures = store.return_value.publish.call_args[0][1]
        self.assertIn('network unavailable', failures['jira'])
        self.assertNotIn('login', failures['jira'])


class DashboardRunTests(unittest.TestCase):
    def test_run_treats_every_helper_command_alike(self):
        from tui import run
        result = subprocess.CompletedProcess([], 1, '', 'HTTP 401 Bad credentials secret-fixture')
        with patch('subprocess.run', return_value=result):
            with self.assertRaises(AccessFailure) as failure:
                run(['sidequest-data', 'pr-feedback', '--json'])
        self.assertTrue(str(failure.exception).startswith('sidequest-data: login unavailable'))
        self.assertNotIn('secret-fixture', str(failure.exception))

    def test_run_has_no_keychain_exception_for_diagnostics(self):
        from tui import run
        result = subprocess.CompletedProcess([], 0, '{}', 'sidequest-data: no Jira token in the Keychain')
        with patch('subprocess.run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'reported diagnostics'):
                run(['sidequest-data', 'pr-feedback', '--json'])


if __name__ == '__main__':
    unittest.main()
