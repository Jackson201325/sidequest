"""Plan and Updates are read-only views of the ticket document."""
from pathlib import Path
import tempfile
import os
import time
import unittest
from unittest.mock import patch

from core import Store
import tui


class PlanUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(':memory:')
        self.addCleanup(self.store.close)
        self.app = tui.App(self.store, self.root, demo=True)
        self.ticket = self.app.selected()
        self.path = self.root / self.ticket.key / 'plan.md'
        self.path.parent.mkdir()
        self.plans = patch.object(tui, 'PLANS', self.root)
        self.plans.start()
        self.addCleanup(self.plans.stop)

    def view(self, name):
        self.app.detail_tab = name
        return '\n'.join(self.app.details(self.ticket))

    def test_updates_and_their_subsections_are_separate_from_planning_sections(self):
        text = ('# Ticket plan\n## Approach\nValidate inputs before saving.\n'
                '## Updates\n### 2026-01-02\nImplemented the validation.\n'
                '## Risks\nKeep the existing rollback path.\n')
        self.path.write_text(text)
        plan = self.view('Plan')
        self.assertIn('Validate inputs before saving.', plan)
        self.assertIn('Keep the existing rollback path.', plan)
        self.assertNotIn('Implemented the validation.', plan)
        updates = self.view('Updates')
        self.assertIn('Implemented the validation.', updates)
        self.assertIn('2026-01-02', updates)
        self.assertNotIn('Validate inputs before saving.', updates)
        self.assertNotIn('Keep the existing rollback path.', updates)
        self.assertEqual(self.path.read_text(), text)

    def test_implementation_progress_and_qa_results_move_but_test_plan_stays(self):
        self.path.write_text('# Plan\n## Tests\nAdd an invalid-input test.\n'
                             '## Implementation progress\nValidation is implemented.\n'
                             '### Verification\nRan the focused checks.\n'
                             '## QA results\nThe fixture passed.\n'
                             '## Open questions\nConfirm the copy.\n')
        plan = self.view('Plan')
        updates = self.view('Updates')
        for line in ('Validation is implemented.', 'Ran the focused checks.', 'The fixture passed.'):
            self.assertNotIn(line, plan)
            self.assertIn(line, updates)
        self.assertIn('Add an invalid-input test.', plan)
        self.assertIn('Confirm the copy.', plan)
        self.assertNotIn('Add an invalid-input test.', updates)

    def test_markdown_examples_do_not_turn_code_into_update_sections(self):
        self.path.write_text('# Plan\n## Approach\n```markdown\n## Updates\n'
                             'This is a literal example.\n```\n'
                             'Keep this planning paragraph.\n## Updates\nActual progress note.\n')
        plan = self.view('Plan')
        updates = self.view('Updates')
        self.assertIn('This is a literal example.', plan)
        self.assertIn('Keep this planning paragraph.', plan)
        self.assertNotIn('This is a literal example.', updates)
        self.assertNotIn('Keep this planning paragraph.', updates)
        self.assertIn('Actual progress note.', updates)

    def test_missing_updates_are_explicit_and_both_views_reload_after_editing(self):
        self.assertIn('No updates recorded yet', self.view('Updates'))
        self.path.write_text('# Plan\n## Approach\nFirst proposal.\n')
        self.assertIn('No updates recorded yet', self.view('Updates'))
        self.assertIn('First proposal.', self.view('Plan'))
        self.path.write_text('# Plan\n## Approach\nRevised proposal.\n## Updates\nReviewed the proposal.\n')
        edited = time.time() + 3
        os.utime(self.path, (edited, edited))
        self.assertIn('Reviewed the proposal.', self.view('Updates'))
        self.assertIn('Revised proposal.', self.view('Plan'))
        self.assertNotIn('Reviewed the proposal.', self.view('Plan'))


if __name__ == '__main__':
    unittest.main()
