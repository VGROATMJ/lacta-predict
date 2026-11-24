// Service worker sederhana: cache semua aset supaya app jalan offline.
const CACHE = 'lacta-predict-v4';
const ASSETS = [
  './', './index.html', './css/style.css', './js/app.js', './js/auth.js', './js/firebase-config.js', './js/supabase-config.js', './js/supabase-sync.js',
  './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png',
  './icons/icon-maskable-512.png', './icons/favicon.svg'
];
const SDK_HOST = 'www.gstatic.com'; // SDK Firebase di-cache agar sesi login tetap terbaca saat offline
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  const sameOrigin = url.origin === self.location.origin;
  const isSdk = url.hostname === SDK_HOST && url.pathname.startsWith('/firebasejs/');
  // Request lain (API Firebase/Google, dll.) langsung ke jaringan, tidak di-cache.
  if (!sameOrigin && !isSdk) return;
  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(res => {
      if (res && (res.ok || res.type === 'opaque')) {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
      }
      return res;
    }).catch(() => e.request.mode === 'navigate' ? caches.match('./index.html') : Response.error()))
  );
});
