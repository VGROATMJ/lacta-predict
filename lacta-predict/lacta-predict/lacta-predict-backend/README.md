# lacta-predict-backend

Backend AI untuk Lacta-Predict: melatih model, melayani prediksi, menyimpan hasil ke Supabase.
Folder ini **terpisah dari `www/`** sehingga tidak ikut build Capacitor/APK.

```
lacta-predict-backend/
├── train_model.py      # generator dataset dummy + training K-Means & regresi + evaluasi + simpan .joblib
├── app.py              # API Flask: /predict, /predict/all, /logs/reset, /health, /model-info
├── common.py           # fitur & konstanta yang dipakai bersama training dan serving (jangan diduplikasi)
├── supabase_client.py  # klien REST Supabase (service role)
├── supabase_setup.sql  # penyesuaian FK profiles & policy RLS (mode uji coba)
├── requirements.txt  .env.example
├── data/dataset_susu.csv      # dataset DUMMY hasil generator
├── models/*.joblib, metrics.json   # model hasil training pada data dummy
└── tests/test_api.py          # 14 tes (tanpa jaringan)
```

## Jalankan

```bash
cd lacta-predict-backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python train_model.py        # (opsional) latih ulang; CSV belum ada -> dataset dummy dibuat otomatis
cp .env.example .env         # isi SUPABASE_URL & SUPABASE_KEY (service_role), ADMIN_TOKEN
python app.py                # http://localhost:8000      (produksi: gunicorn -w 2 -b 0.0.0.0:8000 app:app)
python -m pytest -q tests    # uji
```

Model `.joblib` yang disertakan dilatih dengan scikit-learn 1.9. Jika versi minor Anda berbeda dan muncul
peringatan/galat saat memuat, jalankan `python train_model.py` lagi.

### Memakai data sendiri
`python train_model.py --csv data_saya.csv` dengan kolom: `cattle_id, tanggal, usia, tahap_laktasi,
jumlah_pakan, jenis_pakan, suhu_kandang, volume_susu_aktual` (ekspor dari `cattle` + `daily_logs`).

## Endpoint

| Metode | Path | Akses | Fungsi |
|---|---|---|---|
| POST | `/predict` `{"cattle_id"}` | token Firebase pemilik / admin | prediksi H+1..H+3, segmen, peringatan → tabel `predictions` |
| POST | `/predict/all` | `X-Admin-Token` | prediksi semua sapi (mis. dipicu cron harian) |
| DELETE | `/logs/reset` `{"cattle_id", "include_predictions", "include_cattle"}` | pemilik (sapinya) / admin | hapus log uji coba satu sapi |
| DELETE | `/logs/reset` `{"confirm":"RESET"}` | `X-Admin-Token` | hapus SEMUA log (+ prediksi; `include_cattle:true` juga sapi) |
| GET | `/health`, `/model-info` | publik | status & metrik model |

Contoh reset semua data uji coba:
```bash
curl -X DELETE http://localhost:8000/logs/reset -H "X-Admin-Token: $ADMIN_TOKEN" \
     -H "Content-Type: application/json" -d '{"confirm":"RESET","include_cattle":true}'
```

## Cara kerja singkat
* **Regresi**: satu model per horizon (H+1, H+2, H+3); target = volume ÷ rata-rata 3 hari terakhir. Fitur: lag
  volume/pakan/suhu 7 hari, indeks heat stress (suhu > 27 °C), usia, tahap laktasi, jenis pakan, jumlah hari riwayat.
  Dilatih dengan pemotongan riwayat acak agar sapi baru (1 log) tetap bisa diprediksi. Linear Regression vs Random
  Forest dipilih otomatis pada data validasi (split berbasis waktu).
* **Peringatan dini**: menyala bila prediksi H+1..H+3 turun ≥ *ambang* dari rata-rata 3 hari terakhir. "Penurunan
  tajam" didefinisikan ≥ 10%. Ambang disetel otomatis saat training (recall ≥ 85% di validasi) dan bisa ditimpa
  lewat `ALERT_THRESHOLD`.
* **K-Means**: 3 klaster dari rata-rata volume, efisiensi (L/kg pakan), dan kestabilan (CV) 30 hari terakhir;
  klaster diberi nama Rendah/Sedang/Tinggi menurut rata-rata volume.
* `predictions` diisi 3 baris per sapi per panggilan (`tanggal_prediksi` = tanggal yang diprediksi); baris lama
  untuk tanggal yang sama diganti.

## Asumsi tentang skema Anda (cek kalau ada yang beda)
* `cattle.usia` = **bulan** (nilai ≤ 15 dianggap tahun). `cattle.tahap_laktasi` = teks `awal|puncak|tengah|akhir`
  (juga dikenali: early/peak/mid/late, angka 1–4, atau hari laktasi).
* `predictions.peringatan_dini` = boolean (ubah `PERINGATAN_FORMAT=text` jika kolomnya teks).
* `profiles.id` dan `cattle.farmer_id` bertipe uuid; UID Firebase dipetakan ke uuid v5 deterministik
  (`FARMER_NAMESPACE` di `common.py` = `farmerNamespace` di `js/supabase-config.js`).
* `daily_logs.jenis_pakan` teks (`hijauan|konsentrat|campuran`).

## Keamanan & batasan
* `SUPABASE_KEY` di sini = **service_role**; jangan pernah ditaruh di frontend. Frontend memakai kunci **anon**.
* Backend memverifikasi ID token Firebase dan memastikan sapi milik pemanggil. Namun karena Supabase tidak
  mengenali token Firebase, penulisan langsung dari app ke tabel memakai role `anon` (lihat `supabase_setup.sql`,
  mode uji coba). Untuk produksi: aktifkan *Third-party Auth → Firebase* di Supabase lalu perketat RLS per pemilik,
  atau pindahkan penulisan `cattle`/`daily_logs` lewat backend.
* Metrik pada model yang disertakan berasal dari **data dummy** — bukan klaim akurasi lapangan. Latih ulang dengan
  data peternakan asli sebelum dipakai mengambil keputusan.
* HP/APK harus memanggil backend lewat **HTTPS** publik (WebView Capacitor memblokir HTTP dari halaman HTTPS).
