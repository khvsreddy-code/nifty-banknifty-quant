# OI Pulse Pro V11 — true browser live chart

## What changed
- Sidebar is now **Upstox access token only**.
- Removed the visible analytics pulse control.
- Removed event-risk note, max-risk budget, and index-weight upload controls from the sidebar.
- Lightweight Charts is pinned to **5.2.0**.
- The chart uses the v5.2 `addSeries()` API and realtime `ISeriesApi.update()` path.
- The chart is a light/white TradingView-style workspace.
- Browser live prices no longer expose the Upstox access token.
- Live ticks are delivered from the server-side Upstox V3 stream into `live_ticks`.
- The browser subscribes to Supabase Realtime and has a 1-second REST fallback.
- Existing OI/levels/research/backtest/validation logic is retained.
- Supabase `live_ticks` realtime publication is already included in `SUPABASE_FULL_CAPTURE_MIGRATION.sql`.

## Supabase
The browser uses `SUPABASE_URL` and `SUPABASE_KEY` from Streamlit Secrets. The included SQL grants the `anon` role SELECT/INSERT access to `live_ticks` and adds the table to `supabase_realtime`.

For production, `SUPABASE_KEY` exposed to the browser should be the public/anon key, never a service-role key.

## Important
The live chart is intentionally outside the Streamlit analytics fragment. A tick calls Lightweight Charts `series.update()` instead of rebuilding the chart or calling `setData()`.

The Upstox access token stays server-side for the Upstox websocket and REST fallback.


## V11.1 — no Streamlit polling / multi-asset live workspace

- Removed the `st.fragment(run_every=...)` analytics loop. The app no longer
  periodically reruns itself.
- The Upstox V3 websocket is started explicitly by the chart bootstrap and is
  process-lifetime. It publishes at most one browser tick per second to
  `live_ticks`.
- The browser receives those ticks through Supabase Realtime (with a 1-second
  REST fallback) and calls Lightweight Charts 5.2 `series.update()`; it does
  not call `setData()` for realtime ticks.
- Added a Markets explorer for Stocks, NSE/BSE Futures, Options and MCX futures
  using Upstox's Instrument Search API.
- Generic instruments use their stable Upstox `instrument_key` as the
  `live_ticks.symbol`, so multiple asset types do not collide.
- The sidebar remains access-token only.
