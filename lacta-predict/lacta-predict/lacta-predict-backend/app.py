#!/usr/bin/env python3
"""Lacta-Predict - API backend (Flask).

Alur utama  POST /predict {"cattle_id": "<uuid>"}:
  1. ambil data sapi (cattle) + log harian terbaru (daily_logs) dari Supabase
  2. hitung fitur -> prediksi volume susu H+1..H+3 (regresi .joblib) + segmen (K-Means .joblib)
  3. tentukan peringatan dini + alasan, simpan ke tabel `predictions`

Endpoint:
  GET    /health             cek server & model
  GET    /model-info         metrik evaluasi model
  POST   /predict            prediksi 1 sapi              (token Firebase pemilik sapi / admin)
  POST   /predict/all        prediksi semua sapi          (X-Admin-Token)
  DELETE /logs/reset         hapus log uji coba           (pemilik: sapinya sendiri; admin: semua)

Jalankan:  python app.py            (dev)     |   gunicorn -w 2 -b 0.0.0.0:8000 app:app   (produksi)
"""
from __future__ import annotations

import hmac
import os
import time
from datetime import timedelta

import jwt                                  # PyJWT
import joblib
import numpy as np
import pandas as pd
import requests
from cryptography import x509
from dotenv import load_dotenv
from flask import Flask, jsonify, request

import common as C
from supabase_client import SupabaseError, SupabaseREST

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))


# ================================================================== konfigurasi
class Config:
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
    MODELS_DIR = os.getenv("MODELS_DIR", os.path.join(BASE, "models"))
    FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "lacta-predict")
    REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "true").lower() != "false"
    ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
    ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
    PERINGATAN_FORMAT = os.getenv("PERINGATAN_FORMAT", "bool").lower()      # bool | text
    ALERT_THRESHOLD = os.getenv("ALERT_THRESHOLD", "")                      # kosong = dari model


app = Flask(__name__)
_models: dict = {}
_sb: SupabaseREST | None = None


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@app.errorhandler(ApiError)
def _api_error(e):
    return jsonify({"ok": False, "error": e.message}), e.status


@app.errorhandler(SupabaseError)
def _sb_error(e):
    app.logger.error("Supabase: %s", e)
    return jsonify({"ok": False, "error": "Gagal mengakses database Supabase.", "detail": str(e)}), 502


@app.after_request
def _cors(resp):
    origin = request.headers.get("Origin")
    allow = Config.ALLOWED_ORIGINS
    if origin and ("*" in allow or origin in allow):
        resp.headers["Access-Control-Allow-Origin"] = "*" if "*" in allow else origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Admin-Token"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return resp


def sb() -> SupabaseREST:
    global _sb
    if _sb is None:
        _sb = SupabaseREST(Config.SUPABASE_URL, Config.SUPABASE_KEY)
    return _sb


def models() -> dict:
    if not _models:
        try:
            _models["reg"] = joblib.load(os.path.join(Config.MODELS_DIR, "regresi_susu.joblib"))
            _models["seg"] = joblib.load(os.path.join(Config.MODELS_DIR, "kmeans_segmen.joblib"))
        except FileNotFoundError as e:
            raise ApiError(503, "Model belum ada. Jalankan `python train_model.py` terlebih dahulu.") from e
    return _models


# ================================================================== autentikasi
_CERTS = {"keys": {}, "exp": 0.0}
CERT_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"


def _firebase_public_key(kid: str):
    if time.time() > _CERTS["exp"] or kid not in _CERTS["keys"]:
        r = requests.get(CERT_URL, timeout=10)
        r.raise_for_status()
        _CERTS["keys"] = {k: x509.load_pem_x509_certificate(v.encode()).public_key() for k, v in r.json().items()}
        _CERTS["exp"] = time.time() + 3600
    if kid not in _CERTS["keys"]:
        raise ApiError(401, "Token tidak dikenali.")
    return _CERTS["keys"][kid]


def verify_firebase_token(token: str) -> dict:
    """Verifikasi ID token Firebase (RS256, audience & issuer = project, email terverifikasi)."""
    try:
        kid = jwt.get_unverified_header(token).get("kid", "")
        claims = jwt.decode(token, _firebase_public_key(kid), algorithms=["RS256"],
                            audience=Config.FIREBASE_PROJECT_ID,
                            issuer=f"https://securetoken.google.com/{Config.FIREBASE_PROJECT_ID}")
    except ApiError:
        raise
    except Exception as e:                                  # token rusak/kedaluwarsa/dll.
        raise ApiError(401, "Token login tidak valid atau kedaluwarsa.") from e
    if not claims.get("sub"):
        raise ApiError(401, "Token tidak memiliki identitas pengguna.")
    if claims.get("email") and not claims.get("email_verified", False):
        raise ApiError(403, "Email belum terverifikasi.")
    return claims


def is_admin() -> bool:
    tok = request.headers.get("X-Admin-Token", "")
    return bool(Config.ADMIN_TOKEN) and hmac.compare_digest(tok, Config.ADMIN_TOKEN)


def current_farmer_id() -> str | None:
    """farmer_id pemanggil (dari token Firebase). None jika tak ada token & REQUIRE_AUTH=false."""
    h = request.headers.get("Authorization", "")
    if h.lower().startswith("bearer "):
        return C.farmer_id_from_uid(verify_firebase_token(h[7:].strip())["sub"])
    if Config.REQUIRE_AUTH:
        raise ApiError(401, "Butuh login (header Authorization: Bearer <Firebase ID token>).")
    return None


def authorize_cattle(cattle_id: str) -> dict:
    """Ambil sapi + pastikan pemanggil berhak (pemilik atau admin)."""
    admin = is_admin()
    farmer = None if admin else current_farmer_id()
    cow = sb().get_cattle(cattle_id)
    if not cow:
        raise ApiError(404, "Sapi tidak ditemukan.")
    if not admin and farmer is not None and str(cow.get("farmer_id")) != farmer:
        raise ApiError(403, "Sapi ini bukan milik akun Anda.")
    return cow


# ================================================================= inti prediksi
def _logs_to_frame(logs: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(logs)
    if df.empty:
        return df
    df["tanggal"] = pd.to_datetime(df["tanggal"]).dt.normalize()
    for c in ("jumlah_pakan", "suhu_kandang", "volume_susu_aktual"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.drop_duplicates("tanggal", keep="first")          # sudah urut desc -> ambil entri terbaru
    df = df.dropna(subset=["volume_susu_aktual"])
    return df.sort_values("tanggal").reset_index(drop=True)


def make_features(cow: dict, df: pd.DataFrame):
    """Satu baris fitur dari log terbaru sapi. -> (X, tanggal_terakhir, df)."""
    last = df["tanggal"].iloc[-1]
    idx = df.set_index("tanggal")
    days = [last - timedelta(days=k) for k in range(C.N_LAGS)]

    def lag(col):
        return np.array([[idx[col].get(d, np.nan) for d in days]], dtype=float)

    Y, F, S = lag("volume_susu_aktual"), lag("jumlah_pakan"), lag("suhu_kandang")
    # nilai hari terakhir tak boleh kosong -> pakai nilai terbaru yang ada, kalau tak ada pakai default
    for arr, col, default in ((F, "jumlah_pakan", 10.0), (S, "suhu_kandang", 28.0)):
        if np.isnan(arr[0, 0]):
            known = idx[col].dropna()
            arr[0, 0] = known.iloc[-1] if len(known) else default
    feed_idx = C.normalize_feed_type(idx["jenis_pakan"].iloc[-1] if "jenis_pakan" in idx else None)
    X = C.build_features(Y, F, S, [C.normalize_usia_bulan(cow.get("usia"))],
                         [C.normalize_stage(cow.get("tahap_laktasi"))], [feed_idx])
    return X, last


def predict_cattle(cow: dict, logs: list[dict]) -> dict:
    """Hitung prediksi lengkap untuk satu sapi (tanpa menulis ke database)."""
    m = models()
    df = _logs_to_frame(logs)
    if df.empty:
        raise ApiError(422, "Belum ada log harian dengan volume susu untuk sapi ini.")
    X, last = make_features(cow, df)
    reg = m["reg"]
    ma3 = float(X["ma3"].iloc[0])
    vols = [max(0.0, float(reg["models"][h].predict(X)[0]) * ma3) for h in C.HORIZONS]
    drops = [1 - v / ma3 for v in vols]
    thr = float(Config.ALERT_THRESHOLD) if Config.ALERT_THRESHOLD else float(reg["alert_threshold"])
    flags = [d >= thr for d in drops]
    warn = any(flags)

    seg_m = m["seg"]
    tail = df.tail(C.SEGMENT_WINDOW)
    sf = np.array([C.segment_features(tail["volume_susu_aktual"], tail["jumlah_pakan"])])
    cluster = int(seg_m["kmeans"].predict(seg_m["scaler"].transform(sf))[0])
    segmen = seg_m["cluster_to_label"][cluster]

    reason = C.build_reason(X.iloc[0].to_dict(), drops, warn, thr)
    return {
        "data_terakhir": last.date().isoformat(),
        "segmen_performa": segmen,
        "peringatan_dini": warn,
        "alasan_prediksi": reason,
        "ambang_peringatan": thr,
        "prediksi": [{"horizon": h, "tanggal_prediksi": (last + timedelta(days=h)).date().isoformat(),
                      "prediksi_volume_susu": round(v, 2), "turun_pct": round(100 * d, 1),
                      "peringatan_dini": f}
                     for h, v, d, f in zip(C.HORIZONS, vols, drops, flags)],
    }


def _peringatan_value(flag: bool):
    if Config.PERINGATAN_FORMAT == "text":
        return "Waspada: prediksi produksi turun tajam" if flag else "Normal"
    return bool(flag)


def run_and_store(cow: dict) -> dict:
    logs = sb().get_logs(cow["id"], limit=90)
    res = predict_cattle(cow, logs)
    rows = [{"cattle_id": cow["id"], "tanggal_prediksi": p["tanggal_prediksi"],
             "prediksi_volume_susu": p["prediksi_volume_susu"], "segmen_performa": res["segmen_performa"],
             "peringatan_dini": _peringatan_value(p["peringatan_dini"]),
             "alasan_prediksi": res["alasan_prediksi"]} for p in res["prediksi"]]
    sb().replace_predictions(cow["id"], rows)
    return {"cattle_id": cow["id"], **res}


# ===================================================================== endpoint
@app.get("/health")
def health():
    ok = all(os.path.exists(os.path.join(Config.MODELS_DIR, f)) for f in ("regresi_susu.joblib", "kmeans_segmen.joblib"))
    return jsonify({"status": "ok", "models_loaded": ok})


@app.get("/model-info")
def model_info():
    return jsonify(models()["reg"]["metrics"])


@app.post("/predict")
def predict_one():
    body = request.get_json(silent=True) or {}
    cattle_id = str(body.get("cattle_id", "")).strip()
    if not cattle_id:
        raise ApiError(400, "Field 'cattle_id' wajib diisi.")
    cow = authorize_cattle(cattle_id)
    return jsonify({"ok": True, **run_and_store(cow)})


@app.post("/predict/all")
def predict_all():
    if not is_admin():
        raise ApiError(403, "Butuh header X-Admin-Token yang benar.")
    done, skipped = [], []
    for cow in sb().list_cattle():
        try:
            r = run_and_store(cow)
            done.append({"cattle_id": cow["id"], "tag": cow.get("tag_nomor_sapi"),
                         "peringatan_dini": r["peringatan_dini"], "segmen": r["segmen_performa"]})
        except ApiError as e:
            skipped.append({"cattle_id": cow["id"], "alasan": e.message})
    return jsonify({"ok": True, "diprediksi": len(done), "dilewati": len(skipped), "hasil": done, "skip": skipped})


@app.delete("/logs/reset")
def reset_logs():
    """Hapus log uji coba.
    Body JSON (opsional): {"cattle_id": "...", "include_predictions": true, "include_cattle": false,
                           "confirm": "RESET"}
      - dengan cattle_id : pemilik sapi (token Firebase) atau admin
      - tanpa cattle_id  : SEMUA data -> wajib X-Admin-Token + "confirm": "RESET"
    """
    body = request.get_json(silent=True) or {}
    cattle_id = str(body.get("cattle_id", "")).strip() or None
    inc_pred = body.get("include_predictions", True) is not False
    inc_cattle = body.get("include_cattle", False) is True

    if cattle_id:
        authorize_cattle(cattle_id)
    else:
        if not is_admin():
            raise ApiError(403, "Reset semua data butuh header X-Admin-Token yang benar.")
        if body.get("confirm") != "RESET":
            raise ApiError(400, 'Reset semua data butuh {"confirm": "RESET"} pada body.')

    deleted = []
    if inc_pred or inc_cattle:                              # urutan penghapusan menghormati foreign key
        sb().delete_rows("predictions", cattle_id); deleted.append("predictions")
    sb().delete_rows("daily_logs", cattle_id); deleted.append("daily_logs")
    if inc_cattle:
        sb().delete_rows("cattle", cattle_id); deleted.append("cattle")
    return jsonify({"ok": True, "cattle_id": cattle_id or "SEMUA", "tabel_dihapus": deleted})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=False)
