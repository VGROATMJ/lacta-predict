#!/usr/bin/env python3
"""Lacta-Predict - training 2 model AI dari dataset tabular.

  a) K-Means (3 klaster)  -> segmen performa sapi: Tinggi / Sedang / Rendah
  b) Regresi (Linear Regression & Random Forest, dipilih otomatis) -> volume susu
     1, 2, dan 3 hari ke depan, plus peringatan dini penurunan tajam.

Jika file CSV belum ada, dataset DUMMY realistis dibuat otomatis (data/dataset_susu.csv)
sehingga script bisa langsung dijalankan:

    python train_model.py                      # CSV ada -> dipakai, belum ada -> dibuat
    python train_model.py --csv data_saya.csv  # pakai data sendiri
    python train_model.py --regenerate         # buat ulang dataset dummy

Kolom CSV yang dibutuhkan (sesuai tabel Supabase cattle + daily_logs):
    cattle_id, tanggal, usia, tahap_laktasi, jumlah_pakan, jenis_pakan,
    suhu_kandang, volume_susu_aktual

CATATAN: angka evaluasi pada dataset dummy hanya membuktikan pipeline berjalan,
BUKAN akurasi di dunia nyata. Latih ulang dengan data peternakan asli.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score, silhouette_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import common as C

BASE = Path(__file__).resolve().parent
TARGET_MAPE = 15.0      # persen
TARGET_RECALL = 0.80
REQUIRED_COLS = ["cattle_id", "tanggal", "usia", "tahap_laktasi", "jumlah_pakan",
                 "jenis_pakan", "suhu_kandang", "volume_susu_aktual"]


# =============================================================== dataset dummy
def generate_dummy_dataset(n_cows: int = 150, n_days: int = 180, seed: int = 42,
                           start: str = "2026-01-01", debug: bool = False) -> pd.DataFrame:
    """Simulasi peternakan sapi perah tropis.

    Asumsi yang dimodelkan (semua dari pola umum literatur peternakan, bukan data nyata):
      * kurva laktasi Wood: y = a * DIM^b * exp(-c * DIM), potensi genetik & paritas berbeda tiap sapi
      * heat stress: produksi turun ~2,2%/°C di atas 27°C, dengan jeda 1-2 hari (pola yang
        dilaporkan literatur: susu merespons suhu/THI ~48 jam sebelumnya); sapi berproduksi
        tinggi lebih rentan
      * pakan: kekurangan pakan (kandang kekurangan stok) menurunkan susu keesokan harinya
      * penyakit (mis. mastitis): turun 15-35% mendadak 3-6 hari -> TIDAK terobservasi fiturnya
      * suhu kandang dibagi per kandang (gelombang panas), derau harian berautokorelasi
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=n_days, freq="D")
    n_barns = 8

    # cuaca & kejadian per kandang
    temp = np.zeros((n_barns, n_days))
    shortage = np.ones((n_barns, n_days))
    for b in range(n_barns):
        season = 28.0 + 1.2 * np.sin(2 * np.pi * (np.arange(n_days) + rng.integers(0, 60)) / 120)
        ar, e = np.zeros(n_days), rng.normal(0, 0.9, n_days)
        for t in range(1, n_days):
            ar[t] = 0.7 * ar[t - 1] + e[t]
        wave = np.zeros(n_days)
        t = 0
        while t < n_days:
            if rng.random() < 0.03:
                ln = int(rng.integers(2, 6))
                wave[t:t + ln] += rng.uniform(3.0, 6.0)
                t += ln
            t += 1
        temp[b] = np.clip(season + ar + wave, 22, 40)
        t = 0
        while t < n_days:
            if rng.random() < 0.015:
                ln = int(rng.integers(2, 5))
                shortage[b, t:t + ln] = rng.uniform(0.65, 0.85)
                t += ln
            t += 1

    rows = []
    for i in range(n_cows):
        barn = int(rng.integers(0, n_barns))
        parity = int(rng.choice([1, 2, 3, 4], p=[0.3, 0.25, 0.25, 0.2]))
        usia0 = {1: rng.uniform(26, 36), 2: rng.uniform(38, 52), 3: rng.uniform(54, 70), 4: rng.uniform(72, 100)}[parity]
        pfac = {1: 0.85, 2: 0.95, 3: 1.0, 4: 1.0}[parity]
        a = float(np.clip(rng.normal(10.5, 2.4), 6, 16)) * pfac
        b_w, c_w = rng.uniform(0.20, 0.30), rng.uniform(0.0035, 0.0048)
        dim0 = int(rng.integers(5, 121))
        dim = dim0 + np.arange(n_days)
        base = a * dim ** b_w * np.exp(-c_w * dim)
        peak = base.max()
        feed_type = int(rng.choice(3, p=[0.25, 0.25, 0.5]))
        ftype_eff = [0.97, 1.01, 1.0][feed_type]
        need = 6.5 + 0.22 * peak
        susceptibility = rng.uniform(0.8, 1.4) * (0.8 + peak / 60)

        feed = need * (1 + rng.normal(0, 0.04, n_days)) * shortage[barn]
        T = temp[barn]
        t1, t2 = np.r_[T[0], T[:-1]], np.r_[T[0], T[0], T[:-2]]
        teff = 0.5 * t1 + 0.5 * t2
        heat_eff = -0.022 * susceptibility * np.clip(teff - C.HEAT_THRESHOLD_C, 0, None)
        ratio = 0.3 * (feed / need) + 0.7 * (np.r_[feed[0], feed[:-1]] / need)
        feed_eff = 0.65 * np.minimum(0, ratio - 0.97) + 0.10 * np.clip(ratio - 1, 0, 0.15)

        disease = np.zeros(n_days)
        t = 0
        while t < n_days:
            if rng.random() < 0.0012:
                ln, mag = min(int(rng.integers(3, 7)), n_days - t), rng.uniform(0.15, 0.35)
                disease[t:t + ln] = -mag * np.linspace(1.0, 0.4, ln)
                t += ln
            t += 1

        noise, e = np.zeros(n_days), rng.normal(0, 0.025, n_days)
        for t in range(1, n_days):
            noise[t] = 0.5 * noise[t - 1] + e[t]

        vol = base * ftype_eff * (1 + heat_eff + feed_eff + disease + noise)
        vol = np.clip(vol, 1.0, None)
        for t in range(n_days):
            rows.append((f"SAPI-{i + 1:03d}", dates[t].date().isoformat(),
                         round(usia0 + t / 30.4, 1), C.STAGES[C.stage_from_dim(dim[t])],
                         round(float(feed[t]), 1), C.FEED_TYPES[feed_type],
                         round(float(T[t]), 1), round(float(vol[t]), 1))
                        + ((float(heat_eff[t]), float(feed_eff[t]), float(disease[t]), float(noise[t])) if debug else ()))
    return pd.DataFrame(rows, columns=REQUIRED_COLS + (["_heat", "_feed", "_dis", "_noise"] if debug else []))


# ============================================================== data -> fitur
def load_dataset(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    miss = [c for c in REQUIRED_COLS if c not in df.columns]
    if miss:
        sys.exit(f"CSV {path} kekurangan kolom: {miss}")
    df = df[REQUIRED_COLS].copy()
    df["tanggal"] = pd.to_datetime(df["tanggal"])
    df["volume_susu_aktual"] = pd.to_numeric(df["volume_susu_aktual"], errors="coerce")
    df = df.dropna(subset=["cattle_id", "tanggal", "volume_susu_aktual"])
    df = df[df["volume_susu_aktual"] > 0]
    return df.sort_values(["cattle_id", "tanggal"]).reset_index(drop=True)


def build_supervised(df: pd.DataFrame, rng: np.random.Generator | None = None,
                     augment_frac: float = 0.0, cold_start: bool = False):
    """Ubah log harian -> (X, target T, meta).

    T[:, h-1] = volume pada hari t+h. Rasio target dihitung terhadap X['ma3'] saat training.
    augment_frac : porsi baris yang riwayatnya dipotong acak (1-7 hari) agar model tangguh
                   untuk sapi baru dengan data sedikit (kasus nyata di aplikasi).
    cold_start   : paksa semua baris hanya punya 1 hari riwayat (untuk evaluasi cold-start).
    """
    Ys, Fs, Ss, Us, Gs, Ks, Ts, dates, ids = [], [], [], [], [], [], [], [], []
    for cid, g in df.groupby("cattle_id", sort=False):
        g = g.drop_duplicates("tanggal", keep="last").set_index("tanggal").sort_index()
        g = g.reindex(pd.date_range(g.index.min(), g.index.max(), freq="D"))
        y = g["volume_susu_aktual"]
        f = pd.to_numeric(g["jumlah_pakan"], errors="coerce").ffill().bfill()
        s = pd.to_numeric(g["suhu_kandang"], errors="coerce").ffill().bfill()
        usia = pd.to_numeric(g["usia"], errors="coerce").ffill().bfill()
        stage = g["tahap_laktasi"].ffill().bfill()
        jenis = g["jenis_pakan"].ffill().bfill()
        Y = np.column_stack([y.shift(k).to_numpy(float) for k in range(C.N_LAGS)])
        F = np.column_stack([f.shift(k).to_numpy(float) for k in range(C.N_LAGS)])
        S = np.column_stack([s.shift(k).to_numpy(float) for k in range(C.N_LAGS)])
        T = np.column_stack([y.shift(-h).to_numpy(float) for h in C.HORIZONS])
        keep = ~np.isnan(Y[:, 0]) & ~np.isnan(F[:, 0]) & ~np.isnan(S[:, 0])
        Ys.append(Y[keep]); Fs.append(F[keep]); Ss.append(S[keep]); Ts.append(T[keep])
        Us.append(usia.map(C.normalize_usia_bulan).to_numpy(float)[keep])
        Gs.append(stage.map(C.normalize_stage).to_numpy(int)[keep])
        Ks.append(jenis.map(C.normalize_feed_type).to_numpy(int)[keep])
        dates.append(g.index.to_numpy()[keep])
        ids.append(np.full(keep.sum(), cid))
    Y, F, S, T = map(np.vstack, (Ys, Fs, Ss, Ts))
    if cold_start:
        Y[:, 1:] = np.nan; F[:, 1:] = np.nan; S[:, 1:] = np.nan
    elif augment_frac > 0:
        rng = rng or np.random.default_rng(0)
        pick = np.where(rng.random(len(Y)) < augment_frac)[0]
        L = rng.integers(1, C.N_LAGS + 1, size=len(pick))     # riwayat tersisa 1..7 hari
        for i, l in zip(pick, L):
            Y[i, l:] = np.nan; F[i, l:] = np.nan; S[i, l:] = np.nan
    X = C.build_features(Y, F, S, np.concatenate(Us), np.concatenate(Gs), np.concatenate(Ks))
    meta = pd.DataFrame({"cattle_id": np.concatenate(ids), "tanggal": np.concatenate(dates)})
    return X, T, meta


# ============================================================= model regresi
def make_regressor(kind: str, seed: int):
    if kind == "linear":
        return Pipeline([("sc", StandardScaler()), ("lr", LinearRegression())])
    return RandomForestRegressor(n_estimators=250, min_samples_leaf=5, max_features=0.6,
                                 n_jobs=-1, random_state=seed)


def fit_models(kind, X, T, seed):
    """Satu model per horizon; target = volume(t+h) / rata-rata 3 hari terakhir."""
    models = {}
    for j, h in enumerate(C.HORIZONS):
        ok = ~np.isnan(T[:, j])
        models[h] = make_regressor(kind, seed).fit(X[ok], T[ok, j] / X["ma3"].to_numpy()[ok])
    return models


def predict_volumes(models, X) -> np.ndarray:
    """-> array (n, 3) volume prediksi (liter)."""
    ma3 = X["ma3"].to_numpy()
    out = np.column_stack([models[h].predict(X) * ma3 for h in C.HORIZONS])
    return np.clip(out, 0, None)


def mape(y, p):
    return float(np.mean(np.abs((y - p) / y)) * 100)


def drop_scores(pred, ma3):
    """Skor peringatan = penurunan terbesar (fraksi) di antara horizon 1-3 vs ma3."""
    return np.max(1 - pred / ma3[:, None], axis=1)


def true_drop_label(T, ma3):
    return np.any(T <= (1 - C.DROP_THRESHOLD) * ma3[:, None], axis=1)


def recall_precision(y_true, y_pred):
    tp = int(np.sum(y_true & y_pred)); fn = int(np.sum(y_true & ~y_pred)); fp = int(np.sum(~y_true & y_pred))
    rec = tp / (tp + fn) if tp + fn else float("nan")
    prec = tp / (tp + fp) if tp + fp else float("nan")
    return rec, prec, tp, fn, fp


def evaluate(models, X, T):
    ok = ~np.isnan(T).any(axis=1)
    X, T = X[ok], T[ok]
    P = predict_volumes(models, X)
    res = {"per_horizon": {}}
    for j, h in enumerate(C.HORIZONS):
        res["per_horizon"][h] = {
            "mape": mape(T[:, j], P[:, j]),
            "mae": float(mean_absolute_error(T[:, j], P[:, j])),
            "rmse": float(np.sqrt(np.mean((T[:, j] - P[:, j]) ** 2))),
            "r2": float(r2_score(T[:, j], P[:, j])),
        }
    res["mape_mean"] = float(np.mean([v["mape"] for v in res["per_horizon"].values()]))
    return res, X, T, P


# ================================================================== K-Means
def segment_windows(df: pd.DataFrame) -> np.ndarray:
    """Fitur segmen untuk tiap jendela 30 hari tiap sapi (cocok dengan serving: 30 hari terakhir)."""
    rows = []
    for _, g in df.groupby("cattle_id", sort=False):
        g = g.sort_values("tanggal")
        v, f = g["volume_susu_aktual"].to_numpy(float), pd.to_numeric(g["jumlah_pakan"], errors="coerce").to_numpy(float)
        for s in range(0, len(g) - C.SEGMENT_WINDOW + 1, C.SEGMENT_WINDOW):
            rows.append(C.segment_features(v[s:s + C.SEGMENT_WINDOW], f[s:s + C.SEGMENT_WINDOW]))
    return np.array(rows)


def train_kmeans(df: pd.DataFrame, seed: int) -> dict:
    W = segment_windows(df)
    sc = StandardScaler().fit(W)
    km = KMeans(n_clusters=3, n_init=20, random_state=seed).fit(sc.transform(W))
    centers = sc.inverse_transform(km.cluster_centers_)
    order = np.argsort(centers[:, 0])                  # urut dari rata-rata volume terkecil
    mapping = {int(c): C.SEGMEN_LABELS[rank] for rank, c in enumerate(order)}
    labels = km.labels_
    sil = float(silhouette_score(sc.transform(W), labels))
    info = {}
    for c in order:
        m = labels == c
        info[mapping[int(c)]] = {
            "n_windows": int(m.sum()),
            "mean_volume_l": round(float(centers[c, 0]), 2),
            "efisiensi_l_per_kg": round(float(centers[c, 1]), 3),
            "cv": round(float(centers[c, 2]), 3),
        }
    return {"scaler": sc, "kmeans": km, "cluster_to_label": mapping,
            "feature_names": C.SEGMENT_FEATURES, "silhouette": sil, "segments": info,
            "window_days": C.SEGMENT_WINDOW}


# ===================================================================== main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=str(BASE / "data" / "dataset_susu.csv"))
    ap.add_argument("--models-dir", default=str(BASE / "models"))
    ap.add_argument("--regenerate", action="store_true", help="buat ulang dataset dummy (menimpa CSV)")
    ap.add_argument("--cows", type=int, default=150)
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    csv, models_dir = Path(args.csv), Path(args.models_dir)
    csv.parent.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    if args.regenerate or not csv.exists():
        print(f"[data] CSV tidak ada/regenerate -> membuat dataset DUMMY ({args.cows} sapi x {args.days} hari) -> {csv}")
        generate_dummy_dataset(args.cows, args.days, args.seed).to_csv(csv, index=False)
        source = "dummy"
    else:
        print(f"[data] memakai {csv}")
        source = "csv"
    df = load_dataset(csv)
    print(f"[data] {len(df):,} baris, {df['cattle_id'].nunique()} sapi, "
          f"{df['tanggal'].min().date()} s/d {df['tanggal'].max().date()}")

    # ---- split berbasis waktu (hindari kebocoran masa depan): 70% train / 15% val / 15% test
    d = np.sort(df["tanggal"].unique())
    c1, c2 = d[int(len(d) * 0.70)], d[int(len(d) * 0.85)]
    gap = np.timedelta64(max(C.HORIZONS), "D")
    rng = np.random.default_rng(args.seed)

    X_all, T_all, meta = build_supervised(df, rng=rng, augment_frac=0.0)
    Xa_all, Ta_all, meta_a = build_supervised(df, rng=rng, augment_frac=0.4)   # versi augmentasi riwayat
    dt = meta["tanggal"].to_numpy()
    m_tr, m_va, m_te = dt <= c1 - gap, (dt > c1) & (dt <= c2 - gap), dt > c2
    print(f"[split] train={m_tr.sum():,}  val={m_va.sum():,}  test={m_te.sum():,} baris (berbasis waktu)")

    # ---- pilih model regresi pada validasi
    results = {}
    for kind in ("linear", "random_forest"):
        mdl = fit_models(kind, Xa_all[m_tr], Ta_all[m_tr], args.seed)
        r, *_ = evaluate(mdl, X_all[m_va], T_all[m_va])
        results[kind] = (mdl, r)
        print(f"[val] {kind:14s} MAPE rata-rata = {r['mape_mean']:.2f}%")
    best = min(results, key=lambda k: results[k][1]["mape_mean"])
    models = results[best][0]
    print(f"[pilih] model regresi terbaik di validasi: {best}")

    # ---- tuning ambang peringatan dini pada validasi (cari ambang tertinggi dengan recall >= 85%)
    rv, Xv, Tv, Pv = evaluate(models, X_all[m_va], T_all[m_va])
    sv, yv = drop_scores(Pv, Xv["ma3"].to_numpy()), true_drop_label(Tv, Xv["ma3"].to_numpy())
    grid = np.round(np.arange(0.01, 0.1201, 0.005), 3)
    good = [g for g in grid if recall_precision(yv, sv >= g)[0] >= 0.85]
    thr = float(max(good)) if good else float(grid[0])
    print(f"[alert] ambang peringatan (prediksi turun >= {thr * 100:.1f}% dari rata-rata 3 hari) dipilih di validasi")

    # ---- evaluasi akhir pada TEST (model dilatih hanya dari train)
    rt, Xt, Tt, Pt = evaluate(models, X_all[m_te], T_all[m_te])
    st, yt = drop_scores(Pt, Xt["ma3"].to_numpy()), true_drop_label(Tt, Xt["ma3"].to_numpy())
    rec, prec, tp, fn, fp = recall_precision(yt, st >= thr)
    base_naive = [mape(Tt[:, j], np.repeat(Xt["ma3"].to_numpy()[:, None], 3, 1)[:, j]) for j in range(3)]
    Xc, Tc, _ = build_supervised(df[df["tanggal"] > c2], cold_start=True)
    rc, *_ = evaluate(models, Xc, Tc)

    print("\n" + "=" * 66)
    print(f" EVALUASI TEST ({best}, data {source})")
    print("=" * 66)
    print(f" {'Horizon':<10}{'MAPE':>9}{'MAE (L)':>10}{'RMSE (L)':>10}{'R2':>8}{'MAPE naif*':>13}")
    for j, h in enumerate(C.HORIZONS):
        v = rt["per_horizon"][h]
        print(f" H+{h:<8}{v['mape']:>8.2f}%{v['mae']:>10.2f}{v['rmse']:>10.2f}{v['r2']:>8.3f}{base_naive[j]:>12.2f}%")
    print(f" {'Rata-rata':<10}{rt['mape_mean']:>8.2f}%   (*naif = rata-rata 3 hari terakhir)")
    print(f" MAPE cold-start (hanya 1 hari riwayat): {rc['mape_mean']:.2f}%")
    print("-" * 66)
    print(f" Penurunan tajam (>= {C.DROP_THRESHOLD * 100:.0f}%) nyata pada {int(yt.sum()):,} dari {len(yt):,} sampel test ({yt.mean() * 100:.1f}%)")
    print(f" Recall peringatan dini : {rec * 100:.1f}%   (TP={tp}, FN={fn})")
    print(f" Precision              : {prec * 100:.1f}%   (FP={fp})")
    tradeoff = []
    print(" Trade-off ambang peringatan (test):  ambang   recall  precision  alarm/sampel")
    for g in sorted({thr, 0.03, 0.05, 0.07, 0.09}):
        r_, p_, *_ = recall_precision(yt, st >= g)
        tradeoff.append({"threshold": g, "recall": r_, "precision": p_, "alert_rate": float(np.mean(st >= g))})
        mark = "  <- dipakai" if g == thr else ""
        print(f"{'':37}{g * 100:>4.1f}%  {r_ * 100:>6.1f}%  {p_ * 100:>8.1f}%  {np.mean(st >= g) * 100:>9.1f}%{mark}")
    if np.mean(st >= thr) > 0.35:
        print(" ! Recall tinggi dicapai dengan alarm yang sering (>35% sampel). Kemungkinan penyebab: penurunan"
              "\n   tajam dipicu perubahan suhu/pakan hari-hari BERIKUTNYA yang belum terlihat saat prediksi. Naikkan ambang"
              "\n   (env ALERT_THRESHOLD di backend) jika terlalu banyak alarm, dengan konsekuensi recall turun.")
    print("-" * 66)
    ok_mape = rt["mape_mean"] <= TARGET_MAPE
    ok_rec = rec >= TARGET_RECALL
    print(f" Target MAPE <= {TARGET_MAPE:.0f}%      : {'LULUS' if ok_mape else 'BELUM LULUS'}  ({rt['mape_mean']:.2f}%)")
    print(f" Target Recall >= {TARGET_RECALL * 100:.0f}%    : {'LULUS' if ok_rec else 'BELUM LULUS'}  ({rec * 100:.1f}%)")
    print("=" * 66)
    if source == "dummy":
        print(" ! Dataset DUMMY: angka di atas hanya bukti pipeline jalan, bukan akurasi nyata.")

    # ---- K-Means
    seg = train_kmeans(df, args.seed)
    print(f"\n[kmeans] 3 segmen, silhouette = {seg['silhouette']:.3f}")
    for lab in reversed(C.SEGMEN_LABELS):
        s = seg["segments"][lab]
        print(f"   {lab:<7} n={s['n_windows']:<5} rata-rata {s['mean_volume_l']:>5.1f} L/hari  "
              f"efisiensi {s['efisiensi_l_per_kg']:.2f} L/kg  CV {s['cv']:.3f}")

    # ---- refit final di SELURUH data lalu simpan
    final = fit_models(best, Xa_all, Ta_all, args.seed)
    metrics = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_source": source, "n_rows": int(len(df)), "n_cattle": int(df["cattle_id"].nunique()),
        "model_kind": best, "alert_threshold": thr, "drop_threshold": C.DROP_THRESHOLD,
        "test": {"per_horizon": {f"H+{h}": v for h, v in rt["per_horizon"].items()},
                 "mape_mean": rt["mape_mean"], "mape_cold_start": rc["mape_mean"],
                 "recall_peringatan_dini": rec, "precision_peringatan_dini": prec,
                 "alert_tradeoff": tradeoff,
                 "mape_target_met": bool(ok_mape), "recall_target_met": bool(ok_rec)},
        "kmeans": {"silhouette": seg["silhouette"], "segments": seg["segments"]},
        "sklearn_version": sklearn.__version__,
    }
    joblib.dump({"models": final, "kind": best, "horizons": list(C.HORIZONS),
                 "feature_names": C.FEATURE_NAMES, "alert_threshold": thr,
                 "drop_threshold": C.DROP_THRESHOLD, "metrics": metrics},
                models_dir / "regresi_susu.joblib", compress=3)
    joblib.dump(seg, models_dir / "kmeans_segmen.joblib", compress=3)
    (models_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"\n[simpan] {models_dir / 'regresi_susu.joblib'}\n[simpan] {models_dir / 'kmeans_segmen.joblib'}"
          f"\n[simpan] {models_dir / 'metrics.json'}")


if __name__ == "__main__":
    main()
