# Nifty / Bank Nifty Weighted Flow Engine

A Streamlit research UI using Upstox V3 market data.

## What it does

1. Reads Nifty 50 or Nifty Bank constituents and their index weights.
2. Resolves Upstox instrument keys.
3. Pulls daily historical candles from Upstox V3.
4. Calculates each stock's return.
5. Calculates approximate index pull:
   `contribution % = index weight % × stock return % / 100`
6. Sorts stocks by positive/negative contribution.
7. Produces a transparent directional bias.
8. Estimates a volatility-based expected move for 1 or 5 trading days.

## Install

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
streamlit run app.py
```

## Upstox

Create an Upstox API app and obtain an access token using their OAuth flow. Paste the token into the sidebar.

The app uses:
- V3 Historical Candle Data
- V3 OHLC Quotes
- V3 Instrument Search

## Weightage

For live/production use, upload the latest NSE weightage CSV with exactly:

```csv
symbol,weight_pct
HDFCBANK,10.73
RELIANCE,8.78
...
```

Do not treat the included starter weights as current full-index weights; they are only a demo seed.

## Important model limitation

This does not claim to predict the future with certainty. It measures current weighted pressure and estimates a range from recent volatility. A stronger version can add:
- live WebSocket ticks
- futures basis
- options IV / Greeks
- advance/decline breadth
- sector contribution
- rolling regression/beta
- event/news features
- calibrated backtesting and probability scores
