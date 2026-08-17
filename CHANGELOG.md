# V9.3 — true live chart architecture

- Moved the Lightweight Charts iframe **outside** the Streamlit analytics fragment so fragment pulses cannot delete/white-out the chart.
- Upstox V3 WebSocket now publishes a throttled `live_ticks` row (max 1/sec/index) directly to Supabase.
- Browser subscribes to Supabase Realtime and also polls the latest tick once per second as a fallback.
- Live ticks are aggregated into the selected candle timeframe (1m/3m/5m/15m/30m/1H) instead of creating incorrect 1-minute candles on a 5-minute chart.
- The existing analytics/OI engine continues to pulse independently.
- Existing OI, EOS/EOR, futures, regime, confluence, contributors, recorder and research features are preserved.

# Changelog

## V9.2 — Live chart + session archive
- Added persistent V3 WebSocket-first LTP path with REST fallback.
- Fixed zero/blank daily percentage change by falling back to the previous completed-session close when Upstox quote `cp` is missing.
- Chart iframe is no longer rebuilt on every analytics pulse; the browser chart stays mounted.
- Added Supabase Realtime live-tick bridge so the chart can update without Streamlit rebuilding the chart.
- Added today's complete 1-minute NIFTY 50 / BANK NIFTY price archive to Supabase.
- Added automatic post-market price archive plus a manual sidebar archive button.
- Existing one-minute OI/levels/prediction recorder remains intact.

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

## V9.1 — TradingView-style Lightweight Charts workspace
- Reworked the chart UI into a dark professional terminal layout.
- Added chart-type controls, range controls, indicator manager, settings and fullscreen.
- Added EMA/SMA, VWAP, Bollinger Bands, RSI, MACD, ATR, Stochastic, ADX, OBV and Supertrend pane options.
- Added drawing toolbar: horizontal line, trendline, ray, zone, vertical line, Fibonacci, undo and clear.
- Kept Upstox candles and the existing OI precision support/resistance engine as the chart data source.
- Kept Supabase recorder/full market capture unchanged.


## V10 Live Chart Fix (2026-08-17)
- Removed sidebar refresh/risk/event controls; sidebar now only asks for the Upstox access token.
- Upgraded the browser chart to Lightweight Charts 5.2.
- Chart is white and uses the v5 unified `addSeries` API.
- Added browser-side Upstox V3 LTP polling every second so candles update with `series.update()` without rebuilding the Streamlit chart.
- Kept Supabase live-tick fallback when Supabase is configured.
- Kept existing OI, levels, analytics, research and persistence code intact.
- Daily NIFTY/BANK NIFTY percentage baseline now uses the previous completed session close when available, preventing false `0.00%` readings.
