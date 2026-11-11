"""Herdr 0.9.5 CLI contract, entirely fixture-driven and scoped to a caller pane."""
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from sidequest.application import build_workflow
from sidequest.herdr import HerdrTerminal
from sidequest.terminal import ShellTerminal, TmuxTerminal


CONTEXT = {'HERDR_ENV': '1', 'HERDR_WORKSPACE_ID': 'w7', 'HERDR_PANE_ID': 'w7:p2',
           'HERDR_TAB_ID': 'w7:t1', 'SHELL': '/bin/sh'}


def response(kind, **values):
    return json.dumps({'id': 'fixture', 'result': dict(type=kind, **values)})


class HerdrSpecs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sidequest herdr ')
        self.addCleanup(self.temporary.cleanup)
        self.path = str(Path(self.temporary.name).resolve())
        self.launches = Path(self.path) / 'launches'
        self.calls = []
        self.panes = [{'pane_id': 'w7:p3', 'tab_id': 'w7:t8', 'workspace_id': 'w7', 'cwd': self.path}]
        self.failure = None
        self.terminal = HerdrTerminal(self.run_command, CONTEXT, '/bin/sh', self.launches)

    def run_command(self, args, **kwargs):
        self.calls.append(args)
        if self.failure:
            return self.failure
        command = args[1:3]
        if command == ['pane', 'list']:
            return response('pane_list', panes=self.panes)
        if command == ['tab', 'create']:
            return response('tab_created', tab={'tab_id': 'w7:t19', 'workspace_id': 'w7'},
                            root_pane={'pane_id': 'w7:p41', 'workspace_id': 'w7', 'tab_id': 'w7:t19'})
        if command == ['pane', 'layout']:
            return response('pane_layout', layout={'workspace_id': 'w7', 'tab_id': 'w7:t8',
                            'panes': [{'pane_id': 'w7:p3', 'rect': {'width': 140, 'height': 40}}]})
        if command == ['pane', 'split']:
            return response('pane_info', pane={'pane_id': 'w7:p52', 'workspace_id': 'w7', 'tab_id': 'w7:t8'})
        if command == ['tab', 'focus']:
            return response('tab_info', tab={'tab_id': args[3], 'workspace_id': 'w7'})
        if command == ['pane', 'run']:
            return ''  # Herdr 0.9.5 send_ok_request succeeds silently.
        return response('ok')

    def test_requires_genuine_managed_context_before_any_control(self):
        for env in ({}, {'HERDR_ENV': '0'}, dict(CONTEXT, HERDR_PANE_ID='')):
            with self.subTest(env=env), self.assertRaisesRegex(RuntimeError, 'Herdr-managed pane'):
                HerdrTerminal(self.run_command, env, '/bin/sh', self.launches).launch('APP-21', self.path)
        self.assertEqual(self.calls, [])

    def test_open_discovers_the_matching_tab_in_the_callers_workspace(self):
        result = self.terminal.launch('APP-21', self.path)
        self.assertEqual(self.calls, [['herdr', 'pane', 'list', '--workspace', 'w7'],
                                     ['herdr', 'tab', 'focus', 'w7:t8']])
        self.assertIn('APP-21', result.message)

    def test_open_creates_a_tab_when_no_other_pane_matches(self):
        self.panes[0]['pane_id'] = CONTEXT['HERDR_PANE_ID']
        self.terminal.launch('APP-21', self.path)
        create = self.calls[1]
        self.assertEqual(create, ['herdr', 'tab', 'create', '--workspace', 'w7', '--cwd', self.path,
                                  '--label', 'APP-21', '--no-focus'])
        self.assertEqual(self.calls[-1], ['herdr', 'tab', 'focus', 'w7:t19'])

    def test_a_different_directory_with_the_same_ticket_label_is_not_reused(self):
        self.panes[0].update(cwd='/unrelated/APP-21', label='APP-21')
        self.terminal.launch('APP-21', self.path)
        self.assertEqual(self.calls[1][1:3], ['tab', 'create'])

    def test_explicit_foreground_start_does_not_control_herdr(self):
        result = self.terminal.launch('APP-21', self.path, foreground=True)
        self.assertEqual(result.foreground['argv'], ['/bin/sh', '-i'])
        self.assertEqual(self.calls, [])

    def test_agent_splits_existing_tab_and_keeps_large_prompt_out_of_shell_input(self):
        prompt = "APP-21: 'quotes', $(literal)\n" * 1000
        argv = ['my-agent', '--flag', prompt]
        self.terminal.launch('APP-21', self.path, argv)
        split = next(c for c in self.calls if c[1:3] == ['pane', 'split'])
        self.assertIn('w7:p3', split)
        self.assertIn('right', split)
        command = next(c for c in self.calls if c[1:3] == ['pane', 'run'])
        self.assertEqual(command[3], 'w7:p52')
        self.assertLess(len(command[4]), 1000)
        self.assertNotIn(prompt, command[4])
        script = Path(shlex.split(command[4])[-1])
        self.assertEqual(stat.S_IMODE(script.stat().st_mode), 0o600)
        self.assertIn(repr(argv), script.read_text())
        self.assertEqual(self.calls[-1], ['herdr', 'tab', 'focus', 'w7:t8'])

    def test_unfocused_agent_leaves_the_person_in_their_tab(self):
        result = self.terminal.launch('APP-21', self.path, ['my-agent', 'Review APP-21'], focus=False)
        split = next(c for c in self.calls if c[1:3] == ['pane', 'split'])
        self.assertNotIn('--focus', split)
        self.assertFalse(any(c[1:3] == ['tab', 'focus'] for c in self.calls))
        self.assertTrue(any(c[1:3] == ['pane', 'run'] for c in self.calls))
        self.assertIn('background', result.message)

    def test_split_below_puts_the_command_under_the_callers_pane_at_forty_percent(self):
        result = self.terminal.split_below(self.path, ['my-agent', 'manage'])
        split = next(c for c in self.calls if c[1:3] == ['pane', 'split'])
        self.assertEqual(split, ['herdr', 'pane', 'split', '--pane', 'w7:p2', '--direction', 'down',
                                 '--ratio', '0.6', '--cwd', self.path, '--focus'])
        command = next(c for c in self.calls if c[1:3] == ['pane', 'run'])
        self.assertEqual(command[3], 'w7:p52')
        self.assertIn('below', result.message)

    def test_agent_handoff_executes_literal_arguments_in_the_requested_directory(self):
        recorded = Path(self.path) / 'received.json'
        agent = Path(self.path) / 'agent.py'
        agent.write_text('import json,os,sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps([os.getcwd(),sys.argv[2:]]))\n')
        prompt = "APP-21: 'quotes' $(touch unwanted)\nnext line"
        argv = [sys.executable, str(agent), str(recorded), prompt]
        self.terminal.launch('APP-21', self.path, argv)
        command = next(c for c in self.calls if c[1:3] == ['pane', 'run'])
        script = Path(shlex.split(command[4])[-1])
        subprocess.run(shlex.split(command[4]), check=True)
        self.assertFalse(script.exists())
        self.assertEqual(json.loads(recorded.read_text()), [self.path, [prompt]])
        self.assertFalse((Path(self.path) / 'unwanted').exists())

    def test_agent_in_a_new_tab_uses_the_returned_root_pane_id(self):
        self.panes = []
        self.terminal.launch('APP-21', self.path, ['my-agent', 'Review APP-21'])
        command = next(c for c in self.calls if c[1:3] == ['pane', 'run'])
        self.assertEqual(command[3], 'w7:p41')
        self.assertFalse(any(c[1:3] == ['pane', 'split'] for c in self.calls))

    def test_narrow_panes_split_down(self):
        original = self.terminal.run
        def narrow(args, **kwargs):
            value = original(args, **kwargs)
            if args[1:3] == ['pane', 'layout']:
                data = json.loads(value)
                data['result']['layout']['panes'][0]['rect']['width'] = 70
                return json.dumps(data)
            return value
        self.terminal.run = narrow
        self.terminal.launch('APP-21', self.path, ['my-agent', 'Review APP-21'])
        split = next(c for c in self.calls if c[1:3] == ['pane', 'split'])
        self.assertIn('down', split)

    def test_uncertain_agent_submission_is_not_retried_and_keeps_private_launcher(self):
        original = self.terminal.run
        def failed(args, **kwargs):
            value = original(args, **kwargs)
            if args[1:3] == ['pane', 'run']:
                raise RuntimeError('request may have been admitted')
            return value
        self.terminal.run = failed
        with self.assertRaisesRegex(RuntimeError, 'inspect the session before retrying'):
            self.terminal.launch('APP-21', self.path, ['my-agent', 'Review APP-21'])
        self.assertEqual(sum(c[1:3] == ['pane', 'run'] for c in self.calls), 1)
        self.assertFalse(any(c[1:3] == ['tab', 'focus'] for c in self.calls))
        self.assertEqual(len(list(self.launches.glob('agent-*.py'))), 1)

    def test_malformed_or_error_responses_never_create_or_focus(self):
        for value in ('not JSON', '{}', response('pane_list', panes=None),
                      json.dumps({'error': {'code': 'stale_id', 'message': 'private raw diagnostic'}})):
            self.calls.clear()
            self.failure = value
            with self.subTest(value=value), self.assertRaises(RuntimeError) as raised:
                self.terminal.launch('APP-21', self.path)
            self.assertEqual(len(self.calls), 1)
            self.assertNotIn('private raw diagnostic', str(raised.exception))

    def test_wrong_workspace_and_unusable_identifiers_are_rejected(self):
        for pane in (dict(self.panes[0], workspace_id='another-workspace'),
                     dict(self.panes[0], tab_id='')):
            self.panes = [pane]
            self.calls.clear()
            with self.assertRaises(RuntimeError):
                self.terminal.launch('APP-21', self.path)
            self.assertEqual(len(self.calls), 1)

    def test_failed_control_is_not_retried_or_replaced_with_a_shell(self):
        def failed(args, **kwargs):
            self.calls.append(args)
            raise RuntimeError('fixture transport failure')
        with self.assertRaises(RuntimeError):
            HerdrTerminal(failed, CONTEXT, '/bin/sh', self.launches).launch('APP-21', self.path)
        self.assertEqual(len(self.calls), 1)

    def test_timeout_reports_uncertainty_without_retrying(self):
        def failed(args, **kwargs):
            self.calls.append(args)
            raise subprocess.TimeoutExpired(args, 15)
        with self.assertRaisesRegex(RuntimeError, 'inspect the session before retrying'):
            HerdrTerminal(failed, CONTEXT, '/bin/sh', self.launches).launch('APP-21', self.path)
        self.assertEqual(len(self.calls), 1)


class TerminalSelectionSpecs(unittest.TestCase):
    def setUp(self):
        self.zsh = patch('shutil.which', return_value='/bin/zsh')
        self.zsh.start()
        self.addCleanup(self.zsh.stop)

    def test_herdr_uses_zsh_for_worktree_shells_even_if_parent_shell_is_sh(self):
        with tempfile.TemporaryDirectory() as folder:
            flow = build_workflow({}, dict(CONTEXT, SHELL='/bin/sh'))
            result = flow.terminal.launch('APP-21', folder, foreground=True)
            self.assertEqual(result.foreground['argv'], ['/bin/zsh', '-i'])

    def test_herdr_explains_missing_zsh_before_launching_or_changing_git(self):
        with patch('shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'Herdr requires zsh'):
                build_workflow({}, CONTEXT)

    def test_auto_preserves_tmux_priority_and_detects_herdr_only_inside_its_context(self):
        for env, expected in (({}, ShellTerminal), (CONTEXT, HerdrTerminal),
                              (dict(CONTEXT, TMUX='active'), TmuxTerminal)):
            with self.subTest(expected=expected):
                flow = build_workflow({}, env, run=lambda *a, **k: '')
                self.assertIsInstance(flow.terminal, expected)

    def test_explicit_override_selects_herdr_in_nested_tmux(self):
        flow = build_workflow({}, dict(CONTEXT, TMUX='active', SIDEQUEST_TERMINAL='herdr'))
        self.assertIsInstance(flow.terminal, HerdrTerminal)

    def test_config_can_force_shell_and_unknown_modes_are_errors(self):
        flow = build_workflow({'workspace': {'terminal': 'shell'}}, dict(CONTEXT, TMUX='active'))
        self.assertIsInstance(flow.terminal, ShellTerminal)
        with self.assertRaisesRegex(ValueError, 'workspace.terminal'):
            build_workflow({'workspace': {'terminal': 'unknown'}}, {})

    def test_explicit_managed_terminal_requires_its_context(self):
        for mode in ('herdr', 'tmux'):
            with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                build_workflow({'workspace': {'terminal': mode}}, {})

    def test_invalid_terminal_configuration_is_rejected_when_loading_json(self):
        from sidequest import config
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps({'workspace': {'terminal': 'unknown'}}))
            with self.assertRaisesRegex(ValueError, 'workspace.terminal'):
                config.load(path)


if __name__ == '__main__':
    unittest.main()
