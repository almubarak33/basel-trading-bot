# Backtesting

Replays the trading loop over historical minute bars so strategy changes can be
measured instead of guessed.

## Why it drives the production code

The replay calls the same functions the live bot calls — `build_candidate`,
`assemble_candidates`, `enrich_candidate`, `ArmingTracker`, `evaluate_exit`,
`position_size`, `compute_regime`. Only the clock, the order fills, and the
account are simulated. A parallel reimplementation would drift from the live
engine and quietly stop measuring the thing being shipped.

## Running it

```bash
# No API keys needed — validates the harness on generated data.
python -m app.backtest.cli --synthetic 5 --set min_score=70 --set min_rvol=1.0

# Real history (requires ALPACA_API_KEY / ALPACA_API_SECRET).
python -m app.backtest.cli \
  --start 2024-01-02 --end 2024-03-28 \
  --symbols-file universe.txt \
  --save data/q1.json --json results/q1.json

# Re-run instantly from saved bars, no re-download.
python -m app.backtest.cli --load data/q1.json
```

`universe.txt` is one symbol per line. Choose it carefully — see *Survivorship*
below.

### Useful flags

| Flag | Effect |
| --- | --- |
| `--set KEY=VALUE` | Override any `Settings` field, e.g. `--set min_score=80`. Repeatable. |
| `--legacy-risk-assumption` | Measure R against a flat 1.5% of entry, as the manager did before it read the stop from the broker. |
| `--legacy-screener-change` | Hardcode most-actives day change to `0`, as the scanner did before it derived the real value. |
| `--json PATH` | Write the full summary for diffing between runs. |

Defaults reproduce current live behaviour, so a baseline run measures the bot as
it actually is. The two `--legacy-*` flags reproduce defects that have since
been fixed, for measuring what the fix was worth.

`--legacy-screener-change` only bites when the universe is large enough that the
top-N gainers cut actually excludes something — with a handful of symbols every
riser makes the cut and the flag changes nothing.

## What the report tells you

Win rate, expectancy in R, profit factor, max drawdown, Sharpe, fill rate, and
breakdowns by exit reason, confidence grade, and entry hour. The reject-reason
counts show which filter is doing the gatekeeping — usually the fastest route to
understanding why a parameter change did nothing.

## Modelling assumptions

These are choices, not measurements. Read results with them in mind:

- **Spreads are estimated.** Minute bars carry no quotes, so the spread filter is
  fed `(tick_size × spread_ticks) / price`. This is the least faithful part of
  the replay.
- **Fills come from OHLC only.** A buy limit fills when the bar's low reaches it;
  sub-minute price paths are invisible.
- **No bar both opens and closes a trade.** Positions are managed from the bar
  after the fill.
- **Stop before target** when one bar spans both, which is the conservative read.
- **Stops pay slippage** (`stop_slippage_bps`); limit exits do not.
- **The screener is reconstructed** from your supplied universe by ranking on
  intraday change and cumulative volume. Alpaca's live movers endpoint has no
  historical equivalent, so this approximates *which* symbols the bot would have
  seen.
- **Regular session only.** Extended-hours bars are dropped, so backtested VWAP
  starts at 09:30. The live bot passes Alpaca's raw window through, which can
  include pre-market prints.
- **Positions are flattened at 16:00.** The live bot has no such rule.

## Guarding against lookahead

Every scan is built from a bisect over closed bars only, and the day's `%` change
is measured against the *previous* session's daily close, never the current
close. The 20-day volume average that RVOL depends on uses sessions strictly
before the one being traded. `tests/test_universe.py` covers each of these.

## Survivorship

The universe is whatever you pass in. Building it from today's liquid names
imports a large survivorship bias — the delisted and the collapsed are exactly
what a low-priced momentum strategy runs into. For a defensible result, source
the symbol list from a point-in-time constituent snapshot.

## Tests

```bash
pytest
```
