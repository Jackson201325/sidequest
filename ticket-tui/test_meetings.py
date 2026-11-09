"""The Meetings tab is a read-only view of the ticket folder's meetings.md, written by a meeting-notes tool."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import Store
from plan_document import meeting_sections
import tui

NOTES = """# {key} · meeting notes

## 2026-11-03 10:00 · demo-app

- Asked of me: show **$0.00** instead of NaN
- Context: only `GiftCard#balance` is affected

Source: tickets/meetings/2026-11-03-1000-demo-app.md

## 2026-11-06 19:00 · demo-app

- Decided: no backfill
"""


class MeetingSectionsTests(unittest.TestCase):
    def test_sections_come_newest_first_with_plan_style_bullets(self):
        sections = meeting_sections(NOTES.format(key="APP-1"))
        self.assertEqual([h for h, _ in sections], ["2026-11-06 19:00 · demo-app", "2026-11-03 10:00 · demo-app"])
        self.assertEqual(sections[0][1], ["• Decided: no backfill"])
        self.assertIn("• Asked of me: show $0.00 instead of NaN", sections[1][1])
        self.assertIn("• Context: only GiftCard#balance is affected", sections[1][1])
        self.assertEqual(sections[1][1][-1], "Source: tickets/meetings/2026-11-03-1000-demo-app.md")

    def test_text_before_the_first_meeting_is_ignored(self):
        self.assertEqual(meeting_sections("# APP-1 · meeting notes\nstray\n"), [])


class MeetingsTabTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(':memory:')
        self.addCleanup(self.store.close)
        self.app = tui.App(self.store, self.root, demo=True)
        self.ticket = self.app.selected()
        self.path = self.root / self.ticket.key / 'meetings.md'
        self.path.parent.mkdir()
        plans = patch.object(tui, 'PLANS', self.root)
        plans.start()
        self.addCleanup(plans.stop)

    def view(self, name):
        self.app.detail_tab = name
        return '\n'.join(self.app.details(self.ticket))

    def test_m_is_a_tab_key(self):
        self.assertEqual(tui.TAB_KEYS["m"], "Meetings")

    def test_without_notes_it_says_how_they_get_there(self):
        text = self.view('Meetings')
        self.assertIn(f"No meeting notes for {self.ticket.key} yet.", text)
        self.assertIn(str(self.path), text)
        self.assertIn("Meetings: none recorded (m)", self.view('Overview'))

    def test_notes_show_newest_first_and_follow_file_changes(self):
        self.path.write_text(NOTES.format(key=self.ticket.key))
        text = self.view('Meetings')
        self.assertIn("2 meetings, newest first", text)
        self.assertLess(text.index("2026-11-06 19:00"), text.index("2026-11-03 10:00"))
        self.assertIn("Meetings: 2, latest 2026-11-06 19:00 (m)", self.view('Overview'))
        self.path.write_text(NOTES.format(key=self.ticket.key) + "\n## 2026-11-07 09:00 · demo-app\n\n- Open: who owns QA\n")
        import os, time
        later = time.time() + 5
        os.utime(self.path, (later, later))
        self.assertIn("3 meetings, newest first", self.view('Meetings'))

    def test_the_file_is_never_rewritten(self):
        self.path.write_text(NOTES.format(key=self.ticket.key))
        before = self.path.read_bytes()
        self.view('Meetings')
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
