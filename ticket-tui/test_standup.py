import unittest
from datetime import datetime, time
from unittest.mock import patch

import standup
from core import TZ, Ticket


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=TZ)


def ticket(key, lane, action, score=50, age=0, prs=(), court="me", title="Title"):
    t = Ticket(key, title)
    t.lane, t.action, t.score, t.age, t.court, t.prs = lane, action, score, age, court, list(prs)
    return t


class WindowTests(unittest.TestCase):
    def check(self, clock, meeting, covered):
        got_meeting, got_start = standup.window(at(clock))
        self.assertEqual(got_meeting, at(meeting))
        self.assertEqual(got_start, at(covered))

    def test_afternoon_previews_tomorrow_covering_today(self):
        self.check("2026-10-27T16:00", "2026-10-28T09:00", "2026-10-27T00:00")  # Tue -> Wed

    def test_before_standup_previews_today_covering_the_previous_business_day(self):
        self.check("2026-10-27T08:00", "2026-10-27T09:00", "2026-10-26T00:00")  # Tue morning

    def test_monday_morning_covers_friday(self):
        self.check("2026-10-26T08:30", "2026-10-26T09:00", "2026-10-23T00:00")

    def test_friday_afternoon_and_weekend_preview_monday(self):
        self.check("2026-10-23T17:00", "2026-10-26T09:00", "2026-10-23T00:00")
        self.check("2026-10-24T11:00", "2026-10-26T09:00", "2026-10-23T00:00")

    def test_custom_time(self):
        meeting, _ = standup.window(at("2026-10-27T09:30"), time(10, 0))
        self.assertEqual(meeting, at("2026-10-27T10:00"))
        self.assertEqual(standup.parse_standup_time("10:15"), time(10, 15))
        with self.assertRaises(ValueError):
            standup.parse_standup_time("ten")


class PreviewTests(unittest.TestCase):
    clock = at("2026-10-27T16:00")

    def test_done_uses_only_the_covered_period_and_folds_noise(self):
        t = ticket("DEMO-600", "Waiting", "Waiting for review", court="them", prs=[{"number": 2059}], title="Analytics")
        commits = [
            {"sha": "a1", "date": "2026-10-27T10:00:00-03:00", "subject": "Add report email"},
            {"sha": "a2", "date": "2026-10-27T11:00:00-03:00", "subject": "small fix"},
            {"sha": "a3", "date": "2026-10-27T12:00:00-03:00", "subject": "Merge branch 'main'"},
            {"sha": "a4", "date": "2026-10-26T12:00:00-03:00", "subject": "Old work from Monday"},
            {"sha": "a1", "date": "2026-10-27T10:00:00-03:00", "subject": "Add report email"},
        ]
        with patch("standup.next_owner", return_value="miguel"):
            data = standup.preview([t], {"entries": {"DEMO-600": commits}}, self.clock)
        self.assertEqual(data["done"], ["DEMO-600 Analytics: Add report email; small fixes"])
        self.assertEqual(data["waiting"], ["DEMO-600 Analytics: waiting for review (miguel, PR #2059)"])
        self.assertEqual(data["today"], [])

    def test_today_lists_my_lanes_by_score_and_blockers_flag_long_waits(self):
        tickets = [ticket("DEMO-1", "Needs me", "Address requested changes", score=90, prs=[{"number": 1}]),
                   ticket("DEMO-2", "Waiting", "Follow up on QA", score=70, age=6, court="them"),
                   ticket("DEMO-3", "Clarify", "Clarify who has the next action", score=30),
                   ticket("DEMO-4", "Waiting", "Continue implementation", score=10),
                   ticket("DEMO-5", "Done", "No action")]
        with patch("standup.next_owner", return_value="QA team"):
            data = standup.preview(tickets, {}, self.clock)
        self.assertEqual([r.split()[0] for r in data["today"]], ["DEMO-1", "DEMO-2"])
        self.assertEqual(data["blockers"], ["DEMO-2 Title: waiting 6d business time on QA team",
                                            "DEMO-3 Title: clarify who has the next action"])
        self.assertFalse(any("DEMO-5" in row for row in data["today"] + data["waiting"] + data["blockers"]))

    def test_repeated_key_in_title_is_dropped(self):
        tickets = [ticket("DEMO-297", "Needs me", "Fix it", title="DEMO 297 Remove emojis", prs=[{"number": 1}]),
                   ticket("DEMO-537", "Needs me", "Fix it", title="DEMO-537: Track declines", prs=[{"number": 2}]),
                   ticket("DEMO-9", "Needs me", "Fix it", title="Plain title", prs=[{"number": 3}])]
        data = standup.preview(tickets, {}, self.clock)
        self.assertEqual(sorted(data["today"]), ["DEMO-297 Remove emojis: Fix it", "DEMO-537 Track declines: Fix it",
                                                 "DEMO-9 Plain title: Fix it"])

    def test_today_skips_my_tickets_with_no_work_yet(self):
        tickets = [ticket("DEMO-10", "Needs me", "Continue implementation", score=90),
                   ticket("DEMO-11", "Needs me", "Continue implementation", score=80),
                   ticket("DEMO-12", "Needs me", "Finish draft work", score=70, prs=[{"number": 5}]),
                   ticket("DEMO-13", "Waiting", "Follow up", score=60, age=3, court="them")]
        old = [{"sha": "b1", "date": "2026-09-01T10:00:00-03:00", "subject": "Start DEMO-11"}]
        data = standup.preview(tickets, {"entries": {"DEMO-11": old}}, self.clock)
        self.assertEqual([r.split()[0] for r in data["today"]], ["DEMO-11", "DEMO-12", "DEMO-13"])

    def test_text_headings(self):
        data = standup.preview([], {}, at("2026-10-26T08:30"))
        text = standup.as_text(data)
        self.assertTrue(text.startswith("Since Friday:\n- No commits or logged progress recorded"))
        self.assertIn("Blockers:\n- None", text)
        self.assertNotIn("Waiting on others", text)
        self.assertTrue(standup.as_text(standup.preview([], {}, self.clock)).startswith("Yesterday:"))


class WrittenReportTests(unittest.TestCase):
    report = """# DEMO status · Mon 02 Nov

## Needs you
- DEMO-1 something

## Standup
Yesterday (2026-10-30)
- DEMO-600: walked QA through the report page

Today
- DEMO-766: start the events report fix

Blockers
- None

## Tickets
- DEMO-600 ...
"""

    def test_report_standup_section_replaces_the_commit_preview(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "2026-11-02.md").write_text(self.report)
            data = standup.preview([], {}, at("2026-11-02T08:45"))
            data["written"] = standup.written(folder, data["meeting"])
            text = standup.as_text(data)
            self.assertTrue(text.startswith("Yesterday (2026-10-30)\n- DEMO-600"))
            self.assertTrue(text.endswith("Blockers\n- None"))
            self.assertNotIn("Needs you", text)
            self.assertNotIn("## Tickets", text)
            lines = standup.view_lines(data)
            self.assertIn("Today:", lines)
            self.assertIn("saved report", lines[1])

    def test_no_report_for_the_meeting_day_keeps_the_draft(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "2026-10-30.md").write_text(self.report)   # an older day's report
            data = standup.preview([], {}, at("2026-10-30T16:00"))       # next standup: Mon 02 Nov
            data["written"] = standup.written(folder, data["meeting"])
            self.assertIsNone(data["written"])
            self.assertTrue(standup.as_text(data).startswith("Yesterday:") or standup.as_text(data).startswith("Since"))
            self.assertTrue(any("saved report" in line for line in standup.view_lines(data)))


SAMPLE_REPORT = WrittenReportTests.report


class ReportRefreshTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.reports, self.backups = self.folder / "reports", self.folder / "backups"
        self.reports.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def draft(self, clock):
        t = ticket("DEMO-766", "Needs me", "Fix the events report", prs=[{"number": 2089}])
        return standup.preview([t], {}, at(clock))

    def test_refresh_replaces_only_the_standup_section_and_keeps_a_backup(self):
        original = SAMPLE_REPORT
        (self.reports / "2026-11-02.md").write_text(original)
        result = standup.update_report(self.reports, self.draft("2026-11-02T08:45"), at("2026-11-02T08:45"),
                                       "Jira 1m ago", self.backups)
        text = (self.reports / "2026-11-02.md").read_text()
        self.assertEqual(result["path"], str(self.reports / "2026-11-02.md"))
        self.assertTrue(text.startswith("# DEMO status · Mon 02 Nov"))
        self.assertIn("## Needs you\n- DEMO-1 something", text)
        self.assertIn("## Tickets\n- DEMO-600 ...", text)
        self.assertIn("- DEMO-600: walked QA through the report page", text)   # written text is kept
        self.assertIn("- DEMO-766: start the events report fix", text)
        self.assertNotIn("DEMO-766 Title: Fix the events report", text)       # already in Today: not repeated
        self.assertIn("Refreshed Mon 02 Nov 08:45", text)
        self.assertIn("Jira 1m ago", text)
        backups = list(self.backups.glob("*.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), original)

    def test_refreshed_section_reads_back_as_the_written_standup_without_the_note(self):
        (self.reports / "2026-11-02.md").write_text(SAMPLE_REPORT)
        clock = at("2026-11-02T08:45")
        standup.update_report(self.reports, self.draft("2026-11-02T08:45"), clock, "", self.backups)
        data = self.draft("2026-11-02T08:45")
        data["written"] = standup.written(self.reports, data["meeting"])
        text = standup.as_text(data)
        self.assertTrue(text.startswith("Yesterday (2026-10-30)"), text)   # the written standup, kept
        self.assertNotIn("Refreshed", text)
        self.assertIn("Today:", standup.view_lines(data))

    def test_refresh_after_the_meeting_keeps_yesterday_and_only_adds_new_tickets_to_today(self):
        report = SAMPLE_REPORT
        (self.reports / "2026-11-02.md").write_text(report)
        clock = at("2026-11-02T09:09")                      # after the 9:00 standup
        tickets = [ticket("DEMO-766", "Needs me", "Fix the events report", prs=[{"number": 2089}]),
                   ticket("DEMO-792", "Needs me", "Start Calendar & Tasks", prs=[{"number": 2111}])]
        data = standup.preview(tickets, {}, clock, today=True)
        self.assertEqual(data["meeting"], at("2026-11-02T09:00"))   # today's standup, not tomorrow's
        standup.update_report(self.reports, data, clock, "", self.backups)
        text = (self.reports / "2026-11-02.md").read_text()
        self.assertIn("Yesterday (2026-10-30)\n- DEMO-600: walked QA through the report page", text)
        self.assertIn("- DEMO-766: start the events report fix\n- DEMO-792 Title: Start Calendar & Tasks\n", text)
        self.assertEqual(text.count("DEMO-766"), 1)
        self.assertIn("Blockers\n- None", text)
        self.assertIn("added 1 item to Today", text)

    def test_second_refresh_does_not_add_the_same_items_again(self):
        (self.reports / "2026-11-02.md").write_text(SAMPLE_REPORT)
        clock = at("2026-11-02T09:09")
        data = standup.preview([ticket("DEMO-792", "Needs me", "Start", prs=[{"number": 1}])], {}, clock, today=True)
        standup.update_report(self.reports, data, clock, "", self.backups)
        standup.update_report(self.reports, data, at("2026-11-02T10:00"), "", self.backups)
        text = (self.reports / "2026-11-02.md").read_text()
        self.assertEqual(text.count("DEMO-792"), 1)
        self.assertEqual(text.count("> Refreshed"), 1)

    def test_empty_standup_section_gets_the_full_draft(self):
        (self.reports / "2026-11-02.md").write_text("# DEMO status\n\n## Standup\n\n## Tickets\n- DEMO-1\n")
        standup.update_report(self.reports, self.draft("2026-11-02T08:45"), at("2026-11-02T08:45"), "", self.backups)
        text = (self.reports / "2026-11-02.md").read_text()
        self.assertIn("**Today**\n- DEMO-766 Title: Fix the events report", text)
        self.assertIn("## Tickets\n- DEMO-1", text)

    def test_report_without_a_standup_section_gets_one_appended(self):
        (self.reports / "2026-11-02.md").write_text("# DEMO status\n\n## Tickets\n- DEMO-1\n")
        standup.update_report(self.reports, self.draft("2026-11-02T08:45"), at("2026-11-02T08:45"), "", self.backups)
        text = (self.reports / "2026-11-02.md").read_text()
        self.assertIn("## Tickets\n- DEMO-1\n\n## Standup\n", text)

    def test_missing_report_for_today_is_not_created(self):
        (self.reports / "2026-10-30.md").write_text(SAMPLE_REPORT)
        result = standup.update_report(self.reports, self.draft("2026-11-02T08:45"), at("2026-11-02T08:45"), "", self.backups)
        self.assertIsNone(result)
        self.assertEqual(sorted(p.name for p in self.reports.iterdir()), ["2026-10-30.md"])
        self.assertEqual((self.reports / "2026-10-30.md").read_text(), SAMPLE_REPORT)


if __name__ == "__main__":
    unittest.main()
