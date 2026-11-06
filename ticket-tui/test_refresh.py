import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core import Store
from tui import App, run


class RefreshTests(unittest.TestCase):
    def test_github_only_collection_does_not_access_jira_credentials(self):
        from sidequest import collector
        from sidequest.jira import client
        with patch('sidequest.identity.GITHUB_REPO', 'example/repo'), patch('sidequest.github.list_open_prs', return_value=[]), \
                patch.object(client, '_auth', side_effect=AssertionError('Jira credentials accessed')):
            self.assertEqual(collector.collect_prs()['open_prs'], [])

    def test_heroku_dns_failure_is_not_reported_as_missing_credentials(self):
        result = subprocess.CompletedProcess([], 1, "", "getaddrinfo ENOTFOUND api.heroku.com")
        with patch("tui.subprocess.run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "DNS lookup failed"):
                run(["heroku", "apps:info", "--app", "fixture-app", "--json"])

    def test_diagnostics_reject_even_successful_empty_json(self):
        result = subprocess.CompletedProcess([], 0, '{"open_prs": []}', "warning: API unreachable")
        with patch("tui.subprocess.run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "keeping the previous snapshot"):
                run(["sidequest-data", "collect", "--json"])

    def test_bad_refresh_retains_snapshot_and_selection_survives_ranking(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(":memory:")
            try:
                app = App(store, Path(folder), demo=True)
                app.demo = False
                original_prs = app.evidence.prs
                with patch("tui.run", return_value="[]"), patch("tui.worktrees", return_value={}), \
                        patch("tui.fetch_environments", return_value={"entries": {}}):
                    app.refresh()
                    deadline = time.monotonic() + 2
                    while (app.refreshing or app.jobs) and time.monotonic() < deadline:
                        app.drain()
                        time.sleep(0.01)
                self.assertFalse(app.refreshing)
                self.assertIs(app.evidence.prs, original_prs)
                self.assertIn("Refresh incomplete", app.message)
                selected = app.selected()
                store.save(selected.key, {"court": "them"})
                app.rebuild()
                self.assertEqual(app.selected().key, selected.key)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
