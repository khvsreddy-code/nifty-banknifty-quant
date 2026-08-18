-- TradingCoreOS Phase 1A: immutable prediction evidence and outcome labels.
-- Run this ONCE in the Supabase SQL Editor after SUPABASE_STREAMLIT_SETUP.sql.
-- The Streamlit server writes with SUPABASE_SERVICE_ROLE_KEY; no browser access
-- is granted to these research tables.

create table if not exists prediction_events (
  event_id text primary key,
  entry_time timestamptz not null,
  trading_date date not null,
  index_name text not null,
  expiry text,
  entry_price numeric not null,
  direction text not null,
  evidence_score numeric,
  target_1 numeric,
  target_2 numeric,
  stop_level numeric,
  regime text not null default 'UNKNOWN',
  phase text not null default 'UNKNOWN',
  state_fingerprint text not null,
  feature_snapshot jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists prediction_events_index_time_idx
  on prediction_events (index_name, entry_time desc);
create index if not exists prediction_events_date_idx
  on prediction_events (trading_date, index_name);

create table if not exists prediction_outcomes (
  event_id text not null references prediction_events(event_id) on delete cascade,
  horizon_minutes integer not null check (horizon_minutes in (5, 15, 30, 60)),
  settled_at timestamptz not null,
  exit_price numeric not null,
  raw_return_pct numeric not null,
  directional_return_pct numeric,
  mfe_pct_close_sampled numeric,
  mae_pct_close_sampled numeric,
  direction_correct boolean,
  target_1_hit boolean,
  target_2_hit boolean,
  stop_hit boolean,
  observation_count integer not null,
  created_at timestamptz not null default now(),
  primary key (event_id, horizon_minutes)
);

-- Upgrade safely when an older build already created either table. `create
-- table if not exists` alone cannot add the newer outcome fields.
alter table prediction_events
  add column if not exists event_id text,
  add column if not exists entry_time timestamptz,
  add column if not exists trading_date date,
  add column if not exists index_name text,
  add column if not exists expiry text,
  add column if not exists entry_price numeric,
  add column if not exists direction text,
  add column if not exists evidence_score numeric,
  add column if not exists target_1 numeric,
  add column if not exists target_2 numeric,
  add column if not exists stop_level numeric,
  add column if not exists regime text,
  add column if not exists phase text,
  add column if not exists state_fingerprint text,
  add column if not exists feature_snapshot jsonb default '{}'::jsonb,
  add column if not exists created_at timestamptz default now();

alter table prediction_outcomes
  add column if not exists event_id text,
  add column if not exists horizon_minutes integer,
  add column if not exists settled_at timestamptz,
  add column if not exists exit_price numeric,
  add column if not exists raw_return_pct numeric,
  add column if not exists directional_return_pct numeric,
  add column if not exists mfe_pct_close_sampled numeric,
  add column if not exists mae_pct_close_sampled numeric,
  add column if not exists direction_correct boolean,
  add column if not exists target_1_hit boolean,
  add column if not exists target_2_hit boolean,
  add column if not exists stop_hit boolean,
  add column if not exists observation_count integer,
  add column if not exists created_at timestamptz default now();

create unique index if not exists prediction_events_event_id_uq
  on prediction_events (event_id);

create unique index if not exists prediction_outcomes_event_horizon_uq
  on prediction_outcomes (event_id, horizon_minutes);

create index if not exists prediction_outcomes_settled_idx
  on prediction_outcomes (settled_at desc);

alter table prediction_events enable row level security;
alter table prediction_outcomes enable row level security;

comment on table prediction_events is
  'Phase 1A immutable feature context captured when a live market state changes.';
comment on table prediction_outcomes is
  'Forward labels from captured minute prices. MFE and MAE are close-sampled, not tick-level.';
