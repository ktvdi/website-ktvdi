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
