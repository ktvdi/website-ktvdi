# KTVDI — migrasi frontend HTML/CSS/JavaScript

## Status pekerjaan
Ini adalah **migrasi bertahap yang sudah diperluas**, tetapi belum boleh dianggap sebagai rilis produksi atau pengganti final sebelum uji integrasi Firebase, SMTP, Gemini, dan peta/DEM dilakukan pada deployment Anda. `legacy_app.py` adalah salinan utuh aplikasi Streamlit lama sebagai referensi dan cadangan. Entry point baru adalah `app.py`.

## Arsitektur
- `app.py`: Streamlit Community Cloud sebagai host Python dan jembatan custom component. Tidak menggunakan widget Streamlit untuk UI aplikasi.
- `frontend/index.html`, `style.css`, `main.js`: tampilan dan interaksi HTML/CSS/JavaScript.
- `backend.py`: autentikasi, Firebase Realtime Database, OTP email, CRUD, laporan, komunitas, chatbot, dan validasi otorisasi.
- `terrain.py`: fungsi estimasi propagasi dan difraksi terrain/DEM yang dipindahkan dari aplikasi lama.
- `legacy_app.py`: aplikasi lama, tidak dihapus.

## Fitur yang sudah dipindahkan/diimplementasikan pada kode migrasi
- Beranda dan ringkasan statistik; pencarian data siaran; daftar perubahan/notifikasi.
- Login/logout dengan hash SHA-256 lama untuk kompatibilitas.
- Pendaftaran dan reset password memakai OTP email melalui SMTP Gmail (masa berlaku OTP 10 menit, OTP disimpan sebagai hash di session server).
- Tambah data siaran; edit data milik sendiri atau admin; hapus data milik sendiri atau admin; poin kontribusi.
- Profil pribadi, daftar pengguna dan profil publik, leaderboard, komentar dan poin.
- Laporan koreksi data dan dashboard admin untuk mengubah status/catatan laporan.
- Audit log dan pemulihan snapshot versi sebelumnya oleh admin.
- Peta Leaflet dengan marker koordinat pemancar, titik laporan pengukuran, pengisian koordinat, data teknis pemancar, dan formulir pengukuran aktual TV/STB.
- Prediksi cakupan terrain dari DEM dengan overlay PNG pada peta. Prediksi otomatis aktif saat pemancar UHF 21–48 dipilih (dapat dinonaktifkan melalui checkbox) dan dapat dihitung ulang secara manual. Prediksi merupakan informasi baca-publik dan tidak mensyaratkan login; aksi tulis tetap memerlukan login. Model, fallback teknis, dan keterbatasannya mengikuti fungsi aplikasi lama; hasil tetap indikatif, bukan jaminan penerimaan sinyal. Pengambilan DEM memerlukan akses jaringan dan dapat memakan waktu.
- Chatbot Gemini menggunakan model `gemini-2.5-flash`.

## Perbedaan/pekerjaan yang masih perlu diverifikasi
- UI peta menggunakan Leaflet/OSM, bukan Folium. Peta utama menyediakan layer jalan/satelit, GPS browser, filter provinsi/wilayah/pencarian MUX-kanal, pemilihan marker, zoom area prediksi, overlay DEM, koordinat pointer, pengukuran jarak, marker pengukuran komunitas, dan panel detail.
- Halaman mandiri **Tambah Titik Pemancar** tersedia di navigasi. Pengguna yang login dapat menambahkan koordinat MUX yang belum memiliki titik; perubahan/penghapusan koordinat yang sudah tersimpan hanya dapat dilakukan admin. Peta pemilihan memakai tanda bidik di tengah peta, layer jalan/satelit, dan GPS browser.
- Pengujian end-to-end belum dapat dilakukan di sini karena kredensial Firebase, SMTP, dan Gemini berada di Secrets milik deployment Anda. Paket ini tidak menyertakan atau meminta rahasia tersebut.
- Setelah dipasang, uji seluruh alur tulis/baca, khususnya OTP, edit/hapus/restore, koordinat, pengukuran, serta kalkulasi DEM sebelum mengganti aplikasi aktif.

## Deploy di Streamlit Community Cloud
1. Unggah isi folder proyek ke repositori GitHub.
2. Pastikan `requirements.txt` dan `packages.txt` berada di root repositori. `requirements.txt` memasang dependensi Python, sedangkan `packages.txt` memasang paket sistem Linux yang dibutuhkan lingkungan deployment (termasuk `gdal-bin`, `make`, `curl`, `unzip`, dan `gzip`).
3. Pada Streamlit Community Cloud, pilih `app.py` sebagai Main file.
4. Masukkan konfigurasi yang sama ke **App settings → Secrets**: `FIREBASE`, `GEMINI.api_key`, dan `email.sender` / `email.app_password`.
5. Jangan commit file Secrets atau kredensial.

## Kompatibilitas dan keamanan
- Path Firebase yang sudah ada dipertahankan: `siaran`, `users`, `admins`, `audit_logs`, `broadcast_reports`, `signal_measurements`, `provinsi`, dan `app_metadata`.
- Hash SHA-256 dipertahankan sementara agar akun lama dapat login. SHA-256 bukan KDF password yang direkomendasikan; migrasi ke KDF ber-salt perlu direncanakan terpisah agar kompatibilitas akun lama tidak terputus.
- Aksi tulis memeriksa login/peran di backend, tidak hanya mengandalkan status UI browser.
- Untuk edit/hapus data siaran, pemilik data atau admin yang diizinkan. Perubahan ini memperketat akses dibanding tombol UI lama yang belum selalu membatasi hak akses.
- Jangan tampilkan isi exception konfigurasi atau secrets kepada pengunjung.


## Pemulihan fitur Peta Pemancar

Antarmuka Leaflet kini menyediakan kontrol layer peta jalan/satelit dan overlay prediksi DEM, kontrol GPS browser (memerlukan HTTPS dan izin lokasi), filter provinsi/wilayah/pencarian MUX atau kanal, pemilihan marker langsung, zoom ke pemancar/area prediksi, skala peta, koordinat pointer, pengukuran jarak multi-titik, marker pengukuran komunitas, dan panel detail/analisis pemancar. Filter hanya menyaring marker yang terlihat dan tidak mengubah data Firebase.


CATATAN PERBAIKAN IMPORT TIMESTAMP
Unggah dan timpa app.py serta backend.py dari paket ini secara bersamaan.
Fungsi get_latest_transmitter_update_timestamp() berada di backend.py.
Setelah commit, lakukan Reboot app di Streamlit Cloud.
