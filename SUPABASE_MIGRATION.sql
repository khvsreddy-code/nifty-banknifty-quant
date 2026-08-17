-- Run this ONCE in Supabase SQL Editor after creating the original tables.
-- It adds idempotency keys used by the one-minute cloud recorder.

alter table market_snapshots
    add column if not exists capture_minute timestamptz;

alter table option_chain_snapshots
    add column if not exists capture_minute timestamptz;

alter table level_snapshots
    add column if not exists capture_minute timestamptz;

alter table prediction_snapshots
    add column if not exists capture_minute timestamptz;

update market_snapshots
set capture_minute = date_trunc('minute', captured_at)
where capture_minute is null;

update option_chain_snapshots
set capture_minute = date_trunc('minute', captured_at)
where capture_minute is null;

update level_snapshots
set capture_minute = date_trunc('minute', captured_at)
where capture_minute is null;

update prediction_snapshots
set capture_minute = date_trunc('minute', captured_at)
where capture_minute is null;

create unique index if not exists market_snapshots_minute_uq
on market_snapshots(index_name, capture_minute);

create unique index if not exists option_chain_snapshots_minute_uq
on option_chain_snapshots(index_name, capture_minute, expiry, strike);

create unique index if not exists level_snapshots_minute_uq
on level_snapshots(index_name, capture_minute);

create unique index if not exists prediction_snapshots_minute_uq
on prediction_snapshots(index_name, capture_minute);

-- RLS: the Streamlit app uses the publishable/anon key.
-- These policies allow inserts only; they do NOT expose table reads to anon.
alter table market_snapshots enable row level security;
alter table option_chain_snapshots enable row level security;
alter table level_snapshots enable row level security;
alter table prediction_snapshots enable row level security;

drop policy if exists "market snapshots insert" on market_snapshots;
create policy "market snapshots insert"
on market_snapshots for insert to anon
with check (true);

drop policy if exists "option chain snapshots insert" on option_chain_snapshots;
create policy "option chain snapshots insert"
on option_chain_snapshots for insert to anon
with check (true);

drop policy if exists "level snapshots insert" on level_snapshots;
create policy "level snapshots insert"
on level_snapshots for insert to anon
with check (true);

drop policy if exists "prediction snapshots insert" on prediction_snapshots;
create policy "prediction snapshots insert"
on prediction_snapshots for insert to anon
with check (true);
