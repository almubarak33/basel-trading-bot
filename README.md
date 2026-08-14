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
- No end-of-day flatten: a filled bracket can carry overnight after its day-only
  legs expire.
- Catalyst and insider feeds are stubs reporting `UNVERIFIED`.
- `static/demo.html` is a leftover standalone demo page and is still
  English-only; the live dashboard is `static/index.html`.
