import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core import Store
from tui import AGENT_TASKS, App, agent_command

PANES = "example-project\t@7\tDEMO-901\t/wt/DEMO-901-bulk\n"


def wait(app):
    deadline = time.monotonic() + 3
    while (app.refreshing or app.jobs) and time.monotonic() < deadline:
        app.drain()
        time.sleep(0.01)
    app.drain()


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(":memory:")
        self.app = App(self.store, Path(self.folder.name), demo=True)
        self.app.demo = False
        self.app.evidence.windows = {"DEMO-901": "/wt/DEMO-901-bulk"}
        self.app.rebuild()
        self.ticket = next(t for t in self.app.tickets if t.key == "DEMO-901")

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def launch(self, choice, typed=None):
        calls = []

        def fake_run(args, timeout=45):
            calls.append(args)
            return PANES if args[:2] == ["tmux", "list-panes"] else ""

        with patch.object(App, "choose", return_value=choice), patch.object(App, "prompt", return_value=typed), \
                patch("tui.run", side_effect=fake_run), patch.dict("os.environ", {"TMUX": "/tmp/tmux"}):
            self.app.launch_agent(self.ticket)
            wait(self.app)
        return calls

    def test_command_quotes_the_prompt_and_uses_the_worktree(self):
        self.assertEqual(agent_command("@7", "/wt/a b", "handle feedback on DEMO-1"),
                         ["tmux", "split-window", "-h", "-t", "@7", "-c", "/wt/a b", "claude 'handle feedback on DEMO-1'"])

    def test_presets_are_self_contained_review_prompts(self):
        for index, phrase in ((0, 'Review the PR feedback for DEMO-901'), (1, 'Review the branch for DEMO-901')):
            calls = self.launch(index)
            split = next(c for c in calls if c[1] == 'split-window')
            self.assertTrue(split[-1].startswith("claude '" + phrase))
            self.assertNotIn('skill:', split[-1])
            self.assertIn(['tmux', 'select-window', '-t', '@7'], calls)

    def test_custom_prompt_gets_the_ticket_key(self):
        calls = self.launch(len(AGENT_TASKS) - 1, "  why is CI red?  ")
        split = next(c for c in calls if c[1] == "split-window")
        self.assertEqual(split[-1], "claude 'DEMO-901: why is CI red?'")

    def test_cancel_and_missing_worktree_do_nothing(self):
        self.assertEqual(self.launch(None), [])
        self.assertEqual(self.app.message, "Agent launch cancelled")
        self.assertEqual(self.launch(len(AGENT_TASKS) - 1, "   "), [])
        self.ticket.worktree = ""
        self.assertEqual(self.launch(0), [])                  # feedback needs a branch
        self.assertIn("workspace.repository", self.app.message)

    def test_ticket_start_never_calls_personal_tools_or_changes_jira(self):
        for status in ('Ready for Dev', 'Backlog', 'Blocked'):
            self.ticket.status = status
            with patch('tui.run') as command:
                self.app.start_work(self.ticket)
            command.assert_not_called()
            self.assertIn('read-only', self.app.message)

    def test_shared_collection_details_all_arrive_without_blocking_the_queue(self):
        store = Store(":memory:")
        try:
            app = App(store, Path(tempfile.gettempdir()), demo=True)
            app.demo = False
            keys = [f"DEMO-{n}" for n in range(901, 909)]
            def fake_run(args, timeout=45):
                time.sleep(0.05)
                return json.dumps({"sources": {
                    "jira": {"jira_available": True, "tickets": [{"key": k, "summary": "x", "status": "In Progress"} for k in keys]},
                    "prs": {"open_prs": []}}, "failures": {}})
            with patch("tui.run", side_effect=fake_run), patch("tui.worktrees", return_value={}), patch("tui.fetch_environments", return_value={"entries": {}}):
                app.refresh()
                self.assertTrue(app.refreshing)
                wait(app)
            self.assertEqual({t["key"] for t in app.evidence.jira["tickets"]}, set(keys))
            self.assertIn("Refreshed", app.message + (app.deferred_message or ""))
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
