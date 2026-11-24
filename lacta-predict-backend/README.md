# lacta-predict-backend

Backend AI untuk Lacta-Predict: melatih model dari `lacta_predict_dataset_clean_v2.csv`,
melayani prediksi, dan menyimpan hasil ke Supabase. Folder ini **terpisah dari `www/`**
sehingga tidak ikut build Capacitor/APK.

```
lacta-predict-backend/
├── train_model.py      # training regresi + K-Means dari dataset v2 + evaluasi + simpan .joblib
├── app.py              # API Flask: /predict, /predict/all, /logs/reset, /health, /model-info
├── common.py           # fitur & konstanta yang dipakai bersama training dan serving
├── supabase_client.py  # klien REST Supabase (service role)
├── supabase_setup.sql  # skema tabel + migrasi + policy RLS (mode uji coba)
├── requirements.txt  .env.example
├── data/lacta_predict_dataset_clean_v2.csv   # dataset acuan (2.250 baris)
├── models/*.joblib, metrics.json             # model hasil training
└── tests/test_api.py                          # 17 tes (tanpa jaringan)
```

## Jalankan (Windows CMD)

```bat
cd lacta-predict-backend
py -m venv .venv & .venv\Scripts\activate
pip install -r requirements.txt

python train_model.py        :: latih model dari data\lacta_predict_dataset_clean_v2.csv
copy .env.example .env        :: lalu isi SUPABASE_URL & SUPABASE_KEY (service_role), ADMIN_TOKEN
python app.py                 :: http://localhost:8000 (produksi: pip install waitress & waitress-serve)
python -m pytest -q tests     :: uji
```

Model `.joblib` harus dibuka dengan versi minor scikit-learn yang sama seperti saat training
(lihat `sklearn_version` di `metrics.json`). Jika berbeda, jalankan `python train_model.py` lagi.

## Dataset & model

Dataset `lacta_predict_dataset_clean_v2.csv` (2.250 baris) bersifat **cross-sectional**:
tiap baris = satu sapi pada satu kondisi, dengan produksi sebelumnya (`prev_milk_yield_l`) sebagai
satu-satunya lag. Kolom: `animal_id, genetic_group, thi_range, replication_no, dmi_kg, milk_yield_l,
thi_level_num, suhu_c, kelembapan_pct, thi_score, prev_milk_yield_l, usia_bulan, tahap_laktasi,
data_source, base_animal_id, feed_efficiency_prev, cluster_performa, segmen_nama, split`.

* **Regresi** memprediksi `milk_yield_l` (H+1) dari: `prev_milk_yield_l, dmi_kg, usia_bulan, suhu_c,
  kelembapan_pct, thi_score, feed_efficiency_prev, genetic_group, tahap_laktasi`. `thi_score` dihitung
  dari suhu+kelembaban (formula NRC), `feed_efficiency_prev = prev_milk_yield_l / dmi_kg`. Dibandingkan
  Linear/RandomForest/GradientBoosting; terbaik dipilih via CV 5-fold di train, diuji di `split=test`.
* **Multi-horizon H+1..H+3** dibuat **rekursif**: hasil H+1 menjadi `prev` untuk H+2, dst. Dataset tidak
  memuat ground-truth lebih dari 1 hari, jadi hanya H+1 yang tervalidasi; H+2/H+3 adalah proyeksi.
* **Peringatan dini** menyala bila prediksi turun ≥ ambang dari produksi sebelumnya. Default ambang =
  `DROP_THRESHOLD` (10%); bisa ditimpa `ALERT_THRESHOLD`.
* **K-Means** (3 klaster) atas `feed_efficiency_prev, dmi_kg, prev_milk_yield_l` mereproduksi `segmen_nama`
  dataset (100% pada data saat ini): `Performa Rendah (Prioritas)` / `Rata-rata` / `Tinggi`.

Hasil training saat ini (lihat `models/metrics.json`): GradientBoosting, **H+1 MAPE ≈ 10%, R² ≈ 0,95**,
mengalahkan baseline naif; K-Means silhouette ≈ 0,53, cocok 100% dengan dataset.

### Memakai data sendiri
`python train_model.py --csv data\dataku.csv` dengan kolom minimal: `genetic_group, dmi_kg, milk_yield_l,
suhu_c, kelembapan_pct, prev_milk_yield_l, usia_bulan, tahap_laktasi` (opsional `split`, `segmen_nama`).

## Endpoint

| Metode | Path | Akses | Fungsi |
|---|---|---|---|
| POST | `/predict` `{"cattle_id"}` | token Firebase pemilik / admin | prediksi H+1..H+3, segmen, peringatan → tabel `predictions` |
| POST | `/predict/all` | `X-Admin-Token` | prediksi semua sapi |
| DELETE | `/logs/reset` `{"cattle_id", ...}` | pemilik / admin | hapus log uji coba satu sapi |
| DELETE | `/logs/reset` `{"confirm":"RESET"}` | `X-Admin-Token` | hapus SEMUA log |
| GET | `/health`, `/model-info` | publik | status & metrik model |

## Skema Supabase (lihat `supabase_setup.sql`)
* `cattle`: `genetic_group` (Local/HF50/HF62.5/HF75/HF87.5), `usia` (BULAN), `tahap_laktasi` (Awal/Tengah/Akhir).
* `daily_logs`: `prev_milk_yield_l`, `dmi_kg`, `suhu_c`, `kelembapan_pct`. (Backend juga membaca kolom lama
  `volume_susu_aktual/jumlah_pakan/suhu_kandang` sebagai cadangan.)
* `predictions`: `tanggal_prediksi`, `prediksi_volume_susu`, `segmen_performa`, `peringatan_dini`, `alasan_prediksi`.
* `profiles.id` & `cattle.farmer_id` = uuid; UID Firebase → uuid v5 (`FARMER_NAMESPACE` = `farmerNamespace` di app).

## Keamanan & batasan
* `SUPABASE_KEY` = **service_role**; jangan pernah di frontend. Frontend memakai kunci **anon**.
* Backend memverifikasi ID token Firebase & memastikan sapi milik pemanggil. RLS saat ini **mode uji coba**
  (anon boleh menulis) — untuk produksi aktifkan Third-party Auth (Firebase) di Supabase lalu perketat RLS.
* HP/APK harus memanggil backend lewat **HTTPS** publik (WebView memblokir HTTP dari halaman HTTPS).
