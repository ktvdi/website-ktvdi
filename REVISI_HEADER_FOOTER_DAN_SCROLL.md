# Revisi Header, Footer, dan tinggi halaman KTVDI

## Perubahan
- Header diperbarui dengan gradasi biru gelap-sian, aksen cahaya, navigasi bergaya glass, serta tampilan akun yang lebih rapi.
- Footer dibuat menjadi tiga area: identitas KTVDI, tautan navigasi, dan informasi komunitas.
- Layout shell menggunakan flex-column dengan area utama fleksibel agar footer berada di bawah ketika konten sedikit.
- Pengukuran tinggi iframe tidak lagi memakai batas minimum 600 px. Tinggi mengikuti tinggi dokumen aktual sehingga tidak ada ruang kosong buatan yang memaksa scroll.
- `overscroll-behavior-y` dan overflow horizontal ditata untuk mengurangi efek scroll berlebih.

## File yang diubah
- `frontend/index.html`
- `frontend/style.css`
- `frontend/main.js`

## Penerapan
Backup aplikasi, ekstrak ZIP ini, timpa seluruh file proyek dengan versi dalam arsip, lalu restart/redeploy Streamlit. Jangan hanya menimpa CSS karena perubahan tinggi iframe juga ada di `frontend/main.js`.
