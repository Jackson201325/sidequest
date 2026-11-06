"""Access failures carry their cause as data; text is guessed only for text-only tools."""
import http.client
import io
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import unittest.mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'ticket-tui')]
from sidequest import collector, services
from sidequest.access import AccessFailure, failure_for
from sidequest.jira import client


def http_error(code):
    return urllib.error.HTTPError('https://example.atlassian.net', code, 'error', {}, io.BytesIO(b''))


class AccessFailureTests(unittest.TestCase):
    def test_terminal_text_drops_dashboard_only_advice(self):
        failure = AccessFailure('GitHub', 'login')
        self.assertEqual(failure.terminal_text, 'GitHub: login unavailable or expired. Run gh auth login in your terminal.')
        self.assertEqual(AccessFailure('Jira', 'credentials').terminal_text,
                         'Jira: no credentials yet. Set jira.email in your config and export SIDEQUEST_JIRA_TOKEN '
                         'in the terminal you start Sidequest from, then restart it.')

    def test_new_causes_have_their_own_advice(self):
        self.assertIn('timed out', str(AccessFailure('GitHub', 'timeout')))
        self.assertIn('server error', str(AccessFailure('Jira', 'server')))
        self.assertIn('rate limited', str(AccessFailure('Jira', 'rate_limited')))

    def test_a_failure_is_a_runtime_error_with_the_same_message_users_see(self):
        failure = failure_for('GitHub', 'HTTP 401 Bad credentials')
        self.assertIsInstance(failure, RuntimeError)
        self.assertEqual((failure.service, failure.cause), ('GitHub', 'login'))
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
        for code, cause in ((401, 'login'), (403, 'denied'), (404, 'not_found'), (429, 'rate_limited'),
                            (500, 'server'), (503, 'server'), (418, 'unknown')):
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

    def test_tls_failure_while_reading_the_body_is_tls(self):
        class Response:
            def __enter__(self):
                error = ssl.SSLCertVerificationError(1, 'certificate verify failed')
                error.reason = 'CERTIFICATE_VERIFY_FAILED'  # real SSL errors carry a text reason
                raise error

            def __exit__(self, *args):
                return False
        self.assertEqual(self.request(lambda *a, **k: Response()).cause, 'tls')

    def test_a_dropped_connection_mid_body_is_a_network_failure(self):
        self.assertEqual(self.request(http.client.IncompleteRead(b'{"ac')).cause, 'network')

    def test_jira_errors_never_have_their_cause_guessed_from_wording(self):
        error = client.JiraError('Jira status changed during collection; refresh again')
        self.assertEqual(error.cause, 'unknown')
        self.assertEqual(failure_for('Jira', error).cause, 'unknown')

    def test_a_jira_timeout_is_a_timeout(self):
        self.assertEqual(self.request(urllib.error.URLError(TimeoutError('timed out'))).cause, 'timeout')
        self.assertEqual(self.request(TimeoutError('The read operation timed out')).cause, 'timeout')

    def test_a_login_failure_on_the_first_base_is_not_hidden_by_the_second(self):
        replies = iter([http_error(401), http_error(404)])

        def answer(*args, **kwargs):
            raise next(replies)
        with patch.object(client, 'BASES', ['https://example.atlassian.net', 'https://api.atlassian.com/ex/jira/x']), \
                patch.object(client, '_base', [None]), patch.object(client, '_auth', return_value='Basic fixture'), \
                patch('urllib.request.urlopen', side_effect=answer):
            with self.assertRaises(client.JiraError) as failure:
                client.jira('GET', '/rest/api/3/myself')
        self.assertEqual(failure.exception.cause, 'login')

    def test_misspelled_causes_are_refused(self):
        with self.assertRaises(ValueError):
            client.JiraError('x', cause='dns_failure')

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

    def test_a_gh_timeout_is_a_timeout_not_a_network_failure(self):
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(['gh'], 90)):
            with self.assertRaises(AccessFailure) as failure:
                services.run_command(['gh', 'pr', 'list'])
        self.assertEqual(failure.exception.cause, 'timeout')
        self.assertNotIn('VPN', str(failure.exception))

    def test_a_gh_timeout_still_lets_jira_collect_and_publish(self):
        settings = {'jira': {'site': 'https://example.atlassian.net'}}
        with patch.object(collector.config, 'SETTINGS', settings), patch.object(collector.identity, 'GITHUB_REPO', 'o/r'), \
                patch.object(collector.identity, 'JIRA_ACCOUNT_ID', 'me'), \
                patch('subprocess.run', side_effect=subprocess.TimeoutExpired(['gh'], 90)), \
                patch.object(client, 'search', return_value=[]), tempfile.TemporaryDirectory() as folder:
            result = collector.collect(folder)
        self.assertIn('timed out', result['failures']['prs'])
        self.assertIn('jira', result['sources'])

    def review_app_error(self, args, **run):
        from sidequest import review_apps
        with patch('subprocess.run', **run):
            with self.assertRaises(review_apps.ReviewAppError) as failure:
                review_apps._run(args)
        return str(failure.exception)

    def test_review_app_errors_are_terminal_text_without_dashboard_advice(self):
        message = self.review_app_error(['gh', 'pr', 'view'], side_effect=FileNotFoundError(2, 'missing', 'gh'))
        self.assertIn('GitHub CLI (gh) is not installed', message)
        self.assertNotIn('press r', message)
        self.assertNotIn('Previous data retained', message)

    def test_review_app_blames_the_tool_that_failed(self):
        heroku = self.review_app_error(['heroku', 'auth:token'],
                                       return_value=subprocess.CompletedProcess([], 1, '', 'Error: not logged in'))
        self.assertTrue(heroku.startswith('Heroku: login unavailable'), heroku)
        self.assertNotIn('gh auth login', heroku)
        missing = self.review_app_error(['heroku', 'auth:token'], side_effect=FileNotFoundError(2, 'missing', 'heroku'))
        self.assertIn('Heroku CLI (heroku) is not installed', missing)

    def test_both_gh_runners_report_a_timeout_the_same_way(self):
        timeout = subprocess.TimeoutExpired(['gh'], 45)
        message = self.review_app_error(['gh', 'pr', 'list'], side_effect=timeout)
        with patch('subprocess.run', side_effect=timeout):
            with self.assertRaises(AccessFailure) as failure:
                services.run_command(['gh', 'pr', 'list'])
        self.assertEqual(message, failure.exception.terminal_text)

class DashboardRunTests(unittest.TestCase):
    def test_run_classifies_text_only_tools_and_hides_their_output(self):
        from tui import run
        result = subprocess.CompletedProcess([], 1, '', 'HTTP 401 Bad credentials secret-fixture')
        with patch('subprocess.run', return_value=result):
            with self.assertRaises(AccessFailure) as failure:
                run(['gh', 'pr', 'list'])
        self.assertTrue(str(failure.exception).startswith('GitHub: login unavailable'))
        self.assertNotIn('secret-fixture', str(failure.exception))

    def test_the_dashboard_shows_the_cause_sidequest_data_reports(self):
        from tui import run
        stderr = 'sidequest-data: Jira: no credentials yet. Set jira.email in your config. Previous data retained.\n'
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 2, '', stderr)):
            with self.assertRaises(RuntimeError) as failure:
                run(['sidequest-data', 'ticket', 'APP-1'])
        self.assertEqual(str(failure.exception), 'Jira: no credentials yet. Set jira.email in your config. Previous data retained.')

    def test_the_dashboard_never_echoes_unexpected_helper_output(self):
        from tui import run
        stderr = 'Traceback (most recent call last):\n  token=secret-fixture\nKeyError: x\n'
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', stderr)):
            with self.assertRaises(RuntimeError) as failure:
                run(['sidequest-data', 'collect', '--json'])
        self.assertNotIn('secret-fixture', str(failure.exception))
        self.assertIn('request failed', str(failure.exception))

    def run_data(self, args, error):
        import runpy
        main = runpy.run_path(str(ROOT / 'bin' / 'sidequest-data.py'), run_name='sidequest_data_test')['main']
        stderr = io.StringIO()
        with patch.object(sys, 'argv', ['sidequest-data', *args]), patch('sys.stderr', stderr), \
                patch.object(client, 'fetch_one', side_effect=error), \
                patch.dict(main.__globals__, {'collect': unittest.mock.Mock(side_effect=error)}):
            code = main()
        return code, stderr.getvalue()

    def test_sidequest_data_prints_the_real_cause_and_never_a_login_guess(self):
        code, stderr = self.run_data(['ticket', 'APP-1'], client.JiraError('No Jira credentials', cause='credentials'))
        self.assertEqual(code, 2)
        self.assertTrue(stderr.startswith('sidequest-data: Jira: no credentials yet'), stderr)
        code, stderr = self.run_data(['collect', '--json'], OSError('disk full'))
        self.assertEqual(code, 2)
        self.assertTrue(stderr.startswith('sidequest-data: '), stderr)
        self.assertNotIn('login', stderr)

    def test_run_has_no_keychain_exception_for_diagnostics(self):
        from tui import run
        result = subprocess.CompletedProcess([], 0, '{}', 'sidequest-data: no Jira token in the Keychain')
        with patch('subprocess.run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'reported diagnostics'):
                run(['sidequest-data', 'pr-feedback', '--json'])


if __name__ == '__main__':
    unittest.main()
