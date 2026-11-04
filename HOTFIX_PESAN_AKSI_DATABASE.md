# Hotfix pesan "Aksi tidak dikenal" pada Database Siaran

## Perubahan
- `app.py` sekarang mengirim hasil aksi frontend satu kali saja, lalu mengosongkan hasil tersimpan.
- Ini mencegah pesan hasil aksi lama diputar ulang setiap Streamlit melakukan rerun atau navigasi halaman.
- Handler `load_broadcast_edit_requests` sudah tersedia di `backend.py` pada paket ini.

## Cara menerapkan
1. Cadangkan folder aplikasi yang sedang berjalan.
2. Ekstrak seluruh isi ZIP ini dan timpa file proyek lama (jangan hanya menimpa folder `frontend`).
3. Pastikan `app.py`, `backend.py`, dan seluruh folder `frontend` berasal dari paket yang sama.
4. Restart/redeploy aplikasi Streamlit.
5. Login, buka Database Siaran, lalu pindah halaman dan kembali lagi untuk memastikan pesan lama tidak muncul kembali.

Jika "Aksi tidak dikenal" masih muncul setelah deploy seluruh paket, periksa log server dan pastikan proses Streamlit benar-benar menjalankan `backend.py` dari folder proyek yang baru.
