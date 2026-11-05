"""Visible queue/detail layout at the supported terminal sizes."""
import unittest
from unittest.mock import patch
from pathlib import Path

from core import Store
from tui import App


class Screen:
    def __init__(self, height=24, width=80):
        self.height, self.width = height, width
        self.erase()

    def getmaxyx(self):
        return self.height, self.width

    def erase(self):
        self.cells = [[" "] * self.width for _ in range(self.height)]

    def addnstr(self, y, x, text, limit, attr):
        for offset, char in enumerate(text[:limit]):
            self.cells[y][x + offset] = char

    def refresh(self):
        pass

    @property
    def lines(self):
        return ["".join(row) for row in self.cells]


class KeyScreen(Screen):
    def __init__(self, keys, height=24, width=80):
        super().__init__(height, width)
        self.keys = iter(keys)
        self.frames = []

    def keypad(self, enabled):
        pass

    def timeout(self, milliseconds):
        pass

    def get_wch(self):
        self.frames.append(self.lines)
        return next(self.keys)


class ResponsiveTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.app = App(self.store, Path("/tmp"), demo=True)
        self.app.screen = Screen()

    def tearDown(self):
        self.store.close()

    def test_narrow_terminal_stacks_list_and_details_and_preserves_focus(self):
        app = self.app
        for focus in ("list", "preview"):
            with self.subTest(focus=focus):
                app.focus_pane = focus
                app.draw()
                lines = app.screen.lines
                list_top = next(i for i, line in enumerate(lines) if "Tickets " in line)
                preview_top = next((i for i, line in enumerate(lines) if "DEMO-901 · Validate bulk request quantities" in line), None)
                self.assertIsNotNone(preview_top, "The selected ticket details must remain visible below the list")
                self.assertGreater(preview_top, list_top + 3)
                self.assertIn("KEY", lines[list_top + 1])
                self.assertIn("DEMO-901", lines[list_top + 2])
                self.assertIn("Activity", lines[preview_top + 1])
                self.assertEqual(lines[list_top][0], "┏" if focus == "list" else "╭")
                self.assertEqual(lines[preview_top][0], "┏" if focus == "preview" else "╭")
                list_bottom = next(i for i in range(list_top + 1, preview_top) if lines[i].startswith(("┗", "╰")))
                self.assertLess(list_bottom - list_top, app.screen.height - 3 - preview_top)

    def test_resize_keeps_selection_visible_and_clamps_detail_scroll(self):
        app = self.app
        app.index = len(app.visible()) - 1
        selected = app.selected().key
        app.preview_scroll = 100000
        for height, width in ((32, 145), (24, 80), (18, 64), (12, 80), (24, 109), (24, 110), (24, 80)):
            with self.subTest(height=height, width=width):
                app.focus_pane = "preview"
                app.screen = Screen(height, width)
                app.draw()
                self.assertEqual(app.selected().key, selected)
                self.assertLess(app.preview_scroll, 100000)
                self.assertGreaterEqual(app.preview_scroll, 0)
                lines = app.screen.lines
                if height >= 18:
                    self.assertIn("Tickets ", lines[1])
                    self.assertTrue(any(selected + " · " in line for line in lines[5:height - 2]))
                else:
                    self.assertNotIn("Tickets ", "\n".join(lines))
                    self.assertIn(selected, lines[1])
                app.focus_pane = "list"
                app.draw()
                lines = app.screen.lines
                list_bottom = next(i for i in range(2, height - 2) if lines[i].startswith("┗"))
                self.assertTrue(any(selected in line for line in lines[3:list_bottom]))

    def test_empty_narrow_layout_keeps_both_panels_and_footer_separate(self):
        app = self.app
        app.query = "no-matching-ticket"
        app.draw()
        lines = app.screen.lines
        self.assertTrue(any("No matching tickets" in line for line in lines))
        self.assertTrue(any("No ticket" in line for line in lines))
        self.assertEqual(lines[0][0:10].strip(), "Sidequest")
        self.assertFalse(lines[-2].startswith(("┏", "╭", "┗", "╰")))
        self.assertIn("Space:", lines[-1])

    def test_half_page_scroll_uses_the_stacked_detail_viewport(self):
        class InputScreen(Screen):
            def __init__(self):
                super().__init__()
                self.keys = iter(("l", "\x04", "q"))
                self.frames = []

            def keypad(self, enabled):
                pass

            def timeout(self, milliseconds):
                pass

            def get_wch(self):
                self.frames.append(self.lines)
                return next(self.keys)

        self.app.detail_tab = "Overview"
        screen = InputScreen()
        with patch.dict("os.environ", {"NO_COLOR": "1"}), patch("curses.curs_set"), patch("curses.set_escdelay"):
            self.app.loop(screen)
        # At 80x24, the 14-row detail pane has seven content rows: half a page is three.
        before, after = screen.frames[1:3]
        self.assertEqual(after[14].strip("┃│ "), before[17].strip("┃│ "))

    def test_wide_terminal_also_puts_details_underneath_tickets(self):
        self.app.screen = Screen(32, 145)
        self.app.draw()
        lines = self.app.screen.lines
        self.assertIn("Tickets ", lines[1])
        preview_top = next(i for i, line in enumerate(lines) if "DEMO-901 · Validate bulk request quantities" in line)
        self.assertGreater(preview_top, 4)
        self.assertTrue(lines[preview_top].startswith("╭"))

    def test_plus_minus_move_the_section_divider_and_equals_resets_it(self):
        screen = KeyScreen(("+", "-", "+", "=", "q"))
        selected = self.app.selected().key
        with patch.dict("os.environ", {"NO_COLOR": "1"}), patch("curses.curs_set"), patch("curses.set_escdelay"):
            self.app.loop(screen)
        bottoms = [next(i for i, line in enumerate(frame) if line.startswith("┗")) for frame in screen.frames]
        self.assertEqual(bottoms, [6, 7, 6, 7, 6])
        self.assertEqual(self.app.selected().key, selected)

    def test_section_size_is_remembered_when_the_queue_reopens(self):
        screen = KeyScreen(("+", "q"))
        with patch.dict("os.environ", {"NO_COLOR": "1"}), patch("curses.curs_set"), patch("curses.set_escdelay"):
            self.app.loop(screen)
        reopened = App(self.store, Path("/tmp"), demo=True)
        reopened.screen = Screen()
        reopened.draw()
        bottom = next(i for i, line in enumerate(reopened.screen.lines) if line.startswith("┗"))
        self.assertEqual(bottom, 7)

    def test_repeated_resizing_keeps_both_sections_usable(self):
        for height, width in ((18, 64), (24, 80), (32, 145)):
            with self.subTest(height=height, width=width):
                screen = KeyScreen((*(["+"] * 50), *(["-"] * 50), "q"), height, width)
                with patch.dict("os.environ", {"NO_COLOR": "1"}), patch("curses.curs_set"), patch("curses.set_escdelay"):
                    self.app.loop(screen)
                for lines in screen.frames:
                    list_bottom = next(i for i, line in enumerate(lines) if line.startswith("┗"))
                    preview_top = next(i for i, line in enumerate(lines) if "DEMO-901 · Validate bulk request quantities" in line)
                    self.assertGreaterEqual(list_bottom, 5)
                    self.assertGreaterEqual(height - 2 - preview_top, 8)
