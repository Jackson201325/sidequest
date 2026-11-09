"""Credentials are found by reference (Keychain item or variable name); settings never hold a value."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import config, credentials


def keychain(items):
    """A fake `security find-generic-password` over {(service, account): password}."""
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        args = argv[2:]
        service = args[args.index('-s') + 1]
        account = args[args.index('-a') + 1] if '-a' in args else None
        found = [(acct, pw) for (svc, acct), pw in items.items() if svc == service and account in (None, acct)]
        if not found:
            return subprocess.CompletedProcess(argv, 44, '', 'not found')
        acct, password = found[0]
        out = password + '\n' if '-w' in args else 'keychain: "x"\nattributes:\n    "acct"<blob>="%s"\n' % acct
        return subprocess.CompletedProcess(argv, 0, out, '')
    return run, calls


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.settings = patch.object(config, 'SETTINGS', {'credentials': {
            'jira': 'keychain:team-jira/me@example.com', 'review': 'keychain:team-review', 'qa': 'env:MY_QA_PASSWORD'}})
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.platform = patch.object(credentials.sys, 'platform', 'darwin')
        self.platform.start()
        self.addCleanup(self.platform.stop)

    def test_the_environment_wins_then_the_reference_is_followed(self):
        run, calls = keychain({('team-jira', 'me@example.com'): 'from-keychain'})
        with patch.object(credentials, 'RUN', run), patch.dict('os.environ', {}, clear=True):
            self.assertEqual(credentials.secret('jira'), 'from-keychain')
            self.assertEqual(calls[0], ['security', 'find-generic-password', '-s', 'team-jira', '-a', 'me@example.com', '-w'])
        with patch.object(credentials, 'RUN', run), patch.dict('os.environ', {'SIDEQUEST_JIRA_TOKEN': 'from-env'}, clear=True):
            self.assertEqual(credentials.secret('jira'), 'from-env')

    def test_a_login_takes_the_account_name_from_the_item(self):
        run, _ = keychain({('team-review', 'qa@example.com'): 'pw'})
        with patch.object(credentials, 'RUN', run), patch.dict('os.environ', {}, clear=True):
            self.assertEqual(credentials.login('review'), ('qa@example.com', 'pw'))
        with patch.dict('os.environ', {'SIDEQUEST_REVIEW_EMAIL': 'a@b.c', 'SIDEQUEST_REVIEW_PASSWORD': 'x'}, clear=True):
            self.assertEqual(credentials.login('review'), ('a@b.c', 'x'))

    def test_env_references_missing_items_and_other_systems(self):
        run, _ = keychain({})
        with patch.object(credentials, 'RUN', run), patch.dict('os.environ', {'MY_QA_PASSWORD': 'qa-pw'}, clear=True):
            self.assertEqual(credentials.secret('qa'), 'qa-pw')
            self.assertIsNone(credentials.secret('jira'))
            self.assertEqual(credentials.reference('jira'), 'keychain:team-jira/me@example.com')
        with patch.object(credentials.sys, 'platform', 'linux'), patch.object(credentials, 'RUN', side_effect=AssertionError), \
                patch.dict('os.environ', {}, clear=True):
            self.assertIsNone(credentials.secret('jira'))

    def test_jira_requests_use_the_reference(self):
        sys.path.insert(0, str(ROOT / 'bin'))
        import importlib.util
        spec = importlib.util.spec_from_file_location('sidequest_jira_cli', ROOT / 'bin/sidequest-jira.py')
        jira = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(jira)
        run, _ = keychain({('team-jira', 'me@example.com'): 'tok'})
        with patch.object(credentials, 'RUN', run), patch.dict('os.environ', {}, clear=True), \
                patch.object(jira.identity, 'JIRA_EMAIL', 'me@example.com'):
            header = jira._auth()
        self.assertEqual(base64.b64decode(header.split()[1]).decode(), 'me@example.com:tok')


class CredentialSettingsTests(unittest.TestCase):
    def test_only_references_are_accepted_and_values_are_not_echoed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            for good in ('keychain:svc', 'keychain:svc/me@example.com', 'env:MY_TOKEN'):
                path.write_text(json.dumps({'credentials': {'jira': good}}))
                self.assertEqual(config.load(path)['credentials'], {'jira': good})
            for bad in ('ATATT3xFfGF0-secret', 'keychain:', 'env:1BAD', 'keychain:svc extra'):
                path.write_text(json.dumps({'credentials': {'jira': bad}}))
                with self.subTest(value=bad), self.assertRaises(ValueError) as caught:
                    config.load(path)
                if bad not in ('keychain:',):  # a bare prefix also appears in the help text
                    self.assertNotIn(bad, str(caught.exception))
            path.write_text(json.dumps({'credentials': {'heroku': 'env:X'}}))
            with self.assertRaises(ValueError):
                config.load(path)


if __name__ == '__main__':
    unittest.main()
