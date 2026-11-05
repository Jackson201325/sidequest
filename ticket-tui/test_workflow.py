import json
import unittest
from datetime import datetime

from core import Store, TZ, Ticket, rank
from workflow import next_owner, ownership, stage_context, workflow_path, workflow_strip


class WorkflowTests(unittest.TestCase):
    def test_common_board_statuses_map_to_a_stage(self):
        expected = {"Backlog": 0, "In Design": 0, "Ready for Dev": 0, "In Dev": 1, "Fixing Revisions": 1,
                    "Ready for Code Review": 2, "Ready for QA": 3, "In QA": 3, "Approved": 4,
                    "Ready for Stakeholder Review": 4, "In Stakeholder Review": 4, "Done": 5, "Archived": 5}
        for status, index in expected.items():
            self.assertEqual(stage_context(Ticket("DEMO-1", status=status))["index"], index, status)

    def test_approved_assigned_ticket_names_the_inferred_handoff_owner(self):
        store = Store(":memory:")
        try:
            ticket = Ticket("DEMO-42", status="Approved", assignee="Release Owner", assigned_me=False)
            rank(ticket, store)
            self.assertEqual(ticket.court, "them")
            self.assertEqual(ticket.lane, "Waiting")
            self.assertEqual(next_owner(ticket), "Release Owner")
            self.assertIn("inferred", ownership(ticket)[1])
            ticket.prs = [{"review_decision": "CHANGES_REQUESTED"}]
            rank(ticket, store)
            self.assertEqual(next_owner(ticket), "Release Owner")
        finally:
            store.close()

    def test_workflow_names_current_step_and_owner_without_dot_legend(self):
        ticket = Ticket("DEMO-42", status="In QA", court="them", assignee="QA reviewer")
        self.assertEqual(workflow_strip(ticket), ["YOU ARE HERE: QA testing (step 4 of 6)"])
        path = workflow_path(ticket)
        self.assertEqual(path[3], "4. QA testing   YOU ARE HERE")
        self.assertEqual(sum("YOU ARE HERE" in line for line in path), 1)
        self.assertEqual(next_owner(ticket), "QA reviewer")

    def test_jira_stage_and_attention_are_independent(self):
        store = Store(":memory:")
        try:
            ticket = Ticket("DEMO-42", status="Ready for Code Review", prs=[
                {"number": 42, "requested_reviewers": ["reviewer"]}])
            rank(ticket, store, datetime(2026, 10, 23, 10, tzinfo=TZ))
            self.assertEqual(ticket.lane, "Waiting")
            self.assertEqual(ticket.action, "Waiting for review")
            self.assertEqual(stage_context(ticket)["name"], "Review")
            rank(ticket, store, datetime(2026, 10, 27, 10, tzinfo=TZ))
            self.assertEqual(ticket.lane, "Waiting")
            self.assertEqual(ticket.action, "Follow up on review")
            self.assertEqual(stage_context(ticket)["name"], "Review")
        finally:
            store.close()

    def test_qa_and_jira_approval_take_precedence_over_inferred_pr_stage(self):
        self.assertEqual(stage_context(Ticket("DEMO-42", status="In QA", prs=[{}]))["index"], 3)
        ticket = Ticket("DEMO-42", status="Approved", prs=[{"requested_reviewers": ["reviewer"]}])
        store = Store(":memory:")
        try:
            rank(ticket, store)
            self.assertEqual(stage_context(ticket)["index"], 4)
            self.assertEqual(ticket.lane, "Clarify")
            self.assertNotEqual(ticket.action, "Waiting for review")
        finally:
            store.close()

    def test_pr_approval_does_not_imply_qa_or_jira_approval(self):
        stage = stage_context(Ticket("DEMO-42", prs=[{"review_decision": "APPROVED"}]))
        self.assertEqual(stage["name"], "Review")
        self.assertIn("inferred", stage["source"])

    def test_unmapped_status_does_not_invent_completed_steps(self):
        ticket = Ticket("DEMO-42", status="Waiting on vendor", assigned_me=True)
        self.assertIsNone(stage_context(ticket)["index"])
        self.assertNotIn("●", "".join(workflow_strip(ticket)))

    def test_rewording_actions_preserves_existing_age(self):
        store = Store(":memory:")
        try:
            ticket = Ticket("DEMO-42", status="Code Review", prs=[{"number": 42, "requested_reviewers": ["reviewer"]}])
            friday = datetime(2026, 10, 23, 10, tzinfo=TZ)
            rank(ticket, store, friday)
            old = json.loads(store.get(ticket.key)["signal"])
            old[1] = "Follow up on review"
            store.save(ticket.key, {"signal": json.dumps(old)})
            rank(ticket, store, datetime(2026, 10, 27, 10, tzinfo=TZ))
            self.assertEqual(ticket.age, 2)
            self.assertEqual(store.get(ticket.key)["observed_since"], friday.isoformat())
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
