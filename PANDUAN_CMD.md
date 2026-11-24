# Panduan Eksekusi Lacta-Predict lewat CMD (Windows)

Urutan praktis dari melatih model AI → menjalankan backend → build APK → cek hasil di HP,
plus persiapan iOS dan pengujian kondisi error. Semua perintah untuk **Command Prompt (CMD)**.

Prasyarat: **Python 3.10+**, **Node.js 18+**, (Android) **Android Studio**, (iOS) **macOS + Xcode**.
Akar proyek diasumsikan: `C:\Users\Admin\work\lacta-predict`.

---

## 1. Latih / verifikasi model AI dari dataset

```bat
cd C:\Users\Admin\work\lacta-predict\lacta-predict-backend

:: (sekali) buat virtual env + pasang dependensi
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

:: pastikan dataset ada di data\ (WAJIB, tidak ada dummy)
copy "D:\Downloads\lacta_predict_dataset_clean_v2.csv" data\

:: latih model (regresi + K-Means) -> models\*.joblib + metrics.json
python train_model.py

:: lihat ringkasan metrik
type models\metrics.json

:: jalankan uji (17 tes, tanpa jaringan)
python -m pytest -q tests
```

Target lulus: **H+1 MAPE ≈ 10%**, **R² ≈ 0,95**, K-Means cocok 100% dengan `segmen_nama`.

---

## 2. Siapkan Supabase (sekali)

1. Di Supabase **SQL Editor**, tempel & jalankan `lacta-predict-backend\supabase_setup.sql`
   (Bagian A untuk instalasi baru, atau Bagian B untuk migrasi dari skema lama, lalu selalu Bagian C).
2. Catat **Project URL** dan dua kunci: **anon public** (untuk app) & **service_role** (untuk backend).

## 3. Konfigurasi backend (.env)

```bat
cd C:\Users\Admin\work\lacta-predict\lacta-predict-backend
copy .env.example .env
notepad .env
```
Isi minimal:
```
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=eyJ...SERVICE_ROLE...
FIREBASE_PROJECT_ID=lacta-predict
REQUIRE_AUTH=true
ADMIN_TOKEN=            :: buat: python -c "import secrets;print(secrets.token_urlsafe(32))"
ALLOWED_ORIGINS=*
```

## 4. Jalankan backend + Cloudflare Tunnel

Jendela CMD #1 — server:
```bat
cd C:\Users\Admin\work\lacta-predict\lacta-predict-backend
.venv\Scripts\activate
python app.py
:: untuk produksi lokal: pip install waitress & waitress-serve --listen=0.0.0.0:8000 app:app
```
Cek: buka `http://localhost:8000/health` → `{"status":"ok","models_loaded":true}`.

Jendela CMD #2 — tunnel HTTPS publik (HP tidak bisa pakai localhost):
```bat
:: unduh cloudflared.exe lebih dulu dari situs Cloudflare, lalu:
cloudflared tunnel --url http://localhost:8000
```
Salin URL `https://xxxx.trycloudflare.com` yang muncul.

## 5. Konfigurasi frontend (apiBase + Supabase anon)

```bat
notepad C:\Users\Admin\work\lacta-predict\js\supabase-config.js
```
Isi:
```js
url: 'https://xxxx.supabase.co',
anonKey: 'eyJ...ANON...',            // kunci anon, BUKAN service_role
apiBase: 'https://xxxx.trycloudflare.com',
```
> Selama masih placeholder (`PROJECT.supabase` / `KUNCI_ANON` / `MASUKKAN_...`), aplikasi menampilkan
> status **"Server AI belum dikonfigurasi"** — bukan rumus lokal.

---

## 6. Build ulang APK Android

```bat
cd C:\Users\Admin\work\lacta-predict

:: salin file web root -> www\  lalu sinkron ke proyek Android
npm install
npm run cap:sync:android          :: = node scripts\copy-www.js && npx cap sync android

:: buka Android Studio, lalu Build > Build Bundle(s)/APK(s) > Build APK(s)
npm run cap:open:android
```
Hanya mengubah web (tanpa plugin baru)? Cukup salin aset:
```bat
node scripts\copy-www.js
npx cap copy android
```

## 7. Persiapan iOS (lintas platform via CMD, build akhir di macOS)

Di Windows Anda hanya bisa menyiapkan aset web; **penambahan & build platform iOS WAJIB di macOS + Xcode**.

Di Windows (menyiapkan web):
```bat
cd C:\Users\Admin\work\lacta-predict
node scripts\copy-www.js
```
Lalu pindahkan repo ke **macOS** dan jalankan di Terminal:
```bash
npm install
npm run cap:add:ios        # sekali, membuat folder ios/
npm run cap:sync:ios
npm run cap:open:ios       # buka Xcode: pilih Team/Signing, lalu Run di perangkat/simulator
```
Catatan iOS:
* `capacitor.config.json` sudah menyetel `iosScheme: "capacitor"`, `contentInset: "always"`,
  `cleartext: false` — panggilan ke Supabase & `apiBase` memakai HTTPS sehingga lolos App Transport Security.
* Firebase Auth memakai SDK web compat (email+sandi, tanpa popup) — berjalan di WKWebView.
* `localStorage` persisten di WKWebView (data ternak per akun tetap tersimpan).
* Tidak ada kode khusus Android yang memblokir iOS.

---

## 8. Cek end-to-end sampai hasil AI muncul di HP

1. Backend `/health` = ok, tunnel hidup, `apiBase` sudah diisi URL tunnel.
2. Di aplikasi: daftar/login (email terverifikasi) → **Data Ternak** → **+ Tambah Sapi** → isi
   kelompok genetik, umur, tahap laktasi, produksi kemarin, pakan (DMI), suhu, kelembaban → **Simpan & Prediksi AI**.
3. Verifikasi cepat lewat CMD (ganti token & id):
   ```bat
   curl http://localhost:8000/model-info
   curl -X POST http://localhost:8000/predict -H "Content-Type: application/json" ^
        -H "Authorization: Bearer <FIREBASE_ID_TOKEN>" -d "{\"cattle_id\":\"<UUID_SAPI>\"}"
   ```
4. Di Supabase, tabel `predictions` terisi 3 baris (H+1..H+3) untuk sapi tsb; aplikasi menampilkan
   angka (animasi naik), badge, grafik tren tergambar, dan segmen.

### Uji kondisi error / server mati
* **Server dimatikan** (tutup CMD #1): app menampilkan **"Gagal terhubung ke server AI"** + pesan
  (timeout 45 dtk) — **ketuk kartu prediksi untuk coba lagi**. Tidak ada angka palsu yang muncul.
* **apiBase salah / tunnel mati**: pesan timeout/connect error yang sama.
* **Belum login / email belum verifikasi**: **"Login diperlukan untuk AI"**.
* **Config masih placeholder**: **"Server AI belum dikonfigurasi"**.
* **Sapi tanpa log**: backend balas `422` ("catat produksi & pakan dulu").

Reset data uji coba (butuh ADMIN_TOKEN):
```bat
curl -X DELETE http://localhost:8000/logs/reset -H "X-Admin-Token: %ADMIN_TOKEN% " ^
     -H "Content-Type: application/json" -d "{\"confirm\":\"RESET\",\"include_cattle\":true}"
```

> Setelah mengubah file web, selalu: `node scripts\copy-www.js` lalu `npx cap copy android`
> (atau `npm run cap:sync:android`), dan naikkan `CACHE` di `sw.js` bila perlu memaksa pembaruan PWA.
