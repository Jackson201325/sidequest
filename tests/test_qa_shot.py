import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin/sidequest-qa-shot.py"


def run(args, tickets, cwd=None, env=None):
    environment = dict(os.environ, SIDEQUEST_TICKETS_DIR=str(tickets), **(env or {}))
    return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], cwd=cwd, env=environment,
                          text=True, capture_output=True, timeout=120)


class SpecTests(unittest.TestCase):
    def test_missing_spec_explains_where_to_write_it(self):
        with tempfile.TemporaryDirectory() as d:
            result = run(["DEMO-9"], Path(d))
            self.assertEqual(result.returncode, 2)
            self.assertIn(str(Path(d) / "DEMO-9/qa/shots.json"), result.stderr)

    def test_invalid_specs_are_rejected_before_any_browser_starts(self):
        cases = (({"shots": []}, "no shots"),
                 ({"shots": [{"name": "a", "path": "/"}, {"name": "a", "path": "/x"}]}, "duplicate name"),
                 ({"shots": [{"name": "../a", "path": "/"}]}, "name"),
                 ({"shots": [{"name": "a", "path": "/", "steps": [{"hover": "#x"}]}]}, "unknown step"))
        for spec, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as d:
                qa = Path(d) / "DEMO-9/qa"
                qa.mkdir(parents=True)
                (qa / "shots.json").write_text(json.dumps(spec))
                result = run(["DEMO-9"], Path(d), env={"SIDEQUEST_QA_BROWSER": "/nonexistent/browser"})
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(message, result.stderr)

    def test_websocket_frames_round_trip_masked_and_long_payloads(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("qa_shot", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for size in (5, 300, 70000):
            payload = ("x" * size).encode()
            frame = module.encode_frame(payload)
            self.assertEqual(frame[1] & 0x80, 0x80, "client frames must be masked")
            opcode, decoded = module.decode_frame(frame)
            self.assertEqual((opcode, decoded), (1, payload))


def browser():
    return os.environ.get("SIDEQUEST_QA_BROWSER")


@unittest.skipUnless(browser() and shutil.which(browser()) or (browser() and Path(browser()).exists()),
                     "set SIDEQUEST_QA_BROWSER to a Chromium/Edge binary to run the live capture test")
class LiveCaptureTests(unittest.TestCase):
    PAGES = {
        "/login": b"""<form method=post action=/login><input type=email name=email><input type=password name=password>
                      <button type=submit>Sign in</button></form>""",
        "/orders": b"""<h1>Orders</h1><input id=q><button id=go onclick="document.getElementById('r').textContent=
                       'Found '+document.getElementById('q').value">Search</button><p id=r></p>""",
    }

    def setUp(self):
        pages, posted = self.PAGES, []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self):
                if self.path == "/orders" and "session=1" not in (self.headers.get("Cookie") or ""):
                    self.send_response(302); self.send_header("Location", "/login"); self.end_headers(); return
                body = pages.get(self.path, b"<p>missing</p>")
                self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                posted.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
                self.send_response(302); self.send_header("Set-Cookie", "session=1; Path=/")
                self.send_header("Location", "/orders"); self.end_headers()

        self.posted = posted
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.tickets = Path(self.tmp.name) / "tickets"
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        for args in (["init", "-q", "-b", "feature/DEMO-9-orders"], ["commit", "-q", "--allow-empty", "-m", "base"]):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=self.repo, check=True)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def write(self, shots):
        qa = self.tickets / "DEMO-9/qa"
        qa.mkdir(parents=True, exist_ok=True)
        (qa / "shots.json").write_text(json.dumps({"base_url": "http://127.0.0.1:%d" % self.server.server_port,
                                                   "shots": shots}))
        return qa

    def test_logs_in_runs_steps_and_records_the_commit(self):
        qa = self.write([{"name": "01-search", "path": "/orders", "caption": "Orders search",
                          "steps": [{"fill": "#q", "value": "ABC"}, {"click": "#go"}, {"expect_text": "Found ABC"}]}])
        result = run(["--profile", str(Path(self.tmp.name) / "profile")], self.tickets, cwd=self.repo,
                     env={"SIDEQUEST_QA_EMAIL": "qa@example.test", "SIDEQUEST_QA_PASSWORD": "pw"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((qa / "01-search.png").read_bytes().startswith(b"\x89PNG"))
        manifest = json.loads((qa / "manifest.json").read_text())
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True, capture_output=True).stdout.strip()
        self.assertEqual((manifest["commit"], manifest["shots"][0]["status"]), (head, "ok"))
        self.assertIn("email=qa%40example.test", self.posted[0])

    def test_failed_expectation_saves_evidence_apart_and_exits_1(self):
        qa = self.write([{"name": "01-search", "path": "/orders", "steps": [{"expect_text": "Never shown", "timeout": 1}]}])
        result = run(["--profile", str(Path(self.tmp.name) / "profile")], self.tickets, cwd=self.repo,
                     env={"SIDEQUEST_QA_EMAIL": "qa@example.test", "SIDEQUEST_QA_PASSWORD": "pw"})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Never shown", result.stdout)
        self.assertFalse((qa / "01-search.png").exists())
        self.assertTrue((qa / "failures/01-search.png").exists())
        self.assertEqual(json.loads((qa / "manifest.json").read_text())["shots"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
