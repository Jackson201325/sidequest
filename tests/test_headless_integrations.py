"""Headless helpers must not load the UI or mutate Python's module search path."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class HeadlessIntegrationSpecs(unittest.TestCase):
    def test_explicit_workflow_does_not_read_process_global_configuration(self):
        source = '''
from sidequest.application import build_workflow
from pathlib import Path
flow = build_workflow({'workspace': {'agent_command': 'codex'}}, {'SHELL': '/bin/sh'})
result = flow.agent('APP-21', str(Path.cwd()), 'Review APP-21')
assert result.foreground['argv'] == ['codex', 'Review APP-21']
'''
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'invalid.json'
            config.write_text('invalid JSON')
            result = subprocess.run([sys.executable, '-B', '-c', source],
                                    cwd=Path(__file__).resolve().parents[1],
                                    env=dict(os.environ, SIDEQUEST_CONFIG=str(config)),
                                    text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_review_app_lookup_works_without_importing_the_ui(self):
        source = '''
import io, json, sys
from unittest.mock import patch
before = list(sys.path)
from sidequest import config
from sidequest.review_apps import review_app
config.SETTINGS = {'heroku': {'pipeline': 'fixture-pipeline'}}
with patch.dict('os.environ', {'SIDEQUEST_HEROKU_TOKEN': 'fixture-only-token'}), patch('urllib.request.urlopen', return_value=io.BytesIO(b'[]')):
    result = review_app(21, run=lambda *a, **k: '')
assert result['status'] == 'Not provisioned'
assert sys.path == before, 'Headless lookup added UI paths'
assert not {'core', 'curses', 'tui', 'environments'} & sys.modules.keys(), 'Headless lookup loaded the UI'
print('Headless lookup succeeded')
'''
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-B', '-c', source],
                                cwd=Path(__file__).resolve().parents[1], env=env,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Headless lookup succeeded', result.stdout)


if __name__ == '__main__':
    unittest.main()
