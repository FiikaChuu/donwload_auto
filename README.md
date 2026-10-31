# Afzal Sheets Downloader

Aplikasi desktop berbahasa Indonesia untuk mengambil bahan dari Google Sheets khusus PIC **afzal**. Dibuat untuk penggunaan lokal, terutama Windows seperti contoh pengguna.

## Fitur

- Muat daftar tab dan pilih satu tab, misalnya `FEEDS-OKT` atau `FEEDS-NOV`.
- Pilih rentang inklusif berdasarkan **isi kolom No.**, misalnya 8–14, bukan nomor baris di kiri Sheets.
- Filter PIC tepat `afzal`, tanpa membedakan kapital dan spasi tepi. PIC lain tidak ikut.
- Pratinjau nomor, baris asal, jumlah tautan, dan status sebelum mengunduh.
- Pilih folder di komputer sendiri. Semua bahan No. 9 masuk ke `<folder pilihan>/9/`.
- Baca tautan teks, hyperlink, rumus `HYPERLINK`, serta rich links melalui API privat.
- Sumber: file HTTP/HTTPS langsung, file/folder Google Drive, dan galeri Fotorek melalui Chromium.
- Proses di latar belakang, pembatalan, laporan JSON, pencegahan file parsial, dan pemeriksaan SHA-256 agar file lengkap dapat dilewati saat dijalankan ulang.
- File dengan nama sama dari sumber berbeda diberi akhiran ID pendek; file lama/hasil edit manual tidak ditimpa.
- Gambar diperiksa sebelum disimpan; ekstensi disesuaikan dengan format aslinya tanpa mengompres ulang. Berkas rusak yang berlabel gambar ditolak.
- Catatan unduhan dan laporan tersimpan di data aplikasi, sehingga folder nomor hanya berisi bahan unduhan.
- Jeda minimum dapat diatur 1–300 detik (bawaan 5 detik), unduhan berurutan, dan pembatasan server ditangani tanpa mengulang tanpa batas.

## Jalankan di Windows

1. Pasang **Python stabil 3.13 (disarankan), 3.12, atau 3.11** dari python.org, termasuk Python Launcher dan Tcl/Tk (opsi bawaan installer Windows). Python 3.15 belum didukung. Python versi lain boleh tetap terpasang.
2. Unduh/clone repository ini, lalu buka `setup_windows.bat` sekali. Internet diperlukan untuk dependensi dan Chromium.
3. Buka `jalankan_windows.bat`.
4. Tempel tautan Google Sheets. Untuk Sheets publik, cukup izinkan **Anyone with the link → Viewer** jika memang boleh dibagikan. Untuk data privat, gunakan OAuth di bawah tanpa mengubah izin publik.
5. Klik **Muat tab**, pilih tab, isi nomor awal/akhir, pilih folder tujuan, dan atur **Jeda minimum (detik)**. Mulai dengan 5–10 detik, lalu perbesar bila layanan meminta.
6. Klik **Pratinjau Afzal**, periksa daftarnya, lalu **Mulai unduh**.

Aplikasi menyimpan ke perangkat tempat aplikasi berjalan. Aplikasi yang berjalan di cloud tidak dapat memilih drive `D:` pada komputer Windows milik pengguna; jalankan lokal untuk itu.

Jeda berlaku antarawal permintaan HTTP/file yang dijalankan aplikasi, termasuk metadata Drive dengan OAuth, antarfile Drive publik, pembukaan galeri, langkah scroll, dan tombol unduh galeri. Transfer dari tombol galeri ditunggu selesai sebelum tombol berikutnya ditekan. Jeda dan waktu tunggu bisa dibatalkan melalui tombol **Batalkan**. Permintaan internal browser (misalnya gambar saat halaman dimuat), pengalihan HTTP, autentikasi, dan pemindaian folder oleh gdown tidak seluruhnya bisa diatur dengan interval ini.

Untuk HTTP langsung dan Drive API, respons `429`/gangguan sementara memakai jeda bertambah dan mengikuti `Retry-After` (angka detik atau tanggal HTTP), maksimal tiga percobaan ulang. Jika tetap dibatasi atau server menolak dengan `403`, batch dihentikan dan penyebabnya dicatat dalam laporan. Buka kembali hanya setelah menunggu/perizinan diperbaiki. Membuka halaman Fotorek yang memberi `403` atau `429` juga menghentikan batch. Pengaturan ini mengurangi frekuensi akses; tidak menjamin lolos deteksi bot dan tidak melewati login, CAPTCHA, atau batas layanan.

Installer mencari versi stabil yang didukung secara eksplisit, membuat lingkungan terpisah seperti `.venv-3.13`, dan launcher memakai lingkungan hasil instalasi tersebut. `.venv` lama dari Python 3.15 dibiarkan, sehingga tidak perlu menghapusnya secara manual. Paket dipasang dari wheel biner; installer tidak mencoba mengompilasi Pillow dan tidak memerlukan Visual C++ Build Tools.

Jika muncul pesan Pillow tidak mendukung Python 3.15 / gagal membangun wheel, unduh kode terbaru dan pasang Python 3.13 terlebih dahulu. Di PowerShell bisa menggunakan:

```powershell
winget install -e --id Python.Python.3.13 --source winget
```

Setelah instalasi Python selesai, tutup jendela installer lama dan jalankan `setup_windows.bat` terbaru. Paket biner juga bergantung pada arsitektur mesin; gunakan installer Python 64-bit yang sesuai perangkat.

## Sheets / Drive privat: Login Google

Tidak perlu memberikan kata sandi ke aplikasi atau mengirim token ke siapa pun.

1. Di Google Cloud Console, buat/pilih project dan aktifkan **Google Sheets API** serta **Google Drive API**.
2. Konfigurasikan OAuth consent screen. Jika aplikasi berstatus Testing, tambahkan akun Google sendiri sebagai test user.
3. Buat **OAuth Client ID → Desktop app**, lalu unduh JSON-nya. Ini adalah OAuth Desktop JSON, bukan service account JSON.
4. Di aplikasi, pilih JSON tersebut pada **OAuth JSON (opsional)**, lalu klik **Muat tab**. Login melalui browser dengan akun yang punya akses ke Sheets dan file Drive.
5. Izinkan akses baca Sheets dan Drive. Aplikasi tidak meminta akses tulis.

Token tersimpan lokal di `%LOCALAPPDATA%/AfzalDownloader/` (Windows), atau `~/.config/AfzalDownloader/` (Linux/macOS). Untuk mengganti akun, tutup aplikasi, hapus token dari lokasi itu, lalu login ulang. Jangan commit atau bagikan JSON/token. Aplikasi tidak menyimpan lokasi OAuth atau tautan Sheets dalam repository.

Login Sheets/Drive tidak otomatis memberi akses ke Fotorek; Fotorek adalah layanan terpisah.

## Format Sheets

Dalam 100 baris pertama harus ada satu baris header yang memuat `No.` (atau `No`, `Nomor`, `Number`) dan `PIC`.

| No. | Reference | Location | PIC | Link Drive |
| --- | --- | --- | --- | --- |
| 8 | tautan galeri/file | MOBIL | afzal | tautan Drive opsional |
| 9 | tautan galeri/file | Wey | kayla | |
| 14 | tautan galeri/file | Mori | Afzal | |

Rentang 8–14 mengambil No. 8 dan 14 dari tabel ini. No. 9 tidak diambil karena PIC kayla. Jika ada beberapa baris Afzal dengan nomor yang sama, hasilnya digabung ke folder nomor yang sama.

Kolom tautan otomatis: `Reference`, `Referensi`, `Link Drive`, `Drive`, `Link`, `URL`, atau `Tautan`. Jika nama berbeda, isi huruf kolom dipisah koma, misalnya **B,G**. Kolom tersembunyi tetap terbaca. Baris tanpa tautan ditandai dan dilewati. Nomor harus berupa bilangan bulat nonnegatif (termasuk nilai numerik seperti `9.0`). Rumus nomor menggunakan nilai cache dari ekspor Google bila tersedia.

## Dukungan unduhan dan batasannya

- **File langsung:** foto, video, PDF, ZIP, dan berkas lainnya. Halaman HTML/login ditolak, bukan disimpan sebagai foto palsu. Tautan ke halaman Instagram/TikTok bukan tautan file langsung dan belum didukung.
- **Drive publik:** memakai gdown untuk file/folder dengan izin Viewer melalui tautan. Batas kuota dan pembatasan unduh Google tetap berlaku; folder besar dapat terkena batas gdown. Gunakan OAuth untuk folder privat/besar. Pembatalan Drive publik menunggu transfer aktif selesai.
- **Drive dengan OAuth:** folder ditelusuri rekursif dengan pagination, termasuk shared drives dan shortcut yang dapat diakses akun. Semua isi diratakan ke folder nomor, nama diberi ID agar tidak bentrok. Google Docs/Slides diekspor PDF, Sheets XLSX, Drawing PNG. Jenis Google lain yang tidak didukung dilaporkan gagal.
- **Fotorek:** Chromium membuka halaman, memicu lazy load, mencari tombol unduh serta link download. Jika tidak tersedia, aplikasi mencoba mengambil foto/video berukuran besar yang tampil dan mencatat bahwa kualitas/kelengkapan **perlu diperiksa**. Logo kecil diabaikan. ZIP dari tombol unduh disimpan utuh, tidak diekstrak otomatis. Tidak melewati login, CAPTCHA, atau pembatasan situs.
- **Status Fotorek:** implementasi ini belum diverifikasi terhadap galeri Fotorek asli karena akses `app.fotorek.id` diblokir jaringan lingkungan pengembangan. Jangan menganggap seluruh file asli pasti terambil sebelum diuji pada galeri pengguna; struktur situs mungkin memerlukan penyesuaian. Pesan “Selesai diproses” tidak menjamin kelengkapan galeri.
- Chromium membutuhkan desktop grafis. Jika halaman perlu login atau tidak menampilkan media, proses akan melaporkan masalah; tidak mengklaim sukses saat tidak ada file. Kredensial Google tidak digunakan untuk masuk Fotorek.
- Foto/video yang terhapus, tautan kedaluwarsa, atau izin kurang dilaporkan dalam log. Baris berikutnya tetap diproses.
- Catatan checksum tersimpan di `%LOCALAPPDATA%/AfzalDownloader/manifests/` di Windows (Linux/macOS: `~/.config/AfzalDownloader/manifests/`). Catatan dibedakan per lokasi tujuan dan nomor, tanpa menyimpan tautan/token. Rerun Drive publik masih perlu mengambil data sementara sebelum pemeriksaan duplikat.
- Laporan `laporan-<waktu>.json` tersimpan di `%LOCALAPPDATA%/AfzalDownloader/reports/`, dengan lokasi lengkap ditampilkan pada log aplikasi. Isinya tab, nomor/baris, jumlah file, dan masalah. Log tidak menyimpan query URL bertoken.

## Memperbarui versi lama dan merapikan manifest

Unduh ZIP GitHub terbaru, ekstrak ke folder aplikasi baru, lalu jalankan `setup_windows.bat` lagi karena versi ini menambahkan Pillow untuk pemeriksaan gambar. Pilih lokasi hasil unduhan lama, misalnya `Downloads/hasil donlod` (folder induk yang berisi `8`, `9`, `11`, dan seterusnya), lalu klik **Rapikan folder lama**.

Tombol ini memindahkan `.afzal-manifest.json` versi lama ke data aplikasi setelah salinannya berhasil disimpan. Foto/video tetap di lokasi semula dan catatan unduhan ulang tetap tersedia. Format catatan yang tidak dikenal tidak dihapus. Saat mengunduh lagi, folder nomor yang dipakai juga otomatis dirapikan. Laporan lama yang sudah terlanjur tersimpan di folder tujuan tidak dihapus otomatis.

## Foto tidak terbuka: “Package could not be registered”

Pesan ini biasanya berasal dari registrasi aplikasi **Microsoft Photos** di Windows, bukan bukti bahwa gambar rusak. Jika Explorer masih menampilkan pratinjau, coba klik kanan gambar → **Open with / Buka dengan → Paint**, atau seret gambarnya ke Chrome/Edge. Jika terbuka, perbaiki Microsoft Photos melalui **Settings → Apps → Installed apps → Microsoft Photos → Advanced options → Repair**.

Versi ini memeriksa isi gambar sebelum menyimpan, menolak gambar yang gagal dibaca, dan membetulkan ekstensi (misalnya file JPEG berlabel PNG menjadi `.jpg`). Gambar tidak dikonversi atau dikompres ulang. Pemeriksaan ini tidak memperbaiki registrasi aplikasi Windows dan tidak mengubah file hasil unduhan lama. Kirim contoh berkas jika gambar juga gagal dibuka di Paint atau browser agar isi file bisa diperiksa.

## Linux / macOS dan pengembangan

Gunakan checkout yang ada; tidak perlu Git worktree baru.

```sh
python3 -m venv .venv
# Windows alternatif: .venv\Scripts\activate
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

Tkinter harus tersedia; di Ubuntu paketnya `python3-tk`. Chromium di Linux mungkin membutuhkan dependensi sistem Playwright (`python -m playwright install-deps chromium`). Tidak perlu menjalankan layanan server terpisah.

Jalankan tes tanpa akun Google atau internet:

```sh
python -m unittest discover -s tests -v
```

Tes menguji filter PIC dan nomor, beberapa tab dan hyperlink XLSX, pembacaan rich links API, unduhan HTTP nyata pada server lokal, penggabungan folder, unduhan ulang, pembatalan, kesalahan, preservasi file lama, dan pagination Drive melalui respons simulasi. Integrasi Google/Fotorek asli dan UI Windows memerlukan pengujian pada perangkat/akun pengguna.

Tes tambahan mencakup pemindahan manifest lama, preservasi catatan jika penyimpanan gagal, pemisahan cache berdasarkan lokasi tujuan, penolakan gambar palsu/rusak, dan koreksi ekstensi tanpa mengubah byte gambar. Tes GUI dilewati bila Linux tidak memiliki display; tes browser opsional dijalankan jika variabel `AFZAL_TEST_CHROMIUM` berisi path executable Chromium. Tidak ada tes pada Google/Fotorek asli atau Windows yang diklaim telah lulus.
