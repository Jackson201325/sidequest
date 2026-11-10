"""Menus and search draw over the dashboard instead of replacing it."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from core import Store
from layout import menu_box
from test_responsive import KeyScreen
from tui import App


class PromptScreen(KeyScreen):
    def move(self, y, x):
        pass

    def clrtoeol(self):
        pass


class MenuBoxTests(unittest.TestCase):
    def test_marks_the_choice_and_the_current_value_inside_a_heavy_border(self):
        rows = menu_box("SORT TICKETS", ["Attention", "Priority"], 1, 60, current=0,
                        notes=["Missing dates last."], hint="Enter apply")
        texts = [text for text, _ in rows]
        self.assertEqual(len({len(text) for text in texts}), 1, texts)
        self.assertTrue(texts[0].startswith("┏━ SORT TICKETS "))
        self.assertIn("Attention", texts[1])
        self.assertTrue(texts[1].rstrip("┃ ").endswith("✓"))
        self.assertEqual(rows[1][1], "option")
        self.assertTrue(texts[2].startswith("┃ › Priority"))
        self.assertEqual(rows[2][1], "selected")
        self.assertTrue(texts[3].startswith("┣"))
        self.assertEqual(rows[4], ("┃ Missing dates last." + " " * (len(texts[0]) - 22) + "┃", "note"))
        self.assertTrue(texts[-1].endswith(" Enter apply ━┛"))

    def test_shrinks_to_the_terminal_and_shortens_long_options(self):
        rows = menu_box("TITLE", ["x" * 100], 0, 30, hint="h" * 100)
        self.assertEqual({len(text) for text, _ in rows}, {30})
        self.assertIn("…", rows[1][0])
        self.assertEqual(rows[-3][1], "border")             # the long hint moves into a note row
        self.assertEqual(rows[-2][1], "note")
        self.assertTrue(rows[-1][0].startswith("┗━━"))


class MenuScreenTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.app = App(self.store, Path("/tmp"), demo=True)

    def run_keys(self, keys, action):
        self.app.screen = PromptScreen(keys, 32, 120)
        with patch.dict("os.environ", {"NO_COLOR": "1"}), patch("curses.curs_set"):
            result = action()
        return result, self.app.screen.frames

    def test_picker_draws_a_box_over_the_visible_dashboard(self):
        choice, frames = self.run_keys(("j", "\n"), lambda: self.app.choose("PICK ONE", ["1  First", "2  Second"]))
        self.assertEqual(choice, 1)
        first = "\n".join(frames[0])
        self.assertIn("┏━ PICK ONE ", first)
        self.assertIn("Tickets ", first)                  # the dashboard stays behind the box
        self.assertIn("› 1  First", first)
        self.assertIn("› 2  Second", "\n".join(frames[1]))

    def test_sort_menu_marks_the_current_sort(self):
        _, frames = self.run_keys(("\x1b",), self.app.choose_sort)
        screen = "\n".join(frames[0])
        self.assertIn("┏━ SORT TICKETS ", screen)
        line = next(row for row in frames[0] if "Attention" in row and "┃" in row)
        self.assertIn("✓", line)

    def test_search_filters_live_shows_the_count_and_esc_restores_the_old_query(self):
        total = len(self.app.visible())
        key = self.app.visible()[0].key
        _, frames = self.run_keys(tuple(key) + ("\x1b",), self.app.search)
        last = frames[-1]
        self.assertIn(f"Search: {key}", last[-1])
        self.assertIn(f"1 of {total}", last[-1])
        self.assertIn("Tickets 1", "\n".join(last))
        self.assertEqual(self.app.query, "")

    def test_search_enter_keeps_the_query(self):
        key = self.app.visible()[0].key
        self.run_keys(tuple(key) + ("\n",), self.app.search)
        self.assertEqual(self.app.query, key)
        self.assertEqual([t.key for t in self.app.visible()], [key])


if __name__ == "__main__":
    unittest.main()
