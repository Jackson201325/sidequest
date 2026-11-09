"""Questions tab: read-only view of the ticket's decision record (the ticket folder's questions.md)."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import Store
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import questions
import tui


class QuestionsTabTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(':memory:')
        self.addCleanup(self.store.close)
        self.app = tui.App(self.store, self.root, demo=True)
        self.ticket = self.app.selected()
        self.path = self.root / self.ticket.key / 'questions.md'
        self.plans = patch.object(tui, 'PLANS', self.root)
        self.plans.start()
        self.addCleanup(self.plans.stop)

    def view(self, name='Questions'):
        self.app.detail_tab = name
        return '\n'.join(self.app.details(self.ticket))

    def test_empty_tab_explains_where_the_record_comes_from(self):
        text = self.view()
        self.assertIn('No questions logged yet', text)
        self.assertIn('sidequest-data questions', text)

    def test_record_shows_questions_to_ask_first_and_full_evidence_for_answers(self):
        key = self.ticket.key
        questions.add(self.path, key, 'Should archived rewards be exported?', '2026-11-06',
                      'The ticket does not say.', 'sidequest-start')
        questions.add(self.path, key, 'Which copy for the button?', '2026-11-06')
        questions.add(self.path, key, 'Does QA need staging data?', '2026-11-06')
        questions.asked(self.path, 'Q1', '2026-11-06', 'Alex', 'Jira comment')
        questions.answer(self.path, 'Q1', 'Only active rewards.', '2026-11-07', 'Alex', 'Slack',
                         'Filter archived rewards out of the export.')
        questions.asked(self.path, 'Q3', '2026-11-07', 'Sam', 'Slack')
        before = self.path.read_text()
        text = self.view()
        self.assertIn('1 not asked yet · 1 waiting · 1 answered', text)
        self.assertLess(text.index('NOT ASKED YET'), text.index('ASKED, WAITING'))
        self.assertLess(text.index('ASKED, WAITING'), text.index('ANSWERED'))
        self.assertIn('Why: The ticket does not say.', text)
        self.assertIn('Asked 2026-11-06 to Alex via Jira comment', text)
        self.assertIn('→ Answer 2026-11-07 from Alex via Slack: Only active rewards.', text)
        self.assertIn('✓ Decision 2026-11-07: Filter archived rewards out of the export.', text)
        self.assertEqual(self.app.open_question_count(self.ticket), 2)
        self.assertIn('Unanswered questions: 2 (c)', self.view('Overview'))
        self.assertEqual(self.path.read_text(), before)

    def test_view_follows_changes_written_by_the_command(self):
        questions.add(self.path, self.ticket.key, 'Is the header fixed?', '2026-11-06')
        self.assertIn('1 not asked yet', self.view())
        questions.answer(self.path, 'Q1', 'Yes.', '2026-11-06')
        self.assertIn('0 not asked yet · 0 waiting · 1 answered', self.view())

    def test_plan_open_questions_move_from_plan_to_the_questions_tab(self):
        self.path.parent.mkdir()
        (self.path.parent / 'plan.md').write_text('# Plan\n## Approach\nDo the thing.\n'
                                                  '## Open questions\n- Confirm the copy.\n## Risks\nNone.\n')
        self.assertNotIn('Confirm the copy.', self.view('Plan'))
        text = self.view()
        self.assertIn('FROM PLAN.MD', text)
        self.assertIn('Confirm the copy.', text)


if __name__ == '__main__':
    unittest.main()
