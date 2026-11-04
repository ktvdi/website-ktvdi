# Revisi Security Stage 1 — KTVDI

## Perubahan antarmuka
- Tombol **Edit data siaran** dan **Hapus data siaran** ditampilkan pada panel detail pemancar hanya untuk pemilik data atau admin.
- Form edit memeriksa izin tampilan sebelum ditampilkan. Pemeriksaan otorisasi backend tetap menjadi pengaman utama.
- Form perubahan parameter teknis pemancar hanya ditampilkan kepada admin. Pengguna biasa tetap dapat mengirim pengukuran aktual dan komentar.
- Data lama yang tidak memiliki identitas pemilik tidak menampilkan tombol edit/hapus bagi pengguna biasa.

## Cara menguji
1. Deploy folder proyek ini.
2. Login sebagai pengguna biasa, buka **Peta Pemancar**.
3. Pilih MUX melalui dropdown **Pilih MUX bertitik**. Panel detail akan muncul di bawah peta.
4. Untuk data milik akun tersebut, tombol **Edit data siaran** dan **Hapus data siaran** akan tampil.
5. Untuk data milik akun lain atau data tanpa pemilik, tombol tersebut tidak tampil.
6. Login sebagai admin dan ulangi; admin dapat mengelola semua data siaran dan mengubah parameter teknis.

## Catatan
- Pengujian ini perlu dilakukan pada akun yang memang memiliki data siaran. Jika belum ada, buat satu data uji melalui menu **Tambah Data** saat login dengan akun pengguna biasa.
- Perubahan dalam ZIP tidak otomatis mengubah website yang sedang online. Deploy ulang proyek ini terlebih dahulu.
- Otorisasi backend tetap wajib; menyembunyikan tombol di frontend bukan pengganti pemeriksaan server.
