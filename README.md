# NIFTY / BANK NIFTY Intraday OI Terminal V3

A Streamlit intraday decision-support dashboard built around Upstox option-chain and market-data APIs.

## What V3 adds

- Dynamic EOS / EOR / EOS-1 / EOR+1 map
- CE/PE OI, day ΔOI and session 5m/15m OI shifts
- OI acceleration and migration
- Writing / long buildup / short covering / unwinding inference
- Level strength, health, survival and reaction tracking
- OI pressure heatmap
- ATM pressure
- PCR and PCR direction
- Max-pain reference
- 25-delta IV skew proxy
- ATM IV and straddle-implied move proxy
- Option bid/ask and liquidity/spread context
- Option gamma concentration proxy
- Session VWAP
- 5m / 15m momentum
- Opening-range high/low
- Session high/low
- Best-effort previous-day high/low/close
- India VIX context
- NIFTY vs BANK NIFTY relative strength
- Constituent stock contribution: pushing vs dragging the index
- Breadth / narrow-vs-broad move classification
- Three scenario states with trigger, confirmation, target and invalidation
- Market phase classification
- Data-quality score
- "What changed since the last pulse"
- Full readable option chain
- CSV snapshot download
- Session signal journal / validation panel

## Important modeling notes

EOS/EOR are an independent, transparent OI/LTP model. They do not reproduce a third-party proprietary formula.

The dashboard deliberately distinguishes:

- **Scenario weights** from historical win probabilities.
- **Gross gamma concentration** from dealer GEX. OI alone does not reveal whether each participant is long or short.
- **ATM straddle movement** from a guaranteed forecast.
- **Reference constituent weights** from current official index weights.

For exact index contribution calculations, upload a current official weight CSV:

```text
symbol,weight_pct
HDFCBANK,10.73
RELIANCE,8.78
ICICIBANK,8.21
...
```

## Upstox secret

In Streamlit Cloud Secrets:

```toml
UPSTOX_ACCESS_TOKEN = "your_access_token"
```

## Live refresh

V3 uses stable REST polling by default. Upstox V3 also provides a WebSocket market-data feed with live LTP, OI, option Greeks and depth; that is the natural next transport upgrade once the model has been validated in production. The current design keeps the calculation layer independent from the transport layer.

## Validation

Do not treat model percentages as guaranteed accuracy. Use the session journal and, where your Upstox access permits it, historical/expired derivative data to measure:

- hit rate
- average favorable excursion (MFE)
- average adverse excursion (MAE)
- expectancy after costs
- false-break rate
- level reaction rate
- performance by market phase and expiry day

This project is decision-support software, not a guarantee of profit or a substitute for risk management.
