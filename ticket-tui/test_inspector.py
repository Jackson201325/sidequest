"""Details pane order: facts, NEXT, agent track, then tabs (redesign phase 3, specs/tui-redesign-inbox.md)."""
from datetime import datetime
from pathlib import Path
import unittest

from core import TZ, Store, Ticket
from layout import agent_track, inspector_rows
from test_responsive import Screen
from tui import App

CLOCK = datetime(2026, 11, 11, 12, 0, tzinfo=TZ)


class RowsTests(unittest.TestCase):
    def test_facts_then_next_then_hint_then_agent(self):
        ticket = Ticket("DEMO-1", "Title", status="In Progress", court="me", lane="Needs me",
                        action="Address requested changes", prs=[{"number": 9, "ci": "green"}])
        record = {"step": "implement", "state": "working", "updated": "2026-11-11T11:56:00-03:00", "note": "tests"}
        rows = inspector_rows(ticket, CLOCK, local=["Local clean"], hint="QA shots missing", record=record)
        self.assertEqual([style for _, style in rows],
                         ["Needs me", "pr", "dim", "dim", "plain", "next", "plain", "agent", "dim"])
        texts = [text for text, _ in rows]
        self.assertTrue(texts[0].startswith("● Needs me"))
        self.assertEqual(texts[5], "NEXT → Address requested changes")
        self.assertEqual(texts[6], "→ QA shots missing")
        self.assertTrue(texts[7].startswith("Agent ✓ start ━ "))
        self.assertTrue(texts[8].endswith("tests"))

    def test_no_action_and_no_worker_leave_only_the_facts(self):
        ticket = Ticket("DEMO-2", "Title", status="QA", court="them", lane="Waiting", action="")
        rows = inspector_rows(ticket, CLOCK)
        self.assertNotIn("next", [style for _, style in rows])
        self.assertNotIn("agent", [style for _, style in rows])
        self.assertNotEqual(rows[-1][0], "")

    def test_short_panes_keep_status_and_next(self):
        ticket = Ticket("DEMO-1", "Title", lane="Needs me", action="Do it", prs=[{"number": 9}])
        rows = inspector_rows(ticket, CLOCK, short=True)
        self.assertEqual([style for _, style in rows], ["Needs me", "next"])

    def test_agent_track_marks_done_current_and_ahead(self):
        track = agent_track({"step": "qa-local", "state": "failed"}, 0)
        self.assertEqual(track, "✓ start ━ ✓ implement ━ ✗ qa-local ━ · ship-check")
        self.assertTrue(agent_track({"step": "ship-check", "state": "ready"}, 0).endswith("✓ ship-check"))


class PaneTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.app = App(self.store, Path("/tmp"), demo=True)
        self.app.screen = Screen(32, 119)                 # stacked; test_side_by_side covers wider

    def tearDown(self):
        self.store.close()

    def test_summary_comes_before_the_tabs_and_next_stands_out(self):
        self.app.draw()
        lines = self.app.screen.lines
        top = next(i for i, line in enumerate(lines) if line.startswith("  DEMO-901 · "))
        self.assertTrue(lines[top + 1].strip().startswith("● Needs me"))
        next_row = next(i for i, line in enumerate(lines) if "NEXT → Address requested changes" in line)
        tabs = next(i for i, line in enumerate(lines) if "a Activity" in line)
        self.assertLess(top, next_row)
        self.assertLess(next_row, tabs)
        self.assertIn("newest first", lines[tabs + 1])
        self.assertFalse(any(line.strip() and set(line.strip()) == {"─"} for line in lines[top + 1:tabs]))

    def test_standup_has_no_summary_so_tabs_follow_the_title(self):
        self.app.press("u")
        self.app.draw()
        lines = self.app.screen.lines
        top = next(i for i, line in enumerate(lines) if line[2:].startswith("DEMO-901 · "))
        self.assertIn("a Activity", lines[top + 1])


if __name__ == "__main__":
    unittest.main()
