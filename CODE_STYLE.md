# Panduan format kode

## JavaScript

Konfigurasi proyek tersedia di `.prettierrc.json`. Pasang dependensi pengembangan lalu jalankan:

```bash
npm install
npm run format
npm run format:check
```

## Python

Konfigurasi Ruff tersedia di `pyproject.toml`. Pasang dependensi pengembangan lalu jalankan:

```bash
python -m pip install -r requirements-dev.txt
ruff format .
ruff check . --fix
```

Formatter digunakan untuk menjaga konsistensi indentasi, kutip, dan tata letak kode.
Perubahan struktur fungsi dilakukan secara terpisah agar perilaku fitur tetap mudah ditinjau.
