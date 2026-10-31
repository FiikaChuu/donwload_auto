"""Private bookkeeping lives in application data, never among downloaded media."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


def app_data_dir():
    override = os.environ.get("AFZAL_DATA_DIR")
    if override:
        root = Path(override)
    else:
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".config") / "AfzalDownloader"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def report_dir():
    root = app_data_dir() / "reports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def valid_manifest(data):
    if not isinstance(data, dict):
        return False
    for key, entry in data.items():
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
            return False
        if not isinstance(entry, dict) or set(entry) != {"name", "sha256"}:
            return False
        name = entry["name"]
        if not isinstance(name, str) or not name or name in {".", ".."} or re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
            return False
        if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            return False
    return True


class Manifest:
    def __init__(self, folder, log):
        self.folder = Path(folder).resolve()
        identity = hashlib.sha256(os.path.normcase(str(self.folder)).encode()).hexdigest()
        self.path = app_data_dir() / "manifests" / f"{identity}.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.data = {}
        if not valid_manifest(self.data):
            raise ValueError("Catatan aplikasi rusak. Pindahkan catatan di data aplikasi sebelum mencoba lagi.")
        self.migrated = False
        legacy = self.folder / ".afzal-manifest.json"
        if legacy.is_file() and not legacy.is_symlink():
            original = legacy.read_bytes()
            try:
                old = json.loads(original)
            except (ValueError, UnicodeDecodeError):
                old = None
            if valid_manifest(old):
                # Save the full record before removing the old application-only file.
                self.data = {**old, **self.data}
                atomic_json(self.path, self.data)
                if legacy.read_bytes() == original:
                    legacy.unlink()
                    self.migrated = True
                    log(f"Catatan lama folder {self.folder.name} dipindahkan ke data aplikasi.")
            else:
                log(f"Catatan di folder {self.folder.name} tidak dikenal; dibiarkan agar data pengguna tetap aman.")

    def record(self, key, name, checksum):
        self.data[key] = {"name": name, "sha256": checksum}
        atomic_json(self.path, self.data)
