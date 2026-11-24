// Konfigurasi penyambung Supabase + backend AI. Isi 3 nilai di bawah.
// - url      : Project URL Supabase (Project Settings > API)
// - anonKey  : kunci "anon public" (BUKAN service_role! Kunci service_role hanya untuk backend)
// - apiBase  : alamat backend lacta-predict-backend. Di HP/APK harus alamat publik HTTPS
//              (bukan localhost). Contoh Cloudflare Tunnel: https://xxxx.trycloudflare.com
// Selama masih berisi nilai placeholder (PROJECT.supabase / KUNCI_ANON / YOUR_...),
// sinkronisasi AI dinonaktifkan dan aplikasi menampilkan status "Server AI belum dikonfigurasi".
window.LACTA_SUPABASE = {
  url: 'https://plswweswcbclgnuoomgq.supabase.co',
  anonKey: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBsc3d3ZXN3Y2JjbGdudW9vbWdxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQ5NzcwNjksImV4cCI6MjExMDU1MzA2OX0._e4xwE1K9VbPp1f1WSueQobENid21UIQmCckdGkpBjU',
  apiBase: 'https://studied-frames-picture-shot.trycloudflare.com',
  // Harus SAMA dengan FARMER_NAMESPACE di lacta-predict-backend/common.py
  farmerNamespace: 'a3f1c2de-5b6a-4c1e-9d8f-1a2b3c4d5e6f',
  // Nilai bawaan bila sapi dibuat tanpa atribut (jarang terjadi; form sudah memintanya).
  defaultGeneticGroup: 'HF50',           // Local | HF50 | HF62.5 | HF75 | HF87.5
  defaultUsiaBulan: 48,
  defaultTahapLaktasi: 'Tengah',         // Awal | Tengah | Akhir
  defaultKelembapan: 70
};