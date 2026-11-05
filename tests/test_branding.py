import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BrandingTests(unittest.TestCase):
    def invoke(self, folder, *args, config=None):
        env = {key: value for key, value in os.environ.items() if not key.startswith('SIDEQUEST_')}
        env.update(HOME=folder, XDG_DATA_HOME=folder + '/data', XDG_STATE_HOME=folder + '/state',
                   XDG_CONFIG_HOME=folder + '/config', PYTHONDONTWRITEBYTECODE='1')
        if config is not None:
            path = Path(folder) / 'settings.json'
            path.write_text(json.dumps(config))
            env['SIDEQUEST_CONFIG'] = str(path)
        return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sidequest'), *args],
                              cwd=folder, env=env, capture_output=True, text=True)

    def test_sidequest_entry_point_has_its_own_help(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke(folder, '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Sidequest', result.stdout)

    def test_sidequest_demo_uses_fictional_project_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke(folder, '--demo', '--list')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DEMO-901', result.stdout)
        self.assertEqual(len(result.stdout.strip().splitlines()), 4)

    def test_sidequest_uses_its_own_default_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke(folder, '--list', config={})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(folder) / 'data/sidequest/tickets.sqlite3').is_file())

    def test_sidequest_config_environment_variable_is_used(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke(folder, '--list', config={'jira': {'token': 'fictional-value'}})
        self.assertEqual(result.returncode, 2)
        self.assertIn('Keep credentials in environment variables', result.stderr)
        self.assertNotIn('fictional-value', result.stderr)


if __name__ == '__main__':
    unittest.main()
