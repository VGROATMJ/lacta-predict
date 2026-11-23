# Lacta-Predict

Aplikasi mobile prediksi produksi susu sapi perah (demo alur aplikasi).
Dibangun dengan HTML + CSS + JavaScript murni, tanpa framework dan tanpa backend.

## Isi proyek

```
lacta-predict/
├── index.html              # Semua layar (login, verifikasi email, beranda, data ternak, form, hasil, akun)
├── css/style.css           # Tampilan + mode terang/gelap
├── js/app.js               # Logika, rumus prediksi, penyimpanan lokal (per akun)
├── login.html              # Halaman login mandiri (Firebase Auth), redirect ke index.html
├── js/auth.js              # Firebase Auth: daftar, login, verifikasi email, reset sandi, keluar
├── js/firebase-config.js   # Konfigurasi proyek Firebase
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

## Setup Firebase Authentication (wajib sekali saja)

Di [Firebase Console](https://console.firebase.google.com) proyek `lacta-predict`:

1. **Authentication > Sign-in method**: aktifkan **Email/Password**.
2. **Authentication > Settings > Authorized domains**: tambahkan domain tempat app di-hosting
   (mis. `namaapp.netlify.app`). `localhost` sudah ada, dipakai saat uji lokal dan APK Capacitor.
3. **Authentication > Templates**: ubah bahasa email verifikasi/reset ke Indonesia (opsional).
4. (Disarankan) Di Google Cloud Console > Credentials, batasi API key ke domain Anda.

Alur akun: Daftar (nama, email, kata sandi min. 8 karakter huruf+angka) -> email verifikasi dikirim ->
akun **tidak bisa masuk ke aplikasi sebelum email diverifikasi** -> masuk. Tersedia juga kirim ulang
verifikasi (jeda 60 detik), lupa kata sandi, ganti kata sandi, dan keluar di menu **Akun**.

## Catatan penting

- Prediksi saat ini memakai **rumus sederhana** di `predict()` pada `js/app.js`,
  bukan model AI/ML. Ganti fungsi itu (atau panggil API model) jika sudah ada model asli.
- Login memakai **Firebase Auth (email + kata sandi)**; login dengan No. HP belum didukung.
- Data sapi disimpan di `localStorage` perangkat, **dipisah per akun**. Belum ada sinkronisasi server,
  dan data hilang jika cache browser dihapus. Karena data lokal, login di sini berfungsi sebagai
  gerbang akses aplikasi, bukan perlindungan data di server.
- Akun baru otomatis diberi 3 sapi contoh (bisa dihapus lewat tombol **Hapus** di Data Ternak).
- Grafik tren memakai proyeksi 3 hari dari rumus yang sama (bukan data historis).
- Setelah mengubah file yang di-cache, naikkan versi `CACHE` di `sw.js`
  (sekarang `lacta-predict-v2`) supaya pengguna dapat versi terbaru.
- Setelah mengubah kode web untuk APK: `npm run cap:sync`.

## Integrasi Supabase + backend AI (opsional)

Folder `lacta-predict-backend/` (di luar `www/`) berisi training model dan API prediksi. Frontend tersambung lewat
`js/supabase-config.js` (isi URL Supabase, kunci anon, alamat backend) dan `js/supabase-sync.js`. Selama
`supabase-config.js` masih berisi `YOUR_...`, aplikasi berjalan seperti semula (rumus lokal). Detail: lihat
`lacta-predict-backend/README.md`. Setelah mengubah file di `js/`, jalankan `npm run cap:sync`.
