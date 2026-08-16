-- FULL CAPTURE MIGRATION
-- Run once in Supabase SQL Editor.
-- This extends the existing recorder tables so future research retains
-- every common Upstox quote field that our normalizer can expose.

alter table market_snapshots
  add column if not exists day_change numeric,
  add column if not exists day_change_pct numeric,
  add column if not exists futures_oi numeric,
  add column if not exists futures_change_oi numeric,
  add column if not exists futures_volume numeric,
  add column if not exists futures_vwap numeric,
  add column if not exists futures_basis_pct numeric;

alter table option_chain_snapshots
  add column if not exists ce_ltp_change numeric,
  add column if not exists ce_bid numeric,
  add column if not exists ce_ask numeric,
  add column if not exists ce_bid_qty numeric,
  add column if not exists ce_ask_qty numeric,
  add column if not exists ce_iv numeric,
  add column if not exists ce_delta numeric,
  add column if not exists ce_gamma numeric,
  add column if not exists ce_theta numeric,
  add column if not exists ce_vega numeric,
  add column if not exists pe_ltp_change numeric,
  add column if not exists pe_bid numeric,
  add column if not exists pe_ask numeric,
  add column if not exists pe_bid_qty numeric,
  add column if not exists pe_ask_qty numeric,
  add column if not exists pe_iv numeric,
  add column if not exists pe_delta numeric,
  add column if not exists pe_gamma numeric,
  add column if not exists pe_theta numeric,
  add column if not exists pe_vega numeric;

-- Make sure the minute idempotency keys from the first migration exist.
alter table market_snapshots add column if not exists capture_minute timestamptz;
alter table option_chain_snapshots add column if not exists capture_minute timestamptz;
alter table level_snapshots add column if not exists capture_minute timestamptz;
alter table prediction_snapshots add column if not exists capture_minute timestamptz;

update market_snapshots set capture_minute=date_trunc('minute',captured_at)
where capture_minute is null;
update option_chain_snapshots set capture_minute=date_trunc('minute',captured_at)
where capture_minute is null;
update level_snapshots set capture_minute=date_trunc('minute',captured_at)
where capture_minute is null;
update prediction_snapshots set capture_minute=date_trunc('minute',captured_at)
where capture_minute is null;

create unique index if not exists market_snapshots_minute_uq
on market_snapshots(index_name,capture_minute);
create unique index if not exists option_chain_snapshots_minute_uq
on option_chain_snapshots(index_name,capture_minute,expiry,strike);
create unique index if not exists level_snapshots_minute_uq
on level_snapshots(index_name,capture_minute);
create unique index if not exists prediction_snapshots_minute_uq
on prediction_snapshots(index_name,capture_minute);

-- Add insert policies if they do not already exist.
alter table market_snapshots enable row level security;
alter table option_chain_snapshots enable row level security;
alter table level_snapshots enable row level security;
alter table prediction_snapshots enable row level security;

drop policy if exists "market snapshots insert" on market_snapshots;
create policy "market snapshots insert" on market_snapshots
for insert to anon with check (true);

drop policy if exists "option chain snapshots insert" on option_chain_snapshots;
create policy "option chain snapshots insert" on option_chain_snapshots
for insert to anon with check (true);

drop policy if exists "level snapshots insert" on level_snapshots;
create policy "level snapshots insert" on level_snapshots
for insert to anon with check (true);

drop policy if exists "prediction snapshots insert" on prediction_snapshots;
create policy "prediction snapshots insert" on prediction_snapshots
for insert to anon with check (true);
