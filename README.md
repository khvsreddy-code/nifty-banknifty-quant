# Nifty Quant Pulse v1

This is the first mathematically explicit trading dashboard build.

## What it does

- Live Nifty 50 and Nifty Bank LTP.
- Automatic refresh (default 5 seconds).
- Nifty/Bank Nifty option chain from Upstox.
- Current OI and previous OI.
- CE/PE premium change.
- Intraday stock contribution: `weight × stock return / 100`.
- EOS/EOR-style independent reversal map.
- EOS-1 and EOR+1 extension zones.
- Support/resistance scores.
- OI pulse around ATM.
- Breadth.
- Next-move scenario engine.
- Narrow-rally / broad-rally information through breadth and constituent impact.
- LTP option calculator.

## Important math note

EOS/EOR here are **our own independent calculations**, not a reproduction of Dr. Vinay Prakash Tiwari's proprietary formulas.

The level engine uses:

- 55% nearby strike OI concentration
- 30% fresh writing evidence (positive OI change + falling option premium)
- 15% proximity to spot

The strongest PE-supported strike below spot is EOS.
The strongest CE-supported strike above spot is EOR.
EOS-1/EOR+1 are one index strike step beyond.

The next-move score uses:

- 35% stock-flow pressure
- 20% breadth
- 30% options structure
- 15% spot location relative to EOS/EOR

This is a transparent scenario model, not a guaranteed prediction.

## Token

Streamlit Cloud -> Settings -> Secrets:

```toml
UPSTOX_ACCESS_TOKEN = "YOUR_TOKEN"
```

Do not put the real token in GitHub.

## Full stock coverage

For exact current index pressure, upload a CSV for each index:

```csv
symbol,weight_pct
HDFCBANK,10.56
ICICIBANK,8.32
...
```

Without uploads, the app uses reference top constituents from recent NSE Indices factsheets and displays the coverage percentage.

## Upstox endpoints used

- V2 Instrument Search
- V3 LTP
- V2 Put/Call Option Chain

The code deliberately uses Upstox `instrument_key` values.

## Production upgrade

For true tick-by-tick delivery, move the live quote layer to Upstox V3 WebSocket. The current build uses short REST caching so the math and dashboard are easy to validate first.
