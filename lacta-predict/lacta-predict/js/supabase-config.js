// Konfigurasi penyambung Supabase + backend AI. Isi 3 nilai di bawah.
// - url      : Project URL Supabase (Project Settings > API)
// - anonKey  : kunci "anon public" (BUKAN service_role! Kunci service_role hanya untuk backend)
// - apiBase  : alamat backend lacta-predict-backend. Di HP/APK harus alamat publik HTTPS
//              (bukan localhost). Contoh: https://lacta-api.onrender.com
// Selama masih berisi "YOUR_...", sinkronisasi dinonaktifkan dan aplikasi berjalan seperti semula
// (rumus lokal + localStorage).
window.LACTA_SUPABASE = {
  url: 'https://YOUR_PROJECT.supabase.co',
  anonKey: 'YOUR_SUPABASE_ANON_KEY',
  apiBase: 'https://YOUR_BACKEND_HOST',
  // Harus SAMA dengan FARMER_NAMESPACE di lacta-predict-backend/common.py
  farmerNamespace: 'a3f1c2de-5b6a-4c1e-9d8f-1a2b3c4d5e6f',
  // Nilai bawaan karena form belum punya isian usia & tahap laktasi (lihat catatan README backend)
  defaultUsiaBulan: 48,
  defaultTahapLaktasi: 'tengah',   // awal | puncak | tengah | akhir
  defaultJenisPakan: 'campuran'    // hijauan | konsentrat | campuran
};
