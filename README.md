# Basel Trader Mobile

Mobile-first PWA dashboard for a US momentum paper-trading bot.

## Architecture
- iPhone / Android: dashboard only.
- Cloud server: scanner, strategy, risk manager, execution, database.
- Broker: modular adapter; Alpaca Paper in v1.
- The bot continues running on the server even if the phone is locked or offline.

## Safety
Paper only by default. `ENABLE_PAPER_ORDERS=false` prevents execution until explicitly enabled.
