import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core import Store
from tui import App, run
from sidequest.snapshots import SnapshotStore

class AccessErrorTests(unittest.TestCase):
    def test_login_and_network_errors_have_distinct_safe_recovery_steps(self):
        collect = ['sidequest-data', 'collect', '--json']
        cases = [(['gh', 'pr', 'list'], 'HTTP 401 Bad credentials secret-fixture', 'gh auth login'),
                 (['gh', 'pr', 'list'], 'check your internet connection secret-fixture', 'network'),
                 (collect, 'Collection failed. Check configuration, network and service login. secret-fixture', 'request failed')]
        for args, stderr, guidance in cases:
            with self.subTest(stderr=stderr), patch('subprocess.run', return_value=subprocess.CompletedProcess(args, 1, '', stderr)):
                with self.assertRaises(RuntimeError) as failure:
                    run(args)
                self.assertIn(guidance, str(failure.exception))
                self.assertNotIn('secret-fixture', str(failure.exception))

    def test_failed_sources_stay_visible_after_restart_and_in_overview(self):
        with tempfile.TemporaryDirectory() as folder:
            SnapshotStore(folder).publish({}, {'jira': 'Jira login unavailable. Update SIDEQUEST_JIRA_TOKEN.', 'prs': 'GitHub login expired. Run gh auth login.'})
            store = Store(':memory:')
            self.addCleanup(store.close)
            app = App(store, Path(folder))
            self.assertIn('ERROR', app.header_status()[0])
            self.assertIn('gh auth login', '\n'.join(app.details(None)))
            self.assertIn('SIDEQUEST_JIRA_TOKEN', '\n'.join(app.details(None)))

    def test_successful_refresh_clears_persistent_errors(self):
        import json, time
        with tempfile.TemporaryDirectory() as folder:
            store = Store(':memory:')
            self.addCleanup(store.close)
            app = App(store, Path(folder), demo=True)
            app.demo = False
            app.evidence.finish_refresh(({}, ['GitHub login expired. Run gh auth login.'], {'prs'}))
            data = {'version': 1, 'sources': {'jira': {'generated_at': '2026-10-29T10:00:00-03:00', 'jira_available': True, 'tickets': []},
                                            'prs': {'generated_at': '2026-10-29T10:00:00-03:00', 'open_prs': []}}, 'failures': {}}
            def response(args, **kwargs):
                return subprocess.CompletedProcess(args, 0, json.dumps(data) if 'collect' in args else '{}', '')
            with patch('subprocess.run', side_effect=response):
                app.refresh()
                deadline = time.monotonic() + 2
                while (app.refreshing or app.jobs) and time.monotonic() < deadline:
                    app.drain()
                    time.sleep(.01)
            self.assertEqual((app.evidence.refresh_errors, app.evidence.failed_sources), ([], set()))
            self.assertNotIn('ERROR', app.header_status()[0])
            self.assertEqual(store.source('refresh_errors')['messages'], [])

    def test_error_banner_and_recovery_are_rendered_at_supported_widths(self):
        from test_responsive import Screen
        store = Store(':memory:')
        self.addCleanup(store.close)
        app = App(store, Path('/tmp'), demo=True)
        app.evidence.finish_refresh(({}, ['GitHub: login expired. Run gh auth login, then press r.'], {'prs'}))
        for width in (80, 145, 220):
            with self.subTest(width=width):
                app.screen = Screen(40, width)
                app.draw()
                text = '\n'.join(app.screen.lines)
                self.assertIn('ERROR', text)
                self.assertIn('gh auth login', text)
