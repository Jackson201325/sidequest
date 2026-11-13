import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core import Store, Ticket
from sidequest import config
from sidequest.tmux import find_window
from tui import App, readable_date


class WorkspaceTests(unittest.TestCase):
    def test_left_pane_exposes_attention_pr_and_environment_without_database_reads(self):
        class Screen:
            def __init__(self):
                self.lines = [""] * 32

            def getmaxyx(self):
                return 32, 145

            def erase(self):
                pass

            def addnstr(self, y, x, text, limit, attr):
                self.lines[y] += text[:limit]

            def refresh(self):
                pass

        store = Store(":memory:")
        try:
            app = App(store, Path("/tmp"), demo=True)
            self.assertEqual(app.detail_tab, "Activity")          # tickets open on Activity
            app.detail_tab = "Overview"                           # it shows the clock dates
            app.screen = Screen()
            with patch.object(store, "get", side_effect=AssertionError("redraw queried SQLite")), \
                    patch.object(store, "history", side_effect=AssertionError("redraw queried SQLite")):
                app.draw()
            self.assertIn("KEY", app.screen.lines[2])                       # table header
            first = app.screen.lines[3]
            for expected in ("●", "DEMO-901", "In Pro", "(PR feedback)", "you", "#901 ✓", "<1h"):
                self.assertIn(expected, first)
            self.assertTrue(any("DEMO-901 · Validate bulk request quantities" in line for line in app.screen.lines[5:]))   # details below tickets
            self.assertTrue(any("turn: you" in line for line in app.screen.lines))      # summary card
            self.assertTrue(any("Today," in line for line in app.details(app.selected())))
            details = " ".join(app.details(app.selected()))
            self.assertIn("CI: green", details)
            self.assertIn("Building", details)
        finally:
            store.close()

    def test_selects_existing_tw_worktree_without_similar_ticket_or_other_session(self):
        ticket = Ticket("DEMO-42", worktree="/tmp/DEMO-42-stock")
        panes = ("other\t@1\tDEMO-42\t/tmp/DEMO-42-stock\n"
                 "example-project\t@2\tDEMO-420\t/tmp/DEMO-420\n"
                 "example-project\t@3\tEditor\t/tmp/DEMO-42-stock/app\n"
                 "example-project\t@4\tDEMO-42\t/tmp/unrelated\n")
        session = config.get("workspace", "tmux_session")
        self.assertEqual(find_window(panes, ticket.key, ticket.worktree, session), ("@3", "Editor"))
        self.assertIsNone(find_window(panes, "DEMO-4", "", session))

    def test_loading_stays_observable_and_work_does_not_block_ui(self):
        store = Store(":memory:")
        release = threading.Event()
        try:
            app = App(store, Path("/tmp"), demo=True)
            app.background("slow", "Loading environment", lambda: (release.wait(2), "Loaded")[1])
            self.assertIn("Loading environment", app.loading_line())
            self.assertEqual(app.selected().key, "DEMO-901")
            release.set()
            deadline = time.monotonic() + 2
            while app.jobs and time.monotonic() < deadline:
                app.drain()
                time.sleep(0.01)
            self.assertFalse(app.jobs)
            self.assertEqual(app.message, "Loaded")
        finally:
            release.set()
            store.close()

    def test_jump_uses_window_and_session_without_creating_worktrees(self):
        store = Store(":memory:")
        try:
            app = App(store, Path("/tmp"), demo=True)
            app.demo = False
            commands = []

            def command(args, **kwargs):
                commands.append(args)
                return "example-project\t@3\tDEMO-901\t/tmp/DEMO-901\n" if args[1] == "list-panes" else ""

            with patch.dict("os.environ", {"TMUX": "test"}), patch("tui.run", side_effect=command):
                app.jump(app.selected())
                deadline = time.monotonic() + 2
                while app.jobs and time.monotonic() < deadline:
                    app.drain()
                    time.sleep(0.01)
            self.assertIn(["tmux", "select-window", "-t", "@3"], commands)
            self.assertIn(["tmux", "switch-client", "-t", "example-project"], commands)
        finally:
            store.close()

    def test_plan_tab_reads_the_tickets_folder_and_rereads_on_change(self):
        import tempfile, os, time as _time
        import tui
        store = Store(":memory:")
        with tempfile.TemporaryDirectory() as folder:
            try:
                app = App(store, Path("/tmp"), demo=True)
                ticket = app.selected()
                app.detail_tab = "Plan"
                plan_lines = lambda: [row.text for row in app.views.plan_rows(ticket, "Plan", Path(folder))]
                headings = lambda: [row.text for row in app.views.plan_rows(ticket, "Plan", Path(folder)) if row.style == "heading"]
                with patch.object(tui, "PLANS", Path(folder)):
                    missing = plan_lines()
                    self.assertIn("No plan yet", missing[0])
                    self.assertIn(f"{ticket.key}/plan.md", missing[-1])
                    plan = Path(folder) / ticket.key / "plan.md"
                    plan.parent.mkdir()
                    plan.write_text("# Plan\n## Acceptance criteria\n- [ ] Reject zero\n- [x] Reject nil\n- **Approach** `x`\n")
                    lines = plan_lines()
                    self.assertTrue(lines[0].startswith(f"{Path(folder).name}/{ticket.key}/plan.md · edited"), lines[0])
                    self.assertIn("ACCEPTANCE CRITERIA", headings())
                    self.assertIn("☐ Reject zero", lines)
                    self.assertIn("☑ Reject nil", lines)
                    self.assertIn("• Approach x", lines)
                    plan.write_text("# Changed\n")
                    os.utime(plan, (_time.time() + 5, _time.time() + 5))
                    self.assertEqual(headings(), ["CHANGED"])
                    self.assertEqual(app.details(ticket)[2], "CHANGED")
            finally:
                store.close()

    def test_readable_dates_have_local_time_without_iso_noise(self):
        self.assertEqual(readable_date("2026-01-02T15:04:22.123-03:00"), "02 Jan 2026, 15:04")
        self.assertEqual(readable_date(""), "Not recorded")


if __name__ == "__main__":
    unittest.main()
