# Struktur layanan backend KTVDI

Backend dipisahkan berdasarkan tanggung jawab tanpa mengubah kontrak event yang digunakan frontend.

## Struktur

```text
backend.py
services/
├── __init__.py
├── core.py
├── auth.py
├── broadcasts.py
└── community.py
```

## Pembagian tanggung jawab

- `services/core.py`: waktu WIB, inisialisasi Firebase, validasi key, audit log, dan pemeriksaan autentikasi/otorisasi.
- `services/auth.py`: hashing password dan OTP, verifikasi/migrasi hash, login, dan pengiriman OTP.
- `services/broadcasts.py`: pembacaan, pencarian, statistik, dan riwayat perubahan data siaran.
- `services/community.py`: penyajian data publik pengguna, laporan, profil, dan komentar.
- `backend.py`: titik masuk kompatibilitas untuk `app.py` dan orkestrasi event dari frontend melalui `handle_event()`.

## Kompatibilitas

Nama fungsi layanan tetap diekspor dari `backend.py`. Dengan demikian, pemanggil lama seperti `app.py` tidak perlu diubah. Format event dan bentuk respons `handle_event()` juga dipertahankan.

## Validasi

Seluruh berkas Python diperiksa menggunakan parser/kompilasi sintaks Python. Pengujian import dan integrasi Firebase belum dapat dijalankan pada lingkungan ini karena dependensi `firebase_admin` tidak terpasang dan kredensial Firebase tidak tersedia.

## Langkah lanjutan

`handle_event()` masih menjadi orkestrator event agar perubahan ini tidak mengubah perilaku aplikasi secara luas. Tahap refactoring berikutnya dapat memindahkan kelompok aksi (autentikasi, siaran, komunitas, laporan, koordinat, dan administrasi) ke modul handler masing-masing, disertai unit test untuk tiap aksi.


## Pemisahan handler event (tahap 2)

Aksi dari frontend kini didelegasikan dari `backend.handle_event()` ke handler berdasarkan fitur:

```text
handlers/
├── __init__.py
├── auth_handler.py
├── broadcast_handler.py
├── coordinate_handler.py
├── measurement_handler.py
├── community_handler.py
└── report_admin_handler.py
```

- `auth_handler.py`: login, logout, registrasi, verifikasi OTP, dan reset password.
- `broadcast_handler.py`: permintaan perubahan data siaran, tambah/edit/hapus siaran, dan data teknis.
- `coordinate_handler.py`: permintaan perubahan titik, persetujuan, penyimpanan, dan penghapusan koordinat.
- `measurement_handler.py`: pengiriman/pemuatan pengukuran, detail, dan kalkulasi terrain.
- `community_handler.py`: profil, komentar, komunitas, dan chatbot.
- `report_admin_handler.py`: laporan koreksi dan operasi administrasi.

`backend.handle_event()` tetap menjadi satu pintu masuk dan mempertahankan format event/response yang digunakan frontend. Validasi dan pemeriksaan otorisasi yang sebelumnya berada di setiap aksi dipertahankan dalam handler terkait.

## Status pengujian tahap 2

- Pemeriksaan sintaks Python berhasil untuk seluruh 16 file Python.
- Seluruh aksi fitur yang dipindahkan memiliki handler.
- Belum dilakukan uji runtime, Firebase, email SMTP, Gemini, atau simulasi terrain karena dependensi dan kredensial layanan eksternal tidak tersedia di lingkungan pemeriksaan.
- Sebelum deployment, jalankan smoke test untuk login, registrasi/OTP, operasi data siaran, koordinat, pengukuran, laporan, serta akses admin.
