from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autodownload.downloads import Downloader, Pacer, Cancelled, AccessPaused, retry_after
from image_fixture import jpeg_bytes


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.waits.append(seconds)
        self.now += seconds
        return False


class PacingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache = tempfile.TemporaryDirectory()
        self.environ = patch.dict(os.environ, {"AFZAL_DATA_DIR": self.cache.name})
        self.environ.start()
        self.cancel = threading.Event()
        self.clock = Clock()
        self.wait = patch.object(self.cancel, "wait", side_effect=self.clock.wait)
        self.wait.start()
        self.d = Downloader(self.temp.name, self.cancel, lambda _: None)
        self.d.pacer.clock = self.clock

    def tearDown(self):
        self.d.close()
        self.wait.stop()
        self.environ.stop()
        self.temp.cleanup()
        self.cache.cleanup()

    def test_default_five_seconds_between_requests(self):
        starts = []
        session = Mock()
        def get(*args, **kwargs):
            starts.append(self.clock.now)
            return Mock(status_code=200)
        session.get.side_effect = get
        for _ in range(3):
            self.d.request("https://example.test/photo", session=session)
        self.assertEqual(starts, [0, 5, 10])

    def test_retry_after_wait_and_response_closed_before_retry(self):
        limited = Mock(status_code=429, headers={"Retry-After": "17"})
        okay = Mock(status_code=200)
        session = Mock()
        session.get.side_effect = [limited, okay]
        self.assertIs(self.d.request("https://example.test", session=session), okay)
        self.assertEqual(self.clock.waits, [17])
        limited.close.assert_called_once()

    def test_persistent_rate_limit_stops_after_bounded_retries(self):
        response = Mock(status_code=429, headers={})
        session = Mock()
        session.get.return_value = response
        with self.assertRaises(AccessPaused):
            self.d.request("https://example.test", session=session)
        self.assertEqual(session.get.call_count, 4)
        self.assertEqual(self.clock.waits, [5, 10, 20])

    def test_access_denial_stops_without_retry(self):
        session = Mock()
        session.get.return_value = Mock(status_code=403)
        with self.assertRaises(AccessPaused):
            self.d.request("https://example.test", session=session)
        self.assertEqual(session.get.call_count, 1)

    def test_cancel_during_wait_prevents_next_request(self):
        session = Mock()
        session.get.return_value = Mock(status_code=200)
        self.d.request("https://example.test", session=session)
        with patch.object(self.cancel, "wait", return_value=True):
            with self.assertRaises(Cancelled):
                self.d.request("https://example.test", session=session)
        self.assertEqual(session.get.call_count, 1)

    def test_retry_after_dates_and_invalid_values(self):
        date = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=60))
        self.assertTrue(58 <= retry_after(date) <= 60)
        for value in [None, "bad", "inf", "nan", "-1"]:
            self.assertEqual(retry_after(value), 0)

    def test_invalid_delays_rejected(self):
        for value in [-1, "nan", "inf", 301]:
            with self.assertRaises(ValueError):
                Pacer(value, self.cancel, lambda _: None)

    def test_public_drive_folder_downloads_each_file_with_delay(self):
        operations = []
        def listing(**kwargs):
            operations.append(("list", self.clock.now))
            self.assertTrue(kwargs["skip_download"])
            return [SimpleNamespace(id=f"file{i}", path=f"photo{i}.jpg",
                                    local_path=str(Path(kwargs["output"]) / "Album" / f"photo{i}.jpg")) for i in range(2)]
        def download(**kwargs):
            operations.append(("file", self.clock.now))
            Path(kwargs["output"]).write_bytes(jpeg_bytes())
            return kwargs["output"]
        with patch("gdown.download_folder", side_effect=listing), patch("gdown.download", side_effect=download):
            self.d.drive("https://drive.google.com/drive/folders/album-id", self.d.folder(9))
        self.assertEqual(operations, [("list", 0), ("file", 5), ("file", 10)])
        self.assertEqual(self.d.completed, 2)


if __name__ == "__main__":
    unittest.main()
