# Lacta-Predict

Aplikasi mobile prediksi produksi susu sapi perah (demo alur aplikasi).
Dibangun dengan HTML + CSS + JavaScript murni, tanpa framework dan tanpa backend.

## Isi proyek

```
lacta-predict/
├── index.html              # Semua layar (login, beranda, data ternak, form, hasil)
├── css/style.css           # Tampilan + mode terang/gelap
├── js/app.js               # Logika, rumus prediksi, penyimpanan lokal
├── manifest.webmanifest    # Konfigurasi PWA
├── sw.js                   # Service worker (offline)
├── icons/                  # Ikon 192, 512, maskable, favicon
├── package.json            # Untuk Capacitor (jadi APK)
├── capacitor.config.json
└── scripts/copy-www.js
```

## Cara 1 - Langsung dipakai (paling cepat)

Buka `index.html` di browser. Untuk fitur install/offline, jalankan lewat server lokal:

```
npx serve . -l 5173
# atau
python3 -m http.server 5173
```

Buka `http://localhost:5173`, lalu di Chrome HP pilih **Tambahkan ke layar utama**.

## Cara 2 - Online jadi PWA (install di HP, gratis)

Upload seluruh isi folder ke hosting HTTPS (Netlify, Vercel, GitHub Pages, Cloudflare Pages).
PWA hanya bisa di-install lewat HTTPS.

## Cara 3 - Jadi APK Android (Capacitor)

Butuh Node.js 18+ dan Android Studio.

```
npm install
npm run cap:add:android
npm run cap:open:android      # buka di Android Studio, lalu Build > Build APK
```

Setelah mengubah kode web: `npm run cap:sync`.

Alternatif tanpa coding: upload URL hasil hosting ke https://www.pwabuilder.com
untuk dapat paket APK/AAB.

## Catatan penting

- Prediksi saat ini memakai **rumus sederhana** di `predict()` pada `js/app.js`,
  bukan model AI/ML. Ganti fungsi itu (atau panggil API model) jika sudah ada model asli.
- Login masih **tampilan saja** (tombol Masuk langsung ke beranda). Belum ada autentikasi.
- Data sapi disimpan di `localStorage` perangkat. Belum ada sinkronisasi server,
  dan data hilang jika cache browser dihapus.
- Menu **Akun**, tombol **Daftar**, dan grafik tren masih statis/placeholder.
- Setelah mengubah file yang di-cache, naikkan versi `CACHE` di `sw.js`
  (mis. `lacta-predict-v2`) supaya pengguna dapat versi terbaru.
