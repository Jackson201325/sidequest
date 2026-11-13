"""Regressions from the Nov 2026 code review: false ticket keys, QA rework, stuck refresh, worktree parsing."""
import json
import queue
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from core import Store, Ticket, infer, ticket_key, tickets_from
from queue_evidence import EVERY, QueueEvidence
from workflow import stage_context
import tui


class TicketKeyTests(unittest.TestCase):
    def test_lowercase_words_are_not_keys_without_known_projects(self):
        self.assertIsNone(ticket_key("Upgrade to utf-8 handling"))
        self.assertIsNone(ticket_key("chore/python-3-bump"))
        self.assertEqual(ticket_key("fix/APP-42-stock"), "APP-42")

    def test_known_projects_accept_any_case_and_reject_other_prefixes(self):
        self.assertEqual(ticket_key("feature/trd-12-totals", {"TRD"}), "TRD-12")
        self.assertIsNone(ticket_key("Bump PYTHON-3 image", {"TRD"}))
        self.assertEqual(ticket_key("PYTHON-3 then TRD-7", {"TRD"}), "TRD-7")

    def test_pr_title_does_not_create_a_phantom_ticket(self):
        jira = {"tickets": [{"key": "APP-1", "summary": "Real"}]}
        prs = {"open_prs": [{"number": 5, "ticket": "PYTHON-3", "title": "Bump python 3.12 base image",
                             "branch": "chore/python-3-bump"}]}
        self.assertEqual(sorted(t.key for t in tickets_from(jira, prs)), ["APP-1", "PR-5"])

    def test_branch_key_wins_over_a_bogus_title_match(self):
        prs = {"open_prs": [{"number": 6, "ticket": "PYTHON-3", "title": "Python 3 fixes", "branch": "fix/app-9-py3"}]}
        self.assertEqual([t.key for t in tickets_from({}, prs, projects=["APP"])], ["APP-9"])


class QaReworkTests(unittest.TestCase):
    def test_qa_failed_assigned_to_me_needs_me(self):
        court, action, _ = infer(Ticket("APP-1", status="QA Failed", assigned_me=True, assignee="Me"))
        self.assertEqual((court, action), ("me", "Address returned work"))

    def test_qa_failed_assigned_elsewhere_is_not_waiting_for_qa(self):
        ticket = Ticket("APP-2", status="QA Failed", assigned_me=False, assignee="Dev Two")
        court, action, _ = infer(ticket)
        self.assertEqual((court, action), ("them", "Waiting for Jira assignee"))
        ticket.court = court
        self.assertEqual(stage_context(ticket)["name"], "Build")

    def test_rework_statuses_match_after_normalising(self):
        for status in ("QA_Failed", "QA  Failed", "Fixing Revisions"):
            with self.subTest(status=status):
                self.assertEqual(infer(Ticket("APP-1", status=status, assigned_me=True))[1], "Address returned work")

    def test_pr_titles_never_create_lowercase_phantom_tickets_without_projects(self):
        prs = {"open_prs": [{"number": 5, "title": "Bump python 3.12 base image", "branch": "chore/python-3-bump"}]}
        self.assertEqual([t.key for t in tickets_from({}, prs)], ["PR-5"])

    def test_real_qa_and_unmapped_qa_statuses_still_wait_for_qa(self):
        for status in ("QA", "Ready for QA", "UAT QA pending"):
            with self.subTest(status=status):
                self.assertEqual(infer(Ticket("APP-3", status=status, assigned_me=False))[1], "Waiting for QA result")


class WorkerTests(unittest.TestCase):
    def app(self):
        app = tui.App.__new__(tui.App)
        app.events, app.jobs, app.refreshing, app.demo, app.dirty = queue.Queue(), {}, False, False, False
        store = Store(":memory:")
        self.addCleanup(store.close)
        app.evidence = QueueEvidence(store, Path("/nonexistent"))
        return app
    def drain(self, app, until):
        deadline, seen = time.monotonic() + 5, []
        while time.monotonic() < deadline:
            try:
                seen.append(app.events.get(timeout=0.1))
            except queue.Empty:
                continue
            if seen[-1][0] == until:
                return seen
        self.fail("worker never finished: %r" % seen)

    def test_refresh_always_finishes_on_an_unexpected_error(self):
        app = self.app()
        with patch.object(tui, "run", side_effect=KeyError("sources")):
            app.refresh()
            events = self.drain(app, "refreshed")
        updates, messages, failed = events[-1][1]
        self.assertIn("failed unexpectedly", messages[0])
        self.assertEqual((updates, failed), ({}, {EVERY}))

    def test_background_job_reports_an_unexpected_error(self):
        app = self.app()
        app.background("worklog", "Loading dated work history", lambda: {}["missing"], "worklog")
        events = self.drain(app, "job_done")
        self.assertEqual(events[0][0], "message")
        self.assertIn("Loading dated work history failed unexpectedly", events[0][1])

    def test_a_busy_job_is_named_by_what_runs_not_by_what_was_asked(self):
        app = self.app()
        app.jobs["crew"] = ("Starting the DEMO-1 crew worker", time.monotonic())
        app.background("crew", "Opening the crew manager", lambda: "never runs")
        self.assertEqual(app.message, "Starting the DEMO-1 crew worker already in progress")


class DashboardAuditTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_space_m_outside_tmux_creates_the_tickets_folder_it_runs_in(self):
        store = Store(":memory:")
        self.addCleanup(store.close)
        app = tui.App(store, self.root, demo=True)
        app.demo = False
        tickets = self.root / "state" / "tickets"
        with patch.object(tui.qa, "tickets_dir", return_value=tickets), patch.object(tui.App, "choose", return_value=1), \
                patch.dict("os.environ", {}, clear=True):
            app.meeting()
        self.assertEqual(app.foreground_target["cwd"], str(tickets))
        self.assertTrue(tickets.is_dir())

    def test_demo_never_lists_workers_from_the_real_tickets_folder(self):
        from sidequest import runs
        runs.update(self.root / "REAL-77" / "run.json", "REAL-77", "implement", "waiting", "private note",
                    "2026-11-11T10:00:00+00:00")
        seen = []

        def wrapper(loop):
            app = loop.__self__
            app.view = "AI"
            seen.extend(ticket.key for ticket in app.visible())
        argv = ["sidequest", "--demo", "--snapshots", str(self.root / "s"), "--data-dir", str(self.root / "d")]
        with patch.object(tui, "PLANS", self.root), patch.object(sys, "argv", argv), \
                patch.object(tui.curses, "wrapper", wrapper):
            tui.main()
        self.assertTrue(seen)
        self.assertNotIn("REAL-77", seen)

    def test_an_open_pr_does_not_hide_a_failed_worker(self):
        import layout
        from sidequest import runs
        record = {"key": "APP-1", "step": "implement", "state": "failed", "note": "rspec failed", "updated": ""}
        self.assertEqual(runs.after_ship(record), record)
        ticket = Ticket("APP-1", title="Totals", prs=[{"number": 12}], court="me")
        glyph, rest = layout.pipeline_row(ticket, record, 0, 200, None)
        self.assertEqual(glyph, "✗")
        self.assertIn("→ rspec failed", rest)
        self.assertNotIn("PR open", rest)
        waiting = runs.after_ship(dict(record, state="waiting"))
        self.assertEqual((waiting["step"], waiting["state"]), ("qa-review", "waiting"))

    def test_space_m_and_space_c_hand_over_the_terminal_inside_tmux_when_the_terminal_is_shell(self):
        from sidequest import config
        store = Store(":memory:")
        self.addCleanup(store.close)
        app = tui.App(store, self.root, demo=True)
        app.demo = False
        started = []
        with patch.object(config, "SETTINGS", {"workspace": {"terminal": "shell"}}), \
                patch.object(tui.qa, "tickets_dir", return_value=self.root / "tickets"), \
                patch.object(tui.App, "choose", return_value=1), \
                patch.object(tui, "run_meeting", lambda args: started.append("meeting")), \
                patch.object(tui, "run_crew", lambda args: started.append("crew")), \
                patch.dict("os.environ", {"TMUX": "/tmp/tmux,1,0"}, clear=True):
            for action, script in ((app.meeting, tui.MEETING), (app.crew_manager, tui.CREW)):
                app.foreground_target = None
                action()
                deadline = time.monotonic() + 2
                while app.jobs and time.monotonic() < deadline:
                    app.drain()
                self.assertIsNotNone(app.foreground_target, script.name)
                self.assertIn(str(script), app.foreground_target["argv"])
        self.assertEqual(started, [])

    def test_a_handed_off_row_does_not_say_the_worker_waits_for_you(self):
        import layout
        from sidequest import runs
        ticket = Ticket("APP-1", title="Totals", court="them", assignee="Eddie Sitt", assigned_me=False)
        record = {"key": "APP-1", "step": "ship-check", "state": "waiting", "note": runs.HOOK_NOTES["stop"],
                  "updated": ""}
        for note in (runs.HOOK_NOTES["stop"], runs.HOOK_NOTES["notify"], ""):
            _, rest = layout.pipeline_row(ticket, dict(record, note=note), 0, 200, None)
            with self.subTest(note=note):
                self.assertIn("with Eddie Sitt", rest)
                self.assertNotIn("→", rest)
        _, rest = layout.pipeline_row(ticket, dict(record, note="PR 12 is ready"), 0, 200, None)
        self.assertIn("→ PR 12 is ready", rest)
        ticket.court = "me"
        _, rest = layout.pipeline_row(ticket, record, 0, 200, None)
        self.assertIn("→ " + runs.HOOK_NOTES["stop"], rest)

    def test_the_card_and_details_of_a_handed_off_ticket_do_not_say_it_either(self):
        from sidequest import runs
        store = Store(":memory:")
        self.addCleanup(store.close)
        app = tui.App(store, self.root, demo=True)
        ticket = app.selected()
        ticket.court, ticket.assignee, ticket.assigned_me, ticket.prs = "them", "Eddie Sitt", False, []
        runs.update(self.root / ticket.key / "run.json", ticket.key, "ship-check", "waiting", "", "2026-11-11T10:00:00+00:00")
        runs.hook(self.root / ticket.key / "run.json", "prompt", "2026-11-11T10:01:00+00:00")
        runs.hook(self.root / ticket.key / "run.json", "stop", "2026-11-11T10:02:00+00:00")
        with patch.object(tui, "PLANS", self.root):
            card = [line for line in app.summary_card(ticket) if line.startswith("Agent ")][0]
            details = " ".join(row.text for row in app.views.agent_rows(ticket, self.root))
        self.assertIn("with Eddie Sitt", card)
        self.assertNotIn("waits for you", card)
        self.assertNotIn("waits for you", details.split("HISTORY")[0])

    def ai_app(self):
        """A dashboard on the sample tickets whose ticket folders are self.root."""
        store = Store(":memory:")
        self.addCleanup(store.close)
        app = tui.App(store, self.root, demo=True)
        plans = patch.object(tui, "PLANS", self.root)
        plans.start()
        self.addCleanup(plans.stop)
        return app

    def worker(self, key, step="implement", state="failed", note="rspec failed"):
        from sidequest import runs
        runs.update(self.root / key / "run.json", key, step, state, note, "2026-11-11T10:00:00+00:00")

    def test_space_c_in_a_plain_shell_says_so_before_it_creates_a_worktree(self):
        from unittest.mock import MagicMock
        from sidequest import config
        app = self.ai_app()
        app.demo = False
        ticket = app.selected()
        ticket.worktree = ""
        workflow, started = MagicMock(), []
        app.workflow_factory = lambda: workflow
        with patch.object(config, "SETTINGS", {"workspace": {"repository": str(self.root)}}), \
                patch.object(tui.App, "choose", return_value=0) as choose, \
                patch.object(tui, "run_crew", lambda args: started.append(args) or "x"), \
                patch.dict("os.environ", {}, clear=True):
            app.crew_worker(ticket)
            deadline = time.monotonic() + 2
            while app.jobs and time.monotonic() < deadline:
                app.drain()
        self.assertIn("inside tmux or Herdr", app.message)
        choose.assert_not_called()
        workflow.prepare.assert_not_called()
        self.assertEqual(started, [])

    def test_a_worker_outside_the_queue_keeps_its_worktree(self):
        app = self.ai_app()
        self.worker("OUT-1")
        app.evidence.windows["OUT-1"] = "/trees/OUT-1"
        app.view = "AI"
        row = next(ticket for ticket in app.visible() if ticket.key == "OUT-1")
        self.assertEqual(row.worktree, "/trees/OUT-1")

    def test_the_ai_lane_count_is_the_number_of_rows_in_its_list(self):
        app = self.ai_app()
        self.worker("OUT-1")
        app.tickets[0].status = "Blocked"
        app.view = "AI"
        self.assertEqual(app.lane_count("AI"), len(app.visible()))
        self.assertNotEqual(app.lane_count("AI"), sum(app.in_view(t, "AI") for t in app.tickets))
        self.assertEqual(app.lane_count("All"), sum(app.in_view(t, "All") for t in app.tickets))

    def test_the_pipeline_header_sits_over_the_pipeline_cells(self):
        import layout
        record = {"key": "APP-1", "step": "implement", "state": "working", "note": "", "updated": ""}
        for width in (100, 160):
            _, rest = layout.pipeline_row(Ticket("APP-1", title="Totals"), record, 0, width, None)
            with self.subTest(width=width):
                self.assertEqual(layout.pipeline_header(width).index(layout.PIPELINE_STAGES[0]), rest.index("✓"))

    def test_the_help_scrolls_on_a_short_terminal(self):
        from test_responsive import KeyScreen
        app = self.ai_app()
        app.screen = KeyScreen(["\x04", "\x04", "k", "x"], height=24, width=120)
        app.help()
        frames = ["\n".join(frame) for frame in app.screen.frames]
        self.assertEqual(len(frames), 4)
        self.assertIn("Sidequest attention queue", frames[0])
        self.assertNotIn(" DATA", frames[0])
        self.assertIn("more ↓", frames[0])
        self.assertIn(" DATA", frames[2])
        self.assertIn("Terminal: workspace.terminal", frames[2])
        self.assertNotIn("more ↓", frames[2])
        self.assertNotEqual(frames[2], frames[3])
        tall = KeyScreen(["j"], height=70, width=120)
        app.screen = tall
        app.help()
        self.assertEqual(len(tall.frames), 1)
        self.assertIn(" DATA", "\n".join(tall.frames[0]))

    def test_a_narrow_ai_row_shows_the_current_step_and_the_reason(self):
        import layout
        ticket = Ticket("APP-12", title="Totals page", court="me")
        record = {"key": "APP-12", "step": "implement", "state": "failed", "note": "rspec failed", "updated": ""}
        glyph, rest = layout.pipeline_row(ticket, record, 0, 76, None)
        header = layout.pipeline_header(76)
        self.assertEqual(glyph, "✗")
        self.assertIn("implement · failed", rest)
        self.assertIn("→ rspec failed · Totals page", rest)
        self.assertNotIn("━", rest)
        self.assertNotIn("SHIP-CHECK", header)
        self.assertEqual(header.index("REASON"), rest.index("→"))
        self.assertEqual(header.index("STEP"), rest.index("implement"))
        _, rest = layout.pipeline_row(ticket, None, 0, 76, None)
        self.assertIn("no worker", rest)
        self.assertIn("Totals page", rest)
        _, wide = layout.pipeline_row(ticket, record, 0, 100, None)
        self.assertIn("✓━", wide)
        self.assertIn("SHIP-CHECK", layout.pipeline_header(100))

    def test_tab_keys_do_nothing_in_ai_mode_where_no_tab_shows(self):
        app = self.ai_app()
        app.view, app.detail_tab, app.focus_pane = "AI", "Activity", "list"
        app.press("p")
        self.assertEqual((app.detail_tab, app.focus_pane), ("Activity", "list"))
        app.view = "All"
        app.press("p")
        self.assertEqual((app.detail_tab, app.focus_pane), ("Plan", "preview"))

    def test_a_sort_keeps_the_selected_ticket(self):
        app = self.ai_app()
        app.index = len(app.visible()) - 1
        key = app.selected().key
        for mode in tui.SORT_MODES:
            app.set_sort(mode)
            with self.subTest(mode=mode):
                self.assertEqual(app.selected().key, key)

    def test_gl_in_ai_mode_goes_to_the_worker_that_needs_you(self):
        app = self.ai_app()
        target = next(t for t in app.tickets if t.lane not in ("Needs me", "Clarify", "Done"))
        self.worker(target.key)
        app.view = "AI"
        rows = app.visible()
        self.assertEqual(rows[0].key, target.key)
        for start in (0, len(rows) - 1):
            app.index = start
            app.press("g")
            app.press("l")
            with self.subTest(start=start):
                self.assertEqual(app.selected().key, target.key)

    def test_an_automatic_reload_does_not_replace_the_status_line_when_it_is_busy(self):
        from sidequest import config
        app = self.ai_app()
        app.demo = False
        app.message = "Refresh incomplete: Jira token expired"
        for name in ("worklog", "worktrees", "branch_state"):
            app.jobs[name] = ("Loading", time.monotonic())
        with patch.object(config, "workspace_repository", return_value=str(self.root)):
            app.refresh_worklog()
            app.load_worktrees()
            app.refresh_branch_state()
        self.assertEqual(app.message, "Refresh incomplete: Jira token expired")

    def test_an_automatic_reload_asked_for_while_its_job_runs_runs_when_the_job_ends(self):
        from sidequest import config
        app = self.ai_app()
        app.demo = False
        loads = []
        app.jobs["worklog"] = ("Loading dated work history", time.monotonic())
        with patch.object(config, "workspace_repository", return_value=str(self.root)), \
                patch.object(tui, "collect_worklog", lambda *args: loads.append(1) or {}):
            app.refresh_worklog()
            app.refresh_worklog()
            self.assertEqual(loads, [])
            app.events.put(("job_done", "worklog"))
            deadline = time.monotonic() + 2
            app.drain()
            while app.jobs and time.monotonic() < deadline:
                app.drain()
        self.assertEqual(loads, [1])
        self.assertNotIn("worklog", app.jobs)

    def test_the_standup_is_copied_off_the_ui_thread(self):
        import threading
        app = self.ai_app()
        seen = []

        def pbcopy(argv, **kwargs):
            seen.append((argv, threading.current_thread(), kwargs.get("input")))
        with patch.object(tui.subprocess, "run", pbcopy):
            app.copy_standup()
            deadline = time.monotonic() + 2
            while app.jobs and time.monotonic() < deadline:
                app.drain()
            app.drain()
        self.assertEqual(seen[0][0], ["pbcopy"])
        self.assertTrue(seen[0][2])
        self.assertIsNot(seen[0][1], threading.main_thread())
        self.assertEqual(app.message, "Standup copied to the clipboard")
        with patch.object(tui.subprocess, "run", side_effect=OSError("no pbcopy")):
            app.copy_standup()
            deadline = time.monotonic() + 2
            while app.jobs and time.monotonic() < deadline:
                app.drain()
            app.drain()
        self.assertIn("pbcopy unavailable", app.message)

    def test_the_skip_reason_is_stored_on_the_ui_thread(self):
        import threading
        from sidequest import crew
        app = self.ai_app()
        app.demo = False
        ticket = app.selected()
        ticket.worktree = str(self.root)
        threads = []

        class Recorder(dict):
            def __setitem__(self, key, value):
                threads.append(threading.current_thread())
                super().__setitem__(key, value)
        app.crew_skipped = Recorder()
        answer = f"skip {ticket.key}: Jira status is In QA; " + crew.AGAIN_HINT
        with patch.object(tui.App, "choose", return_value=0), patch.object(tui, "run_crew", lambda args: answer), \
                patch.dict("os.environ", {"TMUX": "/tmp/tmux,1,0"}):
            app.crew_worker(ticket)
            deadline = time.monotonic() + 2
            while app.jobs and time.monotonic() < deadline:
                app.drain()
            app.drain()
        self.assertEqual(dict(app.crew_skipped), {ticket.key: "Jira status is In QA"})
        self.assertEqual(threads, [threading.main_thread()])
        self.assertIn("press Space c again", (app.message or "") + (app.deferred_message or ""))


class WorktreeTests(unittest.TestCase):
    def test_backup_branches_and_lowercase_keys(self):
        porcelain = ("worktree /repo\nHEAD 1\nbranch refs/heads/main\n\n"
                     "worktree /wt/app-7\nHEAD 2\nbranch refs/heads/feature/APP-7-totals\n\n"
                     "worktree /wt/backup\nHEAD 3\nbranch refs/heads/backup/APP-7-old\n\n")
        with patch.object(tui.config, "workspace_repository", return_value="/repo"), patch.object(tui, "run", return_value=porcelain):
            self.assertEqual(tui.worktrees(), {"APP-7": "/wt/app-7"})

    def test_only_branch_segment_keys_map_a_worktree_like_lookup(self):
        porcelain = ("worktree /repo\nHEAD 1\nbranch refs/heads/main\n\n"
                     "worktree /wt/a\nHEAD 2\nbranch refs/heads/feature/APP-1-revert-APP-2\n\n"
                     "worktree /wt/b\nHEAD 3\nbranch refs/heads/fix/APP-3-utf-8\n\n")
        with patch.object(tui.config, "workspace_repository", return_value="/repo"), patch.object(tui, "run", return_value=porcelain):
            self.assertEqual(tui.worktrees(), {"APP-1": "/wt/a", "APP-3": "/wt/b"})


class FirstRunTests(unittest.TestCase):
    """Found by the fresh-install e2e run on Python 3.9."""

    def test_jira_offsets_without_a_colon_parse_on_every_supported_python(self):
        from sidequest.evidence import parse_time
        stamp = parse_time("2026-11-04T10:35:58.000+0000")
        self.assertIsNotNone(stamp)
        self.assertEqual(stamp.utcoffset().total_seconds(), 0)
        self.assertEqual(parse_time("2026-11-04T07:35:58-0300"), parse_time("2026-11-04T10:35:58Z"))

    def test_jira_comments_and_updates_reach_the_activity_tab(self):
        from activity import ticket_activity
        ticket = Ticket("APP-43", updated="2026-11-04T10:00:00.000+0000",
                        jira_comments=[{"author": "Rae", "body": "Off by a cent",
                                        "created_at": "2026-11-04T10:35:58.000+0000",
                                        "updated_at": "2026-11-04T10:35:58.000+0000"}])
        self.assertEqual([e["title"] for e in ticket_activity(ticket)], ["Comment added", "Ticket updated"])

    def test_first_run_errors_name_the_missing_piece(self):
        from sidequest.access import failure_for
        gh = str(failure_for("GitHub", "[Errno 2] No such file or directory: 'gh'"))
        self.assertIn("GitHub CLI (gh) is not installed", gh)
        jira = str(failure_for("Jira", "No Jira credentials: configure jira.email and set SIDEQUEST_JIRA_TOKEN"))
        self.assertIn("no credentials yet", jira)
        self.assertNotIn("expired", jira)
        self.assertIn("login unavailable or expired", str(failure_for("Jira", "Jira HTTP 401; previous data retained")))

    def test_header_marks_unconfigured_and_failed_sources(self):
        app = tui.App.__new__(tui.App)
        app.refreshing, app.jobs, app.sort_descending, app.sort_mode, app.styles = False, {}, True, "Attention", {}
        store = Store(":memory:")
        self.addCleanup(store.close)
        app.evidence = QueueEvidence(store, Path("/nonexistent"))
        app.evidence.jira = {"enabled": False, "generated_at": tui.now().isoformat()}
        app.evidence.prs = {"enabled": True, "generated_at": tui.now().isoformat()}
        text = app.header_status()[0]
        self.assertIn("Jira off", text)
        self.assertNotIn("STALE", text)
        app.evidence.finish_refresh(({}, ["GitHub: request failed. Previous data retained."], {"prs"}))
        self.assertIn("GitHub failed, data now", app.header_status()[0])

    def test_header_marks_every_kind_of_refresh_failure(self):
        app = tui.App.__new__(tui.App)
        app.refreshing, app.jobs, app.sort_descending, app.sort_mode, app.styles = False, {}, True, "Attention", {}
        store = Store(":memory:")
        self.addCleanup(store.close)
        app.evidence = QueueEvidence(store, Path("/nonexistent"))
        fresh = {"enabled": True, "jira_available": True, "tickets": [], "open_prs": []}

        def timed_out(args, timeout):
            raise OSError("Command timed out after 300 seconds")
        cases = {"rejected Jira": (lambda args, timeout: json.dumps({"sources": {"prs": fresh, "jira": {}}}), ("Jira failed",)),
                 "unconfigured Jira": (lambda args, timeout: json.dumps({"sources": {"prs": fresh}, "failures": {
                     "jira": "Jira is not configured; configure jira.site. Previous data retained."}}), ("Jira failed",)),
                 "timed-out run": (timed_out, ("Jira failed", "GitHub failed"))}
        for case, (run, expected) in cases.items():
            with self.subTest(case=case):
                app.evidence.jira = app.evidence.prs = dict(fresh, generated_at=tui.now().isoformat())
                app.evidence.finish_refresh(app.evidence.collect(run))
                text = app.header_status()[0]
                for marker in expected:
                    self.assertIn(marker, text)
                if len(expected) == 1:
                    self.assertNotIn("GitHub failed", text)

    def test_refresh_names_rejected_sources_as_the_header_does(self):
        worker = WorkerTests()
        worker.addCleanup = self.addCleanup
        app = worker.app()
        data = json.dumps({"sources": {"jira": {"tickets": []}, "prs": {"open_prs": "bad"}}, "failures": {}})
        with patch.object(tui, "run", return_value=data):
            app.refresh()
            events = worker.drain(app, "refreshed")
        _, messages, failed = events[-1][1]
        self.assertEqual(messages, ["Jira unavailable; keeping previous data", "GitHub unavailable; keeping previous data"])
        self.assertEqual(failed, {"jira", "prs"})


if __name__ == "__main__":
    unittest.main()
