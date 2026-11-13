"""Every setting can also come from a SIDEQUEST_<SECTION>_<KEY> environment variable."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import config


class EnvironmentSettingsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'config.json'
        self.path.write_text(json.dumps({'jira': {'site': 'https://file.atlassian.net', 'email': 'file@example.com'}}))

    def test_variables_override_the_file_and_fill_missing_sections(self):
        settings = config.load(self.path, {
            'SIDEQUEST_JIRA_SITE': 'https://env.atlassian.net', 'SIDEQUEST_JIRA_PROJECTS': 'APP, OPS',
            'SIDEQUEST_GITHUB_REPOSITORY': 'example/app', 'SIDEQUEST_APP_SWITCH_COMMAND': 'make up',
            'SIDEQUEST_GITHUB_BRANCH_TICKETS': '{"hotfix/x": "APP-3"}', 'SIDEQUEST_WORKSPACE_TMUX_SESSION': 'demo'})
        self.assertEqual(settings['jira'], {'site': 'https://env.atlassian.net', 'email': 'file@example.com',
                                            'projects': ['APP', 'OPS']})
        self.assertEqual(settings['github'], {'repository': 'example/app', 'branch_tickets': {'hotfix/x': 'APP-3'}})
        self.assertEqual(settings['app'], {'switch_command': 'make up'})
        self.assertEqual(settings['workspace'], {'tmux_session': 'demo'})

    def test_other_sidequest_variables_and_the_token_are_not_settings(self):
        settings = config.load(self.path, {
            'SIDEQUEST_JIRA_TOKEN': 'secret', 'SIDEQUEST_CONFIG': '/x', 'SIDEQUEST_TICKETS_DIR': '/t',
            'SIDEQUEST_QA_PASSWORD': 'p', 'SIDEQUEST_REVIEW_PASSWORD': 'p', 'SIDEQUEST_REPO': '/r',
            'SIDEQUEST_TERMINAL': 'tmux', 'SIDEQUEST_DATA_DIR': '/d', 'SIDEQUEST_STATE_DIR': '/s'})
        self.assertEqual(set(settings), {'jira'})
        self.assertNotIn('secret', json.dumps(settings))

    def test_the_documented_heroku_token_is_a_credential_not_a_setting(self):
        settings = config.load(self.path, {'SIDEQUEST_HEROKU_TOKEN': 'secret'})
        self.assertEqual(set(settings), {'jira'})
        self.assertNotIn('secret', json.dumps(settings))

    def test_qa_browser_and_email_are_settings_but_the_password_is_not(self):
        self.path.write_text(json.dumps({'qa': {'browser': '/file/edge'}}))
        settings = config.load(self.path, {'SIDEQUEST_QA_EMAIL': 'qa@example.com', 'SIDEQUEST_QA_PASSWORD': 'p'})
        self.assertEqual(settings, {'qa': {'browser': '/file/edge', 'email': 'qa@example.com'}})
        self.path.write_text(json.dumps({'qa': {'password': 'p'}}))
        with self.assertRaisesRegex(ValueError, 'environment variables'):
            config.load(self.path)

    def test_agent_tasks_and_reports_dir_are_workspace_settings(self):
        tasks = [{'label': 'Ship', 'prompt': 'ship {key}', 'skill': '/skills/ship.md'}, {'label': 'Look', 'prompt': 'look at {key}'}]
        settings = config.load(self.path, {'SIDEQUEST_WORKSPACE_AGENT_TASKS': json.dumps(tasks),
                                           'SIDEQUEST_WORKSPACE_REPORTS_DIR': '/reports'})
        self.assertEqual(settings['workspace'], {'agent_tasks': tasks, 'reports_dir': '/reports'})
        for bad in ('{"label": "x"}', '[{"label": "x"}]', '[{"label": "x", "prompt": "y", "extra": "z"}]', '[1]', '{bad'):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'agent_tasks'):
                config.load(self.path, {'SIDEQUEST_WORKSPACE_AGENT_TASKS': bad})

    def test_checks_are_settings(self):
        settings = config.load(self.path, {'SIDEQUEST_CHECKS_LINT': 'make lint', 'SIDEQUEST_CHECKS_TEST': 'make test'})
        self.assertEqual(settings['checks'], {'lint': 'make lint', 'test': 'make test'})
        with self.assertRaises(ValueError):
            config.load(self.path, {'SIDEQUEST_CHECKS_DEPLOY': 'make deploy'})

    def test_layout_windows_and_hooks_are_workspace_settings(self):
        windows = [{'name': 'queue', 'command': 'sidequest', 'at': 'start', 'stay': True}, {'name': 'notes', 'cwd': '~/notes', 'keys': 'nvimc'}]
        settings = config.load(self.path, {'SIDEQUEST_WORKSPACE_WINDOWS': json.dumps(windows),
                                           'SIDEQUEST_WORKSPACE_ON_UP': json.dumps(['make sync'])})
        self.assertEqual(settings['workspace'], {'windows': windows, 'on_up': ['make sync']})
        for name, bad in (('WINDOWS', '[{"command": "x"}]'), ('WINDOWS', '[{"name": "a", "at": "middle"}]'),
                          ('WINDOWS', '[{"name": "a", "stay": "yes"}]'), ('ON_UP', '["ok", 3]'), ('ON_UP', '"make"')):
            with self.subTest(name=name, bad=bad), self.assertRaisesRegex(ValueError, 'workspace.' + name.lower()):
                config.load(self.path, {'SIDEQUEST_WORKSPACE_' + name: bad})

    def test_unknown_or_invalid_variables_are_refused(self):
        for name, value in (('SIDEQUEST_JIRA_SITEE', 'https://x.atlassian.net'), ('SIDEQUEST_APP_URL', 'ftp://x'),
                            ('SIDEQUEST_JIRA_PROJECTS', 'not a key'), ('SIDEQUEST_GITHUB_PR_TICKETS', '[1]'),
                            ('SIDEQUEST_GITHUB_PR_TICKETS', '{bad json')):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError) as caught:
                config.load(self.path, {name: value})
            self.assertNotIn(value, str(caught.exception), 'values are not echoed')

    def test_without_variables_the_file_is_used_as_is(self):
        self.assertEqual(config.load(self.path), {'jira': {'site': 'https://file.atlassian.net', 'email': 'file@example.com'}})

    def test_the_running_app_uses_variables_and_separate_storage_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
            env.update(SIDEQUEST_CONFIG=str(Path(folder) / 'none.json'), SIDEQUEST_IDENTITY_TIMEZONE='Asia/Tokyo',
                       SIDEQUEST_STATE_DIR=str(Path(folder) / 'state'), SIDEQUEST_DATA_DIR=str(Path(folder) / 'data'))
            code = ('from sidequest import config, identity, app_booking; '
                    'print(identity.TZ, config.STATE_DIR, config.DATA_DIR, app_booking.lock_path(), sep="|")')
            out = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout.strip().split('|'), [
                'Asia/Tokyo', str(Path(folder) / 'state'), str(Path(folder) / 'data'), str(Path(folder) / 'state/app.lock')])


if __name__ == '__main__':
    unittest.main()
