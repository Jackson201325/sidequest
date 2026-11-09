"""bin/sidequest-map.py: a read-only map of calls, file writes, config reads and programs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequest import codemap

FILES = {
    'sidequest/__init__.py': '',
    'sidequest/config.py': '''
        """Settings."""
        KEYS = {'jira': ('site', 'unused'), 'workspace': ('windows', 'terminal')}
        SETTINGS = {}
        def get(section, key, default=''):
            return SETTINGS.get(section, {}).get(key, default)
        def site():
            return get('jira', 'site')
    ''',
    'sidequest/store.py': '''
        """Snapshot storage."""
        import os
        from pathlib import Path
        from sidequest import config

        def save(path, text):
            tmp = Path(path).with_suffix('.tmp')
            tmp.write_text(text)
            os.replace(tmp, path)

        def site(settings):
            home = os.environ.get('SIDEQUEST_HOME', '')
            return config.get('jira', 'site') + settings['workspace'].get('windows', '') + home + config.get('jira', 'typo')
    ''',
    'sidequest/terminal.py': '''
        from sidequest import config
        def mode(herdr):
            values = config.get('workspace')
            herdr._call(['pane', 'list'])
            return values.get('terminal', 'auto')
    ''',
    'ticket-tui/tui.py': '''
        import subprocess
        from sidequest.store import save
        HELPER = 'sidequest-tool.py'

        class App:
            def draw(self):
                self.refresh()

            def refresh(self):
                save('a', 'b')
                subprocess.run(['git', 'status'])
    ''',
    'bin/sidequest-tool.py': '''
        #!/usr/bin/env python3
        from sidequest import store
        store.save('x', 'y')
    ''',
    'bin/sidequest-launch': '''
        #!/usr/bin/env python3
        print('launch')
    ''',
    'tests/test_store.py': '''
        from sidequest.store import save
        def test_it():
            save('a', 'b')
    ''',
}


class CodeMapTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='sidequest map ')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for name, text in FILES.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(text).lstrip())
        self.data = codemap.scan(self.root)
        self.functions = {item['id']: item for item in self.data['functions']}

    def test_modules_have_layers_and_tests_are_left_out(self):
        layers = {item['id']: item['layer'] for item in self.data['modules']}
        self.assertEqual(layers['ticket-tui/tui.py'], 'ui')
        self.assertEqual(layers['bin/sidequest-tool.py'], 'entry')
        self.assertEqual(layers['bin/sidequest-launch'], 'entry')
        self.assertEqual(layers['sidequest/config.py'], 'config')
        self.assertNotIn('tests/test_store.py', layers)
        self.assertIn('tests/test_store.py', {item['id'] for item in codemap.scan(self.root, tests=True)['modules']})

    def test_calls_are_resolved_across_modules_and_methods(self):
        self.assertIn('ticket-tui/tui.py:App.refresh', self.functions['ticket-tui/tui.py:App.draw']['calls'])
        self.assertIn('sidequest/store.py:save', self.functions['ticket-tui/tui.py:App.refresh']['calls'])
        self.assertIn('sidequest/store.py:save', self.functions['bin/sidequest-tool.py:<module>']['calls'])
        self.assertIn(['ticket-tui/tui.py', 'sidequest/store.py'], self.data['imports'])

    def test_file_writes_config_env_and_programs_are_listed(self):
        save = self.functions['sidequest/store.py:save']
        self.assertEqual([write['op'] for write in save['writes']], ['write_text', 'os.replace'])
        site = self.functions['sidequest/store.py:site']
        self.assertEqual(site['config'], [['jira', 'site'], ['workspace', 'windows'], ['jira', 'typo']])
        self.assertEqual(site['env'], ['SIDEQUEST_HOME'])
        self.assertEqual(self.functions['ticket-tui/tui.py:App.refresh']['programs'], ['git'])
        self.assertEqual(self.functions['sidequest/config.py:site']['config'], [['jira', 'site']])
        terminal = self.functions['sidequest/terminal.py:mode']
        self.assertEqual((terminal['config'], terminal['programs']), ([['workspace', 'terminal']], []))
        self.assertIn('bin/sidequest-tool.py', self.functions['ticket-tui/tui.py:<module>']['runs'])

    def test_config_check_finds_unused_and_unknown_keys(self):
        self.assertEqual(self.data['config']['unused'], [['jira', 'unused']])
        self.assertEqual(self.data['config']['unknown'], [['jira', 'typo']])

    def test_html_is_self_contained(self):
        page = codemap.render(self.data)
        self.assertIn('<script>', page)
        self.assertNotIn('src="http', page)
        self.data['modules'][0]['doc'] = '</script><b>'
        page = codemap.render(self.data)
        embedded = page.split('const DATA = ', 1)[1].split(';\n', 1)[0]
        self.assertNotIn('</', embedded)
        self.assertEqual(json.loads(embedded)['modules'], self.data['modules'])

    def test_command_writes_the_page_outside_the_scanned_folder(self):
        with tempfile.TemporaryDirectory() as out:
            page = Path(out) / 'map.html'
            ran = subprocess.run([sys.executable, str(ROOT / 'bin/sidequest-map.py'), '--root', str(self.root), '--out', str(page)],
                                 capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertIn(str(page), ran.stdout)
            self.assertIn('sidequest/store.py', page.read_text())
            ran = subprocess.run([sys.executable, str(ROOT / 'bin/sidequest-map.py'), '--root', str(self.root), '--json'],
                                 capture_output=True, text=True)
            self.assertEqual(json.loads(ran.stdout)['config']['unknown'], [['jira', 'typo']])

    def test_sidequest_map_opens_the_page_in_the_configured_browser(self):
        with tempfile.TemporaryDirectory() as out:
            page, opened = Path(out) / 'map.html', Path(out) / 'opened'
            browser = Path(out) / 'browser'
            browser.write_text('#!/bin/sh\nprintf %s "$1" > "$OPENED"\n')
            browser.chmod(0o755)
            settings = Path(out) / 'config.json'
            settings.write_text(json.dumps({'workspace': {'browser': str(browser)}}))
            env = {**os.environ, 'SIDEQUEST_CONFIG': str(settings), 'OPENED': str(opened)}
            ran = subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), 'map', '--root', str(self.root),
                                  '--out', str(page), '--open'], capture_output=True, text=True, env=env)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertIn(str(page), ran.stdout)
            self.assertIn('sidequest/store.py', page.read_text())
            self.assertEqual(opened.read_text(), page.resolve().as_uri())


if __name__ == '__main__':
    unittest.main()
