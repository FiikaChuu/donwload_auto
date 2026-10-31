from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from openpyxl import Workbook
import requests

from autodownload.downloads import Downloader, Cancelled, safe_name
from autodownload.models import Cell, select_tasks, spreadsheet_id
from autodownload.sheets import SheetSource


def cells(*values):
    return [Cell(str(v)) for v in values]


class SelectionTests(unittest.TestCase):
    def test_only_exact_afzal_and_inclusive_business_number(self):
        rows = [cells("Judul"), cells("No.", "PIC", "Reference", "Link Drive"),
                cells(7, "afzal", "https://example.com/7.jpg"),
                cells(8, " AfZaL ", "https://example.com/8.jpg"),
                cells(9, "kayla", "https://example.com/no.jpg"),
                cells(14, "afzal", "https://example.com/14.jpg"),
                cells(15, "afzal", "https://example.com/15.jpg"),
                cells(10, "afzal backup", "https://example.com/no.jpg"),
                cells(8, "afzal", "https://example.com/extra.jpg"),
                cells(11, "afzal", "Tidak ada link")]
        tasks = select_tasks(rows, 8, 14)
        self.assertEqual([t.number for t in tasks], [8, 14, 8, 11])
        self.assertEqual(tasks[0].sheet_row, 4)
        self.assertEqual(tasks[-1].urls, ())

    def test_link_formula_rich_link_and_custom_columns(self):
        rows = [cells("No", "PIC", "Bahan"),
                [Cell("9.0"), Cell("afzal"), Cell('=HYPERLINK("https://example.com/a.jpg","foto")',
                                                     ("https://example.com/a.jpg", "https://example.com/b.jpg"))]]
        self.assertEqual(select_tasks(rows, 9, 9, "C")[0].urls,
                         ("https://example.com/a.jpg", "https://example.com/b.jpg"))

    def test_invalid_range_headers_and_columns(self):
        for rows, start, end, cols in [([], 8, 14, ""), ([cells("No", "PIC", "Link")], 14, 8, ""),
                                       ([cells("No", "PIC", "Link")], 8, 14, "../../")]:
            with self.assertRaises(ValueError):
                select_tasks(rows, start, end, cols)

    def test_spreadsheet_url_validation(self):
        ident = "a" * 40
        self.assertEqual(spreadsheet_id(f"https://docs.google.com/spreadsheets/d/{ident}/edit#gid=9"), ident)
        with self.assertRaises(ValueError):
            spreadsheet_id(f"https://evil.example/spreadsheets/d/{ident}")


class SheetTests(unittest.TestCase):
    def test_public_xlsx_multiple_tabs_and_hyperlinks(self):
        workbook = Workbook()
        workbook.active.title = "FEEDS-OKT"
        workbook.active.append(["No.", "PIC", "Reference", "Link Drive"])
        workbook.active.append([9, "afzal", "Lihat foto", '=HYPERLINK("https://example.com/video.mp4","Video")'])
        workbook.active["C2"].hyperlink = "https://example.com/photo.jpg"
        workbook.create_sheet("FEEDS-NOV")
        data = BytesIO()
        workbook.save(data)
        source = SheetSource("a" * 40)
        source.session = Mock()
        source.session.get.return_value = Mock(content=data.getvalue())
        self.assertEqual(source.load(), ["FEEDS-OKT", "FEEDS-NOV"])
        tasks = select_tasks(source.rows("FEEDS-OKT"), 9, 9)
        self.assertEqual(tasks[0].urls, ("https://example.com/photo.jpg", "https://example.com/video.mp4"))
        source.close()

    def test_login_html_is_not_treated_as_workbook(self):
        source = SheetSource("a" * 40)
        source.session = Mock()
        source.session.get.return_value = Mock(content=b"<html>Login</html>")
        with self.assertRaisesRegex(ValueError, "OAuth"):
            source.load()

    def test_private_rich_links_formula_and_absolute_sheet_row(self):
        source = SheetSource("a" * 40)
        source.private = True
        source.session = Mock()
        source.session.get.return_value.json.return_value = {"sheets": [{"data": [{"startRow": 2, "rowData": [
            {"values": [{"formattedValue": "No."}, {"formattedValue": "PIC"}, {"formattedValue": "Reference"}]},
            {"values": [{"formattedValue": "9"}, {"formattedValue": "afzal"},
                        {"formattedValue": "Foto", "hyperlink": "https://example.com/a.jpg",
                         "textFormatRuns": [{"format": {"link": {"uri": "https://example.com/b.jpg"}}}]}]}]}]}]}
        tasks = select_tasks(source.rows("O'Brien"), 9, 9)
        self.assertEqual(tasks[0].sheet_row, 4)
        self.assertEqual(len(tasks[0].urls), 2)
        self.assertEqual(source.session.get.call_args.kwargs["params"]["ranges"], "'O''Brien'")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/fail":
            self.send_error(404)
            return
        body = b"<html>Login required</html>" if self.path == "/html" else b"photo-original-bytes" * 1000
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if self.path == "/html" else "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", 'attachment; filename="photo.jpg"')
        self.end_headers()
        self.wfile.write(body)


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cancel = threading.Event()
        self.downloader = Downloader(self.temp.name, self.cancel, lambda _: None)

    def tearDown(self):
        self.downloader.close()
        self.temp.cleanup()

    def test_filter_to_numbered_folders_real_http_and_repeat(self):
        rows = [cells("No.", "PIC", "Reference"),
                cells(9, "afzal", self.url + "/a"),
                cells(9, "afzal", self.url + "/b"),
                cells(10, "kayla", self.url + "/c"),
                cells(15, "afzal", self.url + "/d")]
        tasks = select_tasks(rows, 8, 14)
        for task in tasks:
            for url in task.urls:
                self.downloader.download(url, task.number)
        folder = Path(self.temp.name) / "9"
        self.assertEqual(len(list(folder.glob("*.jpg"))), 2)
        self.assertFalse((Path(self.temp.name) / "10").exists())
        self.assertFalse((Path(self.temp.name) / "15").exists())
        for photo in folder.glob("*.jpg"):
            self.assertEqual(photo.read_bytes(), b"photo-original-bytes" * 1000)
        self.downloader.close()
        self.downloader = Downloader(self.temp.name, self.cancel, lambda _: None)
        self.downloader.download(self.url + "/a", 9)
        self.assertEqual(self.downloader.skipped, 1)
        self.assertEqual(len(list(folder.glob("*.jpg"))), 2)

    def test_deduplicate_same_link_for_same_number_but_not_other_number(self):
        self.downloader.download(self.url + "/a", 9)
        self.downloader.download(self.url + "/a", 9)
        self.downloader.download(self.url + "/a", 10)
        self.assertEqual(self.downloader.completed, 2)

    def test_http_error_html_and_cancel_leave_no_partial_file(self):
        folder = self.downloader.folder(9)
        with self.assertRaises(requests.HTTPError):
            self.downloader.direct(self.url + "/fail", folder)
        with self.assertRaisesRegex(ValueError, "halaman web"):
            self.downloader.direct(self.url + "/html", folder)
        self.cancel.set()
        with self.assertRaises(Cancelled):
            self.downloader.direct(self.url + "/a", folder)
        self.assertEqual(list(folder.iterdir()), [])

    def test_cancel_during_transfer_cleans_partial(self):
        response = Mock()
        response.headers = {"Content-Type": "image/jpeg"}
        def chunks(_):
            yield b"first part"
            self.cancel.set()
            yield b"last part"
        response.iter_content.side_effect = chunks
        session = Mock()
        session.get.return_value.__enter__ = Mock(return_value=response)
        session.get.return_value.__exit__ = Mock(return_value=False)
        folder = self.downloader.folder(9)
        with self.assertRaises(Cancelled):
            self.downloader.direct(self.url + "/a", folder, session=session)
        self.assertEqual(list(folder.iterdir()), [])

    def test_existing_user_file_preserved_and_modified_file_not_skipped(self):
        folder = self.downloader.folder(9)
        path, _ = self.downloader._target(folder, self.url + "/a", "photo.jpg")
        path.write_bytes(b"my own photo")
        self.downloader.direct(self.url + "/a", folder)
        self.assertEqual(path.read_bytes(), b"my own photo")
        self.assertEqual(len(list(folder.glob("*.jpg"))), 2)
        self.downloader.direct(self.url + "/a", folder)
        self.assertEqual(len(list(folder.glob("*.jpg"))), 2)
        ledger = json.loads((folder / ".afzal-manifest.json").read_text())
        saved = folder / next(iter(ledger.values()))["name"]
        saved.write_bytes(b"manual edit")
        self.downloader.direct(self.url + "/a", folder)
        self.assertEqual(saved.read_bytes(), b"manual edit")
        self.assertEqual(len(list(folder.glob("*.jpg"))), 3)

    def test_safe_filename(self):
        for name in ["../../evil.jpg", "CON", "NUL.txt", "a:b?.jpg"]:
            cleaned = safe_name(name)
            self.assertNotIn("/", cleaned)
            self.assertNotIn("\\", cleaned)
            self.assertNotIn(":", cleaned)
            self.assertNotIn(cleaned, {"CON", "NUL.txt"})

    def test_private_drive_pagination_and_shortcut_cycle(self):
        session = Mock()
        def get(url, params, timeout):
            if url.endswith("/root"):
                data = {"id": "root", "name": "Album", "mimeType": "application/vnd.google-apps.folder"}
            elif url.endswith("/shortcut"):
                data = {"mimeType": "application/vnd.google-apps.shortcut", "shortcutDetails": {"targetId": "root"}}
            elif url.endswith("/child"):
                data = {"name": "Foto.jpg", "mimeType": "image/jpeg"}
            elif params.get("pageToken") == "next":
                data = {"files": [{"id": "child"}]}
            else:
                data = {"files": [{"id": "shortcut"}], "nextPageToken": "next"}
            response = Mock()
            response.json.return_value = data
            return response
        session.get.side_effect = get
        self.downloader.drive_session = session
        with patch.object(self.downloader, "direct") as direct:
            self.downloader.drive("https://drive.google.com/drive/folders/root", self.downloader.folder(9))
        self.assertEqual(direct.call_count, 1)
        self.assertEqual(direct.call_args.kwargs["key"], "drive:child")


if __name__ == "__main__":
    unittest.main()
