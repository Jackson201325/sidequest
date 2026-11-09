"""The project overview: what each profile has, the picker's lines and keys, and when it opens."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import overview


class OverviewTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='sidequest overview ')
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name).resolve()
        self.config, self.state = self.home / 'config' / 'sidequest' / 'projects', self.home / 'state'
        for name, extra in (('acme', {}), ('globex', {'tmux_session': 'gx'})):
            (self.config / name).mkdir(parents=True)
            (self.config / name / 'config.json').write_text(json.dumps(
                {'workspace': dict({'repository': '/code/' + name}, **extra)}))
        tr = self.state / 'sidequest' / 'projects' / 'globex'
        (tr / 'snapshots').mkdir(parents=True)
        (tr / 'snapshots' / 'snapshot.json').write_text(json.dumps({'generated_at': '2026-11-09T08:31:00+00:00'}))
        now = int(time.time())
        (tr / 'app.lock').write_text('/code/APP-766-fix\t' + str(now - 60) + '\t' + str(now - 60) + '\n')

    def run_fake(self, argv):
        if argv[:2] == ['git', '-C'] and argv[2] == '/code/globex':
            return 0, 'worktree /code/globex\nbranch refs/heads/main\n\nworktree /code/APP-1\nbranch refs/heads/f\n\n' \
                      'worktree /code/APP-2\nbranch refs/heads/g\n'
        if argv[:2] == ['git', '-C']:
            return 128, ''
        if argv[:2] == ['tmux', 'list-windows'] and argv[-1] == '=gx':
            return 0, '\n'.join(['w'] * 18) + '\n'
        return 1, ''

    def rows(self):
        return overview.project_rows(self.config, self.state, run=self.run_fake)

    def test_each_profile_shows_its_session_sync_worktrees_and_booking(self):
        acme, tr = self.rows()
        self.assertEqual((acme['name'], acme['session'], acme['windows'], acme['synced'], acme['worktrees'], acme['booked']),
                         ('acme', 'acme', None, '', None, ''))
        self.assertEqual((tr['name'], tr['session'], tr['windows'], tr['worktrees'], tr['booked']),
                         ('globex', 'gx', 18, 2, 'APP-766'))
        self.assertEqual(tr['synced'], '2026-11-09T08:31:00+00:00')

    def test_the_picker_lines_mark_the_selection_and_fit_the_width(self):
        acme, tr = self.rows()
        lines = overview.render([acme, tr], selected=1, width=80, now='2026-11-09T12:00:00+00:00', tz='UTC')
        text = '\n'.join(lines)
        self.assertIn('  acme', text)
        self.assertIn('tmux: none', text)
        self.assertIn('synced never', text)
        self.assertTrue(any(line.startswith('> globex') and 'tmux: running' in line and '18 windows' in line
                            and 'synced 08:31' in line for line in lines), text)
        self.assertIn('2 worktrees · app booked: APP-766', text)
        self.assertIn('repo /code/globex', text)
        self.assertTrue(all(len(line) <= 80 for line in lines))
        older = overview.render([tr], 0, 80, now='2026-11-12T12:00:00+00:00', tz='UTC')
        self.assertIn('synced Nov 09 08:31', '\n'.join(older))

    def test_keys_map_to_commands_for_the_chosen_project(self):
        acme, tr = self.rows()
        self.assertEqual(overview.action('\n', tr), ('attach', 'gx'))
        self.assertEqual(overview.action('a', acme), ('sidequest', ['up', '-n']), 'no session yet: build it offline')
        self.assertEqual(overview.action('u', tr), ('sidequest', ['up']))
        self.assertEqual(overview.action('r', tr), ('confirm', ['up', '-r']))
        self.assertEqual(overview.action('d', tr), ('sidequest', ['up', '--dry-run']))
        self.assertEqual(overview.action('s', tr), ('ask_key', ['start']))
        self.assertEqual(overview.action('q', tr), ('sidequest', []))
        self.assertEqual(overview.action('c', tr), ('data', ['project', 'check']))
        self.assertIsNone(overview.action('x', tr))


class OutsideEveryProjectTests(unittest.TestCase):
    def run_sidequest(self, *args):
        folder = tempfile.TemporaryDirectory(prefix='sidequest outside ')
        self.addCleanup(folder.cleanup)
        home = Path(folder.name).resolve()
        for name in ('acme', 'globex'):
            (home / 'config/sidequest/projects' / name).mkdir(parents=True)
            (home / 'config/sidequest/projects' / name / 'config.json').write_text(
                json.dumps({'workspace': {'repository': str(home / name), 'terminal': 'shell'}}))
        env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
        env.update(XDG_CONFIG_HOME=str(home / 'config'), XDG_STATE_HOME=str(home / 'state'),
                   XDG_DATA_HOME=str(home / 'data'))
        return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), *args], cwd=home, env=env,
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def test_without_a_terminal_up_and_start_name_the_projects_instead_of_guessing(self):
        for args in (['up'], ['up', '-n'], ['start', 'APP-1']):
            with self.subTest(args=args):
                ran = self.run_sidequest(*args)
                self.assertEqual(ran.returncode, 2, ran.stdout + ran.stderr)
                self.assertIn('Several projects: acme, globex. Run this inside a project folder, add --project NAME, '
                              'or run sidequest projects', ran.stderr)

    def test_up_all_prepares_every_project_in_turn_and_names_each(self):
        ran = self.run_sidequest('up', '--all', '-n', '--dry-run')
        self.assertIn('== acme ==', ran.stdout)
        self.assertIn('== globex ==', ran.stdout)
        self.assertLess(ran.stdout.index('sidequest up: acme ('), ran.stdout.index('sidequest up: globex ('))
        self.assertEqual(ran.stdout.count('Dry run: nothing changed.'), 2, ran.stdout + ran.stderr)
        self.assertEqual(ran.returncode, 1, 'no merged-PR data yet: each project reports it blocked')
        named = self.run_sidequest('--project', 'acme', 'up', '--all')
        self.assertEqual(named.returncode, 2)
        self.assertIn('--all prepares every project; leave out --project', named.stderr)

    def test_projects_prints_the_overview_when_there_is_no_terminal(self):
        ran = self.run_sidequest('projects')
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertIn('acme', ran.stdout)
        self.assertIn('globex', ran.stdout)
        self.assertIn('tmux: none', ran.stdout)


if __name__ == '__main__':
    unittest.main()
