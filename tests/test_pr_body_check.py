import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin/sidequest-pr-body-check.py"
CLEAN = "## Summary\nKeeps totals correct.\n\n![where](/Users/me/tickets/DEMO-9/qa/01.png)\n"


class PrBodyCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def body(self, text):
        path = self.dir / "body.md"
        path.write_text(text)
        return str(path)

    def run_check(self, *args, stored=None):
        env = dict(os.environ)
        if stored is not None:
            gh = self.dir / "bin" / "gh"
            gh.parent.mkdir(exist_ok=True)
            gh.write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps(stored) + "\nEOF\n")
            gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
            env["PATH"] = str(gh.parent) + os.pathsep + env["PATH"]
        return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True, env=env)

    def test_clean_body_passes_and_local_screenshot_paths_are_expected_before_creating(self):
        result = self.run_check(self.body(CLEAN))
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "OK: no AI attribution"))

    def test_each_attribution_phrase_is_reported_with_its_line_number(self):
        text = "Summary\nCo-Authored-By: Review Bot\nGenerated with a tool\nasked codex, claude, openai, anthropic, opencode\n"
        result = self.run_check(self.body(text))
        self.assertEqual(result.returncode, 1)
        lines = result.stdout.splitlines()
        self.assertTrue(lines[0].startswith("ATTRIBUTION line 2:"))
        self.assertTrue(lines[1].startswith("ATTRIBUTION line 3:"))
        self.assertTrue(lines[2].startswith("ATTRIBUTION line 4:"))

    def test_a_human_co_author_is_not_ai_attribution(self):
        result = self.run_check(self.body("Summary\nCo-authored-by: Ana Lopez <ana@example.com>\n"))
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "OK: no AI attribution"))

    def test_ship_check_and_pr_body_check_share_one_attribution_rule(self):
        from pathlib import Path
        import sys
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root))
        from sidequest import attribution
        for line, flagged in (("Co-authored-by: Ana Lopez <ana@example.com>", False), ("Co-authored-by: Some Bot", True),
                              ("Co-Authored-By: Claude <noreply@anthropic.com>", True), ("Generated with a tool", True),
                              ("Fix the totals", False)):
            with self.subTest(line=line):
                self.assertEqual(bool(attribution.AI.search(line)), flagged)
        for name in ("sidequest-ship-check.py", "sidequest-pr-body-check.py"):
            source = (root / "bin" / name).read_text()
            self.assertIn("attribution.AI", source)
            self.assertNotIn("co-authored", source)

    def test_missing_file_is_a_usage_error(self):
        result = self.run_check(str(self.dir / "nope.md"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read", result.stderr)

    def test_stored_pr_must_have_uploaded_images_and_no_local_paths(self):
        stored = {"title": "DEMO-9 Fix totals", "files": [{"path": "app/a.rb"}],
                  "body": "Summary\n![where](https://github.com/user-attachments/assets/abc)\n"}
        result = self.run_check("--pr", "5", stored=stored)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK: no AI attribution", result.stdout)
        self.assertIn("FILES 1: app/a.rb", result.stdout)

    def test_stored_pr_with_a_local_path_or_attribution_in_title_or_body_fails(self):
        stored = {"title": "DEMO-9 Fix totals with Claude", "files": [],
                  "body": "![x](/Users/me/Documents/example-project/tickets/DEMO-9/qa/01.png)\n"}
        result = self.run_check("--pr", "5", stored=stored)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ATTRIBUTION title:", result.stdout)
        self.assertIn("LOCAL PATH line 1:", result.stdout)

    def test_gh_failure_is_reported_not_treated_as_clean(self):
        gh = self.dir / "bin" / "gh"
        gh.parent.mkdir()
        gh.write_text("#!/bin/sh\necho boom >&2\nexit 1\n")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        env = dict(os.environ, PATH=str(gh.parent) + os.pathsep + os.environ["PATH"])
        result = subprocess.run([sys.executable, str(SCRIPT), "--pr", "5"], text=True, capture_output=True, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("gh pr view failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
