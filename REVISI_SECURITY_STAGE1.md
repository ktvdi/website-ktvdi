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


## Halaman Database Siaran publik
- Menambahkan menu **Database Siaran** pada navigasi utama.
- Seluruh pengunjung, termasuk yang belum login, dapat melihat, mencari, dan memfilter data MUX/kanal yang telah dimuat backend.
- Pengunjung dapat membuka detail data; fitur kontribusi dan pengelolaan tetap memerlukan login serta pemeriksaan kepemilikan/admin.
- Halaman ini hanya menampilkan data siaran, bukan kredensial, email, atau data privat akun.

## Pemisahan hak akses titik pemancar dari data MUX
- Kepemilikan data siaran/MUX tetap memakai `created_by_username`.
- Titik koordinat memiliki identitas pengelola sendiri: `point_added_by_username`, `point_added_by_name`, dan `point_added_at`.
- Pengguna yang pertama kali menambahkan koordinat dapat memperbarui atau menghapus titik tersebut.
- Admin dapat memperbarui atau menghapus semua titik.
- Pemilik MUX tidak otomatis mendapat hak atas titik koordinat jika bukan pembuat titik.
- Titik lama yang belum memiliki catatan pembuat hanya dapat dikelola admin.
- Pemeriksaan hak akses dilakukan di backend; kontrol frontend hanya membantu menampilkan tombol yang sesuai.


## Mekanisme persetujuan perubahan titik pemancar
- Menu **Tambah Titik Pemancar** diubah namanya menjadi **Kelola Titik Pemancar**.
- Pembuat titik dan admin dapat mengubah/menghapus titik secara langsung.
- Pengguna lain mengajukan perubahan disertai alasan melalui halaman Kelola Titik Pemancar.
- Untuk titik yang memiliki identitas pembuat, permohonan dapat disetujui oleh admin atau pembuat titik (salah satu persetujuan cukup).
- Untuk titik lama tanpa identitas pembuat, hanya admin yang dapat menyetujui permohonan.
- Setelah disetujui, pemohon dapat menyimpan satu kali perubahan koordinat; persetujuan ditandai selesai.
- Hak pemilik MUX tidak memberikan hak khusus atas titik pemancar.
- Pengajuan, persetujuan, penolakan, dan perubahan dicatat dalam audit log.


## Kotak masuk persetujuan titik pemancar
- Halaman Kelola Titik Pemancar kini menampilkan kotak masuk permohonan yang dapat diputuskan oleh akun yang sedang login.
- Admin melihat seluruh permohonan berstatus Menunggu, termasuk titik tanpa identitas pembuat.
- Pembuat titik melihat permohonan untuk titik yang dibuatnya.
- Tombol Setujui/Tolak pada kotak masuk membawa identitas titik dari kartu permohonan, sehingga tidak bergantung pada titik yang sedang dipilih.
