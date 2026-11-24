// Mode AI Langsung: simpan input harian ke Supabase -> panggil POST /predict
// ke backend AI -> tampilkan hasil H+1..H+3 & segmen dari tabel `predictions`.
// TIDAK ADA prediksi/rumus lokal: bila AI belum siap/gagal, UI menampilkan status jelas.
(function () {
  'use strict';
  var cfg = window.LACTA_SUPABASE || {};
  var profileDone = {};
  var inflight = {};

  // Nilai placeholder yang berarti "belum dikonfigurasi".
  function isPlaceholder(s) {
    s = String(s || '');
    return !s || /YOUR_|PROJECT\.supabase|KUNCI_ANON|MASUKKAN_/i.test(s);
  }
  function enabled() {
    return !!(cfg.url && cfg.anonKey && cfg.apiBase) &&
      !isPlaceholder(cfg.url) && !isPlaceholder(cfg.anonKey) && !isPlaceholder(cfg.apiBase) &&
      !!(window.crypto && crypto.subtle) && !!window.fetch;
  }
  function $(id) { return document.getElementById(id); }

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

  async function sbFetch(path, method, body, prefer) {
    var headers = { apikey: cfg.anonKey, Authorization: 'Bearer ' + cfg.anonKey, 'Content-Type': 'application/json' };
    if (prefer) headers.Prefer = prefer;
    var ctl = new AbortController(), t = setTimeout(function () { ctl.abort(); }, 20000);
    try {
      var r = await fetch(cfg.url.replace(/\/$/, '') + '/rest/v1/' + path, {
        method: method, headers: headers, body: body ? JSON.stringify(body) : undefined, signal: ctl.signal
      });
      var txt = await r.text();
      if (!r.ok) throw new Error('Supabase ' + method + ' ' + path.split('?')[0] + ' ' + r.status + ': ' + txt.slice(0, 200));
      return txt ? JSON.parse(txt) : null;
    } catch (e) {
      if (e.name === 'AbortError') throw new Error('Supabase tidak merespons (timeout). Cek koneksi & url Supabase.');
      throw e;
    } finally { clearTimeout(t); }
  }

  function todayLocal() {
    var d = new Date(), p = function (n) { return ('0' + n).slice(-2); };
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
  }

  async function ensureProfile(user) {
    if (profileDone[user.uid]) return profileDone[user.uid];
    var farmerId = await uuid5(cfg.farmerNamespace, user.uid);
    await sbFetch('profiles?on_conflict=id', 'POST',
      { id: farmerId, full_name: user.displayName || (user.email || '').split('@')[0] || 'Peternak', role: 'peternak' },
      'resolution=ignore-duplicates,return=minimal');
    profileDone[user.uid] = farmerId;
    return farmerId;
  }

  async function ensureCattle(cow, user) {
    var farmerId = await ensureProfile(user);
    if (!cow.sbId) {
      var rows = await sbFetch('cattle', 'POST', {
        farmer_id: farmerId,
        tag_nomor_sapi: cow.nama,
        genetic_group: cow.genetic_group || cfg.defaultGeneticGroup || 'HF50',
        usia: cow.usia || cfg.defaultUsiaBulan || 48,
        tahap_laktasi: cow.tahap || cfg.defaultTahapLaktasi || 'Tengah'
      }, 'return=representation');
      cow.sbId = rows[0].id;
      saveCows();
    }
    return cow.sbId;
  }

  async function pushLog(cattleId, cow) {
    await sbFetch('daily_logs', 'POST', {
      cattle_id: cattleId,
      tanggal: todayLocal(),
      prev_milk_yield_l: cow.prev,
      dmi_kg: cow.dmi,
      suhu_c: cow.suhu,
      kelembapan_pct: cow.rh
    }, 'return=minimal');
  }

  async function callBackend(cattleId) {
    var fb = window.firebase && firebase.apps.length && firebase.auth().currentUser;
    var headers = { 'Content-Type': 'application/json' };
    if (fb) headers.Authorization = 'Bearer ' + await fb.getIdToken();
    var ctl = new AbortController(), t = setTimeout(function () { ctl.abort(); }, 45000);
    try {
      var r = await fetch(cfg.apiBase.replace(/\/$/, '') + '/predict', {
        method: 'POST', headers: headers, body: JSON.stringify({ cattle_id: cattleId }), signal: ctl.signal
      });
      var j = await r.json().catch(function () { return {}; });
      if (!r.ok) throw new Error('Backend ' + r.status + ': ' + (j.error || ''));
      return j;
    } catch (e) {
      if (e.name === 'AbortError') throw new Error('Server AI tidak merespons (timeout 45 dtk). Cek apiBase / Cloudflare Tunnel.');
      throw e;
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

  function setWaitingState(cow, msg, detail) {
    $('predBesok').textContent = '…';
    $('predDelta').textContent = detail ? '—' : (msg || 'Menunggu model AI…');
    $('alertBox').className = 'alert-box' + (detail ? '' : ' ok');
    $('alertIcon').textContent = detail ? '⚠️' : '⏳';
    $('alertTitle').textContent = msg || 'Menghitung prediksi AI';
    $('alertSub').textContent = detail || (cow ? (cow.nama + ' — menghubungkan ke server model AI…') : 'Menghubungkan ke server model AI…');
    $('detailBesok').textContent = '…';
    var badge = $('detailBadge');
    badge.textContent = detail ? 'Gagal' : 'AI';
    badge.style.background = detail ? 'rgba(255,120,120,.28)' : 'rgba(255,255,255,.18)';
    $('segVal').textContent = detail ? 'Belum terhubung' : 'Memproses AI…';
    $('trendSolid').setAttribute('points', '');
    $('trendDash').setAttribute('points', '');
  }

  function animateNumber(el, to, suffix) {
    var from = 0, start = null, dur = 600;
    function step(ts) {
      if (start === null) start = ts;
      var k = Math.min(1, (ts - start) / dur);
      var val = from + (to - from) * (1 - Math.pow(1 - k, 3));
      el.textContent = val.toFixed(1).replace('.', ',') + (suffix || '');
      if (k < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function overlay(cow) {
    var m = cow && cow.model;
    if (!m || !m.preds || !m.preds.length || !isFinite(m.preds[0].vol)) {
      setWaitingState(cow, 'Menunggu hasil AI');
      return false;
    }
    var p1 = m.preds[0].vol;
    var drop = cow.prev > 0 ? (cow.prev - p1) / cow.prev * 100 : 0;
    animateNumber($('predBesok'), p1, ' L');
    $('predDelta').textContent = (drop >= 0 ? '↓ ' : '↑ ') + Math.abs(drop).toFixed(1) + '% dari kemarin';
    $('alertBox').className = 'alert-box pop' + (m.warn ? '' : ' ok');
    setTimeout(function(){ $('alertBox').classList.remove('pop'); }, 420);
    $('alertIcon').textContent = m.warn ? '⚠️' : '✅';
    $('alertTitle').textContent = m.warn ? 'Peringatan dini: produksi diperkirakan turun' : 'Produksi stabil';
    $('alertSub').textContent = cow.nama + ' · ' + m.segmen + ' — ' + (m.alasan || (m.warn ? 'cek kondisi pakan & iklim kandang.' : 'tidak ada tindakan khusus.'));
    animateNumber($('detailBesok'), p1, ' L');
    var badge = $('detailBadge');
    badge.textContent = (drop >= 0 ? 'Turun ' : 'Naik ') + Math.abs(drop).toFixed(1) + '%';
    badge.style.background = m.warn ? 'rgba(255,120,120,.28)' : 'rgba(255,255,255,.18)';
    $('segVal').textContent = m.segmen;

    var v = [cow.prev].concat(m.preds.map(function (p) { return p.vol; }));
    var min = Math.min.apply(null, v), max = Math.max.apply(null, v), span = (max - min) || 1;
    var pts = v.map(function (val, i) {
      return [4 + i * (292 / (v.length - 1)), max === min ? 35 : 60 - ((val - min) / span) * 50];
    });
    var str = function (a) { return a.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' '); };
    var solid = $('trendSolid'), dash = $('trendDash');
    solid.setAttribute('points', str(pts.slice(0, 2)));
    dash.setAttribute('points', str(pts.slice(1)));
    animateTrend(solid); animateTrend(dash);
    return true;
  }

  // Animasi garis tren menggambar dari awal (stroke-dash trick).
  function animateTrend(poly) {
    try {
      var len = poly.getTotalLength ? poly.getTotalLength() : 300;
      poly.style.transition = 'none';
      poly.style.strokeDasharray = len + ' ' + len;
      poly.style.strokeDashoffset = len;
      void poly.getBoundingClientRect();
      poly.style.transition = 'stroke-dashoffset .7s ease';
      poly.style.strokeDashoffset = '0';
    } catch (e) {}
  }

  async function runModelForCow(cow, pushInitialLog) {
    if (!cow) return null;
    if (!enabled()) {
      setWaitingState(cow, 'Server AI belum dikonfigurasi', 'Isi url, anonKey, dan apiBase di js/supabase-config.js');
      return null;
    }
    if (!App.user) {
      setWaitingState(cow, 'Login diperlukan untuk AI', 'Silakan masuk menggunakan akun terverifikasi');
      return null;
    }
    if (inflight[cow.id]) return inflight[cow.id];

    var api = window.LactaSync;
    inflight[cow.id] = (async function () {
      try {
        api.status = 'memprediksi';
        if (!cow.model) setWaitingState(cow, 'Memanggil model AI…');
        var cattleId = await ensureCattle(cow, App.user);
        if (pushInitialLog) await pushLog(cattleId, cow);     // pastikan ada snapshot input terbaru
        await callBackend(cattleId);
        var model = await readPredictions(cattleId);
        if (!model) throw new Error('Data prediksi kosong di database (cek tabel predictions & RLS).');
        cow.model = model;
        saveCows();
        var sel = $('cowSelect');
        if (sel && sel.value === cow.id) overlay(cow);
        if (typeof renderList === 'function') renderList();
        api.status = 'selesai'; api.lastError = null;
        return model;
      } catch (e) {
        console.warn('[LactaSync] gagal mengambil prediksi AI:', e);
        api.status = 'gagal';
        api.lastError = String((e && e.message) || e);
        var sel = $('cowSelect');
        if (sel && sel.value === cow.id && !cow.model) setWaitingState(cow, 'Gagal terhubung ke server AI', api.lastError + ' — ketuk untuk coba lagi');
        return null;
      } finally {
        delete inflight[cow.id];
      }
    })();
    return inflight[cow.id];
  }

  async function syncAfterSave(cow) {
    if (!cow) return;
    if (!enabled()) { setWaitingState(cow, 'Server AI belum dikonfigurasi', 'Isi url, anonKey, dan apiBase di js/supabase-config.js'); return; }
    if (!App.user) { setWaitingState(cow, 'Login diperlukan untuk AI', 'Silakan masuk menggunakan akun terverifikasi'); return; }
    var api = window.LactaSync;
    try {
      api.status = 'menyimpan';
      setWaitingState(cow, 'Menyimpan log & memprediksi…');
      var cattleId = await ensureCattle(cow, App.user);
      await pushLog(cattleId, cow);
      await runModelForCow(cow, false);
    } catch (e) {
      console.warn('[LactaSync] sinkronisasi gagal:', e);
      api.status = 'gagal'; api.lastError = String((e && e.message) || e);
      if (!cow.model) setWaitingState(cow, 'Gagal simpan / prediksi AI', api.lastError + ' — ketuk untuk coba lagi');
    }
  }

  async function refreshCow(cow) {
    if (!cow) return;
    if (cow.model && cow.model.savedAt && (Date.now() - cow.model.savedAt) < 120000) { overlay(cow); return; }
    await runModelForCow(cow, true);
  }

  // Ketuk kartu prediksi untuk mencoba lagi saat gagal.
  function retry() {
    var sel = $('cowSelect');
    var cow = sel && typeof cows !== 'undefined' ? cows.find(function (c) { return c.id === sel.value; }) : null;
    if (cow && window.LactaSync && LactaSync.status === 'gagal') { cow.model = null; runModelForCow(cow, true); }
  }
  document.addEventListener('DOMContentLoaded', function () {
    ['alertBox', 'card-pred-tap'].forEach(function (id) { var el = $(id); if (el) el.addEventListener('click', retry); });
  });

  window.LactaSync = {
    enabled: enabled, syncAfterSave: syncAfterSave, refreshCow: refreshCow,
    overlay: overlay, retry: retry, uuid5: uuid5, status: 'idle', lastError: null
  };
})();
