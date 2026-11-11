"""Colour tokens and the short footer (redesign phase 1, specs/tui-redesign-inbox.md)."""
import curses
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from core import Store
from layout import LANE_TOKEN, TOKENS
from test_responsive import KeyScreen, Screen
from tui import App


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.app = App(self.store, Path("/tmp"), demo=True)
        self.app.screen = Screen(32, 145)

    def tearDown(self):
        self.store.close()

    def colours(self, no_color=False):
        """Run setup_colors with fake curses; return {style value: foreground colour}."""
        pairs, styles = {}, {}
        env = {"NO_COLOR": "1"} if no_color else {}
        with patch.dict(os.environ, env), patch("curses.has_colors", return_value=True), \
                patch("curses.start_color"), patch("curses.use_default_colors"), \
                patch("curses.init_pair", side_effect=lambda i, fg, bg: pairs.__setitem__(i, fg)), \
                patch("curses.color_pair", side_effect=lambda i: i << 8):
            if not no_color:
                os.environ.pop("NO_COLOR", None)
            self.app.styles = styles
            self.app.setup_colors()
        return {i << 8: fg for i, fg in pairs.items()}

    def test_tokens_are_named_by_meaning(self):
        self.assertEqual(set(TOKENS), {"accent", "you", "unclear", "waiting", "good", "bad", "info", "agent", "aging"})
        self.assertEqual(LANE_TOKEN["Needs me"], "you")
        self.assertEqual(LANE_TOKEN["Waiting"], "waiting")
        self.assertEqual(LANE_TOKEN["Clarify"], "unclear")

    def test_lanes_use_token_colours(self):
        fg = self.colours()
        style = self.app.style
        self.assertEqual(fg[style("Needs me")], curses.COLOR_YELLOW)
        self.assertEqual(fg[style("Clarify")], curses.COLOR_MAGENTA)
        self.assertEqual(style("Waiting"), curses.A_DIM)
        self.assertEqual(fg[style("bad")], curses.COLOR_RED)
        self.assertEqual(fg[style("good")], curses.COLOR_GREEN)
        self.assertEqual(fg[style("accent")], curses.COLOR_CYAN)
        self.assertEqual(fg[style("In Dev")], curses.COLOR_BLUE)

    def test_no_color_keeps_plain_attributes(self):
        self.colours(no_color=True)
        for name in ("Needs me", "Clarify", "bad", "accent"):
            self.assertEqual(self.app.style(name), 0)

    def test_footer_shows_five_keys(self):
        for width in (145, 64):
            self.app.screen = Screen(32, width)
            self.app.draw()
            footer = " ".join(self.app.screen.lines[-2].split())
            self.assertEqual(footer, "j/k move ⏎ inspect Space actions / search ? help")

    def test_footer_says_scroll_while_the_details_have_focus(self):
        self.app.press("l")
        self.app.draw()
        self.assertIn("j/k scroll", " ".join(self.app.screen.lines[-2].split()))

    def test_help_keeps_the_keys_the_footer_dropped(self):
        self.app.screen = KeyScreen(["q"], 60, 145)
        self.app.help()
        text = "\n".join(self.app.screen.lines)
        for hint in ("h / l", "1..5", "6 ", "w / gw", "r refresh", "o / O", "+ / -", "q / Ctrl-q quit"):
            self.assertIn(hint, text)


if __name__ == "__main__":
    unittest.main()
