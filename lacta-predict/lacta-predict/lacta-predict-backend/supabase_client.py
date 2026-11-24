"""Klien minimal Supabase (PostgREST) berbasis `requests`. Memakai SERVICE ROLE key,
jadi HANYA dipakai di backend, jangan pernah dimasukkan ke aplikasi/frontend."""
from __future__ import annotations

import requests


class SupabaseError(RuntimeError):
    pass


class SupabaseREST:
    def __init__(self, url: str, key: str, timeout: float = 15.0):
        if not url or not key:
            raise SupabaseError("SUPABASE_URL / SUPABASE_KEY belum diisi (lihat .env.example)")
        self.base = url.rstrip("/") + "/rest/v1"
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"apikey": key, "Authorization": f"Bearer {key}",
                               "Content-Type": "application/json"})

    def _req(self, method, table, params=None, json=None, prefer=None):
        headers = {"Prefer": prefer} if prefer else {}
        try:
            r = self.s.request(method, f"{self.base}/{table}", params=params, json=json,
                               headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise SupabaseError(f"Gagal menghubungi Supabase: {e}") from e
        if not r.ok:
            raise SupabaseError(f"Supabase {method} {table} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.text else None

    # ---- bacaan
    def get_cattle(self, cattle_id: str):
        rows = self._req("GET", "cattle", {"id": f"eq.{cattle_id}", "select": "*", "limit": "1"})
        return rows[0] if rows else None

    def list_cattle(self, limit: int = 1000):
        return self._req("GET", "cattle", {"select": "*", "order": "created_at.asc", "limit": str(limit)})

    def get_logs(self, cattle_id: str, limit: int = 90):
        """Log terbaru dulu (tanggal desc, lalu created_at desc agar duplikat tanggal -> yang terbaru)."""
        return self._req("GET", "daily_logs", {
            "cattle_id": f"eq.{cattle_id}", "select": "*",
            "order": "tanggal.desc,created_at.desc", "limit": str(limit)})

    # ---- tulisan
    def replace_predictions(self, cattle_id: str, rows: list[dict]):
        """Hapus prediksi lama untuk tanggal yang sama, lalu simpan yang baru."""
        dates = ",".join(r["tanggal_prediksi"] for r in rows)
        self._req("DELETE", "predictions", {"cattle_id": f"eq.{cattle_id}",
                                            "tanggal_prediksi": f"in.({dates})"})
        return self._req("POST", "predictions", json=rows, prefer="return=representation")

    def delete_rows(self, table: str, cattle_id: str | None = None):
        """Hapus baris satu sapi, atau SEMUA baris tabel (cattle_id=None)."""
        col = "id" if table == "cattle" else "cattle_id"
        params = {col: f"eq.{cattle_id}"} if cattle_id else {"id": "not.is.null"}
        self._req("DELETE", table, params, prefer="return=minimal")
