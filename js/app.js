const THEME_KEY = 'lacta_predict_theme_v1';
function applyTheme(theme){
  const safeTheme = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', safeTheme);
  const icon = document.getElementById('themeIcon');
  const label = document.getElementById('themeLabel');
  if(icon) icon.textContent = safeTheme === 'dark' ? '🌙' : '☀️';
  if(label) label.textContent = safeTheme === 'dark' ? 'Mode Gelap' : 'Mode Terang';
  try{ localStorage.setItem(THEME_KEY, safeTheme); }catch(e){}
}
function toggleTheme(){
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  applyTheme(current === 'dark' ? 'light' : 'dark');
}
(function initTheme(){
  let saved = 'light';
  try{ saved = localStorage.getItem(THEME_KEY) || 'light'; }catch(e){}
  document.documentElement.setAttribute('data-theme', saved === 'dark' ? 'dark' : 'light');
})();

// Data ternak dipisah per akun (uid). Versi v2 menyimpan kolom sesuai dataset model AI.
const STORE_KEY = 'lacta_predict_cows_v2';
let cows = [];
let storeKey = null;

// Kelompok genetik yang dikenali model AI (nilai = genetic_group pada dataset).
const GENETIC_GROUPS = [
  {value:'Local',  label:'Local (sapi lokal / PO)'},
  {value:'HF50',   label:'HF50 (½ Friesian Holstein)'},
  {value:'HF62.5', label:'HF62.5 (⅝ FH)'},
  {value:'HF75',   label:'HF75 (¾ FH)'},
  {value:'HF87.5', label:'HF87.5 (⅞ FH, potensi tinggi)'}
];
const BEEF_BREEDS = ['Limousin','Simmental','Brahman','Angus','PO (Peranakan Ongole)','Madura'];

// Jembatan ke auth.js: dipanggil saat status login berubah.
const App = {
  user: null,
  onSignedIn(user){
    const changed = !this.user || this.user.uid !== user.uid;
    this.user = user;
    document.getElementById('greetText').textContent = greetText(user);
    if(changed){
      storeKey = STORE_KEY + '_' + user.uid;
      loadCows();
      updateBreedOptions();
      renderCow();
    }
  },
  onSignedOut(){
    this.user = null; storeKey = null; cows = [];
  }
};
function greetText(user){
  const h = new Date().getHours();
  const sapa = h<11 ? 'Selamat pagi' : h<15 ? 'Selamat siang' : h<18 ? 'Selamat sore' : 'Selamat malam';
  const nama = (user.displayName || (user.email||'').split('@')[0] || '').trim();
  return nama ? sapa + ', ' + nama : sapa;
}
function escapeHtml(v){
  return String(v==null?'':v).replace(/[&<>"']/g, ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function cuid(){ return Math.random().toString(36).slice(2,9); }
function fmt1(n){ return Number(n).toFixed(1).replace('.', ','); }

// Akun baru diberi 3 sapi contoh (skala dataset v2: produksi ~1-10 L, DMI ~6-13 kg).
function defaultCows(){
  return [
    {id:cuid(), nama:'Sapi A-017', kategori:'perah', ras:'HF75',   genetic_group:'HF75',   kandang:'Kandang B', usia:52, tahap:'Tengah', prev:8.2, dmi:12.4, suhu:26.5, rh:70},
    {id:cuid(), nama:'Sapi A-022', kategori:'perah', ras:'HF50',   genetic_group:'HF50',   kandang:'Kandang A', usia:48, tahap:'Awal',   prev:5.4, dmi:9.8,  suhu:29.0, rh:76},
    {id:cuid(), nama:'Sapi A-031', kategori:'perah', ras:'Local',  genetic_group:'Local',  kandang:'Kandang C', usia:58, tahap:'Akhir',  prev:1.6, dmi:6.3,  suhu:31.5, rh:80},
  ];
}

function loadCows(){
  let raw = null;
  try{ raw = storeKey ? localStorage.getItem(storeKey) : null; }catch(e){}
  if(raw === null){ cows = defaultCows(); saveCows(); return; }
  try{
    const parsed = JSON.parse(raw);
    cows = Array.isArray(parsed) ? parsed.filter(c=>c && typeof c==='object' && c.id && c.nama) : [];
  }catch(e){ cows = []; }
}
function saveCows(){
  if(!storeKey) return;
  try{ localStorage.setItem(storeKey, JSON.stringify(cows)); }catch(e){}
}

// Indeks suhu-kelembaban (THI) — sama dengan formula di backend (common.thi_from).
function thiOf(suhu, rh){
  const t = Number(suhu), h = Math.max(0, Math.min(100, Number(rh)));
  if(!isFinite(t) || !isFinite(h)) return NaN;
  return (1.8*t + 32) - (0.55 - 0.0055*h) * (1.8*t - 26);
}

const PUBLIC_SCREENS = ['s-loading','s-login','s-verify'];
function go(id){
  if(!App.user && PUBLIC_SCREENS.indexOf(id)===-1){
    const pending = window.firebase && firebase.apps.length && firebase.auth().currentUser;
    id = pending ? 's-verify' : 's-login';
  }
  document.querySelectorAll('.screen').forEach(s=>s.classList.remove('active'));
  const el = document.getElementById(id);
  el.classList.add('active');
  // retrigger animasi masuk layar
  el.style.animation = 'none'; void el.offsetWidth; el.style.animation = '';
  const ph = el.closest('.phone');
  if(ph) ph.scrollTop = 0;
  if(id==='s-ternak') renderList();
  if(id==='s-dash' || id==='s-detail') renderCow();
}

function fillSelect(){
  const sel = document.getElementById('cowSelect');
  const keep = sel.value;
  const dairy = cows.filter(c=>(c.kategori||'perah')==='perah');
  sel.innerHTML = dairy.map(c=>`<option value="${escapeHtml(c.id)}">${escapeHtml(c.nama)} · ${escapeHtml(c.kandang)}</option>`).join('');
  if(!dairy.length) sel.innerHTML = '<option value="">Belum ada sapi perah</option>';
  else if(dairy.some(c=>c.id===keep)) sel.value = keep;
}

function renderCow(){
  fillSelect();
  const sel = document.getElementById('cowSelect');
  const cow = cows.find(c=>c.id===sel.value && (c.kategori||'perah')==='perah');
  if(cow) renderCowAI(cow); else clearPrediction();
}

function clearPrediction(){
  document.getElementById('predBesok').textContent = '-';
  document.getElementById('predDelta').textContent = '-';
  document.getElementById('alertBox').className = 'alert-box ok';
  document.getElementById('alertIcon').textContent = '🐄';
  document.getElementById('alertTitle').textContent = 'Belum ada data sapi perah';
  document.getElementById('alertSub').textContent = 'Tambahkan sapi perah di menu Data Ternak untuk melihat prediksi AI.';
  document.getElementById('cowMeta').textContent = 'Belum ada sapi perah dipilih';
  document.getElementById('detailBesok').textContent = '-';
  const badge = document.getElementById('detailBadge');
  badge.textContent = '-'; badge.style.background = 'rgba(255,255,255,.18)';
  ['Prev','Pakan','Suhu'].forEach(k=>{
    document.getElementById('bar'+k+'Val').textContent = '-';
    document.getElementById('bar'+k).style.width = '0%';
  });
  document.getElementById('segVal').textContent = '-';
  document.getElementById('trendSolid').setAttribute('points','');
  document.getElementById('trendDash').setAttribute('points','');
}

// Bar faktor dihitung dari INPUT pengguna (bukan prediksi) — hanya ilustrasi kondisi sapi.
function setFactorBars(cow){
  const eff = cow.dmi>0 ? cow.prev/cow.dmi : 0;          // efisiensi pakan (L susu per kg)
  const thi = thiOf(cow.suhu, cow.rh);
  const comfort = isFinite(thi) ? Math.max(0, Math.min(100, (85 - thi)/(85-65)*100)) : 0;
  const bars = [
    ['Prev',  Math.max(0, Math.min(100, (cow.prev/12)*100)),  fmt1(cow.prev)+' L'],
    ['Pakan', Math.max(0, Math.min(100, (eff/0.9)*100)),       eff.toFixed(2)+' L/kg'],
    ['Suhu',  Math.round(comfort),                             isFinite(thi)?('THI '+Math.round(thi)):'-']
  ];
  bars.forEach(([k,w,val])=>{
    document.getElementById('bar'+k+'Val').textContent = val;
    const el = document.getElementById('bar'+k);
    el.style.width = Math.round(w)+'%';
  });
}

function renderCowAI(cow){
  document.getElementById('cowMeta').textContent = cow.nama + ' (' + (cow.genetic_group||cow.ras) + ' · ' + (cow.tahap||'-') + ') · ' + cow.kandang;
  setFactorBars(cow);
  // Tidak ada perhitungan prediksi lokal: angka produksi HANYA dari model AI (Supabase/predictions).
  if(window.LactaSync){
    LactaSync.overlay(cow);        // tampilkan hasil AI tersimpan, atau status "menunggu/gagal"
    LactaSync.refreshCow(cow);     // ambil/segarkan prediksi dari backend bila perlu
  }
}

function renderList(){
  const wrap = document.getElementById('cowList');
  if(!cows.length){
    wrap.innerHTML = `<div class="hint" style="margin-top:6px">Belum ada sapi tercatat. Tap "+ Tambah Sapi" di atas untuk mulai mencatat.</div>`;
    return;
  }
  wrap.innerHTML = cows.map((c,i)=>{
    const beef=(c.kategori||'perah')==='potong';
    const m = c.model;
    let status = 'AI', cls='badge-good';
    if(beef){ status='Inventaris'; }
    else if(m && m.preds && m.preds.length){ status = m.warn ? 'Perlu cek' : 'Baik'; cls = m.warn ? 'badge-warn' : 'badge-good'; }
    else { status='Menunggu AI'; cls='badge-good'; }
    return `<div class="cow-item" style="animation-delay:${i*40}ms" onclick="selectCow(${i})">
      <div style="flex:1;min-width:0"><div class="ci-name">${escapeHtml(c.nama)}</div><div class="ci-sub">${escapeHtml(c.genetic_group||c.ras)} · ${escapeHtml(c.kandang)} · ${beef?'Sapi potong':'Sapi perah'}</div></div>
      <div class="ci-badge ${cls}">${status}</div>
      <button type="button" class="ci-del" aria-label="Hapus ${escapeHtml(c.nama)}" onclick="event.stopPropagation();deleteCow(${i})">Hapus</button>
    </div>`;
  }).join('') + `<div class="hint" style="margin-top:6px">Tap salah satu sapi untuk lihat prediksi AI-nya, atau "+ Tambah Sapi" untuk mencatat sapi baru.</div>`;
}

function deleteCow(i){
  const c = cows[i]; if(!c) return;
  if(!window.confirm('Hapus "'+c.nama+'" dari daftar ternak? Data tidak bisa dikembalikan.')) return;
  cows.splice(i,1);
  saveCows();
  renderList();
  renderCow();
}

function selectCow(i){
  if(!cows[i]) return;
  if((cows[i].kategori||'perah')==='potong'){ alert('Sapi potong tersimpan di inventaris, tetapi tidak dimasukkan ke prediksi produksi susu.'); return; }
  document.getElementById('cowSelect').value = cows[i].id;
  renderCow();
  go('s-detail');
}

function openForm(){
  ['f-nama','f-kandang','f-usia','f-prev','f-pakan','f-suhu','f-rh'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('f-kategori').value='perah';
  document.getElementById('f-tahap').value='Tengah';
  updateBreedOptions();
  go('s-form');
}

function updateBreedOptions(){
  const kategori=document.getElementById('f-kategori').value;
  const ras=document.getElementById('f-ras');
  const lab=document.getElementById('lab-ras');
  const dairy = kategori==='perah';
  if(dairy){
    lab.textContent = 'Kelompok Genetik';
    ras.innerHTML = GENETIC_GROUPS.map(g=>`<option value="${g.value}">${g.label}</option>`).join('');
    document.getElementById('breedHint').textContent='Kelompok genetik dipakai model AI untuk memperkirakan potensi produksi.';
  } else {
    lab.textContent = 'Jenis / Ras Sapi';
    ras.innerHTML = BEEF_BREEDS.map(x=>`<option value="${x}">${x}</option>`).join('');
    document.getElementById('breedHint').textContent='Sapi potong dicatat sebagai inventaris, tetapi tidak dihitung dalam prediksi produksi susu.';
  }
  document.getElementById('dairy-fields').style.display = dairy ? '' : 'none';
}

function submitForm(){
  const nama = document.getElementById('f-nama').value.trim();
  const ras = document.getElementById('f-ras').value;
  const kategori = document.getElementById('f-kategori').value;
  const kandang = document.getElementById('f-kandang').value.trim() || '-';

  if(kategori==='potong'){
    if(!nama){ alert('Isi nama / ID sapi.'); return; }
    cows.push({id:cuid(), nama, kategori, ras, genetic_group:ras, kandang, usia:0, tahap:'-', prev:0, dmi:0, suhu:0, rh:0});
    saveCows();
    alert('Data sapi potong berhasil ditambahkan ke inventaris. Sapi ini tidak masuk ke prediksi produksi susu.');
    go('s-ternak');
    return;
  }

  const usia = parseFloat(document.getElementById('f-usia').value);
  const tahap = document.getElementById('f-tahap').value;
  const prev = parseFloat(document.getElementById('f-prev').value);
  const dmi  = parseFloat(document.getElementById('f-pakan').value);
  const suhu = parseFloat(document.getElementById('f-suhu').value);
  const rh   = parseFloat(document.getElementById('f-rh').value);

  if(!nama || [usia,prev,dmi,suhu,rh].some(v=>isNaN(v))){
    alert('Lengkapi nama sapi, umur, produksi kemarin, pakan (DMI), suhu, dan kelembaban kandang.');
    return;
  }
  if(!(usia>0 && usia<=200)){ alert('Umur sapi harus 1–200 bulan.'); return; }
  if(!(prev>=0 && prev<=50)){ alert('Produksi susu kemarin tidak wajar (0–50 L).'); return; }
  if(!(dmi>0 && dmi<=50)){ alert('Pakan (DMI) harus lebih dari 0 dan maksimal 50 kg.'); return; }
  if(!(suhu>=10 && suhu<=50)){ alert('Suhu kandang antara 10–50 °C.'); return; }
  if(!(rh>=0 && rh<=100)){ alert('Kelembaban kandang antara 0–100 %.'); return; }

  const cow = {id:cuid(), nama, kategori, ras, genetic_group:ras, kandang, usia, tahap, prev, dmi, suhu, rh};
  cows.push(cow);
  saveCows();
  fillSelect();
  document.getElementById('cowSelect').value = cow.id;
  renderCowAI(cow);
  go('s-detail');
  if(window.LactaSync) LactaSync.syncAfterSave(cow); // simpan ke Supabase -> backend AI -> tampilkan hasil
}

// Data ternak baru dimuat setelah login (lihat App.onSignedIn di atas dan js/auth.js).
applyTheme(document.documentElement.getAttribute('data-theme') || 'light');
updateBreedOptions();

// Daftarkan service worker (offline + bisa di-install)
if('serviceWorker' in navigator && location.protocol!=='file:'){
  window.addEventListener('load',()=>{navigator.serviceWorker.register('sw.js').catch(()=>{});});
}
