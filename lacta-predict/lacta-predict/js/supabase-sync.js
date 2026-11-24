// Penyambung minimal: simpan input harian ke Supabase -> panggil backend AI -> tampilkan
// hasil dari tabel `predictions`. Tidak mengubah tampilan/alur login. Jika gagal (offline,
// server mati, RLS menolak) aplikasi tetap memakai prediksi lokal seperti sebelumnya.
// Bergantung pada: app.js (App, cows, saveCows, fmt1), firebase auth (token untuk backend).
(function () {
  'use strict';
  var cfg = window.LACTA_SUPABASE || {};
  var profileDone = {};   // uid -> true (profil sudah dipastikan ada pada sesi ini)

  function enabled() {
    return !!(cfg.url && cfg.anonKey && cfg.apiBase) &&
      !/YOUR_/.test(cfg.url + cfg.anonKey + cfg.apiBase) &&
      !!(window.crypto && crypto.subtle) && !!window.fetch;
  }
  function $(id) { return document.getElementById(id); }

  // ---------- UUID v5 (sama persis dengan uuid.uuid5 di backend) ----------
  async function uuid5(ns, name) {
    var nsHex = ns.replace(/-/g, ''), nsBytes = new Uint8Array(16);
    for (var i = 0; i < 16; i++) nsBytes[i] = parseInt(nsHex.substr(i * 2, 2), 16);
    var nameBytes = new TextEncoder().encode(name);
    var data = new Uint8Array(16 + nameBytes.length);
    data.set(nsBytes, 0); data.set(nameBytes, 16);
    var h = new Uint8Array(await crypto.subtle.digest('SHA-1', data)).slice(0, 16);
    h[6] = (h[6] & 0x0f) | 0x50; h[8] = (h[8] & 0x3f) | 0x80;
    var hex = Array.prototype.map.call(h, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
    return hex.slice(0, 8) + '-' + hex.slice(8, 12) + '-' + hex.slice(12, 16) + '-' + hex.slice(16, 20) + '-' + hex.slice(20);
  }

  // ---------- Supabase REST (PostgREST) ----------
  async function sbFetch(path, method, body, prefer) {
    var headers = { apikey: cfg.anonKey, Authorization: 'Bearer ' + cfg.anonKey, 'Content-Type': 'application/json' };
    if (prefer) headers.Prefer = prefer;
    var r = await fetch(cfg.url.replace(/\/$/, '') + '/rest/v1/' + path, {
      method: method, headers: headers, body: body ? JSON.stringify(body) : undefined
    });
    var txt = await r.text();
    if (!r.ok) throw new Error('Supabase ' + method + ' ' + path.split('?')[0] + ' ' + r.status + ': ' + txt.slice(0, 200));
    return txt ? JSON.parse(txt) : null;
  }

  function todayLocal() {
    var d = new Date(), p = function (n) { return ('0' + n).slice(-2); };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
  }

  async function ensureProfile(user) {
    if (profileDone[user.uid]) return;
    var farmerId = await uuid5(cfg.farmerNamespace, user.uid);
    // ignore-duplicates: tidak menimpa profil yang sudah ada
    await sbFetch('profiles?on_conflict=id', 'POST',
      { id: farmerId, full_name: user.displayName || (user.email || '').split('@')[0] || 'Peternak', role: 'peternak' },
      'resolution=ignore-duplicates,return=minimal');
    profileDone[user.uid] = farmerId;
  }

  async function ensureCattle(cow, user) {
    if (cow.sbId) return cow.sbId;
    var rows = await sbFetch('cattle', 'POST', {
      farmer_id: profileDone[user.uid],
      tag_nomor_sapi: cow.nama,
      usia: cow.usia || cfg.defaultUsiaBulan,
      tahap_laktasi: cow.tahap_laktasi || cfg.defaultTahapLaktasi
    }, 'return=representation');
    cow.sbId = rows[0].id;
    saveCows();
    return cow.sbId;
  }

  async function callBackend(cattleId) {
    var fb = window.firebase && firebase.apps.length && firebase.auth().currentUser;
    var headers = { 'Content-Type': 'application/json' };
    if (fb) headers.Authorization = 'Bearer ' + await fb.getIdToken();
    var ctl = new AbortController(), t = setTimeout(function () { ctl.abort(); }, 45000); // server gratisan bisa lambat bangun
    try {
      var r = await fetch(cfg.apiBase.replace(/\/$/, '') + '/predict', {
        method: 'POST', headers: headers, body: JSON.stringify({ cattle_id: cattleId }), signal: ctl.signal
      });
      var j = await r.json().catch(function () { return {}; });
      if (!r.ok) throw new Error('Backend ' + r.status + ': ' + (j.error || ''));
      return j;
    } finally { clearTimeout(t); }
  }

  function isWarn(v) {
    return v === true || v === 'true' || (typeof v === 'string' && !/^(normal|false|tidak|aman|-)/i.test(v.trim()));
  }

  async function readPredictions(cattleId) {
    var rows = await sbFetch('predictions?cattle_id=eq.' + encodeURIComponent(cattleId) +
      '&select=tanggal_prediksi,prediksi_volume_susu,segmen_performa,peringatan_dini,alasan_prediksi' +
      '&order=created_at.desc,tanggal_prediksi.asc&limit=3', 'GET');
    if (!rows || !rows.length) return null;
    rows.sort(function (a, b) { return a.tanggal_prediksi < b.tanggal_prediksi ? -1 : 1; });
    return {
      preds: rows.map(function (r) { return { tanggal: r.tanggal_prediksi, vol: Number(r.prediksi_volume_susu), warn: isWarn(r.peringatan_dini) }; }),
      segmen: rows[0].segmen_performa,
      warn: rows.some(function (r) { return isWarn(r.peringatan_dini); }),
      alasan: rows[0].alasan_prediksi || '',
      savedAt: Date.now()
    };
  }

  // ---------- Tampilkan hasil model pada elemen yang SUDAH ADA (tanpa ubah desain) ----------
  function overlay(cow) {
    var m = cow && cow.model;
    if (!m || !m.preds || !m.preds.length || !isFinite(m.preds[0].vol)) return;
    var p1 = m.preds[0].vol;
    var drop = cow.prev > 0 ? (cow.prev - p1) / cow.prev * 100 : 0;
    $('predBesok').textContent = fmt1(p1) + ' L';
    $('predDelta').textContent = (drop >= 0 ? '-' : '+') + Math.abs(drop).toFixed(1) + '% dari kemarin';
    $('alertBox').className = 'alert-box' + (m.warn ? '' : ' ok');
    $('alertIcon').textContent = m.warn ? '⚠️' : '✅';
    $('alertTitle').textContent = m.warn ? 'Peringatan dini: produksi diperkirakan turun' : 'Produksi stabil';
    $('alertSub').textContent = cow.nama + ' · ' + m.segmen + ' — ' + (m.alasan || (m.warn ? 'cek kondisi pakan & suhu kandang.' : 'tidak ada tindakan khusus.'));
    $('detailBesok').textContent = fmt1(p1) + ' L';
    var badge = $('detailBadge');
    badge.textContent = (drop >= 0 ? 'Turun ' : 'Naik ') + Math.abs(drop).toFixed(1) + '%';
    badge.style.background = m.warn ? 'rgba(255,120,120,.28)' : 'rgba(255,255,255,.18)';
    $('segVal').textContent = m.segmen;
    // grafik: kemarin (aktual) + prediksi H+1..H+3 dari tabel predictions
    var v = [cow.prev].concat(m.preds.map(function (p) { return p.vol; }));
    var min = Math.min.apply(null, v), max = Math.max.apply(null, v), span = (max - min) || 1;
    var pts = v.map(function (val, i) { return [4 + i * (292 / (v.length - 1)), max === min ? 35 : 60 - ((val - min) / span) * 50]; });
    var str = function (a) { return a.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' '); };
    $('trendSolid').setAttribute('points', str(pts.slice(0, 2)));
    $('trendDash').setAttribute('points', str(pts.slice(1)));
  }

  // ---------- Dipanggil setelah tombol "Simpan & Lihat Prediksi" ----------
  async function syncAfterSave(cow) {
    if (!enabled() || !App.user || !cow) return;
    var api = window.LactaSync;
    try {
      api.status = 'menyimpan';
      await ensureProfile(App.user);
      var cattleId = await ensureCattle(cow, App.user);
      await sbFetch('daily_logs', 'POST', {
        cattle_id: cattleId, tanggal: todayLocal(), jumlah_pakan: cow.pakan,
        jenis_pakan: cfg.defaultJenisPakan || 'campuran', suhu_kandang: cow.suhu,
        volume_susu_aktual: cow.prev            // "produksi terakhir tercatat" dari form
      }, 'return=minimal');
      api.status = 'memprediksi';
      await callBackend(cattleId);
      var model = await readPredictions(cattleId);
      if (model) {
        cow.model = model; saveCows();
        var sel = $('cowSelect');
        if (sel && sel.value === cow.id) overlay(cow);   // hanya jika sapi ini sedang ditampilkan
      }
      api.status = 'selesai'; api.lastError = null;
    } catch (e) {
      console.warn('[LactaSync] sinkronisasi gagal, memakai prediksi lokal:', e);
      api.status = 'gagal'; api.lastError = String((e && e.message) || e);
    }
  }

  window.LactaSync = { enabled: enabled, syncAfterSave: syncAfterSave, overlay: overlay, uuid5: uuid5, status: 'idle', lastError: null };
})();
