import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin/sidequest-ship-check.py"


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


class ShipCheckTests(unittest.TestCase):
    def test_plan_markers_are_listed_committed_or_not(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            git(repo, "init", "-q", "-b", "main")
            (repo / "app.rb").write_text("x = 1\n")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "base")
            git(repo, "checkout", "-qb", "fix/DEMO-7-thing")
            (repo / "app.rb").write_text("# DEMO-7 (1): entry point, see plan Code flow\nx = 1\n")
            git(repo, "commit", "-qam", "Add marker")
            (repo / "lib.rb").write_text("# DEMO-7 (2): uncommitted marker\n")
            (repo / "notes.rb").write_text("# DEMO-7 is mentioned here without a step number\n")
            run = lambda *a: subprocess.run([sys.executable, str(SCRIPT), "--no-fetch", "--base", "main", *a],
                                            cwd=repo, text=True, capture_output=True, check=True).stdout
            markers = json.loads(run("--json"))["plan_markers"]
            self.assertEqual(sorted(m.split(":")[0] for m in markers), ["app.rb", "lib.rb"])
            self.assertIn("PLAN MARKERS: 2 (remove before the PR)", run())


class UiQaEvidenceTests(unittest.TestCase):
    """UI changes need QA screenshots captured at (or after) the last UI change."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo, self.tickets = root / "repo", root / "tickets"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "app/models").mkdir(parents=True)
        (self.repo / "app/views/orders").mkdir(parents=True)
        (self.repo / "app/models/order.rb").write_text("class Order; end\n")
        (self.repo / "app/views/orders/show.html.erb").write_text("<h1>Order</h1>\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")
        git(self.repo, "checkout", "-qb", "feature/DEMO-9-orders")

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, *args):
        env = dict(os.environ, SIDEQUEST_TICKETS_DIR=str(self.tickets))
        result = subprocess.run([sys.executable, str(SCRIPT), "--no-fetch", "--base", "main", *args],
                                cwd=self.repo, env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def commit(self, path, text, message):
        (self.repo / path).write_text(text)
        git(self.repo, "commit", "-qam", message)

    def capture(self, commit=None):
        qa = self.tickets / "DEMO-9" / "qa"
        qa.mkdir(parents=True, exist_ok=True)
        (qa / "01-order.png").write_bytes(b"png")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True,
                              capture_output=True, check=True).stdout.strip()
        (qa / "manifest.json").write_text(json.dumps({"ticket": "DEMO-9", "commit": commit or head, "dirty": False,
            "shots": [{"file": "01-order.png", "caption": "Order page", "status": "ok"}]}))

    def test_backend_only_branch_needs_no_screenshots(self):
        self.commit("app/models/order.rb", "class Order; def x; end; end\n", "Add x")
        report = json.loads(self.run_check("--json"))
        self.assertEqual(report["ui_files"], [])
        self.assertEqual(report["qa"]["status"], "not needed")
        self.assertIn("UI CHANGES: none", self.run_check())

    def test_ui_change_without_screenshots_asks_for_qa(self):
        self.commit("app/views/orders/show.html.erb", "<h1>Order total</h1>\n", "Show total")
        report = json.loads(self.run_check("--json"))
        self.assertEqual(report["ui_files"], ["app/views/orders/show.html.erb"])
        self.assertEqual(report["qa"]["status"], "missing")
        self.assertIn("QA SCREENSHOTS: missing", self.run_check())

    def test_screenshots_of_the_current_ui_are_reported_ready_to_attach(self):
        self.commit("app/views/orders/show.html.erb", "<h1>Order total</h1>\n", "Show total")
        self.capture()
        self.commit("app/models/order.rb", "class Order; def x; end; end\n", "Backend follow-up")
        report = json.loads(self.run_check("--json"))
        self.assertEqual(report["qa"]["status"], "current")
        self.assertEqual(report["qa"]["screenshots"], [str(self.tickets / "DEMO-9/qa/01-order.png")])
        self.assertIn("QA SCREENSHOTS: 1 current", self.run_check())

    def test_ui_change_after_capture_makes_screenshots_stale(self):
        self.commit("app/views/orders/show.html.erb", "<h1>Order total</h1>\n", "Show total")
        self.capture()
        self.commit("app/views/orders/show.html.erb", "<h1>Order totals</h1>\n", "Rename heading")
        report = json.loads(self.run_check("--json"))
        self.assertEqual(report["qa"]["status"], "stale")
        self.assertEqual(report["qa"]["changed_since"], ["app/views/orders/show.html.erb"])

    def test_uncommitted_ui_edit_or_unknown_capture_commit_is_stale(self):
        self.commit("app/views/orders/show.html.erb", "<h1>Order total</h1>\n", "Show total")
        self.capture(commit="0" * 40)
        self.assertEqual(json.loads(self.run_check("--json"))["qa"]["status"], "stale")
        self.capture()
        (self.repo / "app/views/orders/show.html.erb").write_text("<h1>Edited</h1>\n")
        self.assertEqual(json.loads(self.run_check("--json"))["qa"]["status"], "stale")


if __name__ == "__main__":
    unittest.main()
