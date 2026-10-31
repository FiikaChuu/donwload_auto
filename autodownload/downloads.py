"""Download adapters. Files are committed atomically after successful transfer."""
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qs, unquote, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class Cancelled(Exception):
    pass


def safe_name(value):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", unquote(value)).strip(" .")[:160]
    if not name or name in {".", ".."}:
        name = "file"
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        name = "_" + name
    return name


class Downloader:
    def __init__(self, destination, cancel, log, drive_session=None):
        self.root = Path(destination).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.cancel = cancel
        self.log = log
        self.drive_session = drive_session
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.mount("http://", HTTPAdapter(max_retries=retries))
        self.browser = self.playwright = None
        self.visited = set()
        self.completed = 0
        self.skipped = 0

    def check(self):
        if self.cancel.is_set():
            raise Cancelled("Dibatalkan pengguna.")

    def folder(self, number):
        target = self.root / str(number)
        target.mkdir(exist_ok=True)
        if target.resolve().parent != self.root:
            raise ValueError("Folder nomor mengarah ke luar lokasi tujuan.")
        return target

    def _target(self, folder, key, filename):
        digest = hashlib.sha256(key.encode()).hexdigest()
        try:
            recorded = json.loads((folder / ".afzal-manifest.json").read_text(encoding="utf-8")).get(digest, {}).get("name")
            if recorded and safe_name(recorded) == recorded:
                return folder / recorded, digest
        except (FileNotFoundError, ValueError):
            pass
        name = safe_name(filename)
        p = Path(name)
        return folder / f"{p.stem[:130]}_{digest[:12]}{p.suffix[:20]}", digest

    def _known(self, folder, path, digest):
        ledger = folder / ".afzal-manifest.json"
        try:
            data = json.loads(ledger.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {}
        entry = data.get(digest, {})
        if path.is_file() and entry.get("name") == path.name and entry.get("sha256") == self._hash(path):
            self.skipped += 1
            self.log(f"Lewati file yang sudah lengkap: {path.name}")
            return True
        return False

    @staticmethod
    def _hash(path):
        with path.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    def _commit(self, temporary, path, digest):
        self.check()
        if path.exists() and not self._known(path.parent, path, digest):
            # Preserve an unrelated or manually changed file.
            base = path
            index = 2
            while path.exists():
                path = base.with_name(f"{base.stem} ({index}){base.suffix}")
                index += 1
        os.replace(temporary, path)
        ledger = path.parent / ".afzal-manifest.json"
        try:
            data = json.loads(ledger.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {}
        data[digest] = {"name": path.name, "sha256": self._hash(path)}
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".manifest-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temp, ledger)
        finally:
            Path(temp).unlink(missing_ok=True)
        self.completed += 1
        self.log(f"Tersimpan: {path.parent.name}/{path.name}")

    def direct(self, url, folder, filename=None, session=None, key=None):
        self.check()
        session = session or self.session
        with session.get(url, stream=True, timeout=(20, 90)) as response:
            response.raise_for_status()
            kind = response.headers.get("Content-Type", "").split(";")[0].lower()
            if kind in {"text/html", "application/xhtml+xml"}:
                raise ValueError("Tautan membuka halaman web, bukan file. Gunakan tautan file, Drive, atau galeri Fotorek.")
            if not filename:
                from email.message import Message
                msg = Message()
                msg["content-disposition"] = response.headers.get("Content-Disposition", "")
                filename = msg.get_filename() or Path(urlsplit(url).path).name or "file"
            if not Path(filename).suffix:
                filename += mimetypes.guess_extension(kind) or ""
            path, digest = self._target(folder, key or url, filename)
            if self._known(folder, path, digest):
                return
            fd, temp = tempfile.mkstemp(dir=folder, prefix=".download-", suffix=".part")
            count = 0
            try:
                with os.fdopen(fd, "wb") as f:
                    for chunk in response.iter_content(256 * 1024):
                        self.check()
                        if chunk:
                            f.write(chunk)
                            count += len(chunk)
                expected = response.headers.get("Content-Length")
                if expected and not response.headers.get("Content-Encoding") and count != int(expected):
                    raise IOError("Ukuran unduhan tidak lengkap.")
                if not count:
                    raise IOError("Server mengirim file kosong.")
                self._commit(temp, path, digest)
            finally:
                Path(temp).unlink(missing_ok=True)

    def download(self, url, number):
        self.check()
        folder = self.folder(number)
        marker = (number, url)
        if marker in self.visited:
            return
        before = self.completed + self.skipped
        host = (urlsplit(url).hostname or "").lower()
        if host in {"drive.google.com", "docs.google.com"}:
            self.drive(url, folder)
        elif host == "app.fotorek.id":
            self.fotorek(url, folder)
        else:
            self.direct(url, folder)
        if self.completed + self.skipped == before:
            raise ValueError("Sumber kosong atau tidak ada file yang dapat diunduh.")
        self.visited.add(marker)

    def drive(self, url, folder):
        match = re.search(r"/(?:folders|d)/([\w-]+)", urlsplit(url).path)
        file_id = match.group(1) if match else parse_qs(urlsplit(url).query).get("id", [None])[0]
        if not file_id:
            raise ValueError("ID file/folder Google Drive tidak ditemukan.")
        if self.drive_session:
            self._private_drive(file_id, folder, set())
            return
        import gdown
        self.log("Mengunduh Drive publik; tombol Batal berlaku setelah transfer Drive ini selesai.")
        with tempfile.TemporaryDirectory(prefix=".drive-", dir=folder) as temp:
            if "/folders/" in url:
                output = gdown.download_folder(url=url, output=temp + os.sep, quiet=True,
                                              remaining_ok=False, verify=True)
                if not output:
                    raise ValueError("Folder Drive kosong atau tidak dapat diakses. Gunakan Login Google jika dibatasi.")
            else:
                output = gdown.download(id=file_id, output=temp + os.sep, quiet=True, fuzzy=True, verify=True)
                if not output:
                    raise ValueError("File Drive tidak dapat diunduh; periksa izin Viewer.")
            for source in sorted(Path(temp).rglob("*")):
                self.check()
                if source.is_file():
                    rel = source.relative_to(temp).as_posix()
                    path, digest = self._target(folder, f"drive:{file_id}:{rel}", source.name)
                    if not self._known(folder, path, digest):
                        self._commit(source, path, digest)

    def _private_drive(self, file_id, folder, seen):
        self.check()
        if file_id in seen:
            return
        seen.add(file_id)
        session = self.drive_session
        base = "https://www.googleapis.com/drive/v3/files"
        response = session.get(f"{base}/{file_id}", params={"fields": "id,name,mimeType,shortcutDetails", "supportsAllDrives": "true"}, timeout=60)
        response.raise_for_status()
        meta = response.json()
        kind = meta["mimeType"]
        if kind == "application/vnd.google-apps.shortcut":
            self._private_drive(meta["shortcutDetails"]["targetId"], folder, seen)
        elif kind == "application/vnd.google-apps.folder":
            token = None
            while True:
                self.check()
                params = {"q": f"'{file_id}' in parents and trashed = false", "fields": "nextPageToken,files(id)",
                          "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
                if token:
                    params["pageToken"] = token
                response = session.get(base, params=params, timeout=60)
                response.raise_for_status()
                data = response.json()
                for child in data.get("files", []):
                    self._private_drive(child["id"], folder, seen)
                token = data.get("nextPageToken")
                if not token:
                    break
        else:
            exports = {
                "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
                "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
                "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
                "application/vnd.google-apps.drawing": ("image/png", ".png"),
            }
            if kind in exports:
                mime, ext = exports[kind]
                from urllib.parse import urlencode
                url = f"{base}/{file_id}/export?" + urlencode({"mimeType": mime})
                name = meta["name"] + ext
            elif kind.startswith("application/vnd.google-apps."):
                raise ValueError("Jenis dokumen Google ini tidak mendukung ekspor otomatis.")
            else:
                url = f"{base}/{file_id}?alt=media&supportsAllDrives=true"
                name = meta["name"]
            self.direct(url, folder, name, session, key=f"drive:{file_id}")

    def fotorek(self, url, folder):
        """Use rendered page and real download events; never save the HTML as media."""
        from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
        if not self.playwright:
            self.playwright = sync_playwright().start()
            try:
                self.browser = self.playwright.chromium.launch(headless=False)
            except Exception:
                self.playwright.stop()
                self.playwright = None
                raise ValueError("Browser Chromium belum tersedia. Jalankan: python -m playwright install chromium (desktop grafis diperlukan).") from None
        context = self.browser.new_context(accept_downloads=True)
        page = context.new_page()
        captures = []
        page.on("download", lambda download: captures.append(download))
        before = self.completed + self.skipped
        try:
            self.log("Membuka galeri Fotorek di Chromium…")
            response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if response and response.status >= 400:
                raise ValueError(f"Fotorek mengembalikan HTTP {response.status}.")
            page.wait_for_timeout(2000)
            # Trigger lazy-loaded gallery entries without assuming API endpoints.
            previous = None
            for _ in range(20):
                self.check()
                state = page.evaluate("[document.body.scrollHeight, document.images.length]")
                if state == previous:
                    break
                previous = state
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(600)
            links = page.locator("a[download]").evaluate_all("els => els.map(e => e.href).filter(u => /^https?:/.test(u))")
            buttons = page.get_by_role("button", name=re.compile(r"download|unduh", re.I))
            self.log("Mencari tombol unduh dan media pada galeri…")
            for i in range(min(buttons.count(), 100)):
                self.check()
                button = buttons.nth(i)
                if button.is_visible() and button.is_enabled():
                    try:
                        with page.expect_download(timeout=10000):
                            button.click(timeout=5000)
                    except BrowserTimeout:
                        # A button may reveal download links rather than trigger a file.
                        pass
            for i, download in enumerate(captures):
                self.check()
                if download.failure():
                    raise ValueError("Unduhan galeri gagal di browser.")
                path, digest = self._target(folder, f"{url}:browser:{i}:{download.suggested_filename}", download.suggested_filename)
                if self._known(folder, path, digest):
                    continue
                fd, temp = tempfile.mkstemp(dir=folder, prefix=".download-", suffix=".part")
                os.close(fd)
                try:
                    download.save_as(temp)
                    self._commit(temp, path, digest)
                finally:
                    Path(temp).unlink(missing_ok=True)
            # Prefer explicit file links. If absent, use full-size rendered media.
            links += page.locator("a[download]").evaluate_all("els => els.map(e => e.href).filter(u => /^https?:/.test(u))")
            if not captures and not links:
                links = page.evaluate("""() => [...document.querySelectorAll('video, video source, audio, audio source, img')]
                    .filter(e => e.tagName !== 'IMG' || (e.naturalWidth >= 320 && e.naturalHeight >= 320 && !/logo|avatar|icon/i.test(e.alt + ' ' + e.className)))
                    .map(e => e.currentSrc || e.src).filter(u => /^https?:/.test(u))""")
                if links:
                    self.log("Galeri tidak menyediakan unduhan eksplisit; mengambil media yang tampil. Kelengkapan/orisinal perlu diperiksa.")
            for cookie in context.cookies():
                self.session.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie["path"])
            self.session.headers["Referer"] = url
            self.session.headers["User-Agent"] = page.evaluate("navigator.userAgent")
            for link in dict.fromkeys(links):
                self.check()
                self.direct(link, folder)
            if self.completed + self.skipped == before:
                raise ValueError("Tidak ada file ditemukan pada galeri Fotorek. Galeri mungkin perlu login atau format situs berubah; jangan anggap lengkap.")
        finally:
            context.close()
            self.session.headers.pop("Referer", None)

    def close(self):
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        self.session.close()
