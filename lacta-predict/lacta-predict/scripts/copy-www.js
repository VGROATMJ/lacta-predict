// Menyalin file web ke folder www/ (dipakai Capacitor).
const fs = require('fs'), path = require('path');
const root = path.join(__dirname, '..');
const out = path.join(root, 'www');
const items = ['index.html', 'manifest.webmanifest', 'sw.js', 'css', 'js', 'icons'];
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });
for (const it of items) fs.cpSync(path.join(root, it), path.join(out, it), { recursive: true });
console.log('www/ siap.');
