"""Fungsi & konstanta bersama untuk training (train_model.py) dan serving (app.py).

PENTING: pembuatan fitur harus IDENTIK di training dan serving, karena itu
dipusatkan di sini. Jangan menduplikasi logika fitur di tempat lain.
"""
from __future__ import annotations

import math
import uuid

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- konstanta
N_LAGS = 7                      # riwayat harian yang dipakai (hari t, t-1, ..., t-6)
HORIZONS = (1, 2, 3)            # prediksi 1-3 hari ke depan
DROP_THRESHOLD = 0.10           # "penurunan tajam" = >=10% di bawah rata-rata 3 hari terakhir
HEAT_THRESHOLD_C = 27.0         # di atas suhu ini sapi FH mulai terkena heat stress
STAGES = ["awal", "puncak", "tengah", "akhir"]          # ordinal 0..3
FEED_TYPES = ["hijauan", "konsentrat", "campuran"]
SEGMEN_LABELS = ["Rendah", "Sedang", "Tinggi"]          # urut dari produksi terendah
SEGMENT_WINDOW = 30             # jendela (hari) untuk fitur K-Means

# Namespace UUID untuk memetakan UID Firebase -> profiles.id / cattle.farmer_id.
# HARUS sama dengan FARMER_NAMESPACE di js/supabase-config.js.
FARMER_NAMESPACE = uuid.UUID("a3f1c2de-5b6a-4c1e-9d8f-1a2b3c4d5e6f")


def farmer_id_from_uid(firebase_uid: str) -> str:
    return str(uuid.uuid5(FARMER_NAMESPACE, firebase_uid))


# --------------------------------------------------------- normalisasi input
def stage_from_dim(dim: float) -> int:
    """Hari laktasi (DIM) -> indeks tahap 0..3."""
    if dim <= 30:
        return 0
    if dim <= 100:
        return 1
    if dim <= 200:
        return 2
    return 3


def normalize_stage(v) -> int:
    """tahap_laktasi dari DB (teks atau angka) -> indeks 0..3. Default: 'tengah'."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 2
    if isinstance(v, (int, float, np.integer, np.floating)):
        n = float(v)
        return int(n) - 1 if 1 <= n <= 4 and float(n).is_integer() else stage_from_dim(n)
    s = str(v).strip().lower()
    for key, idx in (("awal", 0), ("early", 0), ("puncak", 1), ("peak", 1),
                     ("tengah", 2), ("mid", 2), ("akhir", 3), ("late", 3), ("kering", 3)):
        if key in s:
            return idx
    try:
        return normalize_stage(float(s))
    except ValueError:
        return 2


def normalize_feed_type(v) -> int:
    """jenis_pakan -> indeks FEED_TYPES. Tak dikenal -> 'campuran'."""
    s = "" if v is None else str(v).strip().lower()
    for i, name in enumerate(FEED_TYPES):
        if name in s:
            return i
    if "hijau" in s or "rumput" in s:
        return 0
    if "konsen" in s or "pelet" in s:
        return 1
    return 2


def normalize_usia_bulan(v) -> float:
    """usia -> bulan. Nilai <= 15 dianggap TAHUN (mis. 4 -> 48 bulan)."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 48.0
    if math.isnan(n) or n <= 0:
        return 48.0
    return n * 12.0 if n <= 15 else n


# --------------------------------------------------------------- fitur regresi
def _ffill_axis1(a: np.ndarray) -> np.ndarray:
    """Isi NaN pada kolom k dengan kolom k-1 (nilai lebih baru). Kolom 0 harus terisi."""
    a = a.copy()
    for k in range(1, a.shape[1]):
        m = np.isnan(a[:, k])
        a[m, k] = a[m, k - 1]
    return a


FEATURE_NAMES = [
    "ma3", "y0_rel", "y1_rel", "y2_rel", "trend", "cv7",
    "f0", "f0_rel", "f1_rel", "f_mean",
    "s0", "s1", "s2", "s3", "s_max3", "heat0", "heat_idx",
    "usia", "stage", "feed_hijauan", "feed_konsentrat", "feed_campuran", "n_hist",
]


def build_features(Y, F, S, usia, stage, feed_idx) -> pd.DataFrame:
    """Bangun matriks fitur.

    Y, F, S : array (n, 7) -> volume susu, pakan (kg), suhu kandang. Kolom 0 = hari t
              (hari terakhir), kolom k = t-k. NaN = data tidak ada (riwayat pendek /
              hari terlewat); diisi dengan nilai terbaru yang tersedia.
    usia (bulan), stage (0..3), feed_idx (0..2) : array (n,)
    """
    Y = np.asarray(Y, dtype=float)
    F = np.asarray(F, dtype=float)
    S = np.asarray(S, dtype=float)
    n_hist = np.sum(~np.isnan(Y), axis=1).astype(float)
    Y, F, S = _ffill_axis1(Y), _ffill_axis1(F), _ffill_axis1(S)

    ma3 = np.clip(Y[:, :3].mean(1), 0.1, None)
    ma7 = np.clip(Y.mean(1), 0.1, None)
    f_mean = np.clip(F.mean(1), 0.1, None)
    s3 = S[:, :3].mean(1)
    feed_idx = np.asarray(feed_idx, dtype=int)

    X = pd.DataFrame({
        "ma3": ma3,
        "y0_rel": Y[:, 0] / ma3,
        "y1_rel": Y[:, 1] / ma3,
        "y2_rel": Y[:, 2] / ma3,
        "trend": ma3 / ma7,
        "cv7": Y.std(1) / ma7,
        "f0": F[:, 0],
        "f0_rel": F[:, 0] / f_mean,
        "f1_rel": F[:, 1] / f_mean,
        "f_mean": f_mean,
        "s0": S[:, 0], "s1": S[:, 1], "s2": S[:, 2],
        "s3": s3,
        "s_max3": S[:, :3].max(1),
        "heat0": np.clip(S[:, 0] - HEAT_THRESHOLD_C, 0, None),
        "heat_idx": np.clip(s3 - HEAT_THRESHOLD_C, 0, None),
        "usia": np.asarray(usia, dtype=float),
        "stage": np.asarray(stage, dtype=float),
        "feed_hijauan": (feed_idx == 0).astype(float),
        "feed_konsentrat": (feed_idx == 1).astype(float),
        "feed_campuran": (feed_idx == 2).astype(float),
        "n_hist": n_hist,
    })
    return X[FEATURE_NAMES]


# ------------------------------------------------------------- fitur K-Means
SEGMENT_FEATURES = ["mean_volume", "efisiensi", "cv"]


def segment_features(volume, feed) -> list[float]:
    """Ringkasan satu sapi (maks. 30 hari terakhir): rata-rata volume, efisiensi
    (liter susu per kg pakan), dan koefisien variasi (kestabilan)."""
    v = np.asarray(volume, dtype=float)
    f = np.asarray(feed, dtype=float)
    v = v[~np.isnan(v)]
    f = f[~np.isnan(f)]
    mean_v = float(v.mean()) if len(v) else 0.0
    mean_f = float(f.mean()) if len(f) else 10.0
    cv = float(v.std() / mean_v) if len(v) > 1 and mean_v > 0 else 0.0
    return [mean_v, mean_v / max(mean_f, 0.1), cv]


# ----------------------------------------------------------------- penjelasan
def build_reason(feat: dict, drop_pcts: list[float], warn: bool, thr: float) -> str:
    """Alasan prediksi dalam bahasa Indonesia (berbasis aturan dari fitur)."""
    r = []
    if feat["s3"] > HEAT_THRESHOLD_C or feat["s0"] > HEAT_THRESHOLD_C + 1:
        r.append(f"suhu kandang {feat['s0']:.1f}°C (rata-rata 3 hari {feat['s3']:.1f}°C) di atas "
                 f"ambang nyaman {HEAT_THRESHOLD_C:.0f}°C, berisiko heat stress")
    if feat["f0_rel"] < 0.92:
        r.append(f"jumlah pakan {feat['f0']:.1f} kg, {100 * (1 - feat['f0_rel']):.0f}% di bawah rata-rata 7 hari")
    if feat["trend"] < 0.97:
        r.append(f"produksi 3 hari terakhir turun {100 * (1 - feat['trend']):.0f}% dibanding rata-rata 7 hari")
    elif feat["trend"] > 1.03:
        r.append(f"produksi 3 hari terakhir naik {100 * (feat['trend'] - 1):.0f}% dibanding rata-rata 7 hari")
    worst = max(drop_pcts)
    if warn:
        head = f"Peringatan dini: volume diperkirakan turun hingga {100 * worst:.1f}% dari rata-rata 3 hari terakhir."
        if not r:
            r.append("tidak ada penyebab tunggal yang jelas; periksa kondisi kesehatan sapi (mis. mastitis) dan pakan")
    elif r:
        head = "Tidak ada penurunan tajam diperkirakan."
    else:
        head = "Tidak ada penurunan tajam diperkirakan; pakan, suhu, dan tren produksi stabil."
    txt = head + (" Faktor: " + "; ".join(r) + "." if r else "")
    if feat["n_hist"] < 3:
        txt += f" Catatan: riwayat baru {int(feat['n_hist'])} hari, akurasi meningkat seiring data harian bertambah."
    return txt
