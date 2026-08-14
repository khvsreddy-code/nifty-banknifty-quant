# V4 — Evidence First

## Major additions

- Evidence-first feature governance: experimental features are visible but excluded from the primary live model until promoted by OOS testing.
- Futures discovery via Upstox Instrument Search.
- Spot/futures basis and futures OI/ΔOI when available from the live feed.
- Spot/options/futures agreement vs divergence.
- Multi-factor EOS/EOR confluence engine.
- Volume profile POC / VAH / VAL approximation.
- Absorption detection.
- Failed EOR breakout / EOS breakdown detection.
- Market regime engine.
- Opening-range and previous-day confluence.
- Execution / risk map with trigger, invalidation, target and underlying R/R.
- Official Upstox Change-in-OI, Max Pain and PCR cross-checks.
- Index futures Smartlist radar.
- Upstox V3 WebSocket integration with REST fallback.
- Feature Lab with expanding-window walk-forward tests.
- Conservative feature-promotion gate.
- Validation metrics: hit rate, Brier score, MFE, MAE, false-break rate, profit factor, drawdown and regime/expiry breakdowns.
- Stronger data-quality and no-edge guardrails.

## Policy change

The app now treats feature selection as a research problem. No feature is considered production-grade until it demonstrates useful out-of-sample evidence.
