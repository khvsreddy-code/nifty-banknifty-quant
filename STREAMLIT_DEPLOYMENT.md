# Streamlit deployment

Deploy **only `app.py`**. Do not upload credentials as files or commit them to the repository.

1. In the Supabase SQL Editor for project `wpbxznfflvhzfhbcdxqb`, run `SUPABASE_STREAMLIT_SETUP.sql` once.
2. Run `SUPABASE_PHASE_1A_OUTCOMES.sql` once. This creates the private prediction-event and 5/15/30/60-minute outcome tables.
3. Run `SUPABASE_PHASE_3_OI_WALLS.sql` once. This creates private OI-wall behavior and reaction-outcome tables.
4. In Streamlit Cloud, open **App settings → Secrets** and add this structure, filling values from your own dashboard:

```toml
UPSTOX_ACCESS_TOKEN = "..."
SUPABASE_URL = "https://wpbxznfflvhzfhbcdxqb.supabase.co"
SUPABASE_ANON_KEY = "your publishable anon key"
SUPABASE_SERVICE_ROLE_KEY = "your service role key"
```

`SUPABASE_SERVICE_ROLE_KEY` is server-only and is never sent into the chart iframe. `SUPABASE_ANON_KEY` is used only for browser Realtime/read access to the `live_ticks` bridge.

The application writes one atomic `tradingcore_snapshots` record for each index/minute during NSE market hours, plus throttled `live_ticks` and session `price_candles`. A Supabase failure cannot stop the live candle chart.

Phase 1A additionally records an immutable prediction event only when the live decision context changes, then labels it at 5, 15, 30 and 60 minutes using the captured minute-price series. MFE/MAE are explicitly close-sampled. If Streamlit is closed, unsettled same-day events are resolved when the app next runs and has the required captured minute records; a separate always-on worker is outside Phase 1A.

Phase 1B reads those private tables in **SIGNAL VALIDATION**. It shows observed results by horizon, score bucket, and market regime with conservative confidence intervals. It deliberately keeps current signal scores labelled as evidence scores until enough independent events from separate market days exist for calibration.

Phase 2 adds a main-dashboard multi-horizon decision map. It combines the current live state, calculated-level candle-close confirmation rule, and the Phase 1A evidence gate. A historical direction rate or move proxy appears only after at least 30 comparable settled events; until then the dashboard explicitly shows **NO TRADE / WAIT** and **COLLECTING EVIDENCE**.

Phase 3 records meaningful calculated OI-wall state transitions (strength, OI change/acceleration, premium response, liquidity, persistence, tests, distance, and migration context). It settles 5/15/30/60-minute hold/rejection, break, or no-reaction labels from captured-minute prices. Wall reaction rates remain hidden until 30 comparable records exist; this research label never changes the chart's candle-close break rule.

Phase 4 adds market context without introducing another external feed: constituent-weight breadth, sector leadership/drag, heavy-weight concentration, expiry proximity, nearby OI concentration, and a transparent compression/expansion read. Context is shown separately from direction and does not alter the live scenario score.

Phase 5 adds an option-expression lens. It links the underlying setup to an ATM reference option's live premium, bid/ask spread, IV, volume and OI change, while retaining **NO TRADE** whenever historical evidence, setup quality, or liquidity is insufficient. It does not place orders or provide personalized investment advice.

Phase 6 currently provides an ML readiness gate and normalized research export. It requires adequate independent state events, separate market days, settled labels, and regime coverage before a day-based walk-forward model should be trained. No live ML model is enabled before those safeguards pass.

Phase 7 adds signal freshness and decay. The core market scenario is not rewritten; instead, the execution layer measures how long a meaningful state has persisted and moves stale states to **NO TRADE / WAIT** until a direction, regime, phase, score-bucket, VWAP-side, or calculated-level transition refreshes it.

Phase 8 adds a nearby-chain positioning proxy and realized-versus-implied volatility context. The proxy combines available OI, gamma, five-minute OI flow and premium behavior, and is explicitly not dealer GEX or participant-position data. Realized volatility is annualized from the available one-minute index candles and compared with ATM IV.
