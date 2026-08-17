# OI Pulse Pro V10 — live-feed fix

Replace the repository's `app.py` with `oi_pulse_v10_app.py` from this package.

What this fixes:
- Upstox V3 websocket is cached for the Streamlit process instead of recreated on every analytics pulse.
- Adds a V3 `/market-quote/ltp` fallback every second when the websocket is silent for ~2.5 seconds.
- The Lightweight Charts iframe is no longer conditionally rendered once and then removed.
- Selected chart timeframe is passed correctly.
- Live candles update in-place and the chart follows the newest bar.
- Browser shows `STALE` if no live tick reaches it for 3 seconds.
- Existing OI, EOS/EOR, heatmap, contributors, futures, regime, research and validation features are preserved because the pinned V9.3 engine is executed after the patches.

Important:
- The live browser bridge still needs the existing Supabase configuration and `live_ticks` table/realtime setup already used by the project.
- Do not put your Upstox access token in this file. Keep it in Streamlit Secrets.
