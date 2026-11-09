import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core import Store
from sidequest.terminal import agent_argv
from sidequest.tmux import split_command
from tui import AGENT_TASKS, App

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
        self.assertEqual(split_command("@7", "/wt/a b", agent_argv("handle feedback on DEMO-1")),
                         ["tmux", "split-window", "-h", "-t", "@7", "-c", "/wt/a b", "claude 'handle feedback on DEMO-1'"])

    def test_configured_agent_tasks_replace_the_presets_and_point_at_their_skill(self):
        from sidequest import config
        tasks = [{"label": "Handle feedback", "prompt": "handle feedback on {key}", "skill": "/skills/team-feedback.md"},
                 {"label": "Look around", "prompt": "look at {key}"}]
        settings = dict(config.SETTINGS, workspace=dict(config.SETTINGS.get("workspace", {}), agent_tasks=tasks))
        with patch.object(config, "SETTINGS", settings):
            with patch.object(App, "choose", return_value=None) as choose:
                self.app.launch_agent(self.ticket)
            labels = choose.call_args[0][1]
            self.assertEqual([label.split("  ", 1)[1] for label in labels], ["Handle feedback", "Look around", "Custom prompt..."])
            split = next(c for c in self.launch(0) if c[1] == "split-window")
            self.assertEqual(split[-1], "claude 'handle feedback on DEMO-901 (use the team-feedback skill: /skills/team-feedback.md)'")
            split = next(c for c in self.launch(1) if c[1] == "split-window")
            self.assertEqual(split[-1], "claude 'look at DEMO-901'")

    def test_bundled_presets_include_the_project_additions(self):
        from sidequest import config
        with tempfile.TemporaryDirectory() as folder:
            addon = Path(folder) / "alpha/skills/feedback.md"
            addon.parent.mkdir(parents=True)
            addon.write_text("Reply in the team's review style.")
            with patch.object(config, "PROJECTS_DIR", Path(folder)), patch.object(config, "PROJECT", "alpha"):
                split = next(c for c in self.launch(0) if c[1] == "split-window")
        self.assertIn("Project additions: alpha", split[-1])
        self.assertIn("Reply in the team", split[-1])

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

    def test_ticket_start_never_calls_personal_tools_or_changes_jira_unless_configured(self):
        for status in ('Ready for Dev', 'Backlog', 'Blocked'):
            self.ticket.status = status
            with patch('tui.run') as command:
                self.app.start_work(self.ticket)
            command.assert_not_called()
            self.assertIn('workspace.repository', self.app.message)

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
