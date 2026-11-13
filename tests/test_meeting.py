"""sidequest meeting: run meeting.command in a pane below, then show what the meeting added."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import meeting

SCRIPT = ROOT / 'bin' / 'sidequest-meeting.py'


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.tickets = Path(self.temporary.name)

    def write(self, key, text, at):
        path = self.tickets / key / 'meetings.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        os.utime(path, (at, at))
        return path

    def test_only_meetings_files_changed_since_the_start_are_summarized_newest_section_only(self):
        self.write('APP-1', '# APP-1 · meeting notes\n\n## 2026-11-12 · old\n- before\n\n'
                            '## 2026-11-13 · standup\n- ship the banner\n- ask QA\n', 2000)
        self.write('APP-2', '# APP-2\n\n## 2026-11-01 · planning\n- untouched\n', 500)
        found = meeting.changed_since(self.tickets, 1000)
        self.assertEqual(found, [('APP-1', '2026-11-13 · standup', ['- ship the banner', '- ask QA'])])
        text = meeting.summary(found)
        self.assertIn('APP-1 · 2026-11-13 · standup', text)
        self.assertNotIn('before', text)
        self.assertIn('No meeting notes', meeting.summary([]))

    def test_pane_argv_runs_this_script_here_for_the_ticket(self):
        argv = meeting.pane_argv('/py', '/sq/bin/sidequest-meeting.py', 'APP-1', project='')
        self.assertEqual(argv, ['/py', '-B', '/sq/bin/sidequest-meeting.py', '--here', 'APP-1'])
        argv = meeting.pane_argv('/py', '/s.py', '', project='work')
        self.assertEqual(argv, ['env', 'SIDEQUEST_PROJECT=work', '/py', '-B', '/s.py', '--here'])

    def test_opens_a_meeting_pane_below_or_selects_the_open_one(self):
        calls = []

        def run(args, timeout=45):
            calls.append(args)
            if args[:2] == ['tmux', 'list-panes']:
                return '%1\t@2\t\n'
            return '%9\n' if args[:2] == ['tmux', 'split-window'] else ''
        message = meeting.open_pane(run, '%1', '/repo', ['/py', '--here'])
        self.assertTrue(any(c[1] == 'split-window' for c in calls))
        self.assertIn(['tmux', 'set-option', '-p', '-t', '%9', '@sidequest_role', 'meeting'], calls)
        self.assertIn('below', message)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.tickets = Path(self.temporary.name) / 'tickets'
        self.tickets.mkdir()

    def run_here(self, command, *keys, extra=None):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('SIDEQUEST_', 'JIRA_')) or k == 'SIDEQUEST_CONFIG'}
        env.update(SIDEQUEST_TICKETS_DIR=str(self.tickets), PYTHONDONTWRITEBYTECODE='1', **(extra or {}))
        if command is not None:
            env['SIDEQUEST_MEETING_COMMAND'] = command
        return subprocess.run([sys.executable, '-B', str(SCRIPT), '--here', *keys], capture_output=True,
                              text=True, env=env, stdin=subprocess.DEVNULL, timeout=30)

    def test_without_meeting_command_it_says_what_to_set(self):
        done = self.run_here(None)
        self.assertEqual(done.returncode, 2)
        self.assertIn('meeting.command', done.stderr)

    def test_runs_the_command_with_the_ticket_then_prints_the_new_meeting_section(self):
        command = ('mkdir -p "$SIDEQUEST_TICKETS_DIR/$SIDEQUEST_TICKET" && '
                   'printf "## 2026-11-13 · sync\\n- decided: keep v1\\n" >> '
                   '"$SIDEQUEST_TICKETS_DIR/$SIDEQUEST_TICKET/meetings.md"')
        done = self.run_here(command, 'APP-7')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('APP-7 · 2026-11-13 · sync', done.stdout)
        self.assertIn('decided: keep v1', done.stdout)

    def test_a_ticket_meeting_gets_a_private_context_file_that_is_removed_after(self):
        folder = self.tickets / 'APP-7'
        folder.mkdir()
        (folder / 'plan.md').write_text('# Plan\n- move the banner\n')
        (folder / 'meetings.md').write_text('## 2026-11-01 · kickoff\n- agreed on v1\n')
        seen = self.tickets / 'seen.txt'
        command = ('cp "$SIDEQUEST_TICKET_CONTEXT" "%s" && echo "$SIDEQUEST_TICKET_CONTEXT" >> "%s" && '
                   'ls -l "$SIDEQUEST_TICKET_CONTEXT" >> "%s"') % (seen, seen.with_suffix('.path'), seen.with_suffix('.mode'))
        done = self.run_here(command, 'APP-7')
        self.assertEqual(done.returncode, 0, done.stderr)
        text = seen.read_text()
        self.assertIn('APP-7', text)
        self.assertIn('move the banner', text)
        self.assertIn('agreed on v1', text)
        self.assertTrue(seen.with_suffix('.mode').read_text().startswith('-rw-------'))
        self.assertFalse(Path(seen.with_suffix('.path').read_text().strip()).exists())

    def test_the_command_gets_the_projects_jira_site_email_and_token(self):
        seen = self.tickets / 'jira.txt'
        env = {'SIDEQUEST_JIRA_SITE': 'https://example.atlassian.net', 'SIDEQUEST_JIRA_EMAIL': 'dev@example.com',
               'SIDEQUEST_JIRA_TOKEN': 'test-token'}
        done = self.run_here('echo "$JIRA_URL|$JIRA_EMAIL|$JIRA_API_TOKEN" > "%s"' % seen, extra=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(seen.read_text().strip(), 'https://example.atlassian.net|dev@example.com|test-token')
        self.assertNotIn('test-token', done.stdout + done.stderr)

    def test_the_command_gets_the_worktrees_folder_else_the_repositorys_parent(self):
        seen = self.tickets / 'trees.txt'
        repo = self.tickets.parent / 'repo'
        repo.mkdir()
        command = 'echo "$SIDEQUEST_WORKTREES_DIR" > "%s"' % seen
        self.run_here(command, extra={'SIDEQUEST_WORKSPACE_REPOSITORY': str(repo)})
        self.assertEqual(seen.read_text().strip(), str(self.tickets.parent))
        self.run_here(command, extra={'SIDEQUEST_WORKSPACE_REPOSITORY': str(repo),
                                      'SIDEQUEST_WORKSPACE_WORKTREES_DIR': str(self.tickets)})
        self.assertEqual(seen.read_text().strip(), str(self.tickets))

    def test_a_general_meeting_gets_no_ticket_or_context(self):
        seen = self.tickets / 'env.txt'
        done = self.run_here('echo "[$SIDEQUEST_TICKET][$SIDEQUEST_TICKET_CONTEXT]" > "%s"' % seen)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(seen.read_text().strip(), '[][]')


class ContextTests(unittest.TestCase):
    def test_context_lists_the_ticket_files_and_skips_missing_ones(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name) / 'APP-1'
            folder.mkdir()
            (folder / 'questions.md').write_text('- Q1: which copy?\n')
            text = meeting.context('APP-1', folder)
        self.assertTrue(text.startswith('Ticket APP-1'))
        self.assertIn('questions.md', text)
        self.assertIn('which copy?', text)
        self.assertNotIn('plan.md', text)

    def test_long_files_keep_their_end(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            (folder / 'meetings.md').write_text('old\n' + 'x' * 50000 + '\nnewest line\n')
            text = meeting.context('APP-1', folder, limit=1000)
        self.assertIn('newest line', text)
        self.assertNotIn('old\n', text)


if __name__ == '__main__':
    unittest.main()
