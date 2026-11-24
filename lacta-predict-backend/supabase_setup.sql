-- ============================================================================
-- Lacta-Predict - Skema & penyesuaian Supabase (jalankan di SQL Editor).
-- Disesuaikan dengan dataset lacta_predict_dataset_clean_v2.csv.
--
-- Bagian A : buat tabel dari nol (instalasi baru).
-- Bagian B : migrasi kolom untuk instalasi LAMA (dari skema jumlah_pakan/volume_susu_aktual).
-- Bagian C : RLS (mode uji coba) + login Firebase.
-- Jalankan A ATAU B sesuai kondisi, lalu selalu jalankan C.
-- ============================================================================

-- ====================== BAGIAN A : INSTALASI BARU ==========================
create extension if not exists "pgcrypto";   -- untuk gen_random_uuid()

-- Peternak (dipetakan dari UID Firebase -> uuid v5 deterministik di app & backend).
create table if not exists public.profiles (
  id          uuid primary key,
  full_name   text,
  role        text default 'peternak',
  created_at  timestamptz not null default now()
);

-- Sapi. Atribut genetik/umur/tahap dipakai sebagai fitur model.
create table if not exists public.cattle (
  id             uuid primary key default gen_random_uuid(),
  farmer_id      uuid references public.profiles(id) on delete cascade,
  tag_nomor_sapi text,
  genetic_group  text default 'HF50',          -- Local | HF50 | HF62.5 | HF75 | HF87.5
  usia           numeric,                       -- umur (BULAN)
  tahap_laktasi  text default 'Tengah',         -- Awal | Tengah | Akhir
  created_at     timestamptz not null default now()
);

-- Log harian = satu snapshot input prediksi (produksi sebelumnya + pakan + iklim mikro).
create table if not exists public.daily_logs (
  id                 uuid primary key default gen_random_uuid(),
  cattle_id          uuid references public.cattle(id) on delete cascade,
  tanggal            date not null default current_date,
  prev_milk_yield_l  numeric,                   -- produksi susu hari sebelumnya (L)
  dmi_kg             numeric,                   -- konsumsi bahan kering / pakan (kg)
  suhu_c             numeric,                   -- suhu kandang (°C)
  kelembapan_pct     numeric,                   -- kelembaban relatif (%)
  created_at         timestamptz not null default now()
);

-- Hasil prediksi AI (3 baris per sapi per panggilan: H+1, H+2, H+3).
create table if not exists public.predictions (
  id                   uuid primary key default gen_random_uuid(),
  cattle_id            uuid references public.cattle(id) on delete cascade,
  tanggal_prediksi     date not null,
  prediksi_volume_susu numeric,                 -- milk_yield_l prediksi (L)
  segmen_performa      text,                    -- Performa Rendah (Prioritas) | Rata-rata | Tinggi
  peringatan_dini      boolean default false,   -- set PERINGATAN_FORMAT=text bila kolom ini bertipe text
  alasan_prediksi      text,
  created_at           timestamptz not null default now()
);

create index if not exists daily_logs_cattle_idx   on public.daily_logs (cattle_id, tanggal desc, created_at desc);
create index if not exists predictions_cattle_idx  on public.predictions (cattle_id, created_at desc);

-- ====================== BAGIAN B : MIGRASI INSTALASI LAMA ==================
-- Jalankan HANYA jika tabel Anda masih memakai kolom lama (jumlah_pakan, suhu_kandang,
-- volume_susu_aktual, jenis_pakan). Aman dijalankan berulang (if not exists / if exists).

-- cattle: tambah kolom genetik (umur & tahap sudah ada di skema lama).
alter table public.cattle    add column if not exists genetic_group text default 'HF50';

-- daily_logs: tambah kolom baru...
alter table public.daily_logs add column if not exists prev_milk_yield_l numeric;
alter table public.daily_logs add column if not exists dmi_kg            numeric;
alter table public.daily_logs add column if not exists suhu_c            numeric;
alter table public.daily_logs add column if not exists kelembapan_pct    numeric;

-- ...lalu pindahkan data lama ke kolom baru (jalankan sekali; sesuaikan bila perlu).
update public.daily_logs set prev_milk_yield_l = coalesce(prev_milk_yield_l, volume_susu_aktual) where prev_milk_yield_l is null;
update public.daily_logs set dmi_kg            = coalesce(dmi_kg, jumlah_pakan)                   where dmi_kg is null;
update public.daily_logs set suhu_c            = coalesce(suhu_c, suhu_kandang)                   where suhu_c is null;
update public.daily_logs set kelembapan_pct    = coalesce(kelembapan_pct, 70)                     where kelembapan_pct is null;
-- Backend tetap bisa membaca kolom lama sebagai cadangan, jadi kolom lama boleh dibiarkan.

-- ====================== BAGIAN C : LOGIN FIREBASE + RLS ====================
-- 1) Login memakai Firebase, bukan Supabase Auth. Jika profiles.id punya foreign key ke auth.users
--    (template bawaan Supabase), insert profil akan gagal. Cek & hapus:
--      select conname from pg_constraint where conrelid = 'public.profiles'::regclass and contype = 'f';
--      alter table public.profiles drop constraint profiles_id_fkey;   -- ganti sesuai hasil query

-- 2) APK memakai kunci ANON; token Firebase tidak dikenali Supabase, jadi klien dilihat sebagai `anon`.
--    !!! MODE DEMO/UJI COBA: siapa pun yang punya kunci anon (ada di dalam APK) dapat menulis & membaca.
--    !!! Untuk produksi: aktifkan Third-party Auth (Firebase) di Supabase lalu perketat RLS per pemilik.
alter table public.profiles    enable row level security;
alter table public.cattle      enable row level security;
alter table public.daily_logs  enable row level security;
alter table public.predictions enable row level security;

drop policy if exists "demo anon insert profiles"    on public.profiles;
drop policy if exists "demo anon insert cattle"      on public.cattle;
drop policy if exists "demo anon select cattle"      on public.cattle;
drop policy if exists "demo anon insert daily_logs"  on public.daily_logs;
drop policy if exists "demo anon select predictions" on public.predictions;

create policy "demo anon insert profiles"    on public.profiles    for insert to anon with check (true);
create policy "demo anon insert cattle"      on public.cattle      for insert to anon with check (true);
create policy "demo anon select cattle"      on public.cattle      for select to anon using (true);   -- perlu utk return=representation
create policy "demo anon insert daily_logs"  on public.daily_logs  for insert to anon with check (true);
create policy "demo anon select predictions" on public.predictions for select to anon using (true);
-- Backend memakai service_role key sehingga melewati RLS (tidak butuh policy).

-- 3) (Opsional) cegah log ganda untuk sapi & tanggal yang sama:
-- create unique index if not exists daily_logs_cattle_tanggal_uq on public.daily_logs (cattle_id, tanggal);
