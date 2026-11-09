"""sidequest-data questions keeps an append-only decision record in the ticket folder's questions.md."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin/sidequest-data"


class QuestionsCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tickets = Path(self.tmp.name)
        self.path = self.tickets / "DEMO-9" / "questions.md"

    def run_questions(self, *args, date="2026-11-06"):
        env = dict(os.environ, SIDEQUEST_TICKETS_DIR=str(self.tickets))
        return subprocess.run([sys.executable, "-B", str(SCRIPT), "questions", "DEMO-9", "--date", date, *args],
                              text=True, capture_output=True, env=env)

    def test_full_trail_from_question_to_decision_is_recorded_in_order(self):
        added = self.run_questions("add", "Should archived rewards be exported?", "--source", "sidequest-start",
                         "--context", "The ticket says export rewards but not which ones.")
        self.assertEqual((added.returncode, added.stdout.strip()), (0, "ADDED Q1 " + str(self.path)))
        self.assertEqual(self.run_questions("asked", "Q1", "--to", "Alex", "--via", "Jira comment").returncode, 0)
        answered = self.run_questions("answer", "1", "No, only active rewards.", "--by", "Alex", "--via", "Slack",
                            "--decision", "Filter archived rewards out of the export.", date="2026-11-07")
        self.assertEqual(answered.stdout.strip(), "UPDATED Q1 " + str(self.path))
        text = self.path.read_text()
        self.assertTrue(text.startswith("# DEMO-9 questions\n"))
        expected = ["## Q1 · Should archived rewards be exported?", "- Status: answered",
                    "- Raised: 2026-11-06 by sidequest-start",
                    "- Context: The ticket says export rewards but not which ones.",
                    "- Asked: 2026-11-06 to Alex via Jira comment",
                    "- Answer: 2026-11-07 from Alex via Slack: No, only active rewards.",
                    "- Decision: 2026-11-07: Filter archived rewards out of the export."]
        block = text[text.index("## Q1"):].splitlines()
        self.assertEqual(block, expected)

    def test_ids_are_stable_duplicates_are_not_repeated_and_other_questions_stay_untouched(self):
        self.run_questions("add", "First?")
        self.run_questions("add", "Second?")
        again = self.run_questions("add", "  first? ")
        self.assertEqual(again.stdout.strip(), "EXISTS Q1 " + str(self.path))
        before = self.path.read_text()
        self.run_questions("answer", "Q2", "Yes.")
        after = self.path.read_text()
        self.assertEqual(after[:after.index("## Q2")], before[:before.index("## Q2")])
        listed = json.loads(self.run_questions("list", "--json").stdout)
        self.assertEqual([(q["id"], q["status"]) for q in listed], [("Q1", "open"), ("Q2", "answered")])

    def test_later_answers_and_decisions_append_instead_of_replacing_evidence(self):
        self.run_questions("add", "Which store?")
        self.run_questions("answer", "Q1", "Store A.", "--by", "Alex")
        self.run_questions("answer", "Q1", "Actually both stores.", "--by", "Alex", date="2026-11-08")
        self.run_questions("decision", "Q1", "Applied to both stores.", date="2026-11-08")
        item = json.loads(self.run_questions("list", "--json").stdout)[0]
        self.assertEqual(len(item["answers"]), 2)
        self.assertIn("Store A.", item["answers"][0])
        self.assertEqual(item["decisions"], ["2026-11-08: Applied to both stores."])
        # Asking again after an answer keeps it answered.
        self.run_questions("asked", "Q1", "--to", "Sam")
        self.assertEqual(json.loads(self.run_questions("list", "--json").stdout)[0]["status"], "answered")

    def test_unknown_questions_and_empty_text_fail_without_writing(self):
        missing = self.run_questions("answer", "Q1", "Yes.")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("No questions logged yet", missing.stderr)
        self.assertFalse(self.path.exists())
        self.run_questions("add", "Only one?")
        before = self.path.read_text()
        for args in (("answer", "Q2", "Yes."), ("answer", "Q1", "  "), ("add", " "), ("decision", "Q1", "")):
            self.assertEqual(self.run_questions(*args).returncode, 1, args)
        self.assertEqual(self.path.read_text(), before)
        self.assertEqual(self.run_questions("list").stdout.count("Only one?"), 1)

    def test_list_reports_an_empty_record_honestly(self):
        result = self.run_questions("list")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "No questions logged for DEMO-9"))


if __name__ == "__main__":
    unittest.main()
