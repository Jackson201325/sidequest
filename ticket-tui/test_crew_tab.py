"""AI mode (6) and the card's Agent line read each ticket's run.json; the dashboard never writes it."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import Store
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import runs
import layout
import tui


class CrewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(':memory:')
        self.addCleanup(self.store.close)
        self.app = tui.App(self.store, self.root, demo=True)
        self.ticket = self.app.selected()
        self.path = self.root / self.ticket.key / 'run.json'
        self.plans = patch.object(tui, 'PLANS', self.root)
        self.plans.start()
        self.addCleanup(self.plans.stop)

    def record(self, key, step, state, note='', at='2026-11-11T10:00:00+00:00'):
        return runs.update(self.root / key / 'run.json', key, step, state, note, at)

    def test_card_shows_the_worker_step_and_what_it_needs(self):
        self.assertFalse(any(line.startswith('Agent ') for line in self.app.summary_card(self.ticket)))
        self.record(self.ticket.key, 'implement', 'waiting', 'Q2: Which copy?')
        before = self.path.read_text()
        agent = [line for line in self.app.summary_card(self.ticket) if line.startswith('Agent ')]
        self.assertEqual(len(agent), 1)
        self.assertTrue(agent[0].startswith('Agent ● implement · waiting on you · '), agent[0])
        self.assertTrue(agent[0].endswith('Q2: Which copy?'))
        self.assertEqual(self.path.read_text(), before)

    def test_working_agents_move_waiting_ones_blink_and_finished_ones_stay_still(self):
        frames = lambda state: {runs.glyph(state, frame) for frame in range(10)}
        self.assertGreater(len(frames('working')), 3)
        self.assertEqual(frames('waiting'), {'●', '○'})
        self.assertEqual((frames('ready'), frames('failed')), ({'✓'}, {'✗'}))
        self.assertEqual(runs.track('qa-local', 'working', 0),
                         '✓ start  ✓ implement  ' + runs.glyph('working', 0) + ' qa-local  · ship-check')

    def test_pipeline_row_shows_done_stages_and_a_moving_arrow_on_the_working_one(self):
        record = {'key': 'DEMO-1', 'step': 'implement', 'state': 'working', 'note': '', 'updated': ''}
        first = layout.pipeline_cells(record, 0, 12)
        self.assertEqual(len(first), 4)
        self.assertTrue(first[0].startswith('✓━'))
        self.assertTrue(first[1].startswith(runs.glyph('working', 0)))
        self.assertIn('▶', first[1])
        self.assertEqual(first[2].strip(), '·')
        self.assertNotEqual(first[1], layout.pipeline_cells(record, 3, 12)[1])
        self.assertTrue(all(len(cell) == 12 for cell in first))
        ready = dict(record, step='ship-check', state='ready')
        self.assertTrue(all(cell.startswith('✓') for cell in layout.pipeline_cells(ready, 0, 12)))
        self.assertEqual([c.strip() for c in layout.pipeline_cells(None, 0, 12)], ['·'] * 4)

    def test_ai_mode_lists_every_ticket_as_a_pipeline_the_persons_turn_first(self):
        keys = [t.key for t in self.app.tickets if t.lane != 'Done']
        self.record(keys[-1], 'implement', 'waiting', 'Q1: Copy?')
        self.record('OTHER-7', 'qa-local', 'working')
        self.app.press('6')
        self.assertEqual(self.app.view, 'AI')
        shown = [t.key for t in self.app.visible()]
        self.assertEqual(shown[:2], [keys[-1], 'OTHER-7'])
        self.assertEqual(sorted(shown[2:]), sorted(keys[:-1]))
        self.assertTrue(self.app.animating())
        self.app.press('1')
        self.assertNotIn('OTHER-7', [t.key for t in self.app.visible()])

    def test_ai_mode_details_show_one_tickets_whole_agent_story(self):
        key = self.ticket.key
        self.record(key, 'implement', 'queued', 'Dispatched by sidequest crew')
        self.record(key, 'implement', 'working', at='2026-11-11T10:01:00+00:00')
        self.record(key, 'qa-local', 'waiting', 'Q1: Staging data?', at='2026-11-11T10:20:00+00:00')
        self.app.press('6')
        while self.app.selected().key != key:
            self.app.press('j')
        text = '\n'.join(self.app.details(self.app.selected()))
        self.assertRegex(text, '✓ start  ✓ implement  [●○] qa-local  · ship-check')
        self.assertIn('→ Q1: Staging data?', text)
        self.assertIn('HISTORY', text)
        self.assertLess(text.index('qa-local · waiting on you'), text.index('implement · queued'))
        self.app.press('j')
        other = self.app.selected().key
        self.assertIn('sidequest crew ' + other, '\n'.join(self.app.details(self.app.selected())))

    def space(self, key, choice=0, environ=None):
        calls = []

        def fake(args):
            calls.append(list(args))
            return 'TRD: worker started'
        with patch.object(tui.App, 'choose', return_value=choice) as choose, patch.object(tui, 'run_crew', fake), \
                patch.dict('os.environ', environ if environ is not None else {'TMUX': '/tmp/tmux'}, clear=environ == {}):
            self.app.press(' ')
            self.app.press(key)
            deadline = __import__('time').monotonic() + 3
            while self.app.jobs and __import__('time').monotonic() < deadline:
                self.app.drain()
            self.app.drain()
        return calls, choose

    def test_space_c_confirms_then_starts_a_worker_on_the_selected_ticket(self):
        self.app.demo = False
        self.ticket.worktree = '/w/' + self.ticket.key
        key = self.ticket.key
        calls, choose = self.space('c')
        title, options = choose.call_args[0][:2]
        self.assertIn(key, title)
        self.assertTrue(options[0].startswith('Start a worker'), options)
        self.assertEqual(calls, [[key]])
        self.assertIn('TRD: worker started', (self.app.message, self.app.deferred_message))

    def test_space_c_offers_a_restart_when_a_worker_is_recorded_as_running(self):
        self.app.demo = False
        self.ticket.worktree = '/w/' + self.ticket.key
        self.record(self.ticket.key, 'implement', 'working')
        calls, choose = self.space('c')
        self.assertTrue(choose.call_args[0][1][0].startswith('Restart'), choose.call_args[0][1])
        self.assertEqual(calls, [[self.ticket.key, '--again']])

    def test_space_c_without_a_worktree_creates_it_then_starts_the_worker(self):
        self.app.demo = False
        key = self.ticket.key
        prepared = []

        class Flow:
            def prepare(self, *args, **kwargs):
                prepared.append((args, kwargs))
                return {'path': '/w/' + key}
        with patch.object(tui.config, 'workspace_repository', return_value='/repo'), \
                patch.object(self.app, 'workflow_factory', Flow), patch.object(tui, 'worktrees', lambda: {}):
            calls, choose = self.space('c')
        self.assertTrue(choose.call_args[0][1][0].startswith('Create the worktree, then start a worker'))
        self.assertEqual(prepared[0][0][0], key)
        self.assertTrue(prepared[0][1].get('apply'))
        self.assertEqual(calls, [[key]])

    def test_space_c_cancelled_or_in_demo_starts_nothing(self):
        self.app.demo = False
        self.ticket.worktree = '/w/' + self.ticket.key
        calls, _ = self.space('c', choice=None)
        self.assertEqual(calls, [])
        self.assertIn('cancelled', self.app.message)
        self.app.demo = True
        calls, choose = self.space('c')
        self.assertEqual((calls, choose.called), ([], False))
        self.assertIn('Demo', self.app.message)

    def test_space_shift_c_opens_the_manager_window_or_hands_over_this_terminal(self):
        self.app.demo = False
        calls, _ = self.space('C')
        self.assertEqual(calls, [[]])
        calls, _ = self.space('C', environ={})
        self.assertEqual(calls, [])
        action = self.app.foreground_target
        self.assertTrue(action['argv'][-1].endswith('sidequest-crew.py'), action)
        self.assertIn(('c', 'crew worker'), [k for _, keys in tui.SPACE_MENU for k in keys])
        self.assertIn(('C', 'crew manager'), [k for _, keys in tui.SPACE_MENU for k in keys])

    def test_crew_is_no_longer_a_ticket_tab(self):
        self.assertNotIn('t', tui.TAB_KEYS)


if __name__ == '__main__':
    unittest.main()
