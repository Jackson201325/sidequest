"""tmux launch and browser opening through the package, without the UI."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sidequest import terminal, tmux
from sidequest.terminal import agent_argv, agent_display_name

SESSION = "example-project"
KEY, WORKTREE = "DEMO-1", "/wt/DEMO-1"


def start(run, prompt, inside):
    argv = agent_argv(prompt)
    return tmux.start_agent(run, KEY, WORKTREE, argv, inside, SESSION, agent_display_name(argv))


PANES = "example-project\t@3\tEditor\t/wt/DEMO-1\nother\t@9\tDEMO-1\t/elsewhere\n"
LIST_PANES = ["tmux", "list-panes", "-a", "-F", "#{session_name}\t#{window_id}\t#{window_name}\t#{pane_current_path}"]


class FakeRun:
    def __init__(self, panes=PANES, no_server=False):
        self.panes, self.no_server, self.calls = panes, no_server, []

    def __call__(self, args, timeout=45):
        self.calls.append(args)
        if args[:2] == ["tmux", "list-panes"]:
            if self.no_server:
                raise RuntimeError("no server running")
            return self.panes
        return ""

    def commands(self):
        return [c for c in self.calls if c != LIST_PANES]


class LauncherTests(unittest.TestCase):

    def test_agent_splits_the_existing_tw_window_and_switches_when_inside_tmux(self):
        run = FakeRun()
        message = start(run, "ship DEMO-1", inside=True)
        self.assertEqual(run.commands(), [
            ["tmux", "split-window", "-h", "-t", "@3", "-c", "/wt/DEMO-1", "claude 'ship DEMO-1'"],
            ["tmux", "select-window", "-t", "@3"],
            ["tmux", "switch-client", "-t", "example-project"]])
        self.assertEqual(message, "Claude Code started in Editor: ship DEMO-1")

    def test_agent_outside_tmux_asks_the_caller_to_attach_instead_of_switching(self):
        run = FakeRun()
        self.assertEqual(start(run, "ship DEMO-1", inside=False), "example-project")
        self.assertNotIn(["tmux", "switch-client", "-t", "example-project"], run.commands())

    def test_agent_opens_a_ticket_window_when_the_session_has_none(self):
        run = FakeRun(panes="example-project\t@5\tOther\t/x\n")
        message = start(run, "p", inside=True)
        self.assertEqual(run.commands()[0],
                         ["tmux", "new-window", "-t", "example-project:", "-n", "DEMO-1", "-c", "/wt/DEMO-1", "claude p"])
        self.assertEqual(run.commands()[1], ["tmux", "select-window", "-t", "example-project:DEMO-1"])
        self.assertEqual(message, "Claude Code started in DEMO-1 (new window): p")

    def test_agent_creates_the_session_when_tmux_has_no_server(self):
        run = FakeRun(no_server=True)
        start(run, "p", inside=False)
        self.assertEqual(run.commands()[0][:5], ["tmux", "new-session", "-d", "-s", "example-project"])

    def test_jump_selects_the_window_and_reports_it(self):
        run = FakeRun()
        self.assertEqual(tmux.jump(run, KEY, WORKTREE, True, SESSION), "Switched to Editor")
        self.assertEqual(run.commands(), [["tmux", "select-window", "-t", "@3"],
                                          ["tmux", "switch-client", "-t", "example-project"]])

    def test_jump_outside_tmux_returns_the_attach_target(self):
        self.assertEqual(tmux.jump(FakeRun(), KEY, WORKTREE, False, SESSION), "example-project")

    def test_jump_without_a_window_explains_configured_session(self):
        with self.assertRaisesRegex(RuntimeError, "No existing tmux window for DEMO-4; open a window in the configured session"):
            tmux.jump(FakeRun(), "DEMO-4", "", True, SESSION)

    def test_jump_does_not_hide_a_tmux_failure(self):
        with self.assertRaisesRegex(RuntimeError, "no server running"):
            tmux.jump(FakeRun(no_server=True), KEY, WORKTREE, True, SESSION)

    def test_switch_client_returns_none_inside_tmux_and_the_session_outside(self):
        run = FakeRun()
        self.assertIsNone(tmux.switch_client(run, True, SESSION))
        self.assertEqual(run.calls, [["tmux", "switch-client", "-t", "example-project"]])
        run = FakeRun()
        self.assertEqual(tmux.switch_client(run, False, SESSION), "example-project")
        self.assertEqual(run.calls, [])

    def test_browser_uses_os_opener_without_sourcing_a_shell(self):
        run = FakeRun()
        with patch('sidequest.terminal.sys.platform', 'darwin'):
            self.assertEqual(terminal.open_browser(run, 'https://github.com/o/r/pull/1?a=b&c=d'), 'Opened in browser')
        self.assertEqual(run.calls, [['open', 'https://github.com/o/r/pull/1?a=b&c=d']])

    def test_browser_uses_the_configured_command(self):
        run = FakeRun()
        terminal.open_browser(run, 'https://github.com/o/r/pull/1', 'firefox --new-tab')
        self.assertEqual(run.calls, [['firefox', '--new-tab', 'https://github.com/o/r/pull/1']])



if __name__ == "__main__":
    unittest.main()
