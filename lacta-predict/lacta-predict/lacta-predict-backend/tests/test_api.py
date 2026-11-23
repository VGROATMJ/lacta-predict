"""Tes API tanpa jaringan: Supabase diganti penyimpan in-memory & token Firebase dibuat dengan RSA lokal.
Jalankan: python -m pytest -q tests"""
import json, sys, threading, time
from datetime import date, timedelta
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


def add_cow(fs, cid, uid, logs):
    fs.cattle[cid] = {"id": cid, "farmer_id": C.farmer_id_from_uid(uid), "tag_nomor_sapi": cid,
                      "usia": 48, "tahap_laktasi": "puncak"}
    today = date(2026, 11, 23)
    for i, (vol, pakan, suhu) in enumerate(logs):
        d = today - timedelta(days=len(logs) - 1 - i)
        fs.logs.append({"cattle_id": cid, "tanggal": d.isoformat(), "jumlah_pakan": pakan, "jenis_pakan": "campuran",
                        "suhu_kandang": suhu, "volume_susu_aktual": vol, "created_at": f"{d}T08:00:00Z"})


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
STABLE = [(20.0, 11.0, 27.0)] * 7


def test_health(env):
    assert env[1].get("/health").get_json() == {"status": "ok", "models_loaded": True}


def test_predict_requires_token(env):
    fs, c = env; add_cow(fs, "c1", "uid-A", STABLE)
    assert c.post("/predict", json={"cattle_id": "c1"}).status_code == 401
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H("sampah")).status_code == 401
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H(token(aud="lain"))).status_code == 401
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H(token(verified=False))).status_code == 403
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H(token(exp=-10))).status_code == 401


def test_predict_ok_and_stored(env):
    fs, c = env; add_cow(fs, "c1", "uid-A", STABLE)
    r = c.post("/predict", json={"cattle_id": "c1"}, headers=H(token()))
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert [p["horizon"] for p in j["prediksi"]] == [1, 2, 3]
    assert all(15 < p["prediksi_volume_susu"] < 25 for p in j["prediksi"])
    assert j["segmen_performa"] in C.SEGMEN_LABELS
    assert len(fs.preds) == 3 and {p["tanggal_prediksi"] for p in fs.preds} == {"2026-11-24", "2026-11-25", "2026-11-26"}
    assert set(fs.preds[0]) == {"cattle_id", "tanggal_prediksi", "prediksi_volume_susu", "segmen_performa",
                                "peringatan_dini", "alasan_prediksi"}
    # panggil ulang -> diganti, bukan menumpuk
    c.post("/predict", json={"cattle_id": "c1"}, headers=H(token()))
    assert len(fs.preds) == 3


def test_other_farmer_forbidden_and_missing(env):
    fs, c = env; add_cow(fs, "c1", "uid-A", STABLE)
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H(token("uid-B"))).status_code == 403
    assert c.post("/predict", json={"cattle_id": "nope"}, headers=H(token())).status_code == 404
    assert c.post("/predict", json={}, headers=H(token())).status_code == 400


def test_cold_start_single_log(env):
    fs, c = env; add_cow(fs, "c1", "uid-A", [(28.8, 11.5, 31.2)])
    j = c.post("/predict", json={"cattle_id": "c1"}, headers=H(token())).get_json()
    assert all(10 < p["prediksi_volume_susu"] < 35 for p in j["prediksi"])
    assert "riwayat baru 1 hari" in j["alasan_prediksi"]


def test_no_logs_422(env):
    fs, c = env; add_cow(fs, "c1", "uid-A", [])
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H(token())).status_code == 422


def test_heat_and_feed_drop_triggers_warning_and_lower_volume(env):
    fs, c = env
    add_cow(fs, "ok", "uid-A", STABLE)
    add_cow(fs, "bad", "uid-A", [(24, 11, 27), (24, 11, 27), (24, 11, 28), (23.5, 10.5, 31), (23, 9, 34), (22, 8, 35), (21, 7, 36)])
    ok = c.post("/predict", json={"cattle_id": "ok"}, headers=H(token())).get_json()
    bad = c.post("/predict", json={"cattle_id": "bad"}, headers=H(token())).get_json()
    assert bad["peringatan_dini"] is True and "heat stress" in bad["alasan_prediksi"]
    assert bad["prediksi"][0]["turun_pct"] > ok["prediksi"][0]["turun_pct"] + 3
    print("stabil:", ok["prediksi"][0], "| panas+pakan turun:", bad["prediksi"][0])


def test_gap_and_duplicate_dates(env):
    fs, c = env; add_cow(fs, "c1", "uid-A", STABLE)
    fs.logs += [dict(fs.logs[-1], volume_susu_aktual=21.0, created_at="2026-11-23T20:00:00Z")]   # duplikat tanggal
    del fs.logs[2:4]                                                                              # hari bolong
    assert c.post("/predict", json={"cattle_id": "c1"}, headers=H(token())).status_code == 200


def test_threshold_override_and_text_format(env, monkeypatch):
    fs, c = env; add_cow(fs, "c1", "uid-A", STABLE)
    monkeypatch.setattr(A.Config, "ALERT_THRESHOLD", "0.5")
    monkeypatch.setattr(A.Config, "PERINGATAN_FORMAT", "text")
    j = c.post("/predict", json={"cattle_id": "c1"}, headers=H(token())).get_json()
    assert j["peringatan_dini"] is False and fs.preds[0]["peringatan_dini"] == "Normal"


def test_reset_rules(env):
    fs, c = env
    add_cow(fs, "c1", "uid-A", STABLE); add_cow(fs, "c2", "uid-B", STABLE)
    c.post("/predict", json={"cattle_id": "c1"}, headers=H(token()))
    # pemilik lain ditolak; tanpa cattle_id wajib admin + confirm
    assert c.delete("/logs/reset", json={"cattle_id": "c1"}, headers=H(token("uid-B"))).status_code == 403
    assert c.delete("/logs/reset", json={}, headers=H(token())).status_code == 403
    assert c.delete("/logs/reset", json={}, headers={"X-Admin-Token": "rahasia-admin"}).status_code == 400
    # pemilik menghapus log & prediksi sapinya sendiri
    r = c.delete("/logs/reset", json={"cattle_id": "c1"}, headers=H(token()))
    assert r.status_code == 200 and r.get_json()["tabel_dihapus"] == ["predictions", "daily_logs"]
    assert not [l for l in fs.logs if l["cattle_id"] == "c1"] and any(l["cattle_id"] == "c2" for l in fs.logs)
    assert "c1" in fs.cattle                                         # sapi tetap ada
    # admin: hapus semua termasuk sapi
    r = c.delete("/logs/reset", json={"confirm": "RESET", "include_cattle": True}, headers={"X-Admin-Token": "rahasia-admin"})
    assert r.status_code == 200 and not fs.logs and not fs.cattle and not fs.preds


def test_predict_all_admin_only(env):
    fs, c = env
    add_cow(fs, "c1", "uid-A", STABLE); add_cow(fs, "c2", "uid-B", []); add_cow(fs, "c3", "uid-B", STABLE)
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
