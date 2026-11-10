import unittest
from datetime import datetime
from core import Store, Ticket, TZ, rank

class MergedWaitingTests(unittest.TestCase):
    def test_approved_handoffs_stay_in_waiting_before_and_after_followup_threshold(self):
        store = Store(':memory:')
        self.addCleanup(store.close)
        for since, label, action in (('2026-10-27T15:00:00-03:00', '2h', 'Awaiting merge/release handoff'),
                                     ('2026-10-26T09:00:00-03:00', '2d', 'Follow up with the next owner')):
            with self.subTest(since=since):
                ticket = Ticket('DEMO-42', status='Approved', assigned_me=False, assignee='Release Owner', status_since=since)
                rank(ticket, store, datetime(2026, 10, 28, 9, tzinfo=TZ))
                self.assertEqual(ticket.lane, 'Waiting')
                self.assertEqual(ticket.wait_label, label)
                self.assertEqual(ticket.action, action)

    def test_lane_keys_show_one_waiting_view_and_no_followup_tab(self):
        from pathlib import Path
        from unittest.mock import patch
        from test_responsive import KeyScreen
        from tui import App
        store = Store(':memory:')
        self.addCleanup(store.close)
        app = App(store, Path('/tmp'), demo=True)
        screen = KeyScreen(('3', 'q'), 32, 145)
        with patch.dict('os.environ', {'NO_COLOR': '1'}), patch('curses.curs_set'), patch('curses.set_escdelay'):
            app.loop(screen)
        self.assertEqual(app.view, 'Waiting')
        self.assertTrue(app.visible())
        self.assertTrue(all(t.lane == 'Waiting' for t in app.visible()))
        self.assertNotIn('Follow up', screen.frames[-1][0])
        screen = KeyScreen(('4', '5', 'q'))
        with patch.dict('os.environ', {'NO_COLOR': '1'}), patch('curses.curs_set'), patch('curses.set_escdelay'):
            app.loop(screen)
        self.assertEqual(app.view, 'In Dev')              # 5 is the In Dev stage tab, not a follow-up lane
        self.assertNotIn('Follow up', screen.frames[-1][0])
