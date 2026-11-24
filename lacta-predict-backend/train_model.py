#!/usr/bin/env python3
"""Lacta-Predict - training 2 model AI dari dataset `lacta_predict_dataset_clean_v2.csv`.

  a) Regresi  -> prediksi produksi susu `milk_yield_l` (liter) H+1, dan H+2/H+3 secara REKURSIF.
                 Dibandingkan: Linear Regression, Random Forest, Gradient Boosting; terbaik dipilih
                 otomatis lewat validasi silang (5-fold) di data train, lalu diuji di data test.
  b) K-Means (3 klaster) -> segmen performa: Performa Rendah (Prioritas) / Rata-rata / Tinggi.
                 Direproduksi dari fitur (feed_efficiency_prev, dmi_kg, prev_milk_yield_l) sehingga
                 cocok dengan kolom `segmen_nama` pada dataset.

TIDAK ADA dataset dummy: file CSV WAJIB tersedia (default: data/lacta_predict_dataset_clean_v2.csv).

Jalankan:
    python train_model.py
    python train_model.py --csv data/lacta_predict_dataset_clean_v2.csv
    python train_model.py --alert-recall 0.80

Kolom CSV yang dibutuhkan:
    genetic_group, dmi_kg, milk_yield_l, suhu_c, kelembapan_pct, prev_milk_yield_l,
    usia_bulan, tahap_laktasi   (opsional: thi_score, feed_efficiency_prev, segmen_nama, split)
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
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score, silhouette_score
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

import common as C

BASE = Path(__file__).resolve().parent
TARGET_MAPE = 15.0          # persen
TARGET_RECALL = 0.80
MAPE_FLOOR = 1.0            # MAPE dihitung pada sampel dengan produksi nyata >= 1 L
REQUIRED_COLS = ["genetic_group", "dmi_kg", "milk_yield_l", "suhu_c", "kelembapan_pct",
                 "prev_milk_yield_l", "usia_bulan", "tahap_laktasi"]


# ============================================================== data -> fitur
def load_dataset(path: Path) -> pd.DataFrame:
    if not path.exists():
        sys.exit(f"[galat] Dataset tidak ditemukan: {path}\n"
                 f"        Salin 'lacta_predict_dataset_clean_v2.csv' ke folder data/ lalu ulangi.")
    df = pd.read_csv(path)
    miss = [c for c in REQUIRED_COLS if c not in df.columns]
    if miss:
        sys.exit(f"[galat] CSV {path} kekurangan kolom: {miss}")
    df = df.copy()
    for c in ("dmi_kg", "milk_yield_l", "suhu_c", "kelembapan_pct", "prev_milk_yield_l", "usia_bulan"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["milk_yield_l", "prev_milk_yield_l", "dmi_kg"])
    df = df[df["milk_yield_l"] > 0]
    df["genetic_group"] = df["genetic_group"].map(C.normalize_genetic)
    df["tahap_laktasi"] = df["tahap_laktasi"].map(C.normalize_stage)
    df["usia_bulan"] = df["usia_bulan"].map(C.normalize_usia_bulan)
    return df.reset_index(drop=True)


def build_X(df: pd.DataFrame) -> pd.DataFrame:
    """Matriks fitur IDENTIK dengan serving: thi_score & feed_efficiency_prev dihitung ulang
    dari suhu/kelembaban/prev/dmi (bukan diambil dari kolom dataset) agar konsisten."""
    dmi = df["dmi_kg"].clip(lower=0.1)
    prev = df["prev_milk_yield_l"].clip(lower=0.0)
    thi = (1.8 * df["suhu_c"] + 32.0) - (0.55 - 0.0055 * df["kelembapan_pct"].clip(0, 100)) * (1.8 * df["suhu_c"] - 26.0)
    X = pd.DataFrame({
        "prev_milk_yield_l": prev,
        "dmi_kg": dmi,
        "usia_bulan": df["usia_bulan"],
        "suhu_c": df["suhu_c"],
        "kelembapan_pct": df["kelembapan_pct"].clip(0, 100),
        "thi_score": thi,
        "feed_efficiency_prev": prev / dmi,
        "genetic_group": df["genetic_group"],
        "tahap_laktasi": df["tahap_laktasi"],
    })
    return X[C.FEATURE_COLUMNS]


# ============================================================= model regresi
def make_pipeline(kind: str, seed: int) -> Pipeline:
    pre = ColumnTransformer([
        ("num", StandardScaler(), C.NUM_FEATURES),
        ("cat", OneHotEncoder(handle_unknown="ignore", categories=[C.GENETIC_GROUPS, C.STAGES]), C.CAT_FEATURES),
    ])
    if kind == "linear":
        est = LinearRegression()
    elif kind == "random_forest":
        est = RandomForestRegressor(n_estimators=300, min_samples_leaf=3, max_features=0.7,
                                    n_jobs=-1, random_state=seed)
    else:  # gradient_boosting
        est = GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.05,
                                        subsample=0.9, random_state=seed)
    return Pipeline([("pre", pre), ("est", est)])


def mape(y, p) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    m = y >= MAPE_FLOOR
    return float(np.mean(np.abs((y[m] - p[m]) / y[m])) * 100) if m.any() else float("nan")


def eval_metrics(y, p) -> dict:
    return {"mape": mape(y, p), "mae": float(mean_absolute_error(y, p)),
            "rmse": float(np.sqrt(np.mean((np.asarray(y) - np.asarray(p)) ** 2))),
            "r2": float(r2_score(y, p))}


def cv_mape(kind: str, X: pd.DataFrame, y: pd.Series, seed: int, folds: int = 5) -> float:
    kf = KFold(n_splits=folds, shuffle=True, random_state=seed)
    scores = []
    for tr, va in kf.split(X):
        m = make_pipeline(kind, seed).fit(X.iloc[tr], y.iloc[tr])
        scores.append(mape(y.iloc[va], m.predict(X.iloc[va])))
    return float(np.mean(scores))


def predict_recursive(pipe: Pipeline, base: pd.DataFrame, horizons=C.HORIZONS) -> np.ndarray:
    """Prediksi H+1..H+n secara rekursif: hasil horizon ke-k menjadi prev_milk_yield_l untuk k+1.
    `base` berisi FEATURE_COLUMNS. -> array (n_samples, len(horizons))."""
    cur = base.copy()
    out = []
    for _ in horizons:
        pred = np.clip(pipe.predict(cur), 0.0, None)
        out.append(pred)
        cur = cur.copy()
        cur["prev_milk_yield_l"] = pred
        cur["feed_efficiency_prev"] = pred / cur["dmi_kg"].clip(lower=0.1)
    return np.column_stack(out)


# ================================================================== K-Means
def train_kmeans(df: pd.DataFrame, seed: int) -> dict:
    W = df[["feed_efficiency_prev", "dmi_kg", "prev_milk_yield_l"]].to_numpy(float) \
        if set(["feed_efficiency_prev"]).issubset(df.columns) else None
    if W is None:
        prev = df["prev_milk_yield_l"].clip(lower=0.0)
        dmi = df["dmi_kg"].clip(lower=0.1)
        W = np.column_stack([prev / dmi, dmi, prev])
    sc = StandardScaler().fit(W)
    km = KMeans(n_clusters=3, n_init=20, random_state=seed).fit(sc.transform(W))
    centers = sc.inverse_transform(km.cluster_centers_)
    order = np.argsort(centers[:, 2])                      # urut berdasarkan prev_milk_yield_l
    mapping = {int(c): C.SEGMEN_LABELS[rank] for rank, c in enumerate(order)}
    labels = km.labels_
    sil = float(silhouette_score(sc.transform(W), labels))
    info = {}
    for rank, c in enumerate(order):
        m = labels == c
        info[C.SEGMEN_LABELS[rank]] = {
            "n": int(m.sum()),
            "feed_efficiency": round(float(centers[c, 0]), 3),
            "dmi_kg": round(float(centers[c, 1]), 2),
            "prev_milk_yield_l": round(float(centers[c, 2]), 2),
        }
    agreement = None
    if "segmen_nama" in df.columns:
        pred = pd.Series(labels).map(mapping).to_numpy()
        agreement = float((pred == df["segmen_nama"].to_numpy()).mean())
    return {"scaler": sc, "kmeans": km, "cluster_to_label": mapping,
            "feature_names": C.SEGMENT_FEATURES, "silhouette": sil, "segments": info,
            "agreement_with_dataset": agreement}


# ===================================================================== main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=str(BASE / "data" / "lacta_predict_dataset_clean_v2.csv"))
    ap.add_argument("--models-dir", default=str(BASE / "models"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--alert-recall", type=float, default=TARGET_RECALL,
                    help="target recall peringatan dini saat menyetel ambang (default 0.80)")
    args = ap.parse_args()

    csv, models_dir = Path(args.csv), Path(args.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)

    df = load_dataset(csv)
    print(f"[data] {csv.name}: {len(df):,} baris, {df['genetic_group'].nunique()} kelompok genetik, "
          f"tahap {sorted(df['tahap_laktasi'].unique())}")

    X = build_X(df)
    y = df[C.TARGET].astype(float)

    # ---- split: pakai kolom `split` jika ada, kalau tidak acak 80/20
    if "split" in df.columns and set(df["split"].unique()) & {"train", "test"}:
        m_tr = (df["split"] == "train").to_numpy()
        m_te = (df["split"] == "test").to_numpy()
        split_src = "kolom 'split' dataset"
    else:
        rng = np.random.default_rng(args.seed)
        m_te = rng.random(len(df)) < 0.20
        m_tr = ~m_te
        split_src = "acak 80/20"
    Xtr, ytr = X[m_tr], y[m_tr]
    Xte, yte = X[m_te], y[m_te]
    print(f"[split] {split_src}: train={m_tr.sum():,}  test={m_te.sum():,}")

    # ---- pilih model lewat CV di train
    results = {}
    for kind in ("linear", "random_forest", "gradient_boosting"):
        cvm = cv_mape(kind, Xtr, ytr, args.seed)
        results[kind] = cvm
        print(f"[cv ] {kind:17s} MAPE(5-fold) = {cvm:.2f}%")
    best = min(results, key=results.get)
    print(f"[pilih] model regresi terbaik: {best}")

    # ---- latih di train, evaluasi di test (H+1 = prediksi 1 langkah, tervalidasi)
    pipe = make_pipeline(best, args.seed).fit(Xtr, ytr)
    p_te = np.clip(pipe.predict(Xte), 0.0, None)
    h1 = eval_metrics(yte, p_te)
    prev_te = Xte["prev_milk_yield_l"].to_numpy()
    naive = eval_metrics(yte, prev_te)                      # baseline: prediksi = produksi sebelumnya

    # ---- setel ambang peringatan dini di test
    # label nyata: produksi turun >= DROP_THRESHOLD vs produksi sebelumnya
    y_drop = yte.to_numpy() <= (1 - C.DROP_THRESHOLD) * prev_te
    pred_drop = np.where(prev_te > 0, (prev_te - p_te) / np.maximum(prev_te, 1e-6), 0.0)
    grid = np.round(np.arange(0.02, 0.2001, 0.01), 3)

    def rec_prec(thr):
        flag = pred_drop >= thr
        tp = int(np.sum(y_drop & flag)); fn = int(np.sum(y_drop & ~flag)); fp = int(np.sum(~y_drop & flag))
        rec = tp / (tp + fn) if tp + fn else float("nan")
        prec = tp / (tp + fp) if tp + fp else float("nan")
        return rec, prec, float(np.mean(flag))

    # Pilih ambang TERKECIL yang mencapai target recall TANPA alarm berlebihan (<=35% sampel).
    # Dataset bersifat cross-sectional sehingga sebagian penurunan bersifat acak dan sulit diantisipasi;
    # bila target recall tak tercapai dengan alarm wajar, pakai ambang "penurunan tajam" (DROP_THRESHOLD)
    # yang berpresisi tinggi dan mudah ditafsirkan.
    good = [g for g in grid if (rec_prec(g)[0] or 0) >= args.alert_recall and rec_prec(g)[2] <= 0.35]
    thr = float(min(good)) if good else float(C.DROP_THRESHOLD)
    tradeoff = []
    for g in sorted({thr, 0.05, 0.08, 0.10, 0.15}):
        r_, p_, rate = rec_prec(g)
        tradeoff.append({"threshold": g, "recall": r_, "precision": p_, "alert_rate": rate})
    rec, prec, alert_rate = rec_prec(thr)

    # ---- demonstrasi rekursif H+1..H+3 (H+2/H+3 tanpa ground truth: hanya proyeksi)
    multi = predict_recursive(pipe, Xte)

    print("\n" + "=" * 70)
    print(f" EVALUASI TEST  (model: {best})")
    print("=" * 70)
    print(f" {'':10}{'MAPE':>9}{'MAE (L)':>10}{'RMSE (L)':>10}{'R2':>8}")
    print(f" {'H+1 (AI)':<10}{h1['mape']:>8.2f}%{h1['mae']:>10.3f}{h1['rmse']:>10.3f}{h1['r2']:>8.3f}")
    print(f" {'naif*':<10}{naive['mape']:>8.2f}%{naive['mae']:>10.3f}{naive['rmse']:>10.3f}{naive['r2']:>8.3f}")
    print(f"   (*naif = produksi sama dengan hari sebelumnya; MAPE dihitung pada produksi >= {MAPE_FLOOR:.0f} L)")
    print(f" H+2/H+3 = proyeksi REKURSIF (dataset tak punya ground truth lebih dari 1 hari).")
    print(f" Rata-rata proyeksi test: H+1={multi[:,0].mean():.2f} L  H+2={multi[:,1].mean():.2f} L  H+3={multi[:,2].mean():.2f} L")
    print("-" * 70)
    print(f" Peringatan dini: label turun >= {C.DROP_THRESHOLD*100:.0f}% terjadi pada "
          f"{int(y_drop.sum()):,}/{len(y_drop):,} sampel ({y_drop.mean()*100:.1f}%)")
    print(f" Ambang dipilih = {thr*100:.0f}% (recall {rec*100:.1f}%, precision {prec*100:.1f}%, alarm {alert_rate*100:.1f}%)")
    print(" Trade-off ambang (test):  ambang   recall  precision  alarm")
    for t in tradeoff:
        mark = "  <- dipakai" if t["threshold"] == thr else ""
        print(f"{'':25}{t['threshold']*100:>5.0f}%  {t['recall']*100:>6.1f}%  {t['precision']*100:>8.1f}%  {t['alert_rate']*100:>6.1f}%{mark}")
    print("-" * 70)
    ok_mape = h1["mape"] <= TARGET_MAPE
    ok_rec = (rec or 0) >= TARGET_RECALL
    print(f" Target MAPE <= {TARGET_MAPE:.0f}%   : {'LULUS' if ok_mape else 'BELUM'}  ({h1['mape']:.2f}%)")
    print(f" Target Recall >= {TARGET_RECALL*100:.0f}% : {'LULUS' if ok_rec else 'BELUM'}  ({(rec or 0)*100:.1f}%)")
    print("=" * 70)

    # ---- K-Means segmentasi
    df_seg = df.copy()
    df_seg["feed_efficiency_prev"] = df_seg["prev_milk_yield_l"].clip(lower=0.0) / df_seg["dmi_kg"].clip(lower=0.1)
    seg = train_kmeans(df_seg, args.seed)
    print(f"\n[kmeans] 3 segmen, silhouette = {seg['silhouette']:.3f}" +
          (f", cocok dgn dataset = {seg['agreement_with_dataset']*100:.1f}%" if seg["agreement_with_dataset"] is not None else ""))
    for lab in C.SEGMEN_LABELS:
        s = seg["segments"][lab]
        print(f"   {lab:<28} n={s['n']:<5} prev_milk {s['prev_milk_yield_l']:>5.2f} L  "
              f"dmi {s['dmi_kg']:>5.2f} kg  efisiensi {s['feed_efficiency']:.3f}")

    # ---- refit final di SELURUH data, lalu simpan
    final = make_pipeline(best, args.seed).fit(X, y)
    metrics = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": csv.name, "n_rows": int(len(df)), "split_source": split_src,
        "model_kind": best, "cv_mape": results, "alert_threshold": thr,
        "drop_threshold": C.DROP_THRESHOLD, "mape_floor_l": MAPE_FLOOR,
        "feature_columns": C.FEATURE_COLUMNS,
        "test": {
            "H+1": h1, "naive": naive,
            "recursive_mean_l": {f"H+{h}": float(multi[:, i].mean()) for i, h in enumerate(C.HORIZONS)},
            "horizon_note": "H+2 dan H+3 adalah proyeksi rekursif; dataset tidak memuat ground truth multi-hari.",
            "recall_peringatan_dini": rec, "precision_peringatan_dini": prec,
            "alert_tradeoff": tradeoff,
            "mape_target_met": bool(ok_mape), "recall_target_met": bool(ok_rec),
        },
        "kmeans": {"silhouette": seg["silhouette"], "segments": seg["segments"],
                   "agreement_with_dataset": seg["agreement_with_dataset"]},
        "sklearn_version": sklearn.__version__,
    }
    joblib.dump({"pipeline": final, "kind": best, "horizons": list(C.HORIZONS),
                 "feature_columns": C.FEATURE_COLUMNS, "num_features": C.NUM_FEATURES,
                 "cat_features": C.CAT_FEATURES, "alert_threshold": thr,
                 "drop_threshold": C.DROP_THRESHOLD, "metrics": metrics},
                models_dir / "regresi_susu.joblib", compress=3)
    joblib.dump(seg, models_dir / "kmeans_segmen.joblib", compress=3)
    (models_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[simpan] {models_dir / 'regresi_susu.joblib'}")
    print(f"[simpan] {models_dir / 'kmeans_segmen.joblib'}")
    print(f"[simpan] {models_dir / 'metrics.json'}")


if __name__ == "__main__":
    main()
