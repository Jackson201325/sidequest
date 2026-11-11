"""Wide terminals put the list left of the details (redesign phase 4, specs/tui-redesign-inbox.md)."""
from pathlib import Path
import unittest
from unittest.mock import patch

from core import Store
from layout import SIDE_BY_SIDE_WIDTH, panel_rects
from test_responsive import KeyScreen, Screen
from tui import App


class RectTests(unittest.TestCase):
    def test_wide_terminals_split_left_and_right(self):
        ticket, detail = panel_rects(30, SIDE_BY_SIDE_WIDTH)
        self.assertEqual((ticket[0], detail[0]), (1, 1))
        self.assertEqual(ticket[1], 0)
        self.assertEqual(detail[1], ticket[3] + 1)                  # one column for the divider
        self.assertEqual(ticket[3] + 1 + detail[3], SIDE_BY_SIDE_WIDTH - 1)
        self.assertEqual((ticket[2], detail[2]), (30 - 4, 30 - 3))  # the details own the closing rule
        self.assertEqual(ticket[3], round((SIDE_BY_SIDE_WIDTH - 1) * 0.45))

    def test_narrower_or_short_terminals_keep_the_old_layouts(self):
        ticket, detail = panel_rects(30, SIDE_BY_SIDE_WIDTH - 1)
        self.assertEqual(detail[1], 0)
        self.assertGreater(detail[0], ticket[0] + ticket[2])
        self.assertEqual(panel_rects(17, 200, "list")[1], None)

    def test_width_share_stays_between_thirty_and_sixty_percent(self):
        usable = 199
        self.assertEqual(panel_rects(30, 200, side_fraction=0.9)[0][3], round(usable * 0.6))
        self.assertEqual(panel_rects(30, 200, side_fraction=0.1)[0][3], round(usable * 0.3))


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.app = App(self.store, Path("/tmp"), demo=True)
        self.app.screen = Screen(32, 145)

    def tearDown(self):
        self.store.close()

    def test_list_and_details_share_the_title_row_with_a_divider(self):
        self.app.draw()
        lines = self.app.screen.lines
        split = panel_rects(32, 145)[0][3]
        self.assertTrue(lines[1].startswith("▸ Tickets 4 "))
        self.assertIn("  DEMO-901 · Validate", lines[1][split:])
        self.assertEqual(lines[1][split], "┬")
        self.assertTrue(all(lines[y][split] == "│" for y in range(2, 32 - 3)))
        self.assertEqual(lines[32 - 3][split], "┴")
        self.assertTrue(lines[32 - 3].startswith("───"))
        self.assertTrue(any("DEMO-903" in line[:split] for line in lines))    # the whole queue fits

    def test_narrow_details_keep_every_tab_key_and_the_current_name(self):
        self.app.draw()
        split = panel_rects(32, 145)[0][3]
        row = next(line[split:] for line in self.app.screen.lines if "Activity" in line[split:])
        self.assertTrue(row.rstrip().endswith(" u"), row)
        for key in "apdcmvsfu":
            self.assertIn(f" {key} ", row)

    def test_plus_minus_change_the_width_share_and_it_is_remembered(self):
        screen = KeyScreen(("+", "+", "-", "q"), 32, 145)
        with patch.dict("os.environ", {"NO_COLOR": "1"}), patch("curses.curs_set"), patch("curses.set_escdelay"):
            self.app.loop(screen)
        self.assertAlmostEqual(self.app.side_fraction, 0.5)
        self.assertAlmostEqual(self.app.list_fraction, 0.3)                    # the stacked size is untouched
        self.assertIn("Tickets 50% / details 50%", self.app.message)
        reopened = App(self.store, Path("/tmp"), demo=True)
        self.assertAlmostEqual(reopened.side_fraction, 0.5)
        self.app.screen = Screen(32, 145)
        self.app.press("=")
        self.assertAlmostEqual(self.app.side_fraction, 0.45)


if __name__ == "__main__":
    unittest.main()
