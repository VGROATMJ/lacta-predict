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

function defaultCows(){
  return [
    {id:cuid(), nama:'Sapi A-017', kategori:'perah', ras:'Friesian Holstein (FH)', kandang:'Kandang B', prev:28.8, pakan:11.5, suhu:31.2},
    {id:cuid(), nama:'Sapi A-022', kategori:'perah', ras:'Peranakan Friesian Holstein (PFH)', kandang:'Kandang A', prev:23.6, pakan:9.0, suhu:33.5},
    {id:cuid(), nama:'Sapi A-031', kategori:'perah', ras:'Jersey', kandang:'Kandang C', prev:19.4, pakan:8.2, suhu:28.0},
  ];
}
function cuid(){ return Math.random().toString(36).slice(2,9); }

function loadCows(){
  try{
    const raw = localStorage.getItem(STORE_KEY);
    cows = raw ? JSON.parse(raw) : defaultCows();
  }catch(e){ cows = defaultCows(); }
  if(!cows || !cows.length) cows = defaultCows();
}
function saveCows(){
  try{ localStorage.setItem(STORE_KEY, JSON.stringify(cows)); }catch(e){}
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

function go(id){
  document.querySelectorAll('.screen').forEach(s=>s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  const ph = document.getElementById(id).closest('.phone');
  if(ph) ph.scrollTop = 0;
  if(id==='s-ternak') renderList();
  if(id==='s-dash') renderCow();
}

function fillSelect(){
  const sel = document.getElementById('cowSelect');
  const dairy = cows.map((c,i)=>({c,i})).filter(x=>(x.c.kategori||'perah')==='perah');
  sel.innerHTML = dairy.map(x=>`<option value="${x.i}">${x.c.nama} · ${x.c.kandang}</option>`).join('');
  if(!dairy.length) sel.innerHTML = '<option value="">Belum ada sapi perah</option>';
}

function renderCow(){
  fillSelect();
  const sel = document.getElementById('cowSelect');
  const i = Number(sel.value);
  if(Number.isInteger(i) && cows[i]) showPrediction(cows[i]);
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
}

function renderList(){
  const wrap = document.getElementById('cowList');
  wrap.innerHTML = cows.map((c,i)=>{
    const beef=(c.kategori||'perah')==='potong';
    const r = beef?null:predict(c);
    const warn = beef?false:r.dropPct>=10;
    return `<div class="cow-item" onclick="selectCow(${i})">
      <div><div class="ci-name">${c.nama}</div><div class="ci-sub">${c.ras} · ${c.kandang} · ${beef?'Sapi potong':'Sapi perah'}</div></div>
      <div class="ci-badge ${beef?'badge-good':(warn?'badge-warn':'badge-good')}">${beef?'Inventaris':(warn?'Perlu cek':'Baik')}</div>
    </div>`;
  }).join('') + `<div class="hint" style="margin-top:6px">Tap salah satu sapi untuk lihat prediksinya, atau "+ Tambah Sapi" di atas untuk mencatat sapi baru.</div>`;
}

function selectCow(i){
  if((cows[i].kategori||'perah')==='potong'){ alert('Sapi potong tersimpan di inventaris, tetapi tidak dimasukkan ke prediksi produksi susu.'); return; }
  document.getElementById('cowSelect').value = i;
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
  const cow = {id:cuid(), nama, kategori, ras, kandang, prev, pakan, suhu};
  cows.push(cow);
  saveCows();
  fillSelect();
  if(kategori==='perah'){
    document.getElementById('cowSelect').value = cows.length-1;
    showPrediction(cow);
    go('s-detail');
  } else {
    alert('Data sapi potong berhasil ditambahkan ke inventaris. Sapi ini tidak masuk ke prediksi produksi susu.');
    go('s-ternak');
  }
}

loadCows();
applyTheme(document.documentElement.getAttribute('data-theme') || 'light');
updateBreedOptions();
renderCow();

// Daftarkan service worker (offline + bisa di-install)
if('serviceWorker' in navigator && location.protocol!=='file:'){
  window.addEventListener('load',()=>{navigator.serviceWorker.register('sw.js').catch(()=>{});});
}
