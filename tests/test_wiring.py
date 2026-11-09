"""`sidequest-data project wiring`: every command and skill a project plugs in, and where each one really is."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import config, projects

SETTINGS = {
    'checks': {'test': 'sh -c "run {files}"', 'lint': 'no-such-tool-for-sidequest lint'},
    'app': {'switch_command': '/no/such/dir/up-app'},
    'qa': {'browser': '/no/such/Browser App/browser'},
    'workspace': {'browser': 'open -n -a "Some Browser" --args', 'report_command': 'sh report.sh', 'on_up': ['sh -c "echo hook"'],
                  'windows': [{'name': 'queue', 'command': 'sidequest-not-installed-here'},
                              {'name': 'editor', 'keys': 'nvimc'}, {'name': 'notes', 'cwd': '/notes'}]},
    'credentials': {'jira': 'keychain:acme-jira'},
}


class WiringTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='sidequest wiring ')
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name).resolve()
        self.projects = self.home / 'projects'
        skills = self.projects / 'acme' / 'skills'
        skills.mkdir(parents=True)
        real = self.home / 'tools' / 'acme-start.md'
        real.parent.mkdir()
        real.write_text('# Start, the acme way\n')
        (skills / 'start.replace.md').symlink_to(real)
        (skills / 'ship.md').write_text('Also run the acme smoke test.\n')
        stub = self.home / '.claude/skills/sidequest-start/SKILL.md'
        stub.parent.mkdir(parents=True)
        stub.write_text('stub\n')
        self.real = real
        for name, value in (('PROJECT', 'acme'), ('PROJECTS_DIR', self.projects), ('SETTINGS', SETTINGS)):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def lines(self):
        lines, failed = projects.wiring(home=self.home)
        return '\n'.join(lines), failed

    def test_each_command_says_whether_its_program_exists(self):
        text, failed = self.lines()
        self.assertTrue(failed)
        self.assertIn('OK       checks.test: sh -c "run {files}"', text)
        self.assertIn('FAIL     checks.lint: no-such-tool-for-sidequest lint (no-such-tool-for-sidequest is not on PATH)', text)
        self.assertIn('FAIL     app.switch_command: /no/such/dir/up-app (/no/such/dir/up-app does not exist)', text)
        self.assertIn('OK       workspace.on_up[1]: sh -c "echo hook"', text)
        self.assertIn('FAIL     window queue: sidequest-not-installed-here', text)
        self.assertIn('TYPED    window editor: nvimc (typed into its shell; aliases are not checked)', text)
        self.assertIn('SHELL    window notes: a shell in /notes', text)
        self.assertIn('OFF      app.current_command', text)
        self.assertIn('OK       workspace.browser: open -n -a "Some Browser" --args', text, 'a command line, not a path')
        self.assertIn('FAIL     qa.browser: /no/such/Browser App/browser (does not exist)', text)

    def test_each_skill_names_the_file_that_wins_and_where_it_is_installed(self):
        text, _ = self.lines()
        start = str(self.projects / 'acme/skills/start.replace.md')
        self.assertIn('REPLACE  start: ' + start + ' -> ' + str(self.real), text)
        self.assertIn('ADDS     ship: generic + ' + str(self.projects / 'acme/skills/ship.md'), text)
        self.assertIn('GENERIC  triage: ' + str(ROOT / 'agents/skills/sidequest-triage/SKILL.md'), text)
        self.assertIn('stubs: start in claude; missing in codex', text)
        self.assertIn('stubs: triage missing in claude, codex (run sidequest-data skills --apply)', text)

    def test_secrets_show_only_their_reference(self):
        text, _ = self.lines()
        self.assertIn('REF      credentials.jira: keychain:acme-jira', text)

    def test_the_command_needs_a_project(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
        env.update(XDG_CONFIG_HOME=str(self.home / 'empty'))
        ran = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest-data'), 'project', 'wiring'],
                             cwd=self.home, env=env, capture_output=True, text=True)
        self.assertEqual(ran.returncode, 1, ran.stdout + ran.stderr)
        self.assertIn('no project selected', ran.stdout)


if __name__ == '__main__':
    unittest.main()
