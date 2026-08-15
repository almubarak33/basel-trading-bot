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

## Aggressive scanner profile

The default `AGGRESSIVE` profile discovers the top 50 percentage movers plus
the top 100 most-active names, then analyzes up to 100 unique symbols every 30
seconds. It has no upper price or daily-move cap: prices start at `$0.01`,
discovery starts at `+1.5%`, and execution eligibility starts at `+3%`.

Two entry structures are supported: a controlled pullback/reclaim and an
early momentum breakout. In a weak broad market, standalone momentum remains
visible and receives a market-regime caution instead of being silently
discarded. Premarket and after-hours discovery runs from 04:00 to 20:00 New
York time, but automated orders still wait for the regular session.

Aggressive discovery does not remove execution protection. Orders remain Paper
only, require confirmation on two consecutive scans, risk `0.5%` of equity per
trade, cap a position at `20%` of equity, stop at four open positions, and halt
after a `2%` daily loss by default. Sub-dollar order prices retain four decimal
places.

## Interactive stock chart

Stock detail uses the vendored TradingView Lightweight Charts `5.2.0` build.
Candles and volume support crosshair inspection, mouse/touch pan, wheel/pinch
zoom, and one-day/five-day ranges. Completed daily closes appear below the
chart and the most recent prior close is drawn as a reference line.

## Runner exits

The displayed `2R` level is a performance reference, not a take-profit order.
Both automated and manual Paper entries submit an OTO order with a broker-native
protective stop and no fixed upside cap. After a position expands, the manager
tracks peak R and only takes runner profit after the configured giveback floor,
a price below EMA9, a falling latest bar, and two consecutive checks. Hard
stops, thesis failure, the daily risk guard, and end-of-day flattening remain
independent protections.

## End of day

Protective stop legs are day orders, so a position that survives to the bell
loses its stop and carries into the next session's opening gap unprotected. Two
rules prevent that:

- New entries stop `NO_ENTRY_MINUTES_BEFORE_CLOSE` (30) before the close.
- Everything still open is flattened `EOD_FLATTEN_MINUTES_BEFORE_CLOSE` (10)
  before the close, cancelling working orders with it.

Both are measured against Alpaca's `next_close`, not a hardcoded 16:00, so
early-close days — when the market shuts at 13:00 — flatten correctly rather
than never triggering. The entry cutoff must stay at or above the flatten
window, otherwise the bot opens trades it is about to close.

`EOD_FLATTEN_ENABLED=false` accepts overnight exposure with no protective
orders attached.

## Authentication

The API is closed by default — every route under `/api` requires a session
except `/api/i18n`, `/api/session`, `/api/login` and `/api/logout`.

Set `API_TOKEN` to a long random secret. If it is unset, one is generated at
startup and written to the server log, so the bot is never accidentally left
open; that token changes on every restart, which signs everyone out.

Sign in once from the dashboard and the browser holds an HttpOnly,
SameSite=Strict session cookie for 12 hours — the token itself is never
readable from JavaScript, and cross-site requests cannot ride the session.
Scripts can instead send `Authorization: Bearer $API_TOKEN`. Repeated failed
logins from one address lock that address out for 5 minutes.

Sessions live in memory, so restarting the process signs all clients out.

## Languages (English / العربية)

The dashboard ships in both languages and switches instantly from the toggle in
the header, with full RTL mirroring for Arabic. The choice persists in
`localStorage`.

The API is language-neutral. Analysis output carries stable codes plus
pre-formatted values — `reason_codes`, `reject_codes`, `bull_codes`,
`bear_codes`, `decision.thesis_code`, `market_brief.text_code` — and the client
renders them through the catalog served at `/api/i18n`. Switching language
therefore needs no refetch, and wording lives in exactly one place
(`app/messages.py`). The original English strings (`reasons`, `bear_case`,
`thesis`, …) are still in every payload for logs and existing consumers.

Adding a language means adding its key to `LANGUAGES` and one entry per code;
`tests/test_messages.py` fails on any code that is missing a translation, has
mismatched `{value}` placeholders, or was left as untranslated English.

Two details worth preserving when editing translations:

- **Units belong inside the value, not the template** (`"RVOL {value}"` with
  `value="3.20x"`). A `%` or `x` left in the template detaches from its number
  under Arabic bidi and renders as `%3.31`.
- **Numbers stay in Western digits** in both languages, and the client wraps
  every substituted value in a Unicode isolate so bidi cannot reorder it.

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

- Open-position limits count filled positions only, so working orders can push
  real exposure past `MAX_OPEN_POSITIONS`.
- Catalyst and insider feeds are stubs reporting `UNVERIFIED`.
- `static/demo.html` is a leftover standalone demo page and is still
  English-only; the live dashboard is `static/index.html`.
