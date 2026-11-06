"""Queue evidence: last good data, validated refreshes and per-source failures, without curses."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from core import Store
from queue_evidence import EVERY, QueueEvidence
from sidequest.snapshots import SnapshotStore, source_problem


def jira(stamp, *keys, **extra):
    return {"generated_at": stamp, "jira_available": True, "tickets": [{"key": key, **extra} for key in keys]}


def prs(stamp, *numbers):
    return {"generated_at": stamp, "open_prs": [{"number": number} for number in numbers]}


class QueueEvidenceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.snapshots = Path(folder.name)
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def evidence(self):
        return QueueEvidence(self.store, self.snapshots)

    def collected(self, sources, failures=None):
        payload = json.dumps({"sources": sources, "failures": failures or {}})
        return self.evidence().collect(lambda args, timeout: payload)

    def test_startup_uses_the_newest_copy_of_each_source(self):
        self.store.source("jira", jira("2026-11-01T10:00:00+00:00", "APP-1"))
        self.store.source("prs", prs("2026-11-03T10:00:00+00:00", 3))
        (self.snapshots / "pr-feedback.json").write_text(json.dumps(prs("2026-11-02T10:00:00+00:00", 2)))
        SnapshotStore(self.snapshots).publish({"jira": jira("2026-11-02T10:00:00+00:00", "APP-2"),
                                               "prs": prs("2026-11-01T10:00:00+00:00", 1)})
        evidence = self.evidence()
        self.assertEqual([t["key"] for t in evidence.jira["tickets"]], ["APP-2"])
        self.assertEqual([p["number"] for p in evidence.prs["open_prs"]], [3])

    def test_collect_keeps_valid_sources_and_names_rejected_ones(self):
        updates, messages, failed = self.collected({"jira": jira("2026-11-06T10:00:00+00:00", "APP-1"),
                                                    "prs": {"open_prs": "bad"}})
        self.assertEqual(set(updates), {"jira"})
        self.assertEqual(messages, ["GitHub unavailable; keeping previous data"])
        self.assertEqual(failed, {"prs"})

    def test_collect_reports_collector_failures_by_source(self):
        updates, messages, failed = self.collected({"prs": prs("2026-11-06T10:00:00+00:00")},
                                                   {"jira": "Jira: login unavailable or expired."})
        self.assertEqual(set(updates), {"prs"})
        self.assertEqual((messages, failed), (["Jira: login unavailable or expired."], {"jira"}))

    def test_a_failed_collection_run_counts_against_every_source(self):
        def run(args, timeout):
            raise OSError("Command timed out after 300 seconds")
        updates, messages, failed = self.evidence().collect(run)
        self.assertEqual((updates, failed), ({}, {EVERY}))
        evidence = self.evidence()
        evidence.finish_refresh((updates, messages, failed))
        self.assertTrue(evidence.failed("jira") and evidence.failed("prs"))

    def test_finish_refresh_keeps_failed_sources_and_saves_failures_across_restarts(self):
        evidence = self.evidence()
        evidence.finish_refresh(({"jira": jira("2026-11-01T10:00:00+00:00", "APP-1"),
                                  "prs": prs("2026-11-01T10:00:00+00:00", 1)}, [], set()))
        changed = evidence.finish_refresh(({"jira": jira("2026-11-06T10:00:00+00:00", "APP-2")},
                                           ["GitHub unavailable; keeping previous data"], {"prs"}))
        self.assertTrue(changed)
        self.assertEqual([p["number"] for p in evidence.prs["open_prs"]], [1])
        restarted = self.evidence()
        self.assertEqual([t["key"] for t in restarted.jira["tickets"]], ["APP-2"])
        self.assertTrue(restarted.failed("prs"))
        self.assertFalse(restarted.failed("jira"))
        self.assertEqual(restarted.refresh_errors, ["GitHub unavailable; keeping previous data"])

    def test_errors_saved_before_failure_sets_existed_are_read_once_by_their_text(self):
        self.store.source("refresh_errors", {"messages": ["Jira: login unavailable or expired.", "Command timed out"]})
        evidence = self.evidence()
        self.assertEqual(evidence.failed_sources, {"jira", EVERY})

    def test_a_jira_update_keeps_comments_it_did_not_reload(self):
        evidence = self.evidence()
        evidence.apply("jira", jira("2026-11-01T10:00:00+00:00", "APP-1", jira_comments=["old"], jira_comment_total=1))
        evidence.apply("jira", jira("2026-11-06T10:00:00+00:00", "APP-1"))
        self.assertEqual(evidence.jira["tickets"][0]["jira_comments"], ["old"])
        self.assertEqual(self.store.source("jira")["tickets"][0]["jira_comment_total"], 1)

    def test_heroku_results_and_errors_are_saved(self):
        evidence = self.evidence()
        self.assertFalse(evidence.apply("heroku_error", "Heroku: DNS lookup failed."))
        self.assertEqual(self.evidence().environment_error, "Heroku: DNS lookup failed.")
        evidence.apply("heroku", {"entries": {"7": {"status": "Web up"}}})
        restarted = self.evidence()
        self.assertEqual((restarted.environment_error, restarted.environments["entries"]["7"]["status"]), ("", "Web up"))

    def test_worktrees_and_worklog_change_the_ticket_list(self):
        evidence = self.evidence()
        self.assertTrue(evidence.apply("worktrees", {"APP-1": "/wt/app-1"}))
        self.assertTrue(evidence.apply("worklog", {"entries": {}}))
        self.assertEqual((evidence.windows, self.store.source("worklog")), ({"APP-1": "/wt/app-1"}, {"entries": {}}))

    def test_the_queue_and_snapshot_publication_share_one_source_check(self):
        self.assertEqual(source_problem("prs", {"open_prs": "bad"}), "invalid prs snapshot")
        self.assertEqual(source_problem("jira", {"tickets": []}), "Jira unavailable; existing file retained")
        self.assertIsNone(source_problem("prs", {"open_prs": []}))
        with self.assertRaisesRegex(ValueError, "invalid prs snapshot"):
            SnapshotStore(self.snapshots).publish({"prs": {"generated_at": "2026-11-06T10:00:00+00:00", "open_prs": "bad"}})


if __name__ == "__main__":
    unittest.main()
