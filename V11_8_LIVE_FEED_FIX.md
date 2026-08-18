# V11.8 live chart freeze fix

Run `app.py` as the only application entry point.

The candle series is now driven by the Upstox V3 WebSocket and is updated with `series.update()` without rebuilding the Streamlit component. Supabase remains an optional recorder/browser bridge; a Supabase `404` disables only that bridge for five minutes and reports that the chart recovery path is continuing.

Upstox REST quote calls are recovery-only. They are limited to one request every 2.5 seconds in the browser, three seconds in the server fallback, and use exponential backoff (up to 60 seconds) after a `429`. The browser honors Upstox's `Retry-After` response header when present.

To restore Supabase recording/realtime, execute `SUPABASE_FULL_CAPTURE_MIGRATION.sql` once in the SQL Editor of the same Supabase project configured by `SUPABASE_URL`. It creates the required `live_ticks` table and its Realtime publication. The dashboard and live candle updates continue when Supabase is unavailable.
