V8 — Index Universe + Trader UI
- Dynamic NSE/BSE index selector sourced from Upstox BOD index instruments, with sidebar search fallback.
- Automatically upgrades derivative-enabled indices to the full OI/EOS/EOR terminal; index-only fallback for indices without a usable option chain.
- Added last-refresh change cards, nearest meaningful level distance cards, setup timing/state strip, and clearer coverage labels.
- Preserved the OI Battlefield isolated visual style and heatmap exactly; no styling changes were made inside that component.
- Kept NIFTY/BANK constituent impact analysis only where maintained weight maps exist; other indices never receive fabricated weights.

# V4 Fixed

## Fixes
- Fixed the NIFTY vs BANK NIFTY cross-index `TypeError` caused by reusing `b` for both Bank Nifty LTP and a Streamlit column.
- Renamed cross-index variables to explicit names (`nifty_ltp`, `bank_ltp`, etc.).
- Added a guarded warning so temporary cross-index API failures do not crash the whole dashboard.
- Recompiled the full app successfully with Python syntax checking.


## Trader-first UI rebuild
- Reorganized the live index view around market state, bias, key levels, next-move scenario, last 5-minute pulse, OI battlefield, and level health.
- Moved raw chain/Greeks/diagnostics into expandable Quant Details.
- Replaced the dense heatmap presentation with a compact strike battlefield focused on the nearest decision strikes.
- Added plain-language explanations and confirmation checklists.

### V6 — Trader-first UI upgrade
- Reworked the live index header into a compact decision board.
- Surfaced VWAP, opening range, session H/L, futures basis, PCR, VIX, 5m and 15m context.
- Kept the visual OI battlefield and restored it as a primary decision section.
- Promoted index-driver/contributor analysis into the main workflow.
- Kept Quant Details for raw chain, Greeks and diagnostics.
- Preserved existing analytics, research, recorder and backtest functions.


## V7 Intraday Intelligence
- Added setup-specific playbook engine: EOR/EOS breakout, failure, VWAP trend/pullback, range/wait.
- Added no-trade guard based on confirmation and risk/reward.
- Added level lifecycle: active, weakening, broken/above, broken/below.
- Added ATM liquidity/spread warning using option bid/ask data.
- Added OI-weighted gamma/IV pressure view.
- Added multi-timeframe alignment using live 5m/15m returns.
- Added trader-facing confirmation matrix and trigger/target/invalidation panel.

## OI level-selection refinement — high-OI walls only
- Reworked support/resistance selection to stop forcing the nearest strike into the level map.
- Levels now require statistically meaningful local OI evidence (OI percentile + relative OI + local-peak test).
- Added proximity weighting so a strong OI wall near spot outranks a distant OI extreme.
- Added a small ΔOI contribution without allowing short-term noise to create a level by itself.
- Removed the adjacent-strike assumption for EOS-1/EOR+1: extensions now use the next surviving strong OI wall when available.
- Chart lines, nearest meaningful levels, lifecycle state, and scenario level references continue to consume the same `calculate_levels()` output.


### High-OI level/chart correction
- Prioritized the nearest strong OI wall for EOS/EOR.
- Prevented distant high-OI strikes from hiding a meaningful nearby support/resistance.
- Synced chart lines with the filtered OI-wall arrays.
- Deduplicated chart level lines.

## V8.1 — intraday evidence improvements
- Added session-phase context (opening volatility, discovery/breakout, midday range, afternoon repositioning, closing flow).
- Added OI wall persistence/lifetime and test/reaction tracking.
- Added OI migration detection between refreshes.
- Added price/OI interaction classification (build, short covering, unwinding, mixed).
- Added multi-pulse break/retest monitoring to reduce single-tick false-break calls.
- Added active level health/invalidation state based on OI retention, strength and persistence.
- Added empirical score calibration and false-break statistics to the validation panel when enough observations exist.
- Existing level/chart engine remains the source of truth; no new random levels are generated.
