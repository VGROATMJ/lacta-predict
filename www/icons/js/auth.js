// Autentikasi Firebase (Email + Kata Sandi) dengan verifikasi email wajib.
// Bergantung pada: firebase-app-compat, firebase-auth-compat, firebase-config.js, dan app.js (objek App, go()).
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var PUBLIC_SCREENS = ['s-loading', 's-login', 's-verify'];
  var mode = 'login';           // 'login' | 'register' | 'reset'
  var auth = null;
  var resendTimer = null;
  var busy = false;

  var ERRORS = {
    'auth/invalid-email': 'Format email tidak valid.',
    'auth/missing-email': 'Email belum diisi.',
    'auth/missing-password': 'Kata sandi belum diisi.',
    'auth/user-disabled': 'Akun ini dinonaktifkan. Hubungi admin.',
    'auth/user-not-found': 'Email atau kata sandi salah.',
    'auth/wrong-password': 'Email atau kata sandi salah.',
    'auth/invalid-credential': 'Email atau kata sandi salah.',
    'auth/invalid-login-credentials': 'Email atau kata sandi salah.',
    'auth/email-already-in-use': 'Email ini sudah terdaftar. Silakan masuk.',
    'auth/weak-password': 'Kata sandi terlalu lemah. Gunakan minimal 8 karakter, kombinasi huruf dan angka.',
    'auth/too-many-requests': 'Terlalu banyak percobaan. Tunggu beberapa menit lalu coba lagi.',
    'auth/network-request-failed': 'Tidak ada koneksi internet. Periksa jaringan Anda.',
    'auth/operation-not-allowed': 'Login email/kata sandi belum diaktifkan di Firebase Console.',
    'auth/unauthorized-domain': 'Domain ini belum didaftarkan di Firebase (Authorized domains).',
    'auth/requires-recent-login': 'Sesi terlalu lama. Silakan keluar lalu masuk kembali.'
  };
  function errText(e) { return (e && ERRORS[e.code]) || 'Terjadi kesalahan. Coba lagi sebentar lagi.'; }

  function showMsg(id, text, kind) {
    var el = $(id); if (!el) return;
    if (!text) { el.hidden = true; el.textContent = ''; return; }
    el.textContent = text;
    el.className = 'msg' + (kind ? ' ' + kind : '');
    el.hidden = false;
  }
  function setBusy(on, btnId, labelBusy) {
    busy = on;
    var b = $(btnId); if (!b) return;
    if (on) { b.dataset.label = b.textContent; b.textContent = labelBusy || 'Memproses...'; }
    else if (b.dataset.label) { b.textContent = b.dataset.label; }
    b.disabled = on;
  }

  // ---------- Mode form: masuk / daftar / lupa sandi ----------
  function setMode(m) {
    mode = m;
    showMsg('authMsg', '');
    var reg = m === 'register', rst = m === 'reset';
    $('nameGroup').hidden = !reg;
    $('confirmGroup').hidden = !reg;
    $('passHint').hidden = !reg;
    $('passGroup').hidden = rst;
    $('authSubmit').textContent = reg ? 'Daftar' : (rst ? 'Kirim Tautan Reset' : 'Masuk');
    $('authPass').setAttribute('autocomplete', reg ? 'new-password' : 'current-password');
    $('forgotRow').hidden = reg || rst;
    $('toggleText').textContent = reg ? 'Sudah punya akun? ' : (rst ? 'Ingat kata sandi? ' : 'Belum punya akun? ');
    $('toggleLink').textContent = reg ? 'Masuk' : (rst ? 'Kembali masuk' : 'Daftar');
    $('loginHeading').textContent = reg ? 'Buat akun baru' : (rst ? 'Reset kata sandi' : '');
    $('loginHeading').hidden = !(reg || rst);
  }

  function validEmail(v) { return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v); }
  function validPassword(v) { return v.length >= 8 && /[A-Za-z]/.test(v) && /\d/.test(v); }

  function onSubmit(ev) {
    ev.preventDefault();
    if (busy || !auth) return;
    var email = $('loginUser').value.trim();
    var pass = $('authPass').value;
    showMsg('authMsg', '');

    if (!validEmail(email)) { showMsg('authMsg', 'Masukkan email yang valid.', 'err'); return; }

    if (mode === 'reset') { return doReset(email); }
    if (!pass) { showMsg('authMsg', 'Kata sandi belum diisi.', 'err'); return; }

    if (mode === 'register') {
      var name = $('authName').value.trim().replace(/\s+/g, ' ');
      if (name.length < 2) { showMsg('authMsg', 'Nama minimal 2 karakter.', 'err'); return; }
      if (!validPassword(pass)) { showMsg('authMsg', ERRORS['auth/weak-password'], 'err'); return; }
      if (pass !== $('authPass2').value) { showMsg('authMsg', 'Konfirmasi kata sandi tidak sama.', 'err'); return; }
      return doRegister(name, email, pass);
    }
    doLogin(email, pass);
  }

  function doLogin(email, pass) {
    setBusy(true, 'authSubmit', 'Masuk...');
    auth.signInWithEmailAndPassword(email, pass)
      .then(function () { $('authPass').value = ''; /* navigasi ditangani onAuthStateChanged */ })
      .catch(function (e) { showMsg('authMsg', errText(e), 'err'); })
      .then(function () { setBusy(false, 'authSubmit'); });
  }

  function doRegister(name, email, pass) {
    setBusy(true, 'authSubmit', 'Mendaftar...');
    var cred;
    auth.createUserWithEmailAndPassword(email, pass)
      .then(function (c) {
        cred = c;
        return c.user.updateProfile({ displayName: name }).catch(function () {});
      })
      .then(function () {
        return cred.user.sendEmailVerification().then(function () { return true; }, function () { return false; });
      })
      .then(function (sent) {
        $('authPass').value = ''; $('authPass2').value = '';
        route(auth.currentUser);   // tampilkan layar verifikasi dengan nama yang sudah tersimpan
        showMsg('verifyMsg', sent
          ? 'Pendaftaran berhasil. Tautan verifikasi sudah dikirim, cek inbox atau folder spam.'
          : 'Akun dibuat, tetapi email verifikasi gagal dikirim. Tekan "Kirim Ulang Email Verifikasi".', sent ? 'ok' : 'err');
        if (sent) startCooldown();
      })
      .catch(function (e) { showMsg('authMsg', errText(e), 'err'); })
      .then(function () { setBusy(false, 'authSubmit'); });
  }

  function doReset(email) {
    setBusy(true, 'authSubmit', 'Mengirim...');
    auth.sendPasswordResetEmail(email)
      .then(function () { return null; }, function (e) {
        // Jangan bocorkan apakah email terdaftar atau tidak.
        if (e && (e.code === 'auth/user-not-found')) return null;
        return e;
      })
      .then(function (e) {
        if (e) showMsg('authMsg', errText(e), 'err');
        else showMsg('authMsg', 'Jika email terdaftar, tautan reset kata sandi sudah dikirim. Cek inbox atau folder spam.', 'ok');
      })
      .then(function () { setBusy(false, 'authSubmit'); });
  }

  // ---------- Layar verifikasi email ----------
  function startCooldown() {
    var b = $('resendBtn'); if (!b) return;
    var left = 60;
    clearInterval(resendTimer);
    b.disabled = true; b.textContent = 'Kirim ulang dalam ' + left + ' dtk';
    resendTimer = setInterval(function () {
      left--;
      if (left <= 0) { clearInterval(resendTimer); b.disabled = false; b.textContent = 'Kirim Ulang Email Verifikasi'; }
      else b.textContent = 'Kirim ulang dalam ' + left + ' dtk';
    }, 1000);
  }
  function resendVerification() {
    var u = auth && auth.currentUser; if (!u || busy) return;
    var b = $('resendBtn'); b.disabled = true;
    u.sendEmailVerification()
      .then(function () { showMsg('verifyMsg', 'Email verifikasi dikirim ulang ke ' + u.email + '. Cek juga folder spam.', 'ok'); startCooldown(); })
      .catch(function (e) { showMsg('verifyMsg', errText(e), 'err'); b.disabled = false; });
  }
  function checkVerified(silent) {
    var u = auth && auth.currentUser; if (!u) return;
    if (!silent) setBusy(true, 'checkBtn', 'Memeriksa...');
    u.reload()
      .then(function () { return u.getIdToken(true); })
      .then(function () {
        if (auth.currentUser && auth.currentUser.emailVerified) route(auth.currentUser);
        else if (!silent) showMsg('verifyMsg', 'Email belum terverifikasi. Klik tautan di email Anda terlebih dahulu.', 'err');
      })
      .catch(function (e) { if (!silent) showMsg('verifyMsg', errText(e), 'err'); })
      .then(function () { if (!silent) setBusy(false, 'checkBtn'); });
  }

  // ---------- Akun ----------
  function renderAccount(u) {
    $('akunNama').textContent = u.displayName || '-';
    $('akunEmail').textContent = u.email || '-';
    $('akunStatus').textContent = u.emailVerified ? 'Email terverifikasi ✓' : 'Belum terverifikasi';
  }
  function sendResetFromAccount() {
    var u = auth && auth.currentUser; if (!u || !u.email) return;
    auth.sendPasswordResetEmail(u.email)
      .then(function () { showMsg('akunMsg', 'Tautan ganti kata sandi dikirim ke ' + u.email + '.', 'ok'); })
      .catch(function (e) { showMsg('akunMsg', errText(e), 'err'); });
  }
  function logout() {
    if (!auth) return;
    if (!window.confirm('Keluar dari akun ini?')) return;
    auth.signOut().catch(function (e) { showMsg('akunMsg', errText(e), 'err'); });
  }

  // ---------- Routing berdasarkan status login ----------
  function activeScreen() { var a = document.querySelector('.screen.active'); return a ? a.id : ''; }
  function route(user) {
    clearInterval(resendTimer);
    if (!user) {
      App.onSignedOut();
      setMode('login');
      go('s-login');
      return;
    }
    if (!user.emailVerified) {
      App.onSignedOut();
      $('verifyEmail').textContent = user.email;
      if (activeScreen() !== 's-verify') { showMsg('verifyMsg', ''); $('resendBtn').disabled = false; $('resendBtn').textContent = 'Kirim Ulang Email Verifikasi'; }
      go('s-verify');
      return;
    }
    App.onSignedIn(user);
    renderAccount(user);
    if (PUBLIC_SCREENS.indexOf(activeScreen()) !== -1) go('s-dash');
  }

  function failInit(text) {
    setMode('login');
    $('authSubmit').disabled = true;
    showMsg('authMsg', text, 'err');
    go('s-login');
  }

  function init() {
    // Pasang event dulu agar UI tetap responsif walaupun Firebase gagal dimuat.
    $('authForm').addEventListener('submit', onSubmit);
    $('toggleLink').addEventListener('click', function () { setMode(mode === 'login' ? 'register' : 'login'); });
    $('forgotLink').addEventListener('click', function () { setMode('reset'); });
    $('resendBtn').addEventListener('click', resendVerification);
    $('checkBtn').addEventListener('click', function () { checkVerified(false); });
    $('verifyLogout').addEventListener('click', function () { if (auth) auth.signOut(); });
    $('akunReset').addEventListener('click', sendResetFromAccount);
    $('akunLogout').addEventListener('click', logout);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden && activeScreen() === 's-verify') checkVerified(true);
    });
    setMode('login');

    if (!window.firebase || !window.LACTA_FIREBASE_CONFIG) {
      return failInit('Layanan login tidak dapat dimuat. Periksa koneksi internet lalu muat ulang aplikasi.');
    }
    try {
      if (!firebase.apps.length) firebase.initializeApp(window.LACTA_FIREBASE_CONFIG);
      auth = firebase.auth();
      auth.languageCode = 'id';   // email verifikasi/reset berbahasa Indonesia
    } catch (e) {
      return failInit('Gagal menginisialisasi layanan login.');
    }
    auth.onAuthStateChanged(route, function () { failInit('Gagal memeriksa sesi login.'); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
