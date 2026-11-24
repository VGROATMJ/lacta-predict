"""Fungsi & konstanta bersama untuk training (train_model.py) dan serving (app.py).

PENTING: pembuatan fitur harus IDENTIK di training dan serving, karena itu
dipusatkan di sini. Jangan menduplikasi logika fitur di tempat lain.

Dataset acuan: lacta_predict_dataset_clean_v2.csv
Kolom: animal_id, genetic_group, thi_range, replication_no, dmi_kg, milk_yield_l,
       thi_level_num, suhu_c, kelembapan_pct, thi_score, prev_milk_yield_l,
       usia_bulan, tahap_laktasi, data_source, base_animal_id,
       feed_efficiency_prev, cluster_performa, segmen_nama, split

Model memprediksi `milk_yield_l` (produksi hari ini) dari:
  - prev_milk_yield_l  : produksi sehari sebelumnya (lag-1)
  - dmi_kg             : konsumsi bahan kering / pakan (kg)
  - usia_bulan         : umur sapi (bulan)
  - suhu_c, kelembapan_pct, thi_score : iklim mikro kandang (THI diturunkan otomatis)
  - feed_efficiency_prev : efisiensi pakan sebelumnya = prev_milk_yield_l / dmi_kg
  - genetic_group      : Local / HF50 / HF62.5 / HF75 / HF87.5
  - tahap_laktasi      : Awal / Tengah / Akhir
Horizon H+2 & H+3 dihasilkan secara REKURSIF (prediksi dipakai sebagai prev
untuk horizon berikutnya), karena dataset hanya memuat satu lag.
"""
from __future__ import annotations

import math
import uuid

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- konstanta
HORIZONS = (1, 2, 3)                     # prediksi 1-3 hari ke depan (rekursif)
DROP_THRESHOLD = 0.10                    # "penurunan tajam" = >=10% di bawah produksi sebelumnya
HEAT_THI_THRESHOLD = 72.0                # THI > 72 mulai menimbulkan heat stress pada sapi perah

GENETIC_GROUPS = ["Local", "HF50", "HF62.5", "HF75", "HF87.5"]
STAGES = ["Awal", "Tengah", "Akhir"]     # tahap laktasi (3 tahap sesuai dataset)
SEGMEN_LABELS = ["Performa Rendah (Prioritas)", "Performa Rata-rata", "Performa Tinggi"]

# Nama kolom fitur (urutan HARUS stabil: dipakai sebagai kontrak model .joblib)
NUM_FEATURES = ["prev_milk_yield_l", "dmi_kg", "usia_bulan", "suhu_c",
                "kelembapan_pct", "thi_score", "feed_efficiency_prev"]
CAT_FEATURES = ["genetic_group", "tahap_laktasi"]
FEATURE_COLUMNS = NUM_FEATURES + CAT_FEATURES
TARGET = "milk_yield_l"

# Fitur segmentasi K-Means (mereproduksi `segmen_nama` dataset 100%)
SEGMENT_FEATURES = ["feed_efficiency_prev", "dmi_kg", "prev_milk_yield_l"]

# Namespace UUID untuk memetakan UID Firebase -> profiles.id / cattle.farmer_id.
# HARUS sama dengan farmerNamespace di js/supabase-config.js.
FARMER_NAMESPACE = uuid.UUID("a3f1c2de-5b6a-4c1e-9d8f-1a2b3c4d5e6f")


def farmer_id_from_uid(firebase_uid: str) -> str:
    return str(uuid.uuid5(FARMER_NAMESPACE, firebase_uid))


# --------------------------------------------------------- THI (Temperature-Humidity Index)
def thi_from(suhu_c: float, kelembapan_pct: float) -> float:
    """THI dari suhu udara (°C) & kelembaban relatif (%).

    Formula NRC (dipakai pada dataset): THI = (1.8*T + 32) - (0.55 - 0.0055*RH) * (1.8*T - 26).
    Contoh: T=23.5, RH=66.1 -> 71.26 (dataset: 71.24).
    """
    t = _num(suhu_c, 27.0)
    rh = _clip(_num(kelembapan_pct, 70.0), 0.0, 100.0)
    return (1.8 * t + 32.0) - (0.55 - 0.0055 * rh) * (1.8 * t - 26.0)


def thi_level(thi: float) -> int:
    """Kelompok tekanan panas kasar: 0 = nyaman, 1 = ringan/sedang, 2 = berat."""
    if thi < 72:
        return 0
    if thi < 79:
        return 1
    return 2


# --------------------------------------------------------- normalisasi input
def _num(v, default: float) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return float(default)
    return float(default) if math.isnan(n) else n


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def normalize_stage(v) -> str:
    """tahap_laktasi (teks / angka) -> 'Awal' | 'Tengah' | 'Akhir'. Default: 'Tengah'."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "Tengah"
    if isinstance(v, (int, float, np.integer, np.floating)):
        n = float(v)
        if 1 <= n <= 3 and float(n).is_integer():
            return STAGES[int(n) - 1]
        # Anggap sebagai hari laktasi (DIM)
        return "Awal" if n <= 90 else ("Tengah" if n <= 210 else "Akhir")
    s = str(v).strip().lower()
    for key, lab in (("awal", "Awal"), ("early", "Awal"), ("puncak", "Awal"), ("peak", "Awal"),
                     ("tengah", "Tengah"), ("mid", "Tengah"),
                     ("akhir", "Akhir"), ("late", "Akhir"), ("kering", "Akhir")):
        if key in s:
            return lab
    try:
        return normalize_stage(float(s))
    except ValueError:
        return "Tengah"


def normalize_genetic(v) -> str:
    """genetic_group -> salah satu GENETIC_GROUPS. Tak dikenal -> 'HF50' (paling umum)."""
    if v is None:
        return "HF50"
    s = str(v).strip()
    for g in GENETIC_GROUPS:                         # cocokkan persis (case-insensitive)
        if s.lower() == g.lower():
            return g
    low = s.lower().replace(" ", "")
    if "local" in low or "lokal" in low or "po" in low or "ongole" in low:
        return "Local"
    for g in ("HF87.5", "HF75", "HF62.5", "HF50"):   # cocokkan angka persentase HF
        if g.lower().replace("hf", "") in low:
            return g
    if "hf" in low or "fh" in low or "holstein" in low or "friesian" in low:
        return "HF50"
    return "HF50"


def normalize_usia_bulan(v) -> float:
    """usia -> bulan. Nilai <= 15 dianggap TAHUN (mis. 4 -> 48 bulan)."""
    n = _num(v, 48.0)
    if n <= 0:
        return 48.0
    return n * 12.0 if n <= 15 else n


# --------------------------------------------------------------- fitur model
def build_feature_row(prev_milk_yield_l, dmi_kg, usia_bulan, suhu_c,
                      kelembapan_pct, genetic_group, tahap_laktasi) -> pd.DataFrame:
    """Satu baris fitur (DataFrame 1 x len(FEATURE_COLUMNS)) untuk pipeline model.

    Nilai turunan (thi_score, feed_efficiency_prev) dihitung agar IDENTIK dengan dataset:
      thi_score            = thi_from(suhu_c, kelembapan_pct)
      feed_efficiency_prev = prev_milk_yield_l / dmi_kg
    """
    prev = max(0.0, _num(prev_milk_yield_l, 0.0))
    dmi = max(0.1, _num(dmi_kg, 9.85))
    suhu = _num(suhu_c, 27.0)
    rh = _clip(_num(kelembapan_pct, 70.0), 0.0, 100.0)
    thi = thi_from(suhu, rh)
    feff = prev / dmi
    row = {
        "prev_milk_yield_l": prev,
        "dmi_kg": dmi,
        "usia_bulan": normalize_usia_bulan(usia_bulan),
        "suhu_c": suhu,
        "kelembapan_pct": rh,
        "thi_score": thi,
        "feed_efficiency_prev": feff,
        "genetic_group": normalize_genetic(genetic_group),
        "tahap_laktasi": normalize_stage(tahap_laktasi),
    }
    return pd.DataFrame([row], columns=FEATURE_COLUMNS)


def segment_row(prev_milk_yield_l, dmi_kg) -> np.ndarray:
    """Vektor fitur segmentasi (1 x 3) sesuai SEGMENT_FEATURES.
    Dihitung dari produksi sebelumnya & pakan (tersedia saat input, tanpa menunggu prediksi)."""
    prev = max(0.0, _num(prev_milk_yield_l, 0.0))
    dmi = max(0.1, _num(dmi_kg, 9.85))
    return np.array([[prev / dmi, dmi, prev]], dtype=float)


# ----------------------------------------------------------------- penjelasan
def build_reason(feat: dict, pred_h1: float, drop_pct: float, warn: bool, thr: float) -> str:
    """Alasan prediksi dalam bahasa Indonesia (berbasis aturan dari fitur)."""
    r = []
    thi = feat["thi_score"]
    if thi > HEAT_THI_THRESHOLD:
        tingkat = "berat" if thi >= 79 else "ringan-sedang"
        r.append(f"indeks suhu-kelembaban (THI) {thi:.0f} di atas ambang nyaman {HEAT_THI_THRESHOLD:.0f} "
                 f"(suhu {feat['suhu_c']:.1f}°C, kelembaban {feat['kelembapan_pct']:.0f}%), risiko heat stress {tingkat}")
    feff = feat["feed_efficiency_prev"]
    if feff < 0.35:
        r.append(f"efisiensi pakan rendah ({feff:.2f} L susu/kg pakan) — pakan {feat['dmi_kg']:.1f} kg "
                 f"belum sebanding dengan produksi")
    elif feff > 0.60:
        r.append(f"efisiensi pakan baik ({feff:.2f} L susu/kg pakan)")
    g = feat["genetic_group"]
    if g == "Local":
        r.append("kelompok genetik Local memiliki potensi produksi lebih rendah dari galur HF")
    elif g in ("HF75", "HF87.5"):
        r.append(f"kelompok genetik {g} berpotensi produksi tinggi")
    stage = feat["tahap_laktasi"]
    if stage == "Akhir":
        r.append("tahap laktasi Akhir: produksi menurun secara alami menjelang kering")
    elif stage == "Awal":
        r.append("tahap laktasi Awal: produksi cenderung meningkat menuju puncak")

    if warn:
        head = (f"Peringatan dini: produksi H+1 diperkirakan {pred_h1:.1f} L, "
                f"turun {drop_pct:.1f}% dari produksi sebelumnya.")
        if not r:
            r.append("tidak ada penyebab tunggal yang jelas; periksa kesehatan sapi (mis. mastitis), "
                     "kecukupan pakan, dan kondisi kandang")
    else:
        head = (f"Produksi stabil: H+1 diperkirakan {pred_h1:.1f} L "
                f"({'turun' if drop_pct >= 0 else 'naik'} {abs(drop_pct):.1f}% dari sebelumnya).")
    return head + (" Faktor: " + "; ".join(r) + "." if r else "")
