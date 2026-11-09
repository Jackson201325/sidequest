"""Project profiles: shared settings plus projects/<name>/config.json, chosen by flag, variable or folder."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHOW = ('import json, os; from sidequest import config; print(json.dumps({"project": config.PROJECT, '
        '"data": str(config.DATA_DIR), "state": str(config.STATE_DIR), "settings": config.SETTINGS, '
        '"inherited": os.environ.get("SIDEQUEST_PROJECT", "")}))')


class ProfileTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name).resolve()
        self.config = self.home / 'config' / 'sidequest'
        for name in ('alpha-repo', 'alpha-wt/ALP-1-thing/app', 'beta', 'elsewhere'):
            (self.home / name).mkdir(parents=True)
        self.write('config.json', {'identity': {'timezone': 'Asia/Tokyo'}, 'jira': {'email': 'me@example.com'}})
        self.write('projects/alpha/config.json', {'workspace': {'repository': str(self.home / 'alpha-repo'),
                                                                'worktrees_dir': str(self.home / 'alpha-wt')},
                                                  'jira': {'projects': ['ALP']}})
        self.write('projects/beta/config.json', {'workspace': {'repository': str(self.home / 'beta')}})

    def write(self, relative, data):
        path = self.config / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith('SIDEQUEST_')}
        env.update(XDG_CONFIG_HOME=str(self.home / 'config'), XDG_DATA_HOME=str(self.home / 'data'),
                   XDG_STATE_HOME=str(self.home / 'state'), PYTHONPATH=str(ROOT), **extra)
        return env

    def show(self, cwd, **extra):
        result = subprocess.run([sys.executable, '-B', '-c', SHOW], cwd=self.home / cwd, env=self.env(**extra),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_the_folder_chooses_the_project_and_its_own_storage(self):
        shown = self.show('alpha-wt/ALP-1-thing/app')
        self.assertEqual(shown['project'], 'alpha')
        self.assertEqual(shown['data'], str(self.home / 'data/sidequest/projects/alpha'))
        self.assertEqual(shown['state'], str(self.home / 'state/sidequest/projects/alpha'))
        self.assertEqual(shown['settings']['jira'], {'email': 'me@example.com', 'projects': ['ALP']})
        self.assertEqual(shown['settings']['identity'], {'timezone': 'Asia/Tokyo'})
        self.assertEqual(shown['inherited'], 'alpha', 'child commands keep the same project')
        self.assertEqual(self.show('beta')['project'], 'beta')

    def test_outside_every_project_only_the_shared_settings_apply(self):
        shown = self.show('elsewhere')
        self.assertEqual(shown['project'], '')
        self.assertEqual(shown['data'], str(self.home / 'data/sidequest'))
        self.assertNotIn('workspace', shown['settings'])

    def test_a_single_profile_is_used_everywhere(self):
        (self.config / 'projects/beta/config.json').unlink()
        self.assertEqual(self.show('elsewhere')['project'], 'alpha')

    def test_the_variable_wins_over_the_folder_and_unknown_names_fail(self):
        self.assertEqual(self.show('alpha-repo', SIDEQUEST_PROJECT='beta')['project'], 'beta')
        result = subprocess.run([sys.executable, '-B', '-c', SHOW], cwd=self.home, capture_output=True, text=True,
                                env=self.env(SIDEQUEST_PROJECT='gamma'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('alpha, beta', result.stderr)

    def test_an_explicit_settings_file_ignores_profiles(self):
        single = self.home / 'single.json'
        single.write_text(json.dumps({'jira': {'projects': ['ONE']}}))
        shown = self.show('alpha-repo', SIDEQUEST_CONFIG=str(single))
        self.assertEqual((shown['project'], shown['settings']), ('', {'jira': {'projects': ['ONE']}}))

    def test_project_flag_and_project_command(self):
        def data(*args):
            return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest-data.py'), *args], cwd=self.home / 'alpha-repo',
                                  env=self.env(), capture_output=True, text=True)
        shown = data('project')
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(shown.stdout.splitlines()[0], 'project: alpha')
        self.assertIn(str(self.home / 'state/sidequest/projects/alpha'), shown.stdout)
        self.assertEqual(data('--project', 'beta', 'project').stdout.splitlines()[0], 'project: beta')
        self.assertIn('known: alpha, beta', data('--project', 'gamma', 'project').stderr)


    def test_skill_command_names_the_project_commands_first(self):
        self.write('projects/beta/config.json', {
            'workspace': {'repository': str(self.home / 'beta')},
            'checks': {'test': 'make test FILES="{files}"', 'lint': 'make lint-changed'},
            'app': {'switch_command': 'make up'}})

        def skill(cwd):
            return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest-data.py'), 'skill', 'ship'],
                                  cwd=self.home / cwd, env=self.env(), capture_output=True, text=True).stdout
        beta = skill('beta')
        self.assertTrue(beta.startswith('## Project commands: beta'), beta[:60])
        self.assertIn('- Tests: `make test FILES="{files}"`', beta)
        self.assertIn('- Lint: `make lint-changed`', beta)
        self.assertIn(' app --release', beta)
        self.assertLess(beta.index('Project commands'), beta.index('# Ship a ticket'))
        self.assertNotIn('## Project commands', skill('alpha-repo'), 'nothing configured, no block')

    def test_skill_command_adds_the_project_additions(self):
        addon = self.config / 'projects/alpha/skills/ship.md'
        addon.parent.mkdir(parents=True)
        addon.write_text('Run the team linter before the PR.')

        def skill(cwd, *names):
            return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest-data.py'), 'skill', *names],
                                  cwd=self.home / cwd, env=self.env(), capture_output=True, text=True)
        alpha = skill('alpha-repo', 'ship')
        self.assertEqual(alpha.returncode, 0, alpha.stderr)
        self.assertIn('# Ship a ticket', alpha.stdout)
        self.assertNotIn('{{SIDEQUEST_', alpha.stdout)
        self.assertIn('## Project additions: alpha', alpha.stdout)
        self.assertLess(alpha.stdout.index('# Ship a ticket'), alpha.stdout.index('Run the team linter'))
        self.assertEqual(skill('alpha-repo', 'sidequest-ship').stdout, alpha.stdout)
        beta = skill('beta', 'ship')
        self.assertIn('# Ship a ticket', beta.stdout)
        self.assertNotIn('Project additions', beta.stdout)
        unknown = skill('beta', 'deploy')
        self.assertEqual(unknown.returncode, 2)
        self.assertIn('feedback, qa-local, qa-review-app, ship, start, triage', unknown.stderr)

        # A replace version wins over the generic skill and over additions, even through a link.
        team = self.home / 'team-ship.md'
        team.write_text('---\nname: team-ship\ndescription: Team flow\n---\n\n# Team ship\n\nRun {{SIDEQUEST_DATA}} ship-check.\n')
        (addon.parent / 'ship.replace.md').symlink_to(team)
        replaced = skill('alpha-repo', 'ship')
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        self.assertTrue(replaced.stdout.startswith('<!-- Project version: alpha'), replaced.stdout[:80])
        self.assertIn('# Team ship', replaced.stdout)
        self.assertIn(str(ROOT / 'bin/sidequest-data') + ' ship-check', replaced.stdout)
        for absent in ('name: team-ship', '# Ship a ticket', 'Project additions', 'Run the team linter'):
            self.assertNotIn(absent, replaced.stdout)
        self.assertNotIn('Team ship', skill('beta', 'ship').stdout)

    def data(self, cwd, *args, **extra):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest-data.py'), *args], cwd=self.home / cwd,
                              env=self.env(**extra), capture_output=True, text=True)

    def test_project_init_writes_a_profile_and_the_next_steps(self):
        (self.home / 'gamma-repo').mkdir()
        made = self.data('elsewhere', 'project', 'init', 'gamma', '--repo', str(self.home / 'gamma-repo'))
        self.assertEqual(made.returncode, 0, made.stderr)
        profile = self.config / 'projects/gamma'
        settings = json.loads((profile / 'config.json').read_text())
        self.assertEqual(settings['workspace']['repository'], str(self.home / 'gamma-repo'))
        self.assertEqual(settings['credentials']['jira'], 'keychain:sidequest-gamma-jira')
        self.assertNotIn('identity', settings, 'identity stays in the shared file')
        self.assertTrue((profile / 'skills').is_dir())
        self.assertIn('security add-generic-password -s sidequest-gamma-jira', made.stdout)
        self.assertIn('project check', made.stdout)
        self.assertEqual(self.data('gamma-repo', 'project').stdout.splitlines()[0], 'project: gamma')
        again = self.data('elsewhere', 'project', 'init', 'gamma', '--repo', str(self.home / 'gamma-repo'))
        self.assertEqual(again.returncode, 2)
        self.assertIn('already exists', again.stderr)
        self.assertEqual(self.data('elsewhere', 'project', 'init', 'Bad Name', '--repo', str(self.home)).returncode, 2)

    def test_project_check_reports_each_part_without_printing_secrets(self):
        subprocess.run(['git', 'init', '-q', str(self.home / 'alpha-repo')], check=True)
        tools = self.home / 'tools'
        tools.mkdir()
        (tools / 'gh').write_text('#!/bin/sh\nexit 0\n')
        (tools / 'gh').chmod(0o755)
        self.write('projects/alpha/config.json', {
            'workspace': {'repository': str(self.home / 'alpha-repo')},
            'jira': {'site': 'https://alpha.atlassian.net', 'projects': ['ALP']},
            'github': {'repository': 'example/alpha'},
            'checks': {'test': 'make test'},
            'credentials': {'jira': 'env:ALPHA_JIRA'}})
        path = str(tools) + os.pathsep + os.environ['PATH']
        good = self.data('alpha-repo', 'project', 'check', ALPHA_JIRA='SECRETVALUE123', PATH=path)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertIn('OK       Jira token: found (env:ALPHA_JIRA)', good.stdout)
        self.assertIn('OK       repository:', good.stdout)
        self.assertIn('OK       GitHub sign-in', good.stdout)
        self.assertIn('OK       tests: make test', good.stdout)
        self.assertNotIn('SECRETVALUE123', good.stdout + good.stderr)
        bad = self.data('alpha-repo', 'project', 'check', PATH=path)
        self.assertEqual(bad.returncode, 1)
        self.assertIn('FAIL     Jira token: not found (env:ALPHA_JIRA)', bad.stdout)

    def test_commands_work_through_links_such_as_local_bin(self):
        links = self.home / 'bin'
        links.mkdir()
        for name in ('sidequest-data', 'sqapp', 'sidequest'):
            (links / name).symlink_to(ROOT / 'bin' / name)
        for argv, expected in ((['sidequest-data', 'project'], 'project: alpha'), (['sqapp', '--help'], 'usage: sqapp'),
                               (['sidequest', '--help'], 'usage: sidequest')):
            with self.subTest(command=argv[0]):
                result = subprocess.run([str(links / argv[0]), *argv[1:]], cwd=self.home / 'alpha-repo',
                                        env=self.env(), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)


if __name__ == '__main__':
    unittest.main()
