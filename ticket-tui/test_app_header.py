"""The header shows who has the shared app booked, only when sqapp is configured."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from core import Store
from tui import App


class AppHeaderTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        with tempfile.TemporaryDirectory() as folder:
            self.app = App(self.store, Path(folder), demo=True)
        self.app.demo = False

    def test_booking_is_shown_when_configured_and_hidden_otherwise(self):
        booking = {"state": "booked", "owner": "APP-807", "idle_seconds": 120}
        with patch("sidequest.app_booking.configured", return_value=True), \
                patch("sidequest.app_booking.read", return_value=booking):
            self.assertTrue(self.app.header_status()[0].endswith("App APP-807 · idle 2m"))
        self.app.booking_read_at = None
        with patch("sidequest.app_booking.configured", return_value=False):
            self.assertNotIn("App ", self.app.header_status()[0])

    def test_demo_never_reads_the_booking(self):
        self.app.demo = True
        with patch("sidequest.app_booking.configured", return_value=True), \
                patch("sidequest.app_booking.read") as read:
            self.assertNotIn("App ", self.app.header_status()[0])
        read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
