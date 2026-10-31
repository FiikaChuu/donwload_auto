"""Run on a desktop or virtual X display; skipped when DISPLAY is absent on Linux."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from openpyxl import Workbook
import requests

from autodownload.app import App


@unittest.skipIf(sys.platform.startswith("linux") and not os.environ.get("DISPLAY"), "Requires graphical display")
class GuiWorkflowTests(unittest.TestCase):
    def test_load_select_tab_preview_download_and_invalidate(self):
        workbook = Workbook()
        workbook.active.title = "FEEDS-OKT"
        workbook.create_sheet("FEEDS-NOV")
        data = BytesIO()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                body = data.getvalue() if self.path == "/sheet" else b"test-photo-bytes"
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream" if self.path == "/sheet" else "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        local = f"http://127.0.0.1:{server.server_port}"
        for sheet in workbook:
            sheet.append(["No.", "PIC", "Reference"])
        workbook["FEEDS-NOV"].append([9, "afzal", local + "/photo.jpg"])
        workbook["FEEDS-NOV"].append([10, "kayla", local + "/photo.jpg"])
        workbook.save(data)
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        original_get = requests.Session.get
        def routed_get(session, url, **kwargs):
            if url.startswith("https://docs.google.com/"):
                url = local + "/sheet"
                kwargs.pop("params", None)
            return original_get(session, url, **kwargs)
        def wait():
            deadline = time.monotonic() + 10
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            self.assertFalse(app.busy, "Worker did not finish")
        try:
            with tempfile.TemporaryDirectory() as output, patch.object(requests.Session, "get", routed_get), patch("autodownload.app.messagebox.showerror") as error:
                app.url.set("https://docs.google.com/spreadsheets/d/" + "a" * 40 + "/edit")
                app.load()
                wait()
                self.assertEqual(tuple(app.tabs_box["values"]), ("FEEDS-OKT", "FEEDS-NOV"))
                app.tab.set("FEEDS-NOV")
                app.preview()
                wait()
                self.assertEqual(len(app.tasks), 1)
                self.assertEqual(app.tasks[0].number, 9)
                self.assertEqual(str(app.download_button["state"]), "normal")
                app.destination.set(output)
                app.download()
                wait()
                photos = list((Path(output) / "9").glob("*.jpg"))
                self.assertEqual(len(photos), 1)
                self.assertEqual(photos[0].read_bytes(), b"test-photo-bytes")
                self.assertEqual(len(list(Path(output).glob("laporan-*.json"))), 1)
                self.assertFalse((Path(output) / "10").exists())
                self.assertIn("1 file tersimpan", app.status.get())
                app.start.set("10")
                self.assertFalse(app.tasks)
                self.assertEqual(str(app.download_button["state"]), "disabled")
                error.assert_not_called()
        finally:
            if app.source:
                app.source.close()
            root.destroy()
            server.shutdown()
            server.server_close()
            server_thread.join()


if __name__ == "__main__":
    unittest.main()
