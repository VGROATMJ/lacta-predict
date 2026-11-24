"""Tes API tanpa jaringan: Supabase diganti penyimpan in-memory & token Firebase dibuat dengan RSA lokal.
Jalankan: python -m pytest -q tests

Kontrak data sesuai dataset lacta_predict_dataset_clean_v2.csv:
  cattle    : genetic_group, usia (bulan), tahap_laktasi (Awal|Tengah|Akhir)
  daily_logs: prev_milk_yield_l, dmi_kg, suhu_c, kelembapan_pct
  predictions: tanggal_prediksi, prediksi_volume_susu, segmen_performa, peringatan_dini, alasan_prediksi
"""
import json, sys, threading, time
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import jwt, pytest
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as A
import common as C
from supabase_client import SupabaseREST

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PROJECT = "lacta-predict"


def token(uid="uid-A", verified=True, aud=PROJECT, exp=3600):
    now = int(time.time())
    return jwt.encode({"sub": uid, "aud": aud, "iss": f"https://securetoken.google.com/{PROJECT}", "iat": now,
                       "exp": now + exp, "email": "a@b.co", "email_verified": verified},
                      KEY, algorithm="RS256", headers={"kid": "k1"})


class FakeSB:
    def __init__(self):
        self.cattle, self.logs, self.preds = {}, [], []

    def get_cattle(self, cid): return self.cattle.get(cid)
    def list_cattle(self, limit=1000): return list(self.cattle.values())
    def get_logs(self, cid, limit=90):
        rows = [l for l in self.logs if l["cattle_id"] == cid]
        return sorted(rows, key=lambda r: (r["tanggal"], r["created_at"]), reverse=True)[:limit]
    def replace_predictions(self, cid, rows):
        dates = {r["tanggal_prediksi"] for r in rows}
        self.preds = [p for p in self.preds if not (p["cattle_id"] == cid and p["tanggal_prediksi"] in dates)] + rows
    def delete_rows(self, table, cid=None):
        key = "id" if table == "cattle" else "cattle_id"
        keep = lambda r: cid is not None and r[key] != cid
        if table == "cattle": self.cattle = {k: v for k, v in self.cattle.items() if keep(v)}
        elif table == "daily_logs": self.logs = [r for r in self.logs if keep(r)]
        else: self.preds = [r for r in self.preds if keep(r)]


def add_cow(fs, cid, uid, logs, genetic="HF62.5", usia=52, tahap="Tengah"):
    """logs: list of (prev_milk_yield_l, dmi_kg, suhu_c, kelembapan_pct)."""
    fs.cattle[cid] = {"id": cid, "farmer_id": C.farmer_id_from_uid(uid), "tag_nomor_sapi": cid,
                      "genetic_group": genetic, "usia": usia, "tahap_laktasi": tahap}
    today = date(2026, 11, 23)
    for i, (prev, dmi, suhu, rh) in enumerate(logs):
        fs.logs.append({"cattle_id": cid, "tanggal": today.isoformat(),
                        "prev_milk_yield_l": prev, "dmi_kg": dmi, "suhu_c": suhu, "kelembapan_pct": rh,
                        "created_at": f"2026-11-23T{8 + i:02d}:00:00Z"})


@pytest.fixture()
def env(monkeypatch):
    fs = FakeSB()
    monkeypatch.setattr(A, "_sb", fs)
    monkeypatch.setattr(A, "_firebase_public_key", lambda kid: KEY.public_key())
    monkeypatch.setattr(A.Config, "ADMIN_TOKEN", "rahasia-admin")
    monkeypatch.setattr(A.Config, "REQUIRE_AUTH", True)
    monkeypatch.setattr(A.Config, "ALERT_THRESHOLD", "")
    return fs, A.app.test_client()


H = lambda t: {"Authorization": f"Bearer {t}"}
GOOD = [(8.3, 12.6, 26.0, 70.0)]        # HF tinggi, produksi bagus, iklim nyaman


def test_health(env):
    assert env[1].get("/health").get_json() == {"status": "ok", "models_loaded": True}


def test_model_info(env):
    j = env[1].get("/model-info").get_json()
    assert j["model_kind"] in ("linear", "random_forest", "gradient_boosting")
    assert "H+1" in j["test"]


def test_predict_requires_token(env):
    fs, c = env; add_cow(fs, "c1", "uid-A", GOOD)
    assert c.post("/predict", json={"cattle_id": "c1"}).status_code == 401
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H("sampah")).status_code == 401
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H(token(aud="lain"))).status_code == 401
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H(token(verified=False))).status_code == 403
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H(token(exp=-10))).status_code == 401


def test_predict_ok_and_stored(env):
    fs, c = env; add_cow(fs, "c1", "uid-A", GOOD)
    r = c.post("/predict", json={"cattle_id": "c1"}, headers=H(token()))
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert [p["horizon"] for p in j["prediksi"]] == [1, 2, 3]
    assert all(0 < p["prediksi_volume_susu"] < 15 for p in j["prediksi"])   # skala dataset v2
    assert j["segmen_performa"] in C.SEGMEN_LABELS
    assert j["prediksi"][0]["tanggal_prediksi"] == "2026-11-24"
    assert len(fs.preds) == 3 and {p["tanggal_prediksi"] for p in fs.preds} == {"2026-11-24", "2026-11-25", "2026-11-26"}
    assert set(fs.preds[0]) == {"cattle_id", "tanggal_prediksi", "prediksi_volume_susu", "segmen_performa",
                                "peringatan_dini", "alasan_prediksi"}
    c.post("/predict", json={"cattle_id": "c1"}, headers=H(token()))       # panggil ulang -> diganti
    assert len(fs.preds) == 3


def test_segments_match_profile(env):
    fs, c = env
    add_cow(fs, "hi", "uid-A", [(8.3, 12.6, 26.0, 70.0)], genetic="HF87.5")
    add_cow(fs, "lo", "uid-A", [(1.4, 6.1, 27.0, 72.0)], genetic="Local", tahap="Akhir")
    hi = c.post("/predict", json={"cattle_id": "hi"}, headers=H(token())).get_json()
    lo = c.post("/predict", json={"cattle_id": "lo"}, headers=H(token())).get_json()
    assert hi["segmen_performa"] == "Performa Tinggi"
    assert lo["segmen_performa"] == "Performa Rendah (Prioritas)"
    assert hi["prediksi"][0]["prediksi_volume_susu"] > lo["prediksi"][0]["prediksi_volume_susu"]


def test_other_farmer_forbidden_and_missing(env):
    fs, c = env; add_cow(fs, "c1", "uid-A", GOOD)
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H(token("uid-B"))).status_code == 403
    assert c.post("/predict", json={"cattle_id": "nope"}, headers=H(token())).status_code == 404
    assert c.post("/predict", json={}, headers=H(token())).status_code == 400


def test_single_log_enough(env):
    fs, c = env; add_cow(fs, "c1", "uid-A", [(5.0, 9.8, 27.0, 71.0)])
    j = c.post("/predict", json={"cattle_id": "c1"}, headers=H(token())).get_json()
    assert all(0 < p["prediksi_volume_susu"] < 15 for p in j["prediksi"])


def test_no_logs_422(env):
    fs, c = env; add_cow(fs, "c1", "uid-A", [])
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H(token())).status_code == 422


def test_heat_and_low_feed_triggers_warning(env):
    fs, c = env
    add_cow(fs, "ok", "uid-A", [(8.3, 12.6, 26.0, 70.0)], genetic="HF75")
    add_cow(fs, "bad", "uid-A", [(2.0, 5.5, 34.0, 85.0)], genetic="Local", tahap="Akhir")
    ok = c.post("/predict", json={"cattle_id": "ok"}, headers=H(token())).get_json()
    bad = c.post("/predict", json={"cattle_id": "bad"}, headers=H(token())).get_json()
    assert bad["peringatan_dini"] is True
    assert "heat stress" in bad["alasan_prediksi"]
    assert bad["prediksi"][0]["prediksi_volume_susu"] < ok["prediksi"][0]["prediksi_volume_susu"]


def test_legacy_columns_fallback(env):
    """Backend tetap bisa membaca log skema lama (volume_susu_aktual, jumlah_pakan, suhu_kandang)."""
    fs, c = env
    fs.cattle["c1"] = {"id": "c1", "farmer_id": C.farmer_id_from_uid("uid-A"), "tag_nomor_sapi": "c1",
                       "genetic_group": "HF62.5", "usia": 50, "tahap_laktasi": "Tengah"}
    fs.logs.append({"cattle_id": "c1", "tanggal": "2026-11-23", "volume_susu_aktual": 6.0,
                    "jumlah_pakan": 10.0, "suhu_kandang": 27.0, "created_at": "2026-11-23T08:00:00Z"})
    r = c.post("/predict", json={"cattle_id": "c1"}, headers=H(token()))
    assert r.status_code == 200 and len(r.get_json()["prediksi"]) == 3


def test_threshold_override_and_text_format(env, monkeypatch):
    fs, c = env; add_cow(fs, "c1", "uid-A", GOOD)
    monkeypatch.setattr(A.Config, "ALERT_THRESHOLD", "0.9")
    monkeypatch.setattr(A.Config, "PERINGATAN_FORMAT", "text")
    j = c.post("/predict", json={"cattle_id": "c1"}, headers=H(token())).get_json()
    assert j["peringatan_dini"] is False and fs.preds[0]["peringatan_dini"] == "Normal"


def test_reset_rules(env):
    fs, c = env
    add_cow(fs, "c1", "uid-A", GOOD); add_cow(fs, "c2", "uid-B", GOOD)
    c.post("/predict", json={"cattle_id": "c1"}, headers=H(token()))
    assert c.delete("/logs/reset", json={"cattle_id": "c1"}, headers=H(token("uid-B"))).status_code == 403
    assert c.delete("/logs/reset", json={}, headers=H(token())).status_code == 403
    assert c.delete("/logs/reset", json={}, headers={"X-Admin-Token": "rahasia-admin"}).status_code == 400
    r = c.delete("/logs/reset", json={"cattle_id": "c1"}, headers=H(token()))
    assert r.status_code == 200 and r.get_json()["tabel_dihapus"] == ["predictions", "daily_logs"]
    assert not [l for l in fs.logs if l["cattle_id"] == "c1"] and any(l["cattle_id"] == "c2" for l in fs.logs)
    assert "c1" in fs.cattle
    r = c.delete("/logs/reset", json={"confirm": "RESET", "include_cattle": True}, headers={"X-Admin-Token": "rahasia-admin"})
    assert r.status_code == 200 and not fs.logs and not fs.cattle and not fs.preds


def test_predict_all_admin_only(env):
    fs, c = env
    add_cow(fs, "c1", "uid-A", GOOD); add_cow(fs, "c2", "uid-B", []); add_cow(fs, "c3", "uid-B", GOOD)
    assert c.post("/predict/all", headers=H(token())).status_code == 403
    j = c.post("/predict/all", headers={"X-Admin-Token": "rahasia-admin"}).get_json()
    assert j["diprediksi"] == 2 and j["dilewati"] == 1 and len(fs.preds) == 6


def test_cors_preflight(env):
    r = env[1].options("/predict", headers={"Origin": "https://localhost"})
    assert r.status_code in (200, 204) and r.headers["Access-Control-Allow-Origin"] == "*"
    assert "Authorization" in r.headers["Access-Control-Allow-Headers"]


def test_farmer_id_matches_js_vector():
    # vektor uji yang sama dipakai di verifikasi JS (js/supabase-sync.js)
    assert C.farmer_id_from_uid("abc123XYZ") == "762e5d4b-1f55-5f03-a362-7635a0c61d2b"
    assert C.farmer_id_from_uid("Zk9qLwÅ-ünï_0") == "21d18854-7040-5cfe-abde-33b2aaa05ccf"


def test_thi_formula():
    assert abs(C.thi_from(23.5, 66.1) - 71.24) < 0.1       # cocok dengan nilai dataset


# ---- klien REST: pastikan URL/query/header sesuai PostgREST
class Stub(BaseHTTPRequestHandler):
    log = []
    def _h(self):
        n = int(self.headers.get("Content-Length") or 0)
        Stub.log.append((self.command, self.path, dict(self.headers), self.rfile.read(n).decode()))
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(b"[]")
    do_GET = do_POST = do_DELETE = _h
    def log_message(self, *a): pass


def test_rest_client_requests():
    srv = HTTPServer(("127.0.0.1", 0), Stub); threading.Thread(target=srv.serve_forever, daemon=True).start()
    c = SupabaseREST(f"http://127.0.0.1:{srv.server_port}", "SVC")
    c.get_logs("abc", 30)
    c.replace_predictions("abc", [{"tanggal_prediksi": "2026-11-24"}, {"tanggal_prediksi": "2026-11-25"}])
    c.delete_rows("daily_logs", None); c.delete_rows("cattle", "abc")
    srv.shutdown()
    (m1, p1, h1, _), (m2, p2, *_), (m3, p3, _, b3), (m4, p4, *_), (m5, p5, *_) = Stub.log
    assert (m1, h1["apikey"], h1["Authorization"]) == ("GET", "SVC", "Bearer SVC")
    assert p1.startswith("/rest/v1/daily_logs?") and "cattle_id=eq.abc" in p1 and "order=tanggal.desc%2Ccreated_at.desc" in p1 and "limit=30" in p1
    assert m2 == "DELETE" and "tanggal_prediksi=in.%282026-11-24%2C2026-11-25%29" in p2
    assert m3 == "POST" and p3 == "/rest/v1/predictions" and json.loads(b3)[0]["tanggal_prediksi"] == "2026-11-24"
    assert m4 == "DELETE" and p4 == "/rest/v1/daily_logs?id=not.is.null"
    assert p5 == "/rest/v1/cattle?id=eq.abc"
