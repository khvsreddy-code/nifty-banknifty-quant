-- TradingCoreOS Phase 3: OI wall behavior and reaction research.
-- Run once in Supabase SQL Editor after the Phase 1A migration.

create table if not exists oi_wall_events (
  event_id text primary key,
  observed_at timestamptz not null,
  trading_date date not null,
  index_name text not null,
  expiry text,
  side text not null check (side in ('support', 'resistance')),
  structural_strike numeric not null,
  calculated_level numeric not null,
  spot numeric not null,
  behavior_score numeric not null,
  state text not null,
  persistence_pulses integer not null default 0,
  test_count integer not null default 0,
  reaction_count integer not null default 0,
  distance_points numeric not null,
  regime text not null default 'UNKNOWN',
  phase text not null default 'UNKNOWN',
  wall_snapshot jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists oi_wall_events_index_time_idx
  on oi_wall_events (index_name, observed_at desc);
create index if not exists oi_wall_events_side_behavior_idx
  on oi_wall_events (index_name, side, behavior_score);

create table if not exists oi_wall_outcomes (
  event_id text not null references oi_wall_events(event_id) on delete cascade,
  horizon_minutes integer not null check (horizon_minutes in (5, 15, 30, 60)),
  settled_at timestamptz not null,
  exit_price numeric not null,
  outcome text not null check (outcome in ('HOLD_REJECTION', 'BREAK_CLOSE_SAMPLED', 'NO_REACTION')),
  move_away_points numeric not null,
  max_favorable_points numeric,
  max_adverse_points numeric,
  observation_count integer not null,
  created_at timestamptz not null default now(),
  primary key (event_id, horizon_minutes)
);

-- Safe upgrade path if a development build already created these tables.
alter table oi_wall_events
  add column if not exists observed_at timestamptz,
  add column if not exists trading_date date,
  add column if not exists index_name text,
  add column if not exists expiry text,
  add column if not exists side text,
  add column if not exists structural_strike numeric,
  add column if not exists calculated_level numeric,
  add column if not exists spot numeric,
  add column if not exists behavior_score numeric,
  add column if not exists state text,
  add column if not exists persistence_pulses integer default 0,
  add column if not exists test_count integer default 0,
  add column if not exists reaction_count integer default 0,
  add column if not exists distance_points numeric,
  add column if not exists regime text,
  add column if not exists phase text,
  add column if not exists wall_snapshot jsonb default '{}'::jsonb,
  add column if not exists created_at timestamptz default now();

alter table oi_wall_outcomes
  add column if not exists settled_at timestamptz,
  add column if not exists exit_price numeric,
  add column if not exists outcome text,
  add column if not exists move_away_points numeric,
  add column if not exists max_favorable_points numeric,
  add column if not exists max_adverse_points numeric,
  add column if not exists observation_count integer,
  add column if not exists created_at timestamptz default now();

create unique index if not exists oi_wall_outcomes_event_horizon_uq
  on oi_wall_outcomes (event_id, horizon_minutes);

create index if not exists oi_wall_outcomes_settled_idx
  on oi_wall_outcomes (settled_at desc);

alter table oi_wall_events enable row level security;
alter table oi_wall_outcomes enable row level security;

comment on table oi_wall_events is
  'Phase 3 OI wall state transitions. Calculated levels, not round strikes, are the actionable reference.';
comment on table oi_wall_outcomes is
  'Wall reaction labels from captured-minute prices. They do not replace the chart candle-close confirmation rule.';
