# Revisi Database Siaran KTVDI

## Perubahan antarmuka
- Halaman Database Siaran memakai tampilan data-center modern dengan header gelap futuristik, statistik ringkas, filter bertahap, kartu MUX, dan daftar kanal responsif.
- Daftar kanal baru ditampilkan setelah pengguna memilih Provinsi, Wilayah Layanan, dan MUX.
- Pencarian cepat dapat menyaring kanal pada MUX terpilih.

## Hak akses
- Admin dan penginput/pemilik data dapat mengedit atau menghapus data MUX dari halaman Database Siaran.
- Pengguna lain yang login dapat mengirim permohonan perubahan berisi daftar kanal usulan dan alasan (minimal 10 karakter).
- Permohonan hanya dapat diputuskan oleh admin atau pemilik/penginput asli data.
- Persetujuan langsung menerapkan daftar kanal usulan ke Firebase; penolakan tidak mengubah daftar kanal.
- Pemohon dapat melihat status permohonan. Admin/pemilik melihat seluruh permohonan yang menunggu dalam satu kotak persetujuan.

## Backend dan jejak audit
- Permohonan disimpan di `broadcast_edit_requests/{provinsi}/{wilayah}/{mux}/{username}`.
- Aksi persetujuan/penolakan dan perubahan data dicatat pada `audit_logs`.
- Persetujuan memeriksa apakah daftar kanal saat ini masih sama dengan daftar ketika permohonan dibuat, untuk mencegah permohonan lama menimpa perubahan yang lebih baru.
- Validasi nama kanal dijalankan kembali di backend.

## Pemeriksaan yang dilakukan
- `python -m py_compile backend.py`
- `node --check frontend/main.js`

Kedua pemeriksaan sintaks tersebut lulus. Integrasi Firebase dan uji alur pengguna langsung tetap perlu diuji pada environment deployment menggunakan data staging.
