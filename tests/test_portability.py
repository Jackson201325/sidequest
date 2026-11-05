import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'ticket-tui')]
from core import Store, Ticket, tickets_from
from tui import App, run


class PortabilityTests(unittest.TestCase):
    def test_arbitrary_jira_project_keys_join_prs(self):
        tickets = tickets_from({'tickets': [{'key': 'APP-42', 'summary': 'Validate input'}]},
                              {'open_prs': [{'number': 9, 'title': 'APP-42 Validate input'}]})
        self.assertEqual([t.key for t in tickets], ['APP-42'])
        self.assertEqual(tickets[0].prs[0]['number'], 9)

    def test_refresh_uses_bundled_command_instead_of_personal_path_command(self):
        result = subprocess.CompletedProcess([], 0, '{}', '')
        with patch('tui.subprocess.run', return_value=result) as process:
            run(['sidequest-data', 'collect', '--json'])
        command = process.call_args[0][0]
        self.assertIn(str(ROOT / 'bin' / 'sidequest-data.py'), command)
        self.assertNotEqual(command[0], 'sidequest-data')

    def test_unconfigured_heroku_does_not_access_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(':memory:')
            try:
                app = App(store, Path(folder), demo=True)
                app.demo = False
                with patch('tui.fetch_environments') as fetch, patch.object(app, 'background') as background:
                    app.refresh_environments()
                fetch.assert_not_called()
                background.assert_not_called()
            finally:
                store.close()

    def test_unlinked_pr_does_not_become_a_fake_jira_link(self):
        from sidequest import config
        with tempfile.TemporaryDirectory() as folder:
            store = Store(':memory:')
            try:
                app = App(store, Path(folder), demo=True)
                app.demo = False
                ticket = Ticket('PR-42', prs=[{'number': 42}])
                with patch.object(config, 'SETTINGS', {'jira': {'site': 'https://example.atlassian.net'}}), \
                        patch.object(app, 'background') as background:
                    app.open_url(ticket)
                background.assert_not_called()
                self.assertIn('No supported link', app.message)
            finally:
                store.close()

    def test_default_storage_does_not_open_existing_personal_database(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {k: v for k, v in os.environ.items() if not k.startswith(('SIDEQUEST_', 'TW_'))}
            env.update(HOME=folder, XDG_DATA_HOME=folder + '/data', XDG_CONFIG_HOME=folder + '/config',
                       XDG_STATE_HOME=folder + '/state', PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), '--list'],
                                    cwd=folder, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(path.name for path in (Path(folder) / 'data').iterdir()), ['sidequest'])
            self.assertTrue((Path(folder) / 'data/sidequest/tickets.sqlite3').is_file())

    def test_refresh_list_runs_from_a_fresh_directory_without_team_scripts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / 'config.json'
            config.write_text(json.dumps({'github': {'repository': 'example/repo', 'username': 'developer'}}))
            gh = root / 'gh'
            gh.write_text('#!' + sys.executable + '\n' + '''import json, sys
args = sys.argv[1:]
if args[:2] == ['pr', 'list']:
    print(json.dumps([{'number': 42, 'title': 'APP-42 Portable queue', 'url': 'https://github.com/example/repo/pull/42'}]))
elif 'graphql' in args:
    print(json.dumps({'data': {'repository': {'pullRequest': {'reviewThreads': {'nodes': [], 'pageInfo': {'hasNextPage': False}}}}}}))
else:
    print('[]')
''')
            gh.chmod(0o755)
            env = {k: v for k, v in os.environ.items() if not k.startswith(('SIDEQUEST_', 'TW_'))}
            env.update(HOME=folder, XDG_DATA_HOME=folder + '/data', XDG_STATE_HOME=folder + '/state',
                       SIDEQUEST_CONFIG=str(config), PATH=folder + os.pathsep + os.environ.get('PATH', ''),
                       PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), '--refresh', '--list'],
                                    cwd=folder, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('APP-42', result.stdout)
            self.assertTrue((root / 'state/sidequest/snapshots/snapshot.json').is_file())

    def test_bad_configuration_does_not_print_credential_values(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            config.write_text(json.dumps({'jira': {'token': 'fixture-secret-must-not-be-printed'}}))
            env = dict(os.environ, SIDEQUEST_CONFIG=str(config), PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), '--list'],
                                    cwd=folder, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('Keep credentials in environment variables', result.stderr)
            self.assertNotIn('fixture-secret-must-not-be-printed', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
