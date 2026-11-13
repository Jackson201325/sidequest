"""sidequest crew: one worker agent per ticket worktree, reported through run.json, and a manager agent."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import crew, runs

DATA = "/opt/sidequest/bin/sidequest-data"


class WorkerPromptTests(unittest.TestCase):
    def test_new_worker_runs_every_step_and_stops_before_shipping(self):
        prompt = crew.worker_prompt("DEMO-9", None, DATA)
        for step in ("start", "implement", "qa-local", "ship-check"):
            self.assertIn(DATA + " run DEMO-9 set " + step + " working", prompt)
        self.assertLess(prompt.index("set start working"), prompt.index("set implement working"))
        self.assertIn(DATA + " skill implement", prompt)
        self.assertIn(DATA + " questions DEMO-9 add", prompt)
        self.assertIn("set ship-check ready", prompt)
        self.assertIn("Never commit, push", prompt)
        self.assertIn(DATA + " update-branch --keep-conflicts", prompt)
        self.assertLess(prompt.index("update-branch"), prompt.index(DATA + " ship-check"))
        self.assertIn("finishing the rebase or merge", prompt)
        self.assertIn("Skip the start workflow's Jira move", prompt)
        self.assertNotIn("configured start move", prompt)

    def test_a_workflows_finish_reply_does_not_end_the_workers_turn(self):
        for record in (None, {"step": "implement", "state": "waiting", "note": ""}):
            prompt = crew.worker_prompt("DEMO-9", record, DATA)
            self.assertIn("A workflow's Finish reply is not a stop", prompt)
            self.assertIn("go on to the next step in the same turn", prompt)

    def test_qa_local_ends_with_screenshots_and_a_report(self):
        prompt = crew.worker_prompt("DEMO-9", None, DATA)
        qa = prompt[prompt.index("3. qa-local"):prompt.index("4. ship-check")]
        self.assertIn(DATA + " qa-shot DEMO-9", qa)
        self.assertIn("qa/report.md", qa)

    def test_a_ready_ship_check_goes_to_a_challenger_that_assumes_the_work_is_wrong(self):
        record = {"key": "DEMO-9", "step": "ship-check", "state": "ready", "note": "Ready to ship"}
        self.assertEqual(crew.first_step(record, True), "challenge")
        prompt = crew.worker_prompt("DEMO-9", record, DATA)
        self.assertIn("Assume every part of its work is wrong", prompt)
        self.assertIn("wrong", prompt)
        self.assertIn(DATA + " run DEMO-9 set challenge working", prompt)
        self.assertIn(DATA + " run DEMO-9 set challenge ready", prompt)
        self.assertIn("challenge.md", prompt)
        self.assertIn("Never commit, push", prompt)
        self.assertNotIn("skill qa-review-app", prompt)

    def test_a_ready_challenge_continues_at_qa_review_on_the_review_app(self):
        record = {"key": "DEMO-9", "step": "challenge", "state": "ready", "note": "2 fixed"}
        self.assertEqual(crew.first_step(record, True), "qa-review")
        prompt = crew.worker_prompt("DEMO-9", record, DATA)
        self.assertIn("Continue from qa-review", prompt)
        self.assertIn(DATA + " run DEMO-9 set qa-review working", prompt)
        self.assertIn(DATA + " skill qa-review-app", prompt)
        self.assertIn(DATA + " review-app DEMO-9 --json", prompt)
        self.assertIn("qa-review waiting", prompt)
        self.assertEqual(crew.first_step(dict(record, state="working"), True), "challenge")

    def test_resumed_worker_continues_from_the_recorded_step(self):
        record = {"key": "DEMO-9", "step": "qa-local", "state": "waiting", "note": "Q1: Staging data?"}
        prompt = crew.worker_prompt("DEMO-9", record, DATA)
        self.assertIn("Continue from qa-local", prompt)
        self.assertIn("Q1: Staging data?", prompt)
        self.assertIn(DATA + " review-app DEMO-9 --json", prompt.split("Continue from")[0].split("already has a run")[1])

    def test_workers_skip_a_step_that_already_finished_on_the_same_code(self):
        prompt = crew.worker_prompt("DEMO-9", None, DATA)
        self.assertIn(DATA + " run DEMO-9 ran <step>", prompt)

    def test_claude_workers_get_hooks_that_report_waiting(self):
        line = crew.worker_command("claude --model claude-sonnet-5-5", "DEMO-9", DATA)
        argv = shlex.split(line)
        self.assertEqual(argv[:3], ["claude", "--model", "claude-sonnet-5-5"])
        hooks = json.loads(argv[argv.index("--settings") + 1])["hooks"]
        self.assertEqual(hooks["Stop"][0]["hooks"][0]["command"], DATA + " run DEMO-9 hook stop")
        self.assertEqual(hooks["UserPromptSubmit"][0]["hooks"][0]["command"], DATA + " run DEMO-9 hook prompt")
        self.assertEqual(hooks["Notification"][0]["hooks"][0]["command"], DATA + " run DEMO-9 hook notify")
        self.assertEqual(hooks["PostToolUse"][0]["hooks"][0]["command"], DATA + " run DEMO-9 hook tool")
        self.assertEqual(crew.worker_command("codex", "DEMO-9", DATA), "codex")

    def test_a_ready_ship_check_starts_the_challenger_when_the_worker_stops(self):
        line = crew.worker_command("claude", "DEMO-9", DATA, "/opt/sidequest/bin/sidequest")
        hooks = json.loads(shlex.split(line)[shlex.split(line).index("--settings") + 1])["hooks"]
        self.assertEqual([h["command"] for h in hooks["Stop"][0]["hooks"]],
                         [DATA + " run DEMO-9 hook stop", "/opt/sidequest/bin/sidequest crew DEMO-9 --after-stop"])
        self.assertTrue(crew.challenge_due({"step": "ship-check", "state": "ready"}))
        for step, state in (("ship-check", "working"), ("challenge", "ready"), ("implement", "ready")):
            self.assertFalse(crew.challenge_due({"step": step, "state": state}))
        self.assertFalse(crew.challenge_due(None))


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tickets = Path(self.tmp.name)
        self.launched = []
        self.trees = {"DEMO-1": {"state": "worktree", "path": "/w/demo-1"},
                      "DEMO-2": {"state": "none"},
                      "DEMO-3": {"state": "main-checkout", "path": "/repo"}}

    def dispatch(self, keys, again=False, dry_run=False):
        return crew.dispatch(keys, self.trees.get, self.tickets,
                             lambda key, path, prompt: self.launched.append((key, path, prompt)) or "started " + key,
                             DATA, "2026-11-11T10:00:00+00:00", again=again, dry_run=dry_run)

    def test_ticket_with_a_worktree_gets_a_worker_and_a_queued_record(self):
        lines, failed = self.dispatch(["DEMO-1"])
        self.assertFalse(failed)
        self.assertEqual([(k, p) for k, p, _ in self.launched], [("DEMO-1", "/w/demo-1")])
        self.assertEqual(lines, ["DEMO-1: worker started at start"])
        record = runs.read(self.tickets / "DEMO-1" / "run.json")
        self.assertEqual((record["step"], record["state"]), ("start", "queued"))

    def test_a_launcher_that_reused_an_open_pane_is_reported_as_sending_the_prompt(self):
        lines, _ = crew.dispatch(["DEMO-1"], self.trees.get, self.tickets, lambda key, path, prompt: True,
                                 DATA, "2026-11-11T10:00:00+00:00")
        self.assertEqual(lines, ["DEMO-1: prompt sent to the open worker pane at start"])

    def test_ticket_with_a_plan_starts_at_implement(self):
        (self.tickets / "DEMO-1").mkdir()
        (self.tickets / "DEMO-1" / "plan.md").write_text("# Plan\n")
        self.dispatch(["DEMO-1"])
        self.assertEqual(runs.read(self.tickets / "DEMO-1" / "run.json")["step"], "implement")

    def test_the_challenge_step_starts_with_the_challenger_command(self):
        runs.update(self.tickets / "DEMO-1" / "run.json", "DEMO-1", "ship-check", "ready", "", "2026-11-11T09:00:00+00:00")
        challenged = []
        lines, _ = crew.dispatch(["DEMO-1"], self.trees.get, self.tickets,
                                 lambda key, path, prompt: self.launched.append(key), DATA,
                                 "2026-11-11T10:00:00+00:00",
                                 challenger=lambda key, path, prompt: challenged.append(key))
        self.assertEqual((self.launched, challenged), ([], ["DEMO-1"]))
        self.assertEqual(lines, ["DEMO-1: challenger started at challenge"])

    def test_tickets_without_their_own_worktree_are_skipped_with_the_reason(self):
        lines, failed = self.dispatch(["DEMO-2", "DEMO-3"])
        self.assertTrue(failed)
        self.assertEqual(self.launched, [])
        self.assertIn("sidequest start DEMO-2", lines[0])
        self.assertIn("main checkout", lines[1])

    def test_a_running_worker_is_not_doubled_unless_asked(self):
        runs.update(self.tickets / "DEMO-1" / "run.json", "DEMO-1", "implement", "working", "", "2026-11-11T09:00:00+00:00")
        lines, failed = self.dispatch(["DEMO-1"])
        self.assertTrue(failed)
        self.assertIn("--again", lines[0])
        self.assertEqual(self.launched, [])
        self.dispatch(["DEMO-1"], again=True)
        self.assertEqual(len(self.launched), 1)
        self.assertIn("Continue from implement", self.launched[0][2])

    def test_a_worker_whose_pane_is_gone_is_started_again_without_again(self):
        runs.update(self.tickets / "DEMO-1" / "run.json", "DEMO-1", "implement", "working", "", "2026-11-11T09:00:00+00:00")
        launch = lambda key, path, prompt: self.launched.append(key)
        lines, failed = crew.dispatch(["DEMO-1"], self.trees.get, self.tickets, launch, DATA, "2026-11-11T10:00:00+00:00",
                                      alive=lambda key, agent: True)
        self.assertTrue(failed)
        lines, failed = crew.dispatch(["DEMO-1"], self.trees.get, self.tickets, launch, DATA, "2026-11-11T10:00:00+00:00",
                                      alive=lambda key, agent: None)
        self.assertTrue(failed)
        self.assertEqual(self.launched, [])
        seen = []
        lines, failed = crew.dispatch(["DEMO-1"], self.trees.get, self.tickets, launch, DATA, "2026-11-11T10:00:00+00:00",
                                      alive=lambda key, agent: seen.append((key, agent)) or False)
        self.assertFalse(failed)
        self.assertEqual((self.launched, seen), (["DEMO-1"], [("DEMO-1", "worker")]))
        self.assertEqual(lines, ["DEMO-1: the worker pane was gone; worker started at implement"])

    def test_the_record_is_queued_before_launch_and_failed_when_launch_fails(self):
        path = self.tickets / "DEMO-1" / "run.json"
        states = []
        crew.dispatch(["DEMO-1"], self.trees.get, self.tickets, lambda key, p, prompt: states.append(runs.read(path)["state"]),
                      DATA, "2026-11-11T10:00:00+00:00")
        self.assertEqual(states, ["queued"])

        def broken(key, p, prompt):
            raise RuntimeError("tmux is not running")
        with self.assertRaises(RuntimeError):
            crew.dispatch(["DEMO-1"], self.trees.get, self.tickets, broken, DATA, "2026-11-11T10:00:00+00:00", again=True)
        record = runs.read(path)
        self.assertEqual((record["state"], record["note"]), ("failed", "Could not start the worker: tmux is not running"))

    def test_a_ticket_with_someone_else_is_skipped_unless_asked(self):
        lines, failed = crew.dispatch(["DEMO-1"], self.trees.get, self.tickets,
                                      lambda key, path, prompt: self.launched.append(key), DATA,
                                      "2026-11-11T10:00:00+00:00", waiting=lambda key: "Jira status is In QA")
        self.assertTrue(failed)
        self.assertEqual(self.launched, [])
        self.assertEqual(lines, ["skip DEMO-1: Jira status is In QA; use --again to start it anyway"])
        crew.dispatch(["DEMO-1"], self.trees.get, self.tickets, lambda key, path, prompt: self.launched.append(key),
                      DATA, "2026-11-11T10:00:00+00:00", again=True, waiting=lambda key: "Jira status is In QA")
        self.assertEqual(self.launched, ["DEMO-1"])

    def test_dry_run_prints_and_launches_nothing(self):
        lines, failed = self.dispatch(["DEMO-1"], dry_run=True)
        self.assertFalse(failed)
        self.assertEqual(self.launched, [])
        self.assertIn("would start DEMO-1 in /w/demo-1", lines[0])
        self.assertFalse((self.tickets / "DEMO-1" / "run.json").exists())


def load_cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location("crew_cli", ROOT / "bin/sidequest-crew.py")
    cli = importlib.util.module_from_spec(spec)
    with unittest.mock.patch.object(sys, "argv", ["sidequest-crew.py"]):
        spec.loader.exec_module(cli)
    return cli


class AfterStopTests(unittest.TestCase):
    def run_main(self, record_state):
        cli = load_cli()
        tickets = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tickets)
        if record_state:
            runs.update(tickets / "DEMO-1" / "run.json", "DEMO-1", *record_state, "", "2026-11-11T09:00:00+00:00")
        calls = []
        with unittest.mock.patch.object(sys, "argv", ["sidequest-crew.py", "DEMO-1", "--after-stop"]), \
                unittest.mock.patch.object(cli, "tickets_dir", lambda: tickets), \
                unittest.mock.patch.object(cli, "jira_tickets", lambda keys: {}), \
                unittest.mock.patch.object(cli, "workflow", lambda: (object(), False)), \
                unittest.mock.patch.object(cli, "worker_launcher", lambda *a, **kw: None), \
                unittest.mock.patch.object(cli.crew, "dispatch",
                                           lambda keys, *a, **kw: calls.append((keys, kw)) or (["skip DEMO-1: x"], True)):
            code = cli.main()
        return code, calls

    def test_after_stop_starts_the_challenger_only_for_a_ready_ship_check_and_always_exits_0(self):
        for state in (None, ("implement", "working"), ("ship-check", "waiting"), ("challenge", "ready")):
            self.assertEqual(self.run_main(state), (0, []), state)
        code, calls = self.run_main(("ship-check", "ready"))
        self.assertEqual((code, calls[0][0], calls[0][1]["again"] if "again" in calls[0][1] else None), (0, ["DEMO-1"], None))


class ManagerPaneTests(unittest.TestCase):
    def open(self, terminal, environ):
        cli = load_cli()
        flow = type("Flow", (), {"terminal": terminal, "agent_command": ""})()
        with tempfile.TemporaryDirectory() as folder, \
                unittest.mock.patch.object(cli, "tickets_dir", lambda: Path(folder)), \
                unittest.mock.patch("sys.stdout"):
            return cli.open_manager(flow, False, environ), folder

    def test_inside_tmux_the_manager_opens_below_the_callers_pane(self):
        from sidequest.terminal import TmuxTerminal
        calls = []

        def run(args, timeout=45):
            calls.append(args)
            return "%9" if args[1] == "split-window" else ""
        code, _ = self.open(TmuxTerminal(run, "sidequest", "/bin/sh"), {"TMUX_PANE": "%1"})
        self.assertEqual(code, 0)
        split = next(c for c in calls if c[1] == "split-window")
        self.assertEqual(split[2:7], ["-v", "-l", "40%", "-t", "%1"])
        self.assertIn("skill manage", split[-1])
        self.assertFalse(any(c[1] == "new-window" for c in calls))

    def test_a_new_claude_manager_gets_a_session_id_that_continue_resumes(self):
        from sidequest.terminal import TmuxTerminal
        cli = load_cli()
        splits, tagged = [], [""]

        def run(args, timeout=45):
            if args[1] == "list-panes":
                return tagged[0]
            if args[1] == "split-window":
                splits.append(args[-1])
                return "%9"
            return ""
        flow = type("Flow", (), {"terminal": TmuxTerminal(run, "sq", "/bin/sh"), "agent_command": ""})()
        with tempfile.TemporaryDirectory() as folder, \
                unittest.mock.patch.object(cli, "tickets_dir", lambda: Path(folder)), \
                unittest.mock.patch.object(cli.config, "get", lambda *a, **k: "claude --model m"), \
                unittest.mock.patch.object(cli.config, "PROJECT", ""), unittest.mock.patch("sys.stdout"):
            cli.open_manager(flow, False, {"TMUX_PANE": "%1"}, resume=False)
            first = crew.last_manager_session(Path(folder))
            self.assertIn("--session-id " + first, splits[0])
            cli.open_manager(flow, False, {"TMUX_PANE": "%1"}, resume=True)
            self.assertIn("--resume " + first, splits[1])
            self.assertEqual(crew.last_manager_session(Path(folder)), first)
            tagged[0] = "%9\t@2\tcrew\n"
            cli.open_manager(flow, False, {"TMUX_PANE": "%1"}, resume=False)
            self.assertEqual((len(splits), crew.last_manager_session(Path(folder))), (2, first))

    def test_the_terminal_is_asked_only_when_a_last_chat_exists_and_no_flag_decides(self):
        cli = load_cli()
        with tempfile.TemporaryDirectory() as name, \
                unittest.mock.patch.object(cli, "tickets_dir", lambda: Path(name)):
            self.assertFalse(cli.ask_resume(None, ask=lambda q: self.fail(q), interactive=True))
            (Path(name) / crew.MANAGER_SESSION).write_text('{"session_id": "id-1"}')
            self.assertTrue(cli.ask_resume(None, ask=lambda q: "", interactive=True))
            self.assertFalse(cli.ask_resume(None, ask=lambda q: "n", interactive=True))
            self.assertFalse(cli.ask_resume(None, ask=lambda q: self.fail(q), interactive=False))
            self.assertTrue(cli.ask_resume(True, ask=lambda q: self.fail(q), interactive=True))

    def test_manager_argv_continues_only_a_saved_claude_session(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            argv, saved = crew.manager_argv("claude", "go", folder, resume=True, new_id=lambda: "id-1")
            self.assertEqual((argv, saved), (["claude", "--session-id", "id-1", "go"], "id-1"))
            (folder / crew.MANAGER_SESSION).write_text('{"session_id": "id-1"}')
            argv, saved = crew.manager_argv("env A=1 claude", "go", folder, resume=True)
            self.assertEqual((argv[:4], saved), (["env", "A=1", "claude", "--resume"], None))
            self.assertEqual(argv[4], "id-1")
            self.assertEqual(crew.manager_argv("codex", "go", folder, resume=True), (["codex", "go"], None))

    def test_inside_herdr_the_manager_opens_below_the_callers_pane(self):
        seen = []

        class Herdr:
            def split_below(self, path, argv):
                seen.append((path, argv))
                return type("Result", (), {"message": "ok"})()
        code, folder = self.open(Herdr(), {})
        self.assertEqual(code, 0)
        self.assertEqual(seen[0][0], folder)
        self.assertIn("skill manage", seen[0][1][-1])


class WorkerFocusTests(unittest.TestCase):
    def test_crew_workers_start_without_taking_focus(self):
        cli = load_cli()
        calls = []

        class Flow:
            agent_command = ""

            def agent(self, key, path, prompt, focus=True):
                calls.append((key, focus))
                return type("Result", (), {"message": "ok"})()
        launch = cli.worker_launcher(Flow(), "claude", DATA)
        launch("DEMO-1", "/w/demo-1", "prompt")
        self.assertEqual(calls, [("DEMO-1", False)])

    def test_tmux_workers_and_challengers_each_reuse_their_own_tagged_pane(self):
        cli = load_cli()
        from sidequest.terminal import TmuxTerminal
        seen = []

        class Flow:
            agent_command = ""
            terminal = TmuxTerminal(lambda args, timeout=45: "", "proj", "/bin/sh")
        with unittest.mock.patch("sidequest.tmux.start_agent", lambda *a, **kw: seen.append((a[1], kw)) or "ok"):
            cli.worker_launcher(Flow(), "claude", DATA)("DEMO-1", "/w/demo-1", "prompt")
            cli.worker_launcher(Flow(), "claude", DATA, "challenger")("DEMO-1", "/w/demo-1", "prompt")
        self.assertEqual([(key, kw["role"], kw["focus"]) for key, kw in seen],
                         [("DEMO-1", "crew-worker:DEMO-1", False), ("DEMO-1", "crew-challenger:DEMO-1", False)])

    def test_the_tmux_launcher_says_whether_it_reused_an_open_pane(self):
        cli = load_cli()
        from sidequest.terminal import TmuxTerminal

        class Flow:
            agent_command = ""
            terminal = TmuxTerminal(lambda args, timeout=45: "", "proj", "/bin/sh")
        launch = cli.worker_launcher(Flow(), "claude", DATA)
        with unittest.mock.patch("sidequest.tmux.start_agent", return_value="ok"):
            with unittest.mock.patch("sidequest.tmux.role_pane", return_value="%7"):
                self.assertIs(launch("DEMO-1", "/w/demo-1", "prompt"), True)
            with unittest.mock.patch("sidequest.tmux.role_pane", return_value=None):
                self.assertIs(launch("DEMO-1", "/w/demo-1", "prompt"), False)


class WaitingReasonTests(unittest.TestCase):
    def test_review_qa_and_other_assignees_are_waiting_on_someone_else(self):
        cli = load_cli()
        skip = cli.SKIP_STATUSES
        mine = {"assignee": "Me", "assignee_ok": True}
        self.assertIsNone(cli.waiting_reason({**mine, "status": "In Dev"}, skip))
        self.assertIsNone(cli.waiting_reason({**mine, "status": "Fixing Revisions"}, skip))
        self.assertIn("could not read", cli.waiting_reason(None, skip))
        self.assertIsNone(cli.waiting_reason({"status": "In Dev", "assignee": "Unassigned", "assignee_ok": False}, skip))
        self.assertIn("in qa", cli.waiting_reason({**mine, "status": "in qa"}, skip))
        self.assertIn("Ready for Code Review", cli.waiting_reason({**mine, "status": "Ready for Code Review"}, skip))
        self.assertIn("assigned to Eddie", cli.waiting_reason({"status": "In Dev", "assignee": "Eddie",
                                                                "assignee_ok": False}, skip))
        self.assertIsNone(cli.waiting_reason({**mine, "status": "In QA"}, "Done"))

    def test_default_skip_statuses_cover_every_review_qa_approved_and_done_stage(self):
        sys.path.insert(0, str(ROOT / "ticket-tui"))
        from workflow import ALIASES
        skip = {s.strip().casefold() for s in load_cli().SKIP_STATUSES.split(",")}
        self.assertEqual({name for name, stage in ALIASES.items() if stage >= 2} - skip, set())

    def test_status_table_shows_the_jira_status(self):
        records = [{"key": "DEMO-4", "step": "implement", "state": "waiting", "note": "", "updated": None}]
        line = runs.table(records, None, {"DEMO-4": "In QA"})[0]
        self.assertIn("[Jira: In QA]", line)


class CrewCommandTests(unittest.TestCase):
    def test_status_prints_the_overview_without_launching(self):
        with tempfile.TemporaryDirectory() as folder:
            runs.update(Path(folder) / "DEMO-4" / "run.json", "DEMO-4", "implement", "waiting", "Q1: Copy?",
                        "2026-11-11T10:00:00+00:00")
            env = dict(os.environ, SIDEQUEST_TICKETS_DIR=folder)
            shown = subprocess.run([sys.executable, "-B", str(ROOT / "bin/sidequest"), "crew", "--status"],
                                   text=True, capture_output=True, env=env)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("DEMO-4  implement  waiting on you", shown.stdout)
        self.assertIn("Q1: Copy?", shown.stdout)


if __name__ == "__main__":
    unittest.main()
