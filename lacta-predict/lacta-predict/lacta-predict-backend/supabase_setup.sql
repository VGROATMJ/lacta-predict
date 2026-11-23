-- Lacta-Predict: penyesuaian Supabase (jalankan di SQL Editor, sesuaikan seperlunya).
-- Skema 4 tabel Anda TIDAK diubah; file ini hanya soal kompatibilitas login Firebase & RLS.

-- 1) Login memakai Firebase, bukan Supabase Auth. Jika profiles.id punya foreign key ke auth.users
--    (template bawaan Supabase), insert profil akan gagal. Cek nama constraint-nya lalu hapus:
--      select conname from pg_constraint where conrelid = 'public.profiles'::regclass and contype = 'f';
--      alter table public.profiles drop constraint profiles_id_fkey;   -- ganti sesuai hasil query

-- 2) Aplikasi (APK) memakai kunci ANON dan Firebase token TIDAK dikenali Supabase, sehingga untuk
--    saat ini Supabase melihat semua klien sebagai role `anon`. Jika RLS aktif, beri izin minimal:
--    !!! MODE DEMO/UJI COBA: siapa pun yang punya kunci anon (ada di dalam APK) dapat menulis ke
--    !!! tabel ini dan membaca cattle & predictions. Untuk produksi lihat catatan di README backend.
alter table public.profiles    enable row level security;
alter table public.cattle      enable row level security;
alter table public.daily_logs  enable row level security;
alter table public.predictions enable row level security;

create policy "demo anon insert profiles"   on public.profiles    for insert to anon with check (true);
create policy "demo anon insert cattle"     on public.cattle      for insert to anon with check (true);
create policy "demo anon select cattle"     on public.cattle      for select to anon using (true);   -- perlu utk return=representation
create policy "demo anon insert daily_logs" on public.daily_logs  for insert to anon with check (true);
create policy "demo anon select predictions" on public.predictions for select to anon using (true);

-- Backend memakai service_role key sehingga melewati RLS (tidak butuh policy).

-- 3) (Opsional) mencegah log ganda untuk sapi & tanggal yang sama - backend sudah menangani duplikat,
--    jadi ini hanya kerapian data:
-- create unique index if not exists daily_logs_cattle_tanggal_uq on public.daily_logs (cattle_id, tanggal);
