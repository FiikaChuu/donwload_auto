import json
from datetime import datetime
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urlsplit

from .downloads import Downloader, Cancelled
from .models import select_tasks
from .sheets import SheetSource
from .storage import report_dir


def readable_error(error):
    # Signed media URLs and OAuth tokens must not appear in UI logs or reports.
    text = re.sub(r"https?://[^\s\"'<>]+", lambda m: (urlsplit(m[0]).hostname or "server"), str(error))
    return text[:700] or type(error).__name__


class App:
    def __init__(self, root):
        self.root = root
        root.title("Afzal • Sheets Downloader")
        root.geometry("1020x790")
        root.minsize(850, 670)
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.source = None
        self.loaded_identity = None
        self.tasks = []
        self.busy = False
        self.closing = False
        self.url = tk.StringVar()
        self.client = tk.StringVar()
        self.tab = tk.StringVar()
        self.start = tk.StringVar(value="8")
        self.end = tk.StringVar(value="14")
        self.columns = tk.StringVar()
        self.destination = tk.StringVar(value=str(Path.home() / "Downloads" / "Afzal"))
        self.status = tk.StringVar(value="Masukkan tautan Sheets, lalu klik Muat tab.")
        self.controls = []
        self._build()
        for variable in [self.url, self.client, self.tab, self.start, self.end, self.columns]:
            variable.trace_add("write", self.invalidate)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def _build(self):
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TButton", padding=(12, 7))
        style.configure("Title.TLabel", font=("Segoe UI", 21, "bold"))
        style.configure("Treeview", rowheight=28)
        base = ttk.Frame(self.root, padding=22)
        base.pack(fill="both", expand=True)
        ttk.Label(base, text="Sheets → folder, otomatis.", style="Title.TLabel").pack(anchor="w")
        ttk.Label(base, text="Khusus PIC Afzal · pilih tab · tentukan rentang nomor · simpan semua bahan per nomor").pack(anchor="w", pady=(4, 16))
        form = ttk.LabelFrame(base, text="1. Sumber & filter", padding=12)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        self.entry(form, "Tautan Google Sheets", self.url, 0)
        self.button(form, "Muat tab", self.load, row=0, column=2)
        self.entry(form, "OAuth JSON (opsional)", self.client, 1)
        self.button(form, "Pilih JSON…", self.choose_client, row=1, column=2)
        ttk.Label(form, text="Tab sheet").grid(row=2, column=0, sticky="w", pady=5)
        self.tabs_box = ttk.Combobox(form, textvariable=self.tab, state="readonly")
        self.tabs_box.grid(row=2, column=1, sticky="ew", padx=10, pady=5)
        self.controls.append((self.tabs_box, "readonly"))
        self.button(form, "Muat ulang", self.load, row=2, column=2)
        filters = ttk.Frame(form)
        filters.grid(row=3, column=1, columnspan=2, sticky="w", padx=10, pady=5)
        ttk.Label(form, text="Nomor (kolom No.)").grid(row=3, column=0, sticky="w")
        for text, variable in [("Dari", self.start), ("sampai", self.end)]:
            ttk.Label(filters, text=text).pack(side="left", padx=(0, 8))
            widget = ttk.Entry(filters, textvariable=variable, width=9)
            widget.pack(side="left", padx=(0, 16))
            self.controls.append((widget, "normal"))
        ttk.Label(filters, text="PIC: afzal (tetap)").pack(side="left")
        self.entry(form, "Kolom tautan", self.columns, 4)
        ttk.Label(form, text="Kosong = deteksi Reference + Link Drive. Atau isi B,G. Akses Sheets privat perlu OAuth.", wraplength=850).grid(row=5, column=0, columnspan=3, sticky="w", pady=(5, 0))
        output = ttk.LabelFrame(base, text="2. Lokasi penyimpanan di perangkat ini", padding=12)
        output.pack(fill="x", pady=12)
        output.columnconfigure(0, weight=1)
        entry = ttk.Entry(output, textvariable=self.destination)
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.controls.append((entry, "normal"))
        self.button(output, "Pilih folder…", self.choose_folder, row=0, column=1)
        self.button(output, "Rapikan folder lama", self.tidy, row=0, column=2)
        ttk.Label(output, text="Contoh: D:/Bahan/9/ berisi file untuk No. 9. File lama tidak ditimpa; ZIP disimpan sebagai ZIP.").grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        actions = ttk.Frame(base)
        actions.pack(fill="x", pady=(0, 10))
        self.button(actions, "3. Pratinjau Afzal", self.preview, side="left")
        self.download_button = ttk.Button(actions, text="4. Mulai unduh", command=self.download, state="disabled")
        self.download_button.pack(side="left", padx=10)
        self.cancel_button = ttk.Button(actions, text="Batalkan", command=self.stop, state="disabled")
        self.cancel_button.pack(side="left")
        self.button(actions, "Panduan", self.help, side="right")
        table = ttk.Frame(base)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("no", "row", "links", "status"), show="headings", height=6)
        for key, label, width in [("no", "No.", 65), ("row", "Baris Sheets", 100), ("links", "Jumlah tautan", 110), ("status", "Status", 530)]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, stretch=(key == "status"))
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.progress = ttk.Progressbar(base, mode="indeterminate")
        self.progress.pack(fill="x", pady=(12, 8))
        ttk.Label(base, textvariable=self.status, wraplength=950).pack(anchor="w")
        self.logs = tk.Text(base, height=6, wrap="word", state="disabled", font=("Consolas", 9))
        self.logs.pack(fill="x", pady=(8, 0))

    def entry(self, parent, label, variable, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5)
        widget = ttk.Entry(parent, textvariable=variable)
        widget.grid(row=row, column=1, sticky="ew", padx=10, pady=5)
        self.controls.append((widget, "normal"))

    def button(self, parent, text, command, **placement):
        widget = ttk.Button(parent, text=text, command=command)
        if "row" in placement:
            widget.grid(**placement, sticky="ew", pady=5)
        else:
            widget.pack(**placement)
        self.controls.append((widget, "normal"))
        return widget

    def invalidate(self, *_):
        self.tasks = []
        self.download_button.configure(state="disabled")
        for item in self.tree.get_children():
            self.tree.delete(item)

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Pilih lokasi folder hasil unduhan")
        if folder:
            self.destination.set(folder)

    def choose_client(self):
        path = filedialog.askopenfilename(title="Pilih OAuth Client Desktop JSON", filetypes=[("JSON", "*.json")])
        if path:
            self.client.set(path)

    def tidy(self):
        destination = self.destination.get().strip()
        if not destination or not Path(destination).is_dir():
            messagebox.showerror("Pilih folder", "Pilih lokasi hasil unduhan lama terlebih dahulu (folder induk yang berisi folder nomor).")
            return

        def work():
            downloader = Downloader(destination, self.cancel, self.log)
            try:
                count = downloader.tidy()
                self.emit("status", f"Selesai: {count} catatan lama dipindahkan ke data aplikasi. Foto/video tetap tersimpan.")
            finally:
                downloader.close()
        self.run(work, "Memindahkan catatan lama ke data aplikasi…")

    def emit(self, event, payload):
        self.events.put((event, payload))

    def log(self, message):
        self.emit("log", message)

    def run(self, function, status):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self.status.set(status)
        for widget, _ in self.controls:
            widget.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.start(12)

        def work():
            try:
                function()
            except Cancelled:
                self.emit("status", "Dibatalkan. File yang sudah selesai tetap tersimpan.")
            except Exception as error:
                self.emit("error", readable_error(error))
            finally:
                self.emit("idle", None)
        threading.Thread(target=work, daemon=True).start()

    def load(self):
        identity = self.url.get().strip(), self.client.get().strip()
        self.invalidate()

        def work():
            source = SheetSource(*identity)
            try:
                tabs = source.load()
                if self.cancel.is_set():
                    raise Cancelled()
                self.emit("loaded", (identity, source, tabs))
            except Exception:
                source.close()
                raise
        self.run(work, "Memuat daftar tab… Login Google dibuka di browser jika OAuth dipilih.")

    def preview(self):
        identity = self.url.get().strip(), self.client.get().strip()
        if not self.source or identity != self.loaded_identity:
            messagebox.showinfo("Muat Sheets", "Klik Muat tab dahulu setelah mengubah tautan atau OAuth.")
            return
        try:
            start, end = int(self.start.get()), int(self.end.get())
            if start < 0 or end < start:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Rentang salah", "Isi nomor awal dan akhir dengan bilangan bulat; akhir ≥ awal.")
            return
        tab, cols = self.tab.get(), self.columns.get()
        self.invalidate()

        def work():
            tasks = select_tasks(self.source.rows(tab), start, end, cols)
            if self.cancel.is_set():
                raise Cancelled()
            self.emit("preview", tasks)
        self.run(work, "Membaca baris dan menyaring PIC Afzal…")

    def download(self):
        if not self.tasks or not any(task.urls for task in self.tasks):
            return
        destination = self.destination.get().strip()
        if not destination:
            messagebox.showerror("Lokasi kosong", "Pilih folder tujuan terlebih dahulu.")
            return
        tasks = tuple(self.tasks)
        title = self.tab.get()
        session = self.source.session if self.source.private else None

        def work():
            downloader = Downloader(destination, self.cancel, self.log, session)
            report = {"sheet_tab": title, "pic": "afzal", "rows": []}
            failed = 0
            cancelled = False
            try:
                for index, task in enumerate(tasks):
                    downloader.check()
                    if not task.urls:
                        self.emit("row", (index, "Dilewati: tidak ada tautan"))
                        report["rows"].append({"number": task.number, "sheet_row": task.sheet_row, "status": "tanpa tautan"})
                        continue
                    self.emit("row", (index, "Mengunduh…"))
                    errors = []
                    for url in task.urls:
                        downloader.check()
                        try:
                            downloader.download(url, task.number)
                        except Cancelled:
                            raise
                        except Exception as error:
                            message = readable_error(error)
                            errors.append(message)
                            self.log(f"No. {task.number}: {message}")
                    state = f"Gagal/sebagian: {len(errors)} tautan bermasalah" if errors else "Selesai diproses (cek catatan galeri)"
                    failed += bool(errors)
                    self.emit("row", (index, state))
                    report["rows"].append({"number": task.number, "sheet_row": task.sheet_row, "status": state, "errors": errors})
            except Cancelled:
                cancelled = True
                self.emit("status", "Dibatalkan. File yang sudah selesai tetap tersimpan.")
            finally:
                downloader.close()
                report.update(files_saved=downloader.completed, files_skipped=downloader.skipped, cancelled=cancelled)
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                output = report_dir() / f"laporan-{timestamp}.json"
                output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
                self.log(f"Laporan: {output}")
            if not cancelled:
                self.emit("status", f"Proses berakhir: {downloader.completed} file tersimpan, {downloader.skipped} file dilewati, {failed} baris bermasalah. Periksa catatan galeri dan laporan.")
        self.run(work, "Mengunduh… jangan tutup aplikasi sampai proses berakhir.")

    def stop(self):
        self.cancel.set()
        self.status.set("Menunggu proses aktif berhenti… Transfer Drive publik/login dapat memerlukan waktu.")

    def poll(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "log":
                    self.logs.configure(state="normal")
                    self.logs.insert("end", value + "\n")
                    self.logs.see("end")
                    self.logs.configure(state="disabled")
                elif event in {"status", "error"}:
                    self.status.set(value)
                    if event == "error":
                        messagebox.showerror("Proses gagal", value)
                elif event == "loaded":
                    identity, source, tabs = value
                    if self.source:
                        self.source.close()
                    self.source = source
                    self.loaded_identity = identity
                    self.tabs_box.configure(values=tabs)
                    self.tab.set(tabs[0] if tabs else "")
                    self.status.set(f"{len(tabs)} tab dimuat. Pilih tab dan rentang, lalu Pratinjau.")
                elif event == "preview":
                    self.tasks = value
                    for index, task in enumerate(value):
                        self.tree.insert("", "end", iid=str(index), values=(task.number, task.sheet_row, len(task.urls), "Siap" if task.urls else "Tidak ada tautan"))
                    self.status.set(f"{len(value)} baris Afzal cocok; {sum(bool(t.urls) for t in value)} baris memiliki tautan.")
                elif event == "row":
                    index, state = value
                    if self.tree.exists(str(index)):
                        self.tree.set(str(index), "status", state)
                elif event == "idle":
                    self.busy = False
                    self.progress.stop()
                    for widget, state in self.controls:
                        widget.configure(state=state)
                    self.cancel_button.configure(state="disabled")
                    self.download_button.configure(state="normal" if any(t.urls for t in self.tasks) else "disabled")
                    if self.closing:
                        self.close()
                        return
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            if messagebox.askyesno("Proses masih berjalan", "Batalkan proses lalu tutup aplikasi setelah transfer aktif berhenti?"):
                self.closing = True
                self.stop()
            return
        if self.source:
            self.source.close()
        self.root.destroy()

    def help(self):
        messagebox.showinfo("Panduan singkat", "1. Tempel tautan Google Sheets. Akses publik cukup Viewer melalui tautan.\n"
                            "2. Untuk privat, pilih OAuth Desktop JSON (lihat README) dan login Google.\n"
                            "3. Muat tab, pilih tab, isi nomor awal/akhir berdasarkan kolom No.\n"
                            "4. Pilih folder di komputer ini, Pratinjau lalu Mulai unduh.\n\n"
                            "PIC harus tepat afzal (huruf besar/kecil dan spasi tepi diabaikan).\n"
                            "Nomor sama dari beberapa baris digabung ke folder yang sama.\n"
                            "Fotorek dibuka di Chromium; jika hanya media tampil ditemukan, kualitas dan kelengkapannya perlu diperiksa.\n"
                            "Drive privat memerlukan login dengan akun yang memiliki akses.\n"
                            "Jangan bagikan file OAuth/token. Hasil unduh tetap privat di folder pilihanmu.")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
