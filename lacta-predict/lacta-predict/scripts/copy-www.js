// Menyalin file web ke folder www/ (dipakai Capacitor).
const fs = require('fs'), path = require('path');
const root = path.join(__dirname, '..');
const out = path.join(root, 'www');
const items = ['index.html', 'login.html', 'manifest.webmanifest', 'sw.js', 'css', 'js', 'icons'];
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });
for (const it of items) {
  const src = path.join(root, it);
  if (!fs.existsSync(src) || fs.statSync(src).isDirectory() && it === 'login.html') {
    console.warn('Dilewati (tidak ditemukan atau bukan file):', it);
    continue;
  }
  fs.cpSync(src, path.join(out, it), { recursive: true });
}
console.log('www/ siap.');
