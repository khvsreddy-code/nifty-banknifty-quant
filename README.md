# NIFTY / BANK NIFTY Intraday OI Terminal V4 — Evidence First

A Streamlit intraday decision-support terminal built around Upstox option-chain, market-information, futures, historical and V3 WebSocket data.

## Design principle

The terminal is **evidence-first**:

> A feature is not allowed to become a permanent live signal weight merely because it sounds useful.

The Feature Lab tests features out-of-sample. A feature must show measurable improvement before it is promoted into the primary live scenario score.

Recommended promotion criteria:

- out-of-sample hit-rate improvement
- no deterioration in probability calibration / Brier score
- lower false-break rate
- acceptable MFE / MAE
- acceptable drawdown
- realistic costs and slippage
- stability across regimes and expiry/non-expiry sessions

Until a feature passes the gate, it remains visible for research but has **zero weight** in the evidence-first primary model.

## Core live engine

### Options / OI
- CE / PE OI
- day ΔOI
- 5m / 15m OI shift
- OI acceleration
- option premium movement
- writing / long build / short covering / unwinding inference
- ATM pressure
- PCR
- IV skew
- gross gamma concentration proxy
- bid/ask spread and liquidity
- OI migration
- OI pressure heatmap

### EOS / EOR
- dynamic EOS
- dynamic EOR
- EOS-1
- EOR+1
- level strength
- level health
- level survival / reactions
- support/resistance migration
- level flip context
- multi-factor confluence score

### Futures confirmation
- nearest current-month NIFTY/BANK NIFTY future discovery
- futures LTP
- spot/futures basis
- futures OI / ΔOI when available through the live feed
- spot/options/futures agreement vs divergence

### Price structure
- session VWAP
- opening range high/low
- session high/low
- previous-day high/low/close
- 5m / 15m momentum
- approximate volume profile: POC / VAH / VAL
- absorption detection
- failed-breakout / failed-breakdown detection
- market regime state

### Volatility / expiry
- ATM straddle movement proxy
- India VIX
- ATM IV
- 25Δ IV skew proxy
- max pain
- expiry distance
- expiry-aware warnings

### Index flow
- NIFTY vs BANK NIFTY relative strength
- constituent breadth
- weighted stock contribution
- pushing vs dragging stocks
- broad vs narrow move
- optional current weight CSV

### Market intelligence
- Upstox official Change-in-OI cross-check
- official Max Pain cross-check
- official PCR cross-check
- Upstox index-futures Smartlist radar

### Live transport
- optional Upstox MarketDataStreamerV3 WebSocket
- REST remains the authoritative option-chain snapshot
- automatic fallback to REST if WebSocket is unavailable
- live feed targets index, future and key EOS/EOR option instruments

## Decision framework

The top-level logic is:

LIVE DATA → OI SHIFT → EOS/EOR → CONFLUENCE → PRICE CONFIRMATION → FUTURES CONFIRMATION → REGIME → SCENARIO → TRIGGER / TARGET / INVALIDATION

The model can explicitly return **RANGE / WAIT / NO EDGE**. It does not have to manufacture a directional call.

## Scenario model

The app displays:

- upside scenario weight
- range scenario weight
- downside scenario weight
- primary scenario
- trigger
- confirmation conditions
- target
- invalidation
- trade-quality score

These percentages are **scenario weights**, not historical win probabilities, until the model has been validated on a proper out-of-sample dataset.

## Research / backtesting

The Validation tab supports CSV-based evaluation with:

Required:

- `model`
- `future_return`

Optional:

- `mfe`
- `mae`
- `false_break`
- `cost_pct`
- `regime`
- `expiry_day`

The Feature Lab supports:

- expanding-window walk-forward evaluation
- baseline vs feature comparison
- OOS hit rate
- Brier score
- conservative promotion gate

The app deliberately does not invent historical accuracy.

## Upstox token

In Streamlit Cloud Secrets:

```toml
UPSTOX_ACCESS_TOKEN = "your_access_token"
```

No local Python installation is required for the deployed Streamlit app.

## Optional current index weights CSV

```text
symbol,weight_pct
HDFCBANK,10.73
RELIANCE,8.78
ICICIBANK,8.21
...
```

## Important modeling limitations

- EOS/EOR are an independent transparent model and do not reproduce a third-party proprietary formula.
- OI alone cannot prove whether every participant is long or short.
- Gross gamma concentration is not dealer GEX.
- ATM straddle is an implied-move proxy, not a guaranteed forecast.
- Volume profile is approximate because it is reconstructed from minute candles rather than exchange tick-by-tick volume-at-price.
- Futures OI is used only when the available live quote/feed exposes it.
- Event-risk notes are user-entered; the app does not claim to have a complete economic calendar.
- Backtests must avoid look-ahead and include realistic costs/slippage.

## Upstox APIs used / intended

- Option Contracts / Option Chain
- Market Information: OI, Change in OI, Max Pain, PCR
- Instrument Search for futures
- V3 Historical / Intraday candles
- V3 Market Data WebSocket
- V3 option Greeks / market quote data
- Smartlist futures
- Expired derivative endpoints for users whose Upstox plan provides them

## Disclaimer

This is market-data analytics and decision-support software, not a guarantee of trading profits and not personalized investment advice. Use paper trading and independent validation before relying on any signal.
