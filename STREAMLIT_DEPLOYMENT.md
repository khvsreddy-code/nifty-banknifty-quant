# Streamlit deployment

Deploy **only `app.py`**. Do not upload credentials as files or commit them to the repository.

1. In the Supabase SQL Editor for project `wpbxznfflvhzfhbcdxqb`, run `SUPABASE_STREAMLIT_SETUP.sql` once.
2. In Streamlit Cloud, open **App settings → Secrets** and add this structure, filling values from your own dashboard:

```toml
UPSTOX_ACCESS_TOKEN = "..."
SUPABASE_URL = "https://wpbxznfflvhzfhbcdxqb.supabase.co"
SUPABASE_ANON_KEY = "your publishable anon key"
SUPABASE_SERVICE_ROLE_KEY = "your service role key"
```

`SUPABASE_SERVICE_ROLE_KEY` is server-only and is never sent into the chart iframe. `SUPABASE_ANON_KEY` is used only for browser Realtime/read access to the `live_ticks` bridge.

The application writes one atomic `tradingcore_snapshots` record for each index/minute during NSE market hours, plus throttled `live_ticks` and session `price_candles`. A Supabase failure cannot stop the live candle chart.
