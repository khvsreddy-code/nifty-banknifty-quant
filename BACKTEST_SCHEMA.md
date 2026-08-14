# Backtest CSV schema

Minimum:

- `model`: signed model score at signal time
- `future_return`: realized return over the selected horizon

Recommended:

- `timestamp`
- `index`
- `spot`
- `eos`
- `eor`
- `model`
- `future_return`
- `mfe`
- `mae`
- `false_break` (0/1)
- `cost_pct`
- `regime`
- `expiry_day` (0/1)

For Feature Lab add numeric columns matching the feature names in `FEATURE_REGISTRY` and `target_return_30m`.
