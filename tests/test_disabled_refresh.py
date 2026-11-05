"""Unconfigured integrations cannot replace existing queue evidence with emptiness."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from sidequest import collector, config, identity
from sidequest.snapshots import SnapshotStore, stamp


class DisabledRefreshTests(unittest.TestCase):
    def sources(self):
        return {'jira': {'generated_at': stamp(), 'enabled': True, 'jira_available': True,
                         'tickets': [{'key': 'APP-42', 'summary': 'Keep this ticket', 'status': 'In Progress'}]},
                'prs': {'generated_at': stamp(), 'enabled': True, 'open_prs': [{'number': 42, 'ticket': 'APP-42'}]}}

    def test_unconfigured_refresh_retains_existing_sources_and_their_timestamps(self):
        for max_age in (0, 3600):
            with self.subTest(max_age=max_age), tempfile.TemporaryDirectory() as folder:
                sources = self.sources()
                SnapshotStore(folder).publish(sources)
                with patch.object(config, 'SETTINGS', {}), patch.object(identity, 'GITHUB_REPO', ''), \
                        patch.object(collector.github, 'list_open_prs', side_effect=AssertionError('GitHub queried')), \
                        patch.object(collector.client, '_auth', side_effect=AssertionError('Jira credentials accessed')):
                    result = collector.collect(folder, max_age=max_age)
                self.assertEqual(result['sources'], sources)
                self.assertEqual(set(result['failures']), {'jira', 'prs'})
                self.assertIn('not configured', result['failures']['jira'])

    def test_fresh_github_only_or_unconfigured_setup_does_not_fail_for_unused_services(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, 'SETTINGS', {}), \
                patch.object(identity, 'GITHUB_REPO', ''):
            first = collector.collect(folder)
            second = collector.collect(folder)
        self.assertFalse(first['failures'])
        self.assertFalse(second['failures'])
        self.assertFalse(second['sources']['jira']['enabled'])

    def test_a_successful_configured_empty_response_still_replaces_old_data(self):
        with tempfile.TemporaryDirectory() as folder:
            SnapshotStore(folder).publish(self.sources())
            with patch.object(collector, 'collect_prs', return_value={'enabled': True, 'open_prs': []}), \
                    patch.object(collector, 'collect_jira', return_value={'enabled': True, 'jira_available': True, 'tickets': []}):
                result = collector.collect(folder)
            self.assertEqual(result['sources']['jira']['tickets'], [])
            self.assertEqual(result['sources']['prs']['open_prs'], [])
            self.assertFalse(result['failures'])

    def test_cli_refresh_keeps_ticket_visible_when_configuration_is_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config_path = root / 'config.json'
            config_path.write_text('{}')
            SnapshotStore(root / 'snapshots').publish(self.sources())
            env = {k: v for k, v in os.environ.items() if not k.startswith(('SIDEQUEST_', 'HERDR_', 'GIT_'))}
            env.update(SIDEQUEST_CONFIG=str(config_path), SIDEQUEST_TERMINAL='shell', PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve().parents[1] / 'bin/sidequest'),
                                     '--refresh', '--list', '--snapshots', str(root / 'snapshots'),
                                     '--data-dir', str(root / 'data')], cwd=root, env=env, text=True, capture_output=True)
            self.assertIn('APP-42', result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertIn('not configured', result.stderr)


if __name__ == '__main__':
    unittest.main()
