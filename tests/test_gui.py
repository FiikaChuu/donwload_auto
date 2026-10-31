"""Run on a desktop or virtual X display; skipped when DISPLAY is absent on Linux."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import os
import json
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
from autodownload.models import Task
from image_fixture import jpeg_bytes


@unittest.skipIf(sys.platform.startswith("linux") and not os.environ.get("DISPLAY"), "Requires graphical display")
class GuiWorkflowTests(unittest.TestCase):
    def test_server_denial_stops_remaining_rows_and_reports_pause(self):
        requests_seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                requests_seen.append(self.path)
                self.send_error(403)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        from types import SimpleNamespace
        app.source = SimpleNamespace(private=False, close=lambda: None)
        try:
            with tempfile.TemporaryDirectory() as output, tempfile.TemporaryDirectory() as app_data, patch.dict(os.environ, {"AFZAL_DATA_DIR": app_data}), patch("autodownload.app.messagebox.showerror") as error:
                app.tasks = [Task(9, 10, (f"http://127.0.0.1:{server.server_port}/blocked",)),
                             Task(10, 11, (f"http://127.0.0.1:{server.server_port}/next",))]
                for i in range(2):
                    app.tree.insert("", "end", iid=str(i), values=(9+i, 10+i, 1, "Siap"))
                app.destination.set(output)
                app.delay.set("1")
                app.download()
                deadline = time.monotonic() + 10
                while app.busy and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                self.assertFalse(app.busy)
                self.assertEqual(requests_seen, ["/blocked"])
                self.assertIn("403", app.status.get())
                report = json.loads(next((Path(app_data) / "reports").glob("*.json")).read_text())
                self.assertIn("403", report["stopped_reason"])
                self.assertEqual(report["delay_seconds"], 1)
                self.assertEqual(report["rows"][0]["status"], "dihentikan server")
                error.assert_not_called()
        finally:
            app.close()
            server.shutdown()
            server.server_close()
            thread.join()

    def test_load_select_tab_preview_download_and_invalidate(self):
        workbook = Workbook()
        workbook.active.title = "FEEDS-OKT"
        workbook.create_sheet("FEEDS-NOV")
        data = BytesIO()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                body = data.getvalue() if self.path == "/sheet" else jpeg_bytes()
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
            with tempfile.TemporaryDirectory() as output, tempfile.TemporaryDirectory() as app_data, patch.dict(os.environ, {"AFZAL_DATA_DIR": app_data}), patch.object(requests.Session, "get", routed_get), patch("autodownload.app.messagebox.showerror") as error:
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
                self.assertEqual(photos[0].read_bytes(), jpeg_bytes())
                self.assertEqual(len(list((Path(app_data) / "reports").glob("laporan-*.json"))), 1)
                self.assertEqual(list(Path(output).glob("laporan-*.json")), [])
                self.assertEqual(list(Path(output).rglob(".afzal-manifest.json")), [])
                self.assertFalse((Path(output) / "10").exists())
                self.assertIn("1 file tersimpan", app.status.get())
                # Exercise the cleanup action on an old-version record too.
                manifest = next((Path(app_data) / "manifests").glob("*.json"))
                legacy = Path(output) / "9" / ".afzal-manifest.json"
                legacy.write_text(json.dumps(json.loads(manifest.read_text())))
                app.tidy()
                wait()
                self.assertFalse(legacy.exists())
                self.assertEqual(photos[0].read_bytes(), jpeg_bytes())
                self.assertIn("1 catatan lama", app.status.get())
                app.start.set("10")
                self.assertFalse(app.tasks)
                self.assertEqual(str(app.download_button["state"]), "disabled")
                error.assert_not_called()
        finally:
            app.close()
            server.shutdown()
            server.server_close()
            server_thread.join()


if __name__ == "__main__":
    unittest.main()
