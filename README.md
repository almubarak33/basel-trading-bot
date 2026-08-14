# Basel Trader Mobile

Mobile-first PWA dashboard for a US momentum paper-trading bot.

## Architecture
- iPhone / Android: dashboard only.
- Cloud server: scanner, strategy, risk manager, execution, database.
- Broker: modular adapter; Alpaca Paper in v1.
- The bot continues running on the server even if the phone is locked or offline.

Shared decision logic is kept IO-free so the live engine and the backtester run
identical code: `strategy.py` (scoring and levels), `intelligence.py` (grading),
`arming.py` (two-stage confirmation), `exits.py` (management rules),
`indicators.py` (EMA/VWAP/regime), `session.py` (market clock).

## Safety
Paper only by default. `ENABLE_PAPER_ORDERS=false` prevents execution until explicitly enabled.

## Backtesting

```bash
pytest                                    # run the test suite
python -m app.backtest.cli --synthetic 5  # smoke-test the harness, no API keys
python -m app.backtest.cli --start 2024-01-02 --end 2024-03-28 --symbols-file universe.txt
```

See [docs/BACKTESTING.md](docs/BACKTESTING.md) for the modelling assumptions —
they matter for interpreting any result.

## Known gaps

Tracked, not yet fixed:

- The trade manager measures R against a flat 1.5%-of-entry assumption rather
  than the real entry stop, so its profit-protection and time-stop thresholds
  fire at the wrong distance. Backtest it with `--true-initial-risk`.
- The API has no authentication; anything that can reach the server can toggle
  auto-trading, submit orders, or flatten positions.
- Most-actives symbols that are not also gainers receive a hardcoded
  `change_pct=0`, which permanently fails `MIN_CHANGE_PCT` and makes that half of
  the screener unreachable. Backtest it with `--fix-screener-change`.
- `client_order_id` is derived from the symbol alone, so a second order for the
  same symbol collides with the first.
- Open-position limits count filled positions only, so working orders can push
  real exposure past `MAX_OPEN_POSITIONS`.
- No end-of-day flatten: a filled bracket can carry overnight after its day-only
  legs expire.
- Catalyst and insider feeds are stubs reporting `UNVERIFIED`.
