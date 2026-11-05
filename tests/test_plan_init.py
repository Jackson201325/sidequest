import os
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin/sidequest-plan-init.py"
SECTIONS = ["Ticket", "What's going on", "Code flow", "Acceptance criteria", "Approach", "Tests", "Risks",
            "Open questions", "PR"]


class PlanInitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_init(self, *args):
        settings = Path(self.tmp.name) / "settings.json"
        settings.write_text(json.dumps({"jira": {"site": "https://example.atlassian.net"}}))
        env = dict(os.environ, SIDEQUEST_TICKETS_DIR=str(self.tickets), SIDEQUEST_CONFIG=str(settings))
        return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True, env=env)

    def test_writes_the_plan_with_every_section_in_order_and_the_ticket_header(self):
        result = self.run_init("demo-9", "--summary", "Fix order totals", "--type", "Bug")
        plan = self.tickets / "DEMO-9" / "plan.md"
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "CREATED " + str(plan)))
        text = plan.read_text()
        headings = re.findall(r"^## (.+)$", text, re.M)
        self.assertEqual(headings, SECTIONS)
        self.assertTrue(text.startswith("# DEMO-9 Fix order totals\n"))
        self.assertIn("https://example.atlassian.net/browse/DEMO-9", text)
        self.assertIn("Bug", text)
        self.assertIn("Targets the base branch", text)
        self.assertIn("https://example.atlassian.net/browse/DEMO-9", text.split("## PR")[1])

    def test_never_overwrites_an_existing_plan(self):
        plan = self.tickets / "DEMO-9" / "plan.md"
        plan.parent.mkdir()
        plan.write_text("User's edits\n")
        result = self.run_init("DEMO-9")
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "EXISTS " + str(plan)))
        self.assertEqual(plan.read_text(), "User's edits\n")

    def test_creates_the_tickets_folder_and_works_without_a_summary(self):
        self.tickets = self.tickets / "new" / "tickets"
        result = self.run_init("DEMO-5")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.tickets / "DEMO-5" / "plan.md").read_text().startswith("# DEMO-5\n"))

    def test_rejects_a_bad_key(self):
        result = self.run_init("fix-things")
        self.assertEqual(result.returncode, 2)
        self.assertIn("expected a Jira key such as APP-123", result.stderr)


if __name__ == "__main__":
    unittest.main()
