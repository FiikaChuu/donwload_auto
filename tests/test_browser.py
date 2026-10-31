"""Optional real-browser checks against a local gallery fixture, not Fotorek live."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

from autodownload.downloads import Downloader


def png_image():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    pixels = b"".join(b"\x00" + b"\x40\x80\xc0" * 400 for _ in range(400))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 400, 400, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


@unittest.skipUnless(os.environ.get("AFZAL_TEST_CHROMIUM"), "Optional: set AFZAL_TEST_CHROMIUM to installed Chromium path")
class BrowserGalleryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        image = png_image()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path == "/photo.png":
                    body, kind = image, "image/png"
                elif self.path == "/button":
                    body = b'''<button onclick="const a=document.createElement('a');a.href='/photo.png';a.download='photo.png';a.click();">Unduh semua</button>'''
                    kind = "text/html"
                elif self.path == "/link":
                    body, kind = b'<a download href="/photo.png">Unduh</a>', "text/html"
                else:
                    body, kind = b'<main><img alt="Foto acara" src="/photo.png"></main>', "text/html"
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_download_button_explicit_link_and_rendered_media(self):
        from playwright.sync_api import BrowserType
        original = BrowserType.launch
        def launch(browser_type, **kwargs):
            kwargs["executable_path"] = os.environ["AFZAL_TEST_CHROMIUM"]
            return original(browser_type, **kwargs)
        with tempfile.TemporaryDirectory() as output, tempfile.TemporaryDirectory() as app_data, patch.dict(os.environ, {"AFZAL_DATA_DIR": app_data}), patch.object(BrowserType, "launch", launch):
            messages = []
            downloader = Downloader(output, threading.Event(), messages.append)
            try:
                for number, route in enumerate(["button", "link", "media"], 8):
                    folder = downloader.folder(number)
                    downloader.fotorek(f"http://127.0.0.1:{self.server.server_port}/{route}", folder)
                    photos = list(folder.glob("*.png"))
                    self.assertEqual(len(photos), 1, route)
                    self.assertEqual(photos[0].read_bytes(), png_image())
                self.assertEqual(downloader.completed, 3)
                self.assertTrue(any("Kelengkapan/orisinal" in message for message in messages))
            finally:
                downloader.close()


if __name__ == "__main__":
    unittest.main()
