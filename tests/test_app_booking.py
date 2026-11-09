"""sqapp: one worktree at a time uses the project's shared local app."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'ticket-tui')]

SWITCH = 'from pathlib import Path; import os, sys; Path(sys.argv[1]).write_text(os.getcwd()); sys.exit(int(sys.argv[2]))'
CURRENT = 'from pathlib import Path; import sys; p = Path(sys.argv[1]); print(p.read_text() if p.exists() else "")'


class AppBookingTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.state = self.root / 'state'
        self.mounted = self.root / 'mounted'
        (self.root / 'switch.py').write_text(SWITCH)
        (self.root / 'current.py').write_text(CURRENT)
        self.a, self.b = self.repo('APP-1-totals'), self.repo('APP-2-export')
        self.configure()

    def repo(self, name):
        path = self.root / name
        path.mkdir()
        subprocess.run(['git', 'init', '-q'], cwd=path, check=True)
        (path / '.env').write_text('LOCAL=1\n')
        return path

    def configure(self, fail=0, **extra):
        app = {'url': 'http://localhost:3010',
               'switch_command': f'{sys.executable} {self.root / "switch.py"} {self.mounted} {fail}',
               'current_command': f'{sys.executable} {self.root / "current.py"} {self.mounted}',
               'running_command': f'{sys.executable} -c print(True)',
               'required_files': '.env', **extra}
        (self.root / 'config.json').write_text(json.dumps({'app': app}))

    def sqapp(self, where, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('SIDEQUEST_', 'GIT_'))}
        env.update(SIDEQUEST_CONFIG=str(self.root / 'config.json'), XDG_STATE_HOME=str(self.state),
                   PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run([sys.executable, '-B', str(ROOT / 'bin/sqapp'), *args], cwd=where, env=env,
                              capture_output=True, text=True)

    def lock(self):
        return self.state / 'sidequest' / 'app.lock'

    def test_one_worktree_books_and_switches_and_others_get_busy_until_release(self):
        first = self.sqapp(self.a)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.mounted.read_text(), str(self.a))
        self.assertIn('http://localhost:3010', first.stdout)
        busy = self.sqapp(self.b)
        self.assertEqual(busy.returncode, 75)
        self.assertIn('APP-1-totals', busy.stderr)
        self.assertEqual(self.mounted.read_text(), str(self.a), 'a busy app is never switched')
        left = self.sqapp(self.b, '--release')
        self.assertIn('not this worktree', left.stdout)
        self.assertTrue(self.lock().exists())
        status = self.sqapp(self.b, '--status')
        self.assertIn('booked:  APP-1-totals', status.stdout)
        self.assertIn('running: APP-1-totals', status.stdout)
        self.assertEqual(self.sqapp(self.a, '--release').returncode, 0)
        self.assertFalse(self.lock().exists())
        second = self.sqapp(self.b)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.mounted.read_text(), str(self.b))

    def test_rebooking_the_running_worktree_does_not_switch_again(self):
        self.sqapp(self.a)
        self.mounted.write_text(str(self.a))
        os.utime(self.mounted, (1, 1))
        again = self.sqapp(self.a)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn('already runs', again.stdout)
        self.assertEqual(self.mounted.stat().st_mtime, 1, 'switch_command was not run')

    def test_a_host_mount_prefix_still_counts_as_this_worktree(self):
        self.sqapp(self.a)
        self.mounted.write_text('/host_mnt' + str(self.a))
        os.utime(self.mounted, (1, 1))
        again = self.sqapp(self.a)
        self.assertIn('already runs', again.stdout)
        self.assertEqual(self.mounted.stat().st_mtime, 1)

    def test_an_expired_booking_is_taken_over_and_force_takes_a_live_one(self):
        self.sqapp(self.a)
        old = int(time.time()) - 31 * 60
        self.lock().write_text(f'{self.a}\t{old}\t{old}\n')
        taken = self.sqapp(self.b)
        self.assertEqual(taken.returncode, 0, taken.stderr)
        self.assertIn('expired booking', taken.stdout)
        forced = self.sqapp(self.a, '--force')
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual(self.mounted.read_text(), str(self.a))

    def test_wait_gives_up_after_the_configured_minutes(self):
        self.configure(wait_minutes='0')
        self.sqapp(self.a)
        waited = self.sqapp(self.b, '--wait')
        self.assertEqual(waited.returncode, 75)

    def test_a_failed_switch_releases_the_booking(self):
        self.configure(fail=3)
        failed = self.sqapp(self.a)
        self.assertEqual(failed.returncode, 1)
        self.assertIn('releasing the booking', failed.stderr)
        self.assertFalse(self.lock().exists())

    def test_missing_files_and_missing_setup_are_errors_before_booking(self):
        (self.b / '.env').unlink()
        missing = self.sqapp(self.b)
        self.assertEqual(missing.returncode, 1)
        self.assertIn('.env', missing.stderr)
        (self.root / 'config.json').write_text('{}')
        unset = self.sqapp(self.a)
        self.assertEqual(unset.returncode, 1)
        self.assertIn('app.switch_command', unset.stderr)
        self.assertFalse(self.lock().exists())

    def test_outside_a_git_checkout_it_refuses(self):
        outside = self.sqapp(self.root)
        self.assertEqual(outside.returncode, 1)
        self.assertIn('git', outside.stderr)

    def test_app_settings_are_validated(self):
        from sidequest import config
        path = self.root / 'bad.json'
        for app in ({'url': 'ftp://x'}, {'ttl_minutes': 'soon'}, {'switch_command': 'make "up'}, {'other': 'x'}):
            with self.subTest(app=app):
                path.write_text(json.dumps({'app': app}))
                with self.assertRaises(ValueError):
                    config.load(path)


class BookingLabelTests(unittest.TestCase):
    def test_the_dashboard_label_names_the_ticket_and_idle_time(self):
        from sidequest import app_booking
        now = 10_000
        self.assertEqual(app_booking.label(app_booking.parse(f'/wt/APP-807-prices\t{now - 900}\t{now - 120}', now, 1800)),
                         'App APP-807 · idle 2m')
        self.assertEqual(app_booking.label(app_booking.parse(f'/wt/hotfix\t{now}\t{now - 10}', now, 1800)),
                         'App hotfix · idle <1m')
        self.assertEqual(app_booking.label(app_booking.parse(f'/wt/APP-1\t1\t{now - 1801}', now, 1800)), 'App free')
        self.assertEqual(app_booking.label(app_booking.parse('garbage', now, 1800)), 'App free')


if __name__ == '__main__':
    unittest.main()
