"""AI mode (6) and the card's Agent line read each ticket's run.json; the dashboard never writes it."""
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from core import Store
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import crew, runs
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
        self.app.workflow_factory = lambda: self.fail('a test reached the real workspace workflow')
        self.ticket = self.app.selected()
        self.path = self.root / self.ticket.key / 'run.json'
        self.plans = patch.object(tui, 'PLANS', self.root)
        self.plans.start()
        self.addCleanup(self.plans.stop)

    def record(self, key, step, state, note='', at='2026-11-11T10:00:00+00:00'):
        return runs.update(self.root / key / 'run.json', key, step, state, note, at)

    def test_card_shows_the_worker_step_and_what_it_needs(self):
        self.assertFalse(any(line.startswith('Agent ') for line in self.app.summary_card(self.ticket)))
        self.ticket.prs = []
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
                         '✓ start  ✓ implement  ' + runs.glyph('working', 0) + ' qa-local  · ship-check  · challenge  · qa-review')

    def test_pipeline_row_shows_done_stages_and_a_moving_arrow_on_the_working_one(self):
        record = {'key': 'DEMO-1', 'step': 'implement', 'state': 'working', 'note': '', 'updated': ''}
        first = layout.pipeline_cells(record, 0, 12)
        self.assertEqual(len(first), 6)
        self.assertTrue(first[0].startswith('✓━'))
        self.assertTrue(first[1].startswith(runs.glyph('working', 0)))
        self.assertIn('▶', first[1])
        self.assertEqual(first[2].strip(), '·')
        self.assertNotEqual(first[1], layout.pipeline_cells(record, 3, 12)[1])
        self.assertTrue(all(len(cell) == 12 for cell in first))
        ready = dict(record, step='ship-check', state='ready')
        cells = layout.pipeline_cells(ready, 0, 12)
        self.assertTrue(all(cell.startswith('✓') for cell in cells[:4]))
        self.assertEqual([c.strip() for c in cells[4:]], ['·', '·'])
        reviewed = dict(record, step='qa-review', state='ready')
        self.assertTrue(all(cell.startswith('✓') for cell in layout.pipeline_cells(reviewed, 0, 12)))
        self.assertEqual([c.strip() for c in layout.pipeline_cells(None, 0, 12)], ['·'] * 6)

    def test_an_open_pr_moves_the_pipeline_past_ship_check(self):
        record = {'key': self.ticket.key, 'step': 'ship-check', 'state': 'waiting', 'note': '', 'updated': ''}
        self.ticket.prs = [{'number': 12}]
        _, rest = layout.pipeline_row(self.ticket, record, 0, 160, None)
        self.assertEqual(rest.count('✓'), 5)
        self.assertIn('●', rest)
        self.ticket.prs = []
        _, rest = layout.pipeline_row(self.ticket, record, 0, 160, None)
        self.assertEqual(rest.count('✓'), 3)

    def test_a_long_note_keeps_the_title_and_shows_only_its_first_clause(self):
        self.ticket.prs, self.ticket.court = [], 'me'
        self.ticket.title = 'Change the checkout copy for annual plans on the pricing page'
        note = 'rspec failed in billing/invoice_spec.rb after the rounding change; see the log for the stack trace'
        record = {'key': self.ticket.key, 'step': 'implement', 'state': 'failed', 'note': note, 'updated': ''}
        for width in (76, 140, 200):
            _, rest = layout.pipeline_row(self.ticket, record, 0, width, None)
            with self.subTest(width=width):
                self.assertLessEqual(len(rest), width - 1)
                self.assertIn('Change the', rest)
                self.assertRegex(rest, r'  → rspec f\S*.*…$')
                self.assertNotIn('stack trace', rest)
                self.assertLess(rest.index('Change the'), rest.index('→'))
        _, rest = layout.pipeline_row(self.ticket, record, 0, 120, None)
        self.assertRegex(rest, r'→ rspec f\S*…$')
        _, rest = layout.pipeline_row(self.ticket, dict(record, note=runs.HOOK_NOTES['stop'], state='waiting'), 0, 200, None)
        self.assertTrue(rest.endswith('→ ended its turn'))
        _, rest = layout.pipeline_row(self.ticket, dict(record, step='qa-review', state='ready'), 0, 200, None)
        self.assertNotIn('→', rest)
        self.assertTrue(rest.rstrip().endswith('pricing page'))

    def test_the_agent_column_always_ends_before_the_title_and_the_reasons_line_up(self):
        from datetime import datetime, timezone
        from core import Ticket
        clock = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        long_owner = Ticket('APP-1', title='Fix slow order searches', court='them',
                            assignee='Sergio David Perdomo Rivera', assigned_me=False)
        record = {'key': 'APP-1', 'step': 'qa-review', 'state': 'ready', 'note': '',
                  'updated': '2026-11-13T10:00:00+00:00'}
        for width in (76, 200):
            header = layout.pipeline_header(width)
            _, rest = layout.pipeline_row(long_owner, record, 0, width, clock)
            with self.subTest(width=width):
                self.assertEqual(rest.index('Fix slow'), header.index('TITLE'))
                self.assertTrue(rest[:rest.index('Fix slow')].endswith(' 2h  '))
        mine = [Ticket('APP-2', title='Create Calendar & Tasks', court='me'),
                Ticket('APP-3', title='Build In-House Support Ticketing System to Replace Zendesk', court='me')]
        waiting = dict(record, step='implement', state='waiting', note='Q1: build in-house or adopt open source?')
        for width, ticket in ((w, t) for w in (90, 140, 200) for t in mine):
            header = layout.pipeline_header(width)
            _, rest = layout.pipeline_row(ticket, waiting, 0, width, clock)
            with self.subTest(width=width, ticket=ticket.key):
                self.assertEqual(rest.index('→'), header.index('→'))
                self.assertEqual(rest.index(ticket.title[:10]), header.index('TITLE'))

    def test_the_age_has_its_own_column_after_the_agent(self):
        from datetime import datetime, timezone
        from core import Ticket
        clock = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
        rows = [(Ticket('APP-1', title='Totals', court='them', assignee='Sergio David Perdomo Rivera',
                        assigned_me=False), 'ready', '2026-11-13T10:00:00+00:00', '2h'),
                (Ticket('APP-2', title='Totals', court='me'), 'waiting', '2026-11-11T09:00:00+00:00', '2d'),
                (Ticket('APP-3', title='Totals', court='me'), 'failed', '2026-11-11T17:00:00+00:00', '43h')]
        for width in (90, 200):
            header = layout.pipeline_header(width)
            age_end = header.index(' AGE ') + len(' AGE')
            for ticket, state, updated, age in rows:
                record = {'key': ticket.key, 'step': 'qa-review', 'state': state, 'note': 'x', 'updated': updated}
                _, rest = layout.pipeline_row(ticket, record, 0, width, clock)
                with self.subTest(width=width, ticket=ticket.key):
                    self.assertEqual(rest[age_end - len(age) - 1:age_end], ' ' + age)
                    self.assertEqual(rest[age_end:age_end + 2], '  ')
                    self.assertNotIn(age, rest[:age_end - len(age) - 1].split()[-1:])

    def test_a_stopped_pipeline_row_says_why_it_stopped(self):
        self.ticket.prs, self.ticket.court = [], 'me'
        record = {'key': self.ticket.key, 'step': 'implement', 'state': 'waiting', 'note': 'Q2: Which copy?',
                  'updated': ''}
        _, rest = layout.pipeline_row(self.ticket, record, 0, 200, None)
        self.assertRegex(rest, re.escape(self.ticket.title) + r' +→ Q2: Which copy\?$')
        _, rest = layout.pipeline_row(self.ticket, dict(record, state='failed', note=''), 0, 200, None)
        self.assertIn('→ failed without a note', rest)
        _, rest = layout.pipeline_row(self.ticket, dict(record, state='working'), 0, 200, None)
        self.assertNotIn('→', rest)
        self.ticket.prs = [{'number': 12}]
        _, rest = layout.pipeline_row(self.ticket, record, 0, 200, None)
        self.assertIn('→ PR open', rest)
        self.assertNotIn('Which copy', rest)
        self.assertIn('REASON', layout.pipeline_header(200))

    def test_a_ready_worker_on_a_ticket_with_someone_else_names_who_has_it(self):
        self.record(self.ticket.key, 'ship-check', 'ready', 'Clean')
        record = runs.read(self.path)
        self.ticket.court, self.ticket.assignee, self.ticket.prs = 'them', 'Eddie Sitt', []
        self.ticket.assigned_me = False
        self.assertEqual(layout.crew_label(self.ticket, record), 'with Eddie Sitt')
        agent = [line for line in self.app.summary_card(self.ticket) if line.startswith('Agent ')][0]
        self.assertIn('ship-check · with Eddie Sitt · ', agent)
        self.assertNotIn('ready for you', agent)
        self.ticket.court = 'done'
        self.assertEqual(layout.crew_label(self.ticket, record), 'done in Jira')
        self.ticket.court = 'me'
        self.assertEqual(layout.crew_label(self.ticket, record), 'ready for you')
        self.assertIsNone(layout.handed_off(self.ticket, dict(record, state='waiting')))

    def test_a_waiting_worker_is_not_your_turn_when_jira_or_the_pr_says_someone_else_has_it(self):
        record = {'key': self.ticket.key, 'step': 'qa-review', 'state': 'waiting', 'note': '', 'updated': ''}
        self.ticket.court, self.ticket.assignee, self.ticket.status = 'them', 'Eddie Sitt', 'In Code Review'
        self.ticket.assigned_me = False
        self.assertEqual(layout.crew_label(self.ticket, record), 'with Eddie Sitt')
        self.ticket.court = 'unknown'
        self.assertEqual(layout.crew_label(self.ticket, record), 'Jira: In Code Review')
        self.ticket.status = 'In Progress'
        self.assertEqual(layout.crew_label(self.ticket, record), 'waiting on you')
        self.ticket.court, self.ticket.status = 'me', 'In Code Review'
        self.assertEqual(layout.crew_label(self.ticket, record), 'waiting on you')
        self.ticket.court = 'them'
        self.assertEqual(layout.crew_label(self.ticket, dict(record, state='working')), 'working')
        self.assertEqual(layout.crew_label(self.ticket, dict(record, state='failed')), 'failed')

    def test_a_handed_off_waiting_row_stops_blinking(self):
        record = {'key': self.ticket.key, 'step': 'implement', 'state': 'waiting', 'note': '', 'updated': ''}
        self.ticket.court, self.ticket.assignee = 'them', 'Eddie Sitt'
        rows = {layout.pipeline_row(self.ticket, record, frame, 160, None) for frame in range(8)}
        self.assertEqual(len(rows), 1, rows)
        self.ticket.court = 'me'
        rows = {layout.pipeline_row(self.ticket, record, frame, 160, None) for frame in range(8)}
        self.assertGreater(len(rows), 1)

    def test_ai_mode_puts_handed_off_tickets_after_working_ones_and_does_not_count_them(self):
        open_tickets = [t for t in self.app.tickets if t.lane != 'Done' and t.status != 'Blocked']
        held, busy = open_tickets[0], open_tickets[1]
        held.court, held.assignee, held.prs = 'them', 'Eddie Sitt', []
        self.record(held.key, 'implement', 'waiting')
        self.record(busy.key, 'implement', 'working')
        self.app.press('6')
        shown = [t.key for t in self.app.visible()]
        self.assertLess(shown.index(busy.key), shown.index(held.key))
        self.assertEqual(self.app.ai_needs_you(), 0)

    def test_ai_mode_lists_every_ticket_as_a_pipeline_the_persons_turn_first(self):
        keys = [t.key for t in self.app.tickets if t.lane != 'Done' and t.status != 'Blocked']
        mine = next(t.key for t in self.app.tickets if t.court == 'me')
        self.record(mine, 'implement', 'waiting', 'Q1: Copy?')
        self.record('OTHER-7', 'qa-local', 'working')
        self.app.press('6')
        self.assertEqual(self.app.view, 'AI')
        shown = [t.key for t in self.app.visible()]
        self.assertEqual(shown[:2], [mine, 'OTHER-7'])
        self.assertEqual(sorted(shown[2:]), sorted(k for k in keys if k != mine))
        self.assertTrue(self.app.animating())
        self.app.press('1')
        self.assertNotIn('OTHER-7', [t.key for t in self.app.visible()])

    def test_ai_mode_hides_blocked_tickets_even_with_a_worker(self):
        blocked = next(t for t in self.app.tickets if t.lane != 'Done')
        blocked.status = 'Blocked'
        self.record(blocked.key, 'implement', 'waiting')
        self.app.press('6')
        shown = [t.key for t in self.app.visible()]
        self.assertNotIn(blocked.key, shown)
        self.assertTrue(shown)

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
        self.record(key, 'qa-local', 'waiting', at='2026-11-11T10:30:00+00:00')
        self.assertIn('→ waiting without a note; open the worker (w)', '\n'.join(self.app.details(self.app.selected())))
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

    def test_space_c_offers_start_anyway_after_jira_said_the_ticket_is_with_someone_else(self):
        self.app.demo = False
        self.ticket.worktree = '/w/' + self.ticket.key
        key = self.ticket.key
        skip = f'skip {key}: assigned to Ana in Jira; use --again to start it anyway'
        with patch.object(tui, 'run_crew', lambda args: skip), patch.dict('os.environ', {'TMUX': '/tmp/tmux'}):
            self.app.press(' ')
            with patch.object(tui.App, 'choose', return_value=0):
                self.app.press('c')
            deadline = __import__('time').monotonic() + 3
            while self.app.jobs and __import__('time').monotonic() < deadline:
                self.app.drain()
            self.app.drain()
        calls, choose = self.space('c', choice=1)
        self.assertTrue(choose.call_args[0][1][0].startswith('Start anyway'))
        self.assertEqual(calls, [])
        calls, choose = self.space('c')
        option = choose.call_args[0][1][0]
        self.assertTrue(option.startswith('Start anyway'), option)
        self.assertIn('assigned to Ana in Jira', option)
        self.assertEqual(calls, [[key, '--again']])
        calls, choose = self.space('c')
        self.assertTrue(choose.call_args[0][1][0].startswith('Start a worker'))
        self.assertEqual(calls, [[key]])

    def test_a_slow_crew_command_reports_a_timeout_instead_of_raising(self):
        def slow(*args, **kwargs):
            raise tui.subprocess.TimeoutExpired(args[0], kwargs.get('timeout'))
        with patch.object(tui.subprocess, 'run', slow):
            result = tui.run_crew(['DEMO-1'])
        self.assertIn('timed out', result)
        self.assertIn('sidequest crew --status', result)

    def test_the_agent_line_with_an_open_pr_shows_the_step_the_list_shows(self):
        self.record(self.ticket.key, 'ship-check', 'ready', 'Clean')
        self.ticket.court, self.ticket.prs = 'me', [{'number': 7}]
        agent = [line for line in self.app.summary_card(self.ticket) if line.startswith('Agent ')][0]
        self.assertIn('qa-review · waiting on you', agent)

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

    def test_space_shift_c_offers_the_last_manager_chat_or_a_new_one(self):
        self.app.demo = False
        folder = tui.qa.tickets_dir()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / crew.MANAGER_SESSION).write_text('{"session_id": "id-1"}')
        self.addCleanup((folder / crew.MANAGER_SESSION).unlink)
        calls, choose = self.space('C', choice=0)
        self.assertEqual(calls, [['--continue']])
        self.assertIn('Continue the last manager chat', choose.call_args[0][1][0])
        self.assertEqual(self.space('C', choice=1)[0], [['--new']])
        self.assertEqual(self.space('C', choice=2)[0], [])
        calls, _ = self.space('C', choice=1, environ={})
        self.assertEqual(self.app.foreground_target['argv'][-1], '--new')

    def test_space_shift_m_asks_ticket_or_general_then_opens_the_meeting_pane(self):
        self.app.demo = False
        key = self.ticket.key
        with patch.object(tui, 'run_meeting', lambda args: calls.append(args) or 'Opened meeting in a pane below'):
            calls = []
            _, choose = self.space('M', choice=0)
            title, options = choose.call_args[0][:2]
            self.assertIn(key, options[0])
            self.assertTrue(options[1].startswith('General meeting'), options)
            self.assertEqual(calls, [[key]])
            calls = []
            self.space('M', choice=1)
            self.assertEqual(calls, [[]])
            calls = []
            self.space('M', choice=None)
            self.assertEqual(calls, [])
            self.assertIn('cancelled', self.app.message)
            self.space('M', environ={})
            self.assertEqual(calls, [])
        action = self.app.foreground_target
        self.assertEqual(action['argv'][-3:], [str(tui.MEETING), '--here', key])
        self.assertIn(('M', 'meeting'), [k for _, keys in tui.SPACE_MENU for k in keys])
        self.app.demo, self.app.foreground_target = True, None
        self.space('M')
        self.assertIsNone(self.app.foreground_target)

    def test_crew_is_no_longer_a_ticket_tab(self):
        self.assertNotIn('t', tui.TAB_KEYS)


if __name__ == '__main__':
    unittest.main()
