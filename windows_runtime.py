"""Bootstrap with any installed Python; run the app only on supported stable Python."""
import json
import os
from pathlib import Path
import subprocess
import sys

SUPPORTED = ((3, 13), (3, 12), (3, 11))
ROOT = Path(__file__).resolve().parent
MISSING = """Python yang didukung belum ditemukan.
Aplikasi ini menggunakan Python stabil 3.13, 3.12, atau 3.11.
Python 3.15 tidak didukung oleh paket aplikasi ini.

Pasang Python 3.13 (64-bit) tanpa menghapus Python yang sudah ada.
Di PowerShell, jalankan:
  winget install -e --id Python.Python.3.13 --source winget
Atau ambil installer Windows dari https://www.python.org/downloads/windows/
Pastikan Python Launcher dan Tcl/Tk dipasang. Setelah instalasi selesai,
tutup jendela ini lalu buka setup_windows.bat lagi.
Tidak perlu memasang Visual C++ Build Tools.
"""


def probe(command):
    code = "import sys,json; print(json.dumps({'version':list(sys.version_info[:2]),'release':sys.version_info.releaselevel,'python':sys.executable}))"
    try:
        result = subprocess.run([*command, "-c", code], capture_output=True, text=True, timeout=20)
        if result.returncode:
            return None
        info = json.loads(result.stdout.strip())
        version = tuple(info["version"])
        if version in SUPPORTED and info["release"] == "final":
            return Path(info["python"]), version
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        pass
    return None


def find_python():
    for major, minor in SUPPORTED:
        found = probe(["py", f"-{major}.{minor}"])
        if found:
            return found
    # Also works without the launcher when invoked using a supported Python.
    return probe([sys.executable])


def environment_directory(root, version):
    name = f".venv-{version[0]}.{version[1]}"
    for index in range(1, 101):
        folder = root / (name if index == 1 else f"{name}-{index}")
        if not folder.exists():
            return folder
        interpreter = folder / "Scripts" / "python.exe"
        if interpreter.is_file():
            found = probe([str(interpreter)])
            if found and found[1] == version:
                return folder
    raise RuntimeError("Terlalu banyak folder instalasi tidak lengkap. Gunakan folder aplikasi yang baru diekstrak.")


def install(root=ROOT):
    found = find_python()
    if not found:
        raise RuntimeError(MISSING)
    base, version = found
    folder = environment_directory(root, version)
    python = folder / "Scripts" / "python.exe"
    print(f"Memakai Python stabil {version[0]}.{version[1]}.", flush=True)
    print(f"Lingkungan aplikasi: {folder.name}", flush=True)
    # Existing .venv folders (including Python 3.15) remain untouched.
    if not python.is_file():
        subprocess.run([str(base), "-m", "venv", str(folder)], cwd=root, check=True)
    subprocess.run([str(python), "-c", "import tkinter"], cwd=root, check=True)
    # Never fall back to compiling Pillow/greenlet with a local C++ compiler.
    subprocess.run([str(python), "-m", "pip", "install", "--only-binary=:all:",
                    "-r", str(root / "requirements.txt")], cwd=root, check=True)
    subprocess.run([str(python), "-m", "playwright", "install", "chromium"], cwd=root, check=True)
    marker = root / ".afzal-runtime.json"
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps({"python": python.relative_to(root).as_posix()}), encoding="utf-8")
    os.replace(temporary, marker)
    print("Selesai. Buka jalankan_windows.bat untuk menjalankan aplikasi.", flush=True)
    return 0


def run_app(root=ROOT):
    marker = root / ".afzal-runtime.json"
    python = None
    if marker.is_file():
        try:
            candidate = (root / json.loads(marker.read_text(encoding="utf-8"))["python"]).resolve()
            if candidate.is_relative_to(root.resolve()) and candidate.is_file() and probe([str(candidate)]):
                python = candidate
        except (ValueError, KeyError, TypeError):
            pass
    if python is None:
        raise RuntimeError("Jalankan setup_windows.bat versi terbaru terlebih dahulu. Installer akan memilih Python stabil, bukan 3.15.")
    return subprocess.run([str(python), str(root / "main.py")], cwd=root).returncode


def main():
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in {"install", "run"}:
            raise RuntimeError("Gunakan setup_windows.bat atau jalankan_windows.bat.")
        return install() if sys.argv[1] == "install" else run_app()
    except subprocess.CalledProcessError as error:
        print(f"\nLangkah instalasi/aplikasi gagal (kode {error.returncode}). Periksa pesan di atas.")
        print("Installer tidak mengompilasi paket dari sumber. Jika wheel tidak tersedia, gunakan Python 3.13 64-bit.")
        return 1
    except (OSError, RuntimeError) as error:
        print(f"\n{error}")
        return 1
    except KeyboardInterrupt:
        print("\nDibatalkan.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
