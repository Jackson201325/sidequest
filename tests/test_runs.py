"""sidequest-data run keeps each crew worker's step and state in the ticket folder's run.json."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin/sidequest-data"


class RunCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tickets = Path(self.tmp.name)

    def run_cmd(self, *args, at="2026-11-11T10:00:00+00:00", stdin=""):
        env = dict(os.environ, SIDEQUEST_TICKETS_DIR=str(self.tickets))
        return subprocess.run([sys.executable, "-B", str(SCRIPT), "run", *args, "--at", at],
                              text=True, capture_output=True, env=env, input=stdin)

    def show(self, key="DEMO-9"):
        shown = self.run_cmd(key, "show", "--json")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        return json.loads(shown.stdout)

    def test_worker_records_its_step_state_and_note_with_history(self):
        first = self.run_cmd("DEMO-9", "set", "implement", "working", "--note", "Building criterion 1")
        self.assertEqual((first.returncode, first.stdout.strip()),
                         (0, "UPDATED DEMO-9 implement working " + str(self.tickets / "DEMO-9" / "run.json")))
        self.run_cmd("demo-9", "set", "implement", "waiting", "--note", "Q2: Which copy?", at="2026-11-11T10:05:00+00:00")
        record = self.show()
        self.assertEqual((record["key"], record["step"], record["state"], record["note"], record["updated"]),
                         ("DEMO-9", "implement", "waiting", "Q2: Which copy?", "2026-11-11T10:05:00+00:00"))
        self.assertEqual([h["state"] for h in record["history"]], ["working", "waiting"])

    def test_unknown_step_or_state_is_refused_without_writing(self):
        bad = self.run_cmd("DEMO-9", "set", "deploy", "working")
        self.assertNotEqual(bad.returncode, 0)
        self.assertNotEqual(self.run_cmd("DEMO-9", "set", "implement", "sleeping").returncode, 0)
        self.assertFalse((self.tickets / "DEMO-9" / "run.json").exists())

    def test_hooks_mark_a_finished_turn_as_waiting_for_the_person(self):
        self.run_cmd("DEMO-9", "set", "implement", "working")
        stop = self.run_cmd("DEMO-9", "hook", "stop", stdin='{"hook_event_name": "Stop"}')
        self.assertEqual(stop.returncode, 0)
        self.assertEqual(self.show()["state"], "waiting")
        self.run_cmd("DEMO-9", "hook", "prompt")
        self.assertEqual((self.show()["state"], self.show()["step"]), ("working", "implement"))
        self.run_cmd("DEMO-9", "hook", "notify")
        self.assertEqual(self.show()["state"], "waiting")

    def test_hooks_keep_a_state_the_worker_reported_itself(self):
        self.run_cmd("DEMO-9", "set", "ship-check", "ready", "--note", "Diff clean; ready to ship")
        self.run_cmd("DEMO-9", "hook", "stop")
        self.run_cmd("DEMO-9", "hook", "notify")
        record = self.show()
        self.assertEqual((record["state"], record["note"]), ("ready", "Diff clean; ready to ship"))

    def test_hook_without_a_run_writes_nothing_and_never_fails(self):
        for event in ("prompt", "stop", "notify", "bogus"):
            self.assertEqual(self.run_cmd("DEMO-9", "hook", event).returncode, 0)
        self.assertFalse((self.tickets / "DEMO-9").exists())

    def test_list_puts_tickets_that_need_the_person_first(self):
        self.run_cmd("DEMO-1", "set", "implement", "working")
        self.run_cmd("DEMO-2", "set", "qa-local", "waiting", "--note", "Q1: Staging data?")
        self.run_cmd("DEMO-3", "set", "ship-check", "ready")
        listed = self.run_cmd("list", "--json")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual([r["key"] for r in json.loads(listed.stdout)], ["DEMO-2", "DEMO-3", "DEMO-1"])
        text = self.run_cmd("list", at="2026-11-11T10:12:00+00:00").stdout
        self.assertIn("DEMO-2  qa-local  waiting on you  12m  Q1: Staging data?", text)


class QaReviewStepTests(unittest.TestCase):
    def test_qa_review_is_the_last_step(self):
        sys.path.insert(0, str(SCRIPT.parents[1]))
        from sidequest import runs
        self.assertEqual(runs.STEPS[-1], "qa-review")
        self.assertEqual(runs.STEPS[-2], "ship-check")


if __name__ == "__main__":
    unittest.main()
