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
York time. Execution is narrower than discovery: the regular session plus
after-hours until 20:00, never premarket — see below.

Aggressive discovery does not remove execution protection. Orders remain Paper
only, require a stable setup on two consecutive scans, risk `0.5%` of equity per
trade, cap a position at `20%` of equity, stop at four committed positions or
working entries, cap gross exposure at `60%` and portfolio heat at `2%`, and halt
after a `2%` daily loss by default. Order size is reduced to at most `5%` of the
latest one-minute volume and `0.1%` of 20-day average daily volume. Sub-dollar
order prices retain four decimal places.

## Professional execution controls

The autonomous path runs a broker-aware preflight immediately before submission:

- latest quote, trade and bar timestamps must be fresh and the NBBO/OHLC data
  must be internally consistent;
- filled positions and working buy orders both consume portfolio slots and gross
  exposure;
- every existing position must have a visible broker stop before more risk is
  added, and a position whose stop disappears is flattened after a short grace
  period;
- projected gross exposure, aggregate stop risk (portfolio heat), buying power
  buffer, and liquidity participation must all pass;
- automatic orders use a deterministic five-minute signal id, while the broker's
  open-order state prevents duplicate entries after a retry or restart.

Failed symbols remain visible for diagnosis but cannot become an automatic
order. See [docs/PROFESSIONAL_ENGINE.md](docs/PROFESSIONAL_ENGINE.md) for the
standards mapped to these controls and the remaining limitations.

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

## Measured: the market-regime entry block

Two six-month backtests over the same 125 sessions (2023-12-01 → 2024-05-31,
150 symbols), differing only in whether the bot may enter while SPY and QQQ are
both risk-off:

| | AGGRESSIVE (caution only) | **STANDARD (blocks entry)** |
|---|---|---|
| Total return | +13.05% | **+14.96%** |
| Max drawdown | 6.51% | **3.60%** |
| Sharpe / Sortino | 1.99 / 4.56 | **2.79 / 6.39** |
| Calmar | 4.31 | **9.01** |
| Expectancy | +0.068 R | **+0.089 R** |
| Win rate | 30.1% | **34.3%** |
| Trades | 960 | 830 |
| Alpha vs QQQ | −3.46% | **−1.55%** |

STANDARD wins on every metric, so it is the default. The gain is mostly in
risk, not return: roughly the same money for slightly over half the drawdown.

Two things this did *not* fix. The bot still loses to buying QQQ and holding,
by 1.55 points — the alpha hurdle in the report is honest about it. And
`market_regime_risk_off` still cost $6,804 across 348 trades, down only from
$8,656 across 448. Those trades were entered while the market was supportive
and exited after it turned, so the entry block cannot reach them; whether that
exit rule helps or hurts is what the `no-regime-exit` preset measures.

## Measured: the market-regime exit

Removing the regime exit (`REGIME_EXIT_ENABLED=false`) over the same 125
sessions, on top of the entry block:

| | **exit on (default)** | exit off |
|---|---|---|
| Total return | **+14.96%** | +13.42% |
| Profit factor | **1.28** | 1.23 |
| Win rate | 34.3% | 41.2% |
| Avg loss | **−0.48 R** | −0.62 R |
| Trades | 830 | 797 |

Switching it off does not save those positions — it changes how they die.
`market_regime_risk_off` (348 trades, −$6,804) disappears, and in its place
`stop_loss` goes from 44 trades to 152 (−$1,772 → −$6,309) and
`thesis_invalidated` from 113 to 206 (−$1,450 → −$4,032). That is about $7,100
of new losses replacing $6,800 of old ones, and the average loss grows from
−0.48 R to −0.62 R.

The higher win rate is misleading: the rule was cutting losers early, so
removing it leaves more trades alive to reach a full stop. It earns its keep,
and stays on.

## Circuit breakers

The only global guard used to be `MAX_DAILY_LOSS`, which compares equity against
the previous close. Across 44 backtested sessions it fired **zero times**, while
the `market_regime_risk_off` bucket alone lost $3,514 over 195 trades at −0.47 R
each — instalments too small to move a daily percentage.

`protections.py` adds three guards that read the trade record instead, taken in
spirit (not in code) from Freqtrade's `plugins/protections`:

| Guard | Trips when | Scope |
|---|---|---|
| `guard_losing_streak` | `GUARD_LOSS_TRADES` losing exits inside `GUARD_LOSS_LOOKBACK_MINUTES` | all trading |
| `guard_drawdown` | realised drawdown from the window's peak exceeds `GUARD_DRAWDOWN_PCT` of equity | all trading |
| `guard_weak_symbol` | one symbol is net-negative over `GUARD_SYMBOL_TRADES` recent trades | that symbol |

Two deliberate departures from the original. Freqtrade's StoplossGuard counts
only stop-type exits; here every losing exit counts, because the losses that
motivated this were regime and thesis exits rather than stops. And a lock is
measured from its first trigger — repeat triggers do not extend it — so a
stand-down has a predictable end.

Locks survive their triggering trades ageing out of the lookback window;
otherwise the cooling-off period would end exactly when it is needed. The module
is IO-free, so the live engine and the backtester run the identical rules, and
the run summary reports how many entries the guards blocked.

`PROTECTIONS_ENABLED=false` turns them off; the `no-protections` backtest preset
does the same for a single run.

## Extended session (after the bell)

`TRADE_AFTER_HOURS=true` lets the bot work 16:00–20:00 ET as well as the
regular session. `TRADE_PRE_MARKET` stays off, so nothing trades before 09:30.

This is not the regular session with longer hours. The broker accepts **only
plain limit day/gtc orders** outside 09:30–16:00 — bracket and OTO classes are
rejected, market orders are rejected, and so is `DELETE /v2/positions`. Three
consequences follow:

- An after-hours entry carries **no stop at the broker**. `soft_stops.py` holds
  the intended stop and the trade manager sells when price reaches it. That
  protection exists only while the process is running: a crash, a redeploy or a
  dropped connection leaves the position naked until the bot comes back.
- A regular-session position held past 16:00 loses its stop leg the same way —
  it is a day order. The manager copies every working broker stop into the same
  registry while the session is open, so the software stop takes over at the
  bell rather than the position going unguarded.
- Every extended-hours exit is a limit order priced `EXTENDED_MARKETABLE_PCT`
  (0.5%) through the last price, because after-hours spreads are wide and a
  passive limit would sit unfilled.

Liquidity after the bell is a fraction of the regular session and the screener
endpoints may return stale or empty data outside it, so extended-hours entries
may simply be rare.


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

With `TRADE_AFTER_HOURS=true` the day ends four hours later: the cutoff moves to
19:30 and the flatten to 19:50. A half-day still works out — a 13:00 bell means
a 17:00 extended close — because the four hours are added to the broker's own
`next_close` rather than to a fixed clock time. Once past 16:00 that field
already points at tomorrow, so the extended close is computed locally instead.

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
python -m app.backtest.cli --load data/history.json --walk-forward
```

See [docs/BACKTESTING.md](docs/BACKTESTING.md) for the modelling assumptions —
they matter for interpreting any result.

## Known gaps

Tracked, not yet fixed:

- Live market and order updates use REST polling rather than WebSocket streams.
- A strategy still needs enough real rolling out-of-sample history and Paper
  forward trades before it can be considered validated.
- Catalyst and insider feeds are stubs reporting `UNVERIFIED`.
- `static/demo.html` is a leftover standalone demo page and is still
  English-only; the live dashboard is `static/index.html`.
