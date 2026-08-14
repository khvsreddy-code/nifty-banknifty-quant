# Nifty Quant Flow — fixed version

Replace `app.py` and `requirements.txt` in the GitHub repository with these files.

## What was fixed

The previous crash came from using the wrong Instrument Search URL. Current Upstox documentation specifies Instrument Search at `/v2/instruments/search`; the app now uses that endpoint with the documented filters. The market quote and historical candle calls use the V3 endpoints and formats documented by Upstox.

The app also:
- uses Streamlit Secrets for the Upstox token;
- uses V3 OHLC with `interval=1d`;
- uses V3 historical candles with `days/1`;
- handles missing quotes/history;
- shows positive/negative constituent pulls;
- calculates breadth, net pressure and a volatility-based expected move;
- exports CSV.

## Streamlit Secrets

In Streamlit Cloud, open your app's Settings -> Secrets and add:

```toml
UPSTOX_ACCESS_TOKEN = "YOUR_TOKEN"
```

Do NOT commit the real token to GitHub.

If available in your Upstox account, an Analytics Token is designed for read-only market-data/analytics use.

## Weight CSV

For exact full-index analysis, upload a CSV with:

```csv
symbol,weight_pct
HDFCBANK,10.27
ICICIBANK,9.22
RELIANCE,7.92
...
```

The built-in weights are only the top constituents published in the July 31, 2026 Nifty factsheets; they are intentionally not presented as a complete weight file.

## Official docs

Upstox Instrument Search:
https://upstox.com/developer/api-documentation/instrument-search/

Upstox V3 Historical Candles:
https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/

Upstox V3 OHLC:
https://upstox.com/developer/api-documentation/get-market-quote-ohlc-v3/

Upstox Instruments:
https://upstox.com/developer/api-documentation/instruments/

NSE Nifty 50:
https://www.niftyindices.com/indices/equity/broad-based-indices/nifty--50

NSE Nifty Bank:
https://www.niftyindices.com/indices/equity/sectoral-indices/nifty-bank
