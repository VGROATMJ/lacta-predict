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

const STORE_KEY = 'lacta_predict_cows_v1';
let cows = [];
let storeKey = null; // diisi saat login: data ternak dipisah per akun (uid)

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

function defaultCows(){
  return [
    {id:cuid(), nama:'Sapi A-017', kategori:'perah', ras:'Friesian Holstein (FH)', kandang:'Kandang B', prev:28.8, pakan:11.5, suhu:31.2},
    {id:cuid(), nama:'Sapi A-022', kategori:'perah', ras:'Peranakan Friesian Holstein (PFH)', kandang:'Kandang A', prev:23.6, pakan:9.0, suhu:33.5},
    {id:cuid(), nama:'Sapi A-031', kategori:'perah', ras:'Jersey', kandang:'Kandang C', prev:19.4, pakan:8.2, suhu:28.0},
  ];
}
function cuid(){ return Math.random().toString(36).slice(2,9); }

function loadCows(){
  // Akun baru (belum ada data tersimpan) diberi 3 sapi contoh. Setelah itu daftar boleh kosong.
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

// --- rumus perkiraan sederhana (bukan model ML asli, hanya untuk demo alur) ---
function predict(cow){
  const heat = Math.max(0, cow.suhu - 30) * 0.8;
  let pred = cow.prev*0.9 + cow.pakan*0.6 - heat;
  pred = Math.max(3, pred);
  const dropPct = (cow.prev - pred) / cow.prev * 100;
  let segmen = 'Performa Baik';
  if(pred < 20) segmen = 'Perlu Perhatian';
  else if(pred < 27) segmen = 'Rata-rata';
  return {pred, dropPct, segmen,
    fPrev: Math.min(100, Math.round((cow.prev/35)*100)),
    fPakan: Math.min(100, Math.round((cow.pakan/16)*100)),
    fSuhu: Math.min(100, Math.round((Math.max(0,cow.suhu-24)/15)*100))
  };
}
function fmt1(n){ return n.toFixed(1).replace('.', ','); }

const PUBLIC_SCREENS = ['s-loading','s-login','s-verify'];
function go(id){
  if(!App.user && PUBLIC_SCREENS.indexOf(id)===-1){ // layar aplikasi hanya untuk akun terverifikasi
    const pending = window.firebase && firebase.apps.length && firebase.auth().currentUser; // sudah login tapi belum verifikasi
    id = pending ? 's-verify' : 's-login';
  }
  document.querySelectorAll('.screen').forEach(s=>s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  const ph = document.getElementById(id).closest('.phone');
  if(ph) ph.scrollTop = 0;
  if(id==='s-ternak') renderList();
  if(id==='s-dash') renderCow();
}

function fillSelect(){
  const sel = document.getElementById('cowSelect');
  const keep = sel.value; // pertahankan pilihan saat daftar dibangun ulang
  const dairy = cows.filter(c=>(c.kategori||'perah')==='perah');
  sel.innerHTML = dairy.map(c=>`<option value="${escapeHtml(c.id)}">${escapeHtml(c.nama)} · ${escapeHtml(c.kandang)}</option>`).join('');
  if(!dairy.length) sel.innerHTML = '<option value="">Belum ada sapi perah</option>';
  else if(dairy.some(c=>c.id===keep)) sel.value = keep;
}

function renderCow(){
  fillSelect();
  const sel = document.getElementById('cowSelect');
  const cow = cows.find(c=>c.id===sel.value && (c.kategori||'perah')==='perah');
  if(cow) showPrediction(cow); else clearPrediction();
}

function clearPrediction(){
  document.getElementById('predBesok').textContent = '-';
  document.getElementById('predDelta').textContent = '-';
  document.getElementById('alertBox').className = 'alert-box ok';
  document.getElementById('alertIcon').textContent = '🐄';
  document.getElementById('alertTitle').textContent = 'Belum ada data sapi perah';
  document.getElementById('alertSub').textContent = 'Tambahkan sapi perah di menu Data Ternak untuk melihat prediksi.';
  document.getElementById('cowMeta').textContent = 'Belum ada sapi perah dipilih';
  document.getElementById('detailBesok').textContent = '-';
  const badge = document.getElementById('detailBadge');
  badge.textContent = '-'; badge.style.background = 'rgba(255,255,255,.18)';
  ['Prev','Pakan','Suhu'].forEach(k=>{
    document.getElementById('bar'+k+'Val').textContent = '-';
    document.getElementById('bar'+k).style.width = '0%';
  });
  document.getElementById('segVal').textContent = '-';
  drawTrend(null);
}

// Grafik tren: kemarin (data aktual) lalu proyeksi 3 hari memakai rumus predict() yang sama,
// dengan pakan & suhu dianggap tetap.
function drawTrend(cow){
  const solid = document.getElementById('trendSolid');
  const dash = document.getElementById('trendDash');
  if(!cow){ solid.setAttribute('points',''); dash.setAttribute('points',''); return; }
  const v = [cow.prev];
  let cur = {...cow};
  for(let k=0;k<3;k++){ const p = predict(cur).pred; v.push(p); cur = {...cur, prev:p}; }
  const min = Math.min(...v), max = Math.max(...v), span = (max-min) || 1;
  const pts = v.map((val,idx)=>[4 + idx*(292/3), max===min ? 35 : 60 - ((val-min)/span)*50]);
  const str = a=>a.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ');
  solid.setAttribute('points', str(pts.slice(0,2)));
  dash.setAttribute('points', str(pts.slice(1)));
}

function showPrediction(cow){
  const r = predict(cow);
  document.getElementById('predBesok').textContent = fmt1(r.pred) + ' L';
  document.getElementById('predDelta').textContent = (r.dropPct>=0?'-':'+') + Math.abs(r.dropPct).toFixed(1) + '% dari kemarin';

  const box = document.getElementById('alertBox');
  const warn = r.dropPct >= 10;
  box.className = 'alert-box' + (warn?'':' ok');
  document.getElementById('alertIcon').textContent = warn ? '⚠️' : '✅';
  document.getElementById('alertTitle').textContent = warn ? 'Produksi diprediksi turun' : 'Produksi stabil';
  document.getElementById('alertSub').textContent = cow.nama + ' · ' + r.segmen + (warn ? ' — cek kondisi pakan & suhu kandang.' : ' — tidak ada tindakan khusus.');

  document.getElementById('cowMeta').textContent = cow.nama + ' (' + cow.ras + ') · ' + cow.kandang;
  document.getElementById('detailBesok').textContent = fmt1(r.pred) + ' L';
  const badge = document.getElementById('detailBadge');
  badge.textContent = (r.dropPct>=0?'Turun ':'Naik ') + Math.abs(r.dropPct).toFixed(1) + '%';
  badge.style.background = r.dropPct>=10 ? 'rgba(255,120,120,.28)' : 'rgba(255,255,255,.18)';

  document.getElementById('barPrevVal').textContent = r.fPrev+'%';
  document.getElementById('barPrev').style.width = r.fPrev+'%';
  document.getElementById('barPakanVal').textContent = r.fPakan+'%';
  document.getElementById('barPakan').style.width = r.fPakan+'%';
  document.getElementById('barSuhuVal').textContent = r.fSuhu+'%';
  document.getElementById('barSuhu').style.width = r.fSuhu+'%';
  document.getElementById('segVal').textContent = r.segmen;
  drawTrend(cow);
  if(window.LactaSync) LactaSync.overlay(cow); // hasil model dari Supabase (jika ada) menimpa rumus lokal
}

function renderList(){
  const wrap = document.getElementById('cowList');
  if(!cows.length){
    wrap.innerHTML = `<div class="hint" style="margin-top:6px">Belum ada sapi tercatat. Tap "+ Tambah Sapi" di atas untuk mulai mencatat.</div>`;
    return;
  }
  wrap.innerHTML = cows.map((c,i)=>{
    const beef=(c.kategori||'perah')==='potong';
    const r = beef?null:predict(c);
    const warn = beef?false:r.dropPct>=10;
    return `<div class="cow-item" onclick="selectCow(${i})">
      <div style="flex:1;min-width:0"><div class="ci-name">${escapeHtml(c.nama)}</div><div class="ci-sub">${escapeHtml(c.ras)} · ${escapeHtml(c.kandang)} · ${beef?'Sapi potong':'Sapi perah'}</div></div>
      <div class="ci-badge ${beef?'badge-good':(warn?'badge-warn':'badge-good')}">${beef?'Inventaris':(warn?'Perlu cek':'Baik')}</div>
      <button type="button" class="ci-del" aria-label="Hapus ${escapeHtml(c.nama)}" onclick="event.stopPropagation();deleteCow(${i})">Hapus</button>
    </div>`;
  }).join('') + `<div class="hint" style="margin-top:6px">Tap salah satu sapi untuk lihat prediksinya, atau "+ Tambah Sapi" di atas untuk mencatat sapi baru.</div>`;
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
  ['f-nama','f-kandang','f-prev','f-pakan','f-suhu'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('f-kategori').value='perah';
  updateBreedOptions();
  go('s-form');
}

function updateBreedOptions(){
  const kategori=document.getElementById('f-kategori').value;
  const ras=document.getElementById('f-ras');
  const dairy=['Friesian Holstein (FH)','Peranakan Friesian Holstein (PFH)','Jersey','Brown Swiss','Ayrshire','Sahiwal'];
  const beef=['Limousin','Simmental','Brahman','Angus','PO (Peranakan Ongole)','Madura'];
  const options=kategori==='perah'?dairy:beef;
  ras.innerHTML=options.map(x=>`<option value="${x}">${x}</option>`).join('');
  document.getElementById('breedHint').textContent=kategori==='perah'?'Ras sapi perah dapat digunakan pada pencatatan dan demo prediksi susu.':'Sapi potong dapat dicatat sebagai inventaris, tetapi tidak dihitung dalam prediksi produksi susu.';
  ['f-prev','f-pakan','f-suhu'].forEach(id=>{document.getElementById(id).disabled=kategori==='potong';});
}

function submitForm(){
  const nama = document.getElementById('f-nama').value.trim();
  const ras = document.getElementById('f-ras').value;
  const kategori = document.getElementById('f-kategori').value;
  const kandang = document.getElementById('f-kandang').value.trim() || '-';
  const prev = kategori==='perah'?parseFloat(document.getElementById('f-prev').value):0;
  const pakan = kategori==='perah'?parseFloat(document.getElementById('f-pakan').value):0;
  const suhu = kategori==='perah'?parseFloat(document.getElementById('f-suhu').value):0;

  if(!nama || (kategori==='perah' && (isNaN(prev)||isNaN(pakan)||isNaN(suhu)))){
    alert('Isi nama sapi serta data produksi, pakan, dan suhu untuk sapi perah.');
    return;
  }
  if(kategori==='perah' && !(prev>0 && prev<=100 && pakan>0 && pakan<=100 && suhu>=10 && suhu<=50)){
    alert('Periksa angka: produksi dan pakan harus lebih dari 0 (maks. 100), suhu kandang antara 10-50 °C.');
    return;
  }
  const cow = {id:cuid(), nama, kategori, ras, kandang, prev, pakan, suhu};
  cows.push(cow);
  saveCows();
  fillSelect();
  if(kategori==='perah'){
    document.getElementById('cowSelect').value = cow.id;
    showPrediction(cow);
    go('s-detail');
    if(window.LactaSync) LactaSync.syncAfterSave(cow); // simpan ke Supabase -> backend AI -> tampilkan hasil
  } else {
    alert('Data sapi potong berhasil ditambahkan ke inventaris. Sapi ini tidak masuk ke prediksi produksi susu.');
    go('s-ternak');
  }
}

// Data ternak baru dimuat setelah login (lihat App.onSignedIn di atas dan js/auth.js).
applyTheme(document.documentElement.getAttribute('data-theme') || 'light');
updateBreedOptions();

// Daftarkan service worker (offline + bisa di-install)
if('serviceWorker' in navigator && location.protocol!=='file:'){
  window.addEventListener('load',()=>{navigator.serviceWorker.register('sw.js').catch(()=>{});});
}
