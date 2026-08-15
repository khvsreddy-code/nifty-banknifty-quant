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
