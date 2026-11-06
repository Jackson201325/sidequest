"""Keyboard rules through App.press, without a curses screen."""
import curses
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from core import Store
from tui import VIEWS, App


class KeyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.app = App(self.store, Path(folder.name), demo=True)
        self.rows = self.app.visible()
        self.assertGreater(len(self.rows), 2, "demo data must give the keys something to move through")

    def press(self, *keys):
        results = [self.app.press(key) for key in keys]
        return results[-1]

    def test_j_and_k_move_the_selection_and_reset_the_detail_scroll(self):
        self.app.preview_scroll = 4
        self.press("j")
        self.assertEqual((self.app.index, self.app.preview_scroll), (1, 0))
        self.press(curses.KEY_DOWN, "k")
        self.assertEqual(self.app.index, 1)
        self.press(curses.KEY_UP)
        self.assertEqual(self.app.index, 0)

    def test_j_and_k_scroll_details_when_the_detail_pane_has_focus(self):
        self.press("v", "j", "j")
        self.assertEqual((self.app.focus_pane, self.app.index, self.app.preview_scroll), ("preview", 0, 2))
        self.press("k", "k", "k")
        self.assertEqual(self.app.preview_scroll, 0)

    def test_G_goes_to_the_last_ticket_and_gg_back_to_the_first(self):
        self.press("G")
        self.assertEqual(self.app.selected().key, self.rows[-1].key)
        self.press("g", "g")
        self.assertEqual(self.app.index, 0)

    def test_page_keys_move_by_a_page_and_half_page_keys_scroll_details(self):
        from test_responsive import Screen
        self.app.screen = Screen(18, 80)
        self.press("v")
        view = self.app.viewport()
        self.assertEqual(view.list_rows, 2, "an 18-row terminal shows two list rows")
        self.press("h", "\x06")
        self.assertEqual(self.app.index, 2)
        self.press("\x02")
        self.assertEqual(self.app.index, 0)
        self.press("\x04")
        self.assertEqual(self.app.preview_scroll, max(1, view.detail_rows // 2))
        self.press("\x15", "\x15")
        self.assertEqual(self.app.preview_scroll, 0)

    def test_gl_jumps_to_the_next_ticket_that_needs_attention(self):
        attention = [i for i, t in enumerate(self.rows) if t.lane in ("Needs me", "Clarify") or t.age >= self.app.stale_days]
        self.assertTrue(attention, "demo data must contain a ticket that needs attention")
        self.app.index = (attention[0] - 1) % len(self.rows)
        self.press("g", "l")
        self.assertEqual(self.app.index, attention[0])

    def test_number_keys_choose_a_lane_and_reset_the_selection(self):
        self.app.index = 2
        self.press("2")
        self.assertEqual((self.app.view, self.app.index), (VIEWS[1], 0))
        self.press("1")
        self.assertEqual(self.app.view, "All")

    def test_h_l_and_enter_move_focus_and_escape_clears_search_and_focus(self):
        self.press("\n")
        self.assertEqual(self.app.focus_pane, "preview")
        self.press("h")
        self.assertEqual(self.app.focus_pane, "list")
        self.app.query, self.app.focus_pane, self.app.preview_scroll = "bulk", "preview", 3
        self.press("\x1b")
        self.assertEqual((self.app.query, self.app.focus_pane, self.app.preview_scroll), ("", "list", 0))

    def test_detail_tab_keys_switch_tab_and_focus_the_details(self):
        self.app.preview_scroll = 3
        self.press("p")
        self.assertEqual((self.app.detail_tab, self.app.focus_pane, self.app.preview_scroll), ("Plan", "preview", 0))
        self.press("u")
        self.assertEqual(self.app.detail_tab, "Standup")

    def test_search_prompt_sets_the_query_and_cancel_keeps_it(self):
        with patch.object(App, "prompt", return_value="bulk"):
            self.press("/")
        self.assertEqual((self.app.query, self.app.index), ("bulk", 0))
        with patch.object(App, "prompt", return_value=None):
            self.press("/")
        self.assertEqual(self.app.query, "bulk")

    def test_space_shows_the_menu_then_runs_the_chosen_action(self):
        before = self.app.message
        self.press(" ")
        self.assertTrue(self.app.message.startswith("Space → "))
        with patch.object(App, "action") as action:
            self.press("w")
        action.assert_called_once_with("w")
        self.assertEqual(self.app.message, before)

    def test_escape_after_space_restores_the_status_bar(self):
        before = self.app.message
        with patch.object(App, "action"):
            self.press(" ", "\x1b")
        self.assertEqual(self.app.message, before)

    def test_plus_minus_and_equals_resize_the_sections(self):
        with patch.object(App, "resize_sections") as resize:
            self.press("+", "-", "=")
        self.assertEqual([c.args[0] for c in resize.call_args_list], [1, -1, 0])

    def test_command_keys_call_their_actions(self):
        cases = {"r": "refresh", "e": "refresh_environments", "o": "choose_sort", "?": "help"}
        for key, method in cases.items():
            with self.subTest(key=key), patch.object(App, method) as called:
                self.press(key)
                called.assert_called_once()
        with patch.object(App, "jump") as jump:
            self.press("w")
        jump.assert_called_once_with(self.app.selected())

    def test_O_reverses_the_sort_order(self):
        descending = self.app.sort_descending
        self.press("O")
        self.assertEqual(self.app.sort_descending, not descending)

    def test_y_copies_the_standup_only_on_the_standup_tab(self):
        with patch.object(App, "copy_standup") as copy:
            self.press("y")
            copy.assert_not_called()
            self.press("u", "y")
            copy.assert_called_once()

    def test_a_resize_clears_the_screen_even_while_a_prefix_waits(self):
        class Screen:
            cleared = 0

            def clear(self):
                Screen.cleared += 1

            def getmaxyx(self):
                return 40, 120

            def timeout(self, value):
                pass
        self.app.screen = Screen()
        for prefix in (" ", "g"):
            with self.subTest(prefix=prefix), patch.object(App, "action") as action:
                Screen.cleared = 0
                self.press(prefix, curses.KEY_RESIZE)
                self.assertEqual(Screen.cleared, 1)
                self.assertEqual(self.app.pending, prefix, "the prefix still waits for its real key")
                self.press("\x1b")
                action.assert_called_once_with("\x1b") if prefix == " " else action.assert_not_called()

    def test_q_and_ctrl_q_quit_and_other_keys_continue(self):
        self.assertTrue(self.press("j"))
        self.assertFalse(self.press("q"))
        self.assertFalse(self.press("\x11"))

    def test_unknown_keys_change_nothing(self):
        state = (self.app.index, self.app.view, self.app.focus_pane, self.app.detail_tab, self.app.query)
        self.assertTrue(self.press("Z"))
        self.assertEqual(state, (self.app.index, self.app.view, self.app.focus_pane, self.app.detail_tab, self.app.query))

    def test_an_action_error_reaches_the_status_bar(self):
        with patch.object(App, "refresh", side_effect=OSError("collector missing")):
            self.assertTrue(self.press("r"))
        self.assertEqual(self.app.message, "collector missing")
        self.assertGreater(self.app.user_message_at, 0)


if __name__ == "__main__":
    unittest.main()


class EfficiencyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.app = App(self.store, Path(folder.name), demo=True)

    def test_the_loop_waits_longer_when_nothing_is_happening(self):
        self.assertEqual(self.app.wait_ms(), 250)
        cases = {"refreshing": lambda: setattr(self.app, "refreshing", True),
                 "a background job": lambda: self.app.jobs.update(heroku=("Loading", 0)),
                 "a waiting message": lambda: setattr(self.app, "deferred_message", "Refreshed"),
                 "a waiting prefix": lambda: setattr(self.app, "pending", " ")}
        for case, start in cases.items():
            with self.subTest(case=case):
                start()
                self.assertEqual(self.app.wait_ms(), 50)
                self.app.refreshing, self.app.jobs, self.app.deferred_message, self.app.pending = False, {}, None, ""

    def test_prompts_restore_the_current_wait_not_a_fixed_one(self):
        class Screen:
            def __init__(self):
                self.timeouts = []

            def timeout(self, value):
                self.timeouts.append(value)
        self.app.screen = Screen()
        self.app.blocking(lambda: None)
        self.assertEqual(self.app.screen.timeouts, [-1, 250])

    def test_a_key_and_its_draw_build_the_detail_tab_once(self):
        from test_responsive import Screen
        self.app.screen = Screen(40, 145)
        with patch.object(self.app.views, "rows", wraps=self.app.views.rows) as rows:
            self.app.press("j")
            self.app.draw()
        self.assertEqual(rows.call_count, 1)

    def test_a_background_result_after_a_key_is_drawn_fresh(self):
        from test_responsive import Screen
        self.app.screen = Screen(40, 145)
        self.app.press("j")
        self.app.events.put(("heroku_error", "Heroku: DNS lookup failed."))
        self.app.drain()
        with patch.object(self.app.views, "rows", wraps=self.app.views.rows) as rows:
            self.app.draw()
        self.assertEqual(rows.call_count, 1, "a stale detail view must not be reused after new evidence")
