"""Exercise real curses input through a pseudo-terminal, without the shared app."""

import fcntl
import json
import os
import pty
import select
import signal
import sqlite3
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path


class TerminalTests(unittest.TestCase):
    def test_navigation_views_search_and_resize(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            snapshots = folder / "snapshots"
            snapshots.mkdir()
            (snapshots / "standup.json").write_text(json.dumps({
                "generated_at": "2026-10-27T10:00:00-03:00",
                "jira_assigned": [{"key": "DEMO-901", "summary": "Bulk request QA test", "status": "In Progress", "assignee_ok": True}],
            }))
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 145, 0, 0))
            env = dict(os.environ, TERM="xterm-256color", PYTHONDONTWRITEBYTECODE="1")
            plans = folder / 'plans'
            plan = plans / 'DEMO-901' / 'plan.md'
            plan.parent.mkdir(parents=True)
            plan.write_text('# Plan\n## Approach\nPlan view only.\n## Updates\nUpdate view only.\n')
            env['SIDEQUEST_TICKETS_DIR'] = str(plans)
            process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("tui.py")),
                                        "--data-dir", str(folder / "data"), "--snapshots", str(snapshots)],
                                       stdin=slave, stdout=slave, stderr=slave, env=env)
            os.close(slave)
            output = bytearray()

            def until(expected):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if select.select([master], [], [], 0.05)[0]:
                        try:
                            output.extend(os.read(master, 65536))
                        except OSError:
                            break
                    if expected.encode() in output:
                        return
                self.fail(f"Missing terminal text: {expected!r}; output tail: {output[-1000:]!r}")

            def send(value):
                output.clear()
                os.write(master, value.encode())

            try:
                until("DEMO-901")
                send("d")
                until("Update view only.")
                send("p")
                until("Plan view only.")
                send("/no-match\n")
                until("No matching tickets")
                send("\x1b")
                until("DEMO-901")
                # Narrow terminals keep the queue above a full-width details pane.
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
                os.kill(process.pid, signal.SIGWINCH)
                output.clear()
                until("Sidequest")
                until("Tickets ")
                until("DEMO-901 · Bulk request QA test")
                send("+")
                until("Tickets 35% / details 65%")
                send("-")
                send("l")
                until("┏━ DEMO-901")  # Focus changes the border; visible content need not be retransmitted.
                send("v")
                until("To move forward")
                send("s")
                until("Your commits (git + PR)")
                send("f")
                until("WORKFLOW")
                send("u")
                until("STANDUP PREVIEW")
                send("a")
                until("newest first")
                send("o")
                until("SORT TICKETS")
                send("j\n")
                until("Sorted by Last Jira update")
                send("O")                            # reversal is verified in the saved settings below
                send(" ")
                until("→ Open: j Jira")
                send("\x1b")
                until("orted by Last Jira update")       # curses may reuse the S already on screen
                self.assertNotIn(b"Space \xe2\x86\x92", output)
                send("hq")
                deadline = time.monotonic() + 5
                while process.poll() is None and time.monotonic() < deadline:
                    if select.select([master], [], [], 0.05)[0]:
                        try:
                            os.read(master, 65536)
                        except OSError:
                            break
                self.assertEqual(process.wait(timeout=5), 0)
                db = sqlite3.connect(folder / "data/tickets.sqlite3")
                try:
                    settings = json.loads(db.execute("SELECT data FROM local WHERE key='@app'").fetchone()[0])
                    self.assertEqual(settings["sort_mode"], "Last Jira update")
                    self.assertFalse(settings["sort_descending"])
                    self.assertAlmostEqual(settings["list_fraction"], 0.3)
                finally:
                    db.close()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)


if __name__ == "__main__":
    unittest.main()
