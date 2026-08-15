# Professional engine controls

There is no credible "super bot" or guaranteed-profit setting. A professional
system is one whose market data, order lifecycle, portfolio risk, validation and
failure modes are measurable and controlled. This document maps primary-source
guidance to the implementation in Basel Trader.

## Adopted controls

| Standard or practice | Implementation |
| --- | --- |
| Pre-trade exposure and erroneous-order controls | `app/pretrade.py` evaluates working orders, positions, gross exposure, portfolio heat, buying power and liquidity immediately before every automatic Paper order. |
| Market-data and workflow validation | `app/data_quality.py` rejects stale timestamps, crossed quotes, malformed OHLC data and material trade/quote divergence while leaving the symbol visible for diagnosis. |
| Limited-size pilot deployment | Quantity is risk-sized and then reduced by one-minute and average-daily-volume participation ceilings. Live trading remains blocked; Alpaca Paper is the execution venue. |
| Documented, repeatable order lifecycle | Existing positions and working entry orders are reconciled before submission. A stable signal-window `client_order_id` makes retries idempotent. |
| Protective-order reconciliation | The manager allows a short grace period for a new OTO stop to appear, then flattens a Paper position if the stop is missing or later disappears. |
| Independent chronological validation | `python -m app.backtest.cli ... --walk-forward` reports fixed-parameter rolling out-of-sample results and explicit pass/fail criteria. |
| Reality-aware replay | The backtester shares production strategy, arming, preflight and exit code; includes stop slippage, conservative same-bar ordering, pending-order slots and liquidity participation. |

## Research basis

- [FINRA Regulatory Notice 15-09](https://www.finra.org/rules-guidance/notices/15-09)
  calls for documented development and change control, testing in adverse and
  fast markets, pilot deployments with limited size, real-time monitoring,
  quick-disable mechanisms, data-integrity checks and periodic parameter review.
- [SEC Rule 15c3-5](https://www.sec.gov/rules-regulations/2011/06/risk-management-controls-brokers-or-dealers-market-access)
  establishes the principle of automated pre-trade financial and regulatory
  controls that systematically limit exposure and problematic orders.
- [Alpaca order documentation](https://docs.alpaca.markets/us/docs/orders-at-alpaca)
  describes the order lifecycle and client order identifiers used for
  reconciliation and duplicate prevention.
- [QuantConnect slippage models](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/supported-models)
  include volume-share models in which price impact depends on order quantity
  relative to bar volume. Basel Trader currently applies a participation cap and
  stop slippage, a conservative subset rather than a full impact model.
- [QuantConnect walk-forward guidance](https://www.quantconnect.com/docs/v2/writing-algorithms/optimization/walk-forward-optimization)
  explains why parameters can depend on market regime and should be re-evaluated
  over trailing windows.
- Bailey, Borwein, Lopez de Prado and Zhu's
  [Probability of Backtest Overfitting](https://escholarship.org/content/qt4hn4t174/qt4hn4t174.pdf)
  motivates reporting unseen chronological performance instead of selecting a
  strategy from its best in-sample result.

## Remaining limitations

- Market and order state is polled through REST. WebSocket quote/trade and order
  updates would reduce latency and improve reconciliation.
- Minute-bar replay cannot observe queue priority or sub-minute price paths, and
  historical spreads are estimated.
- Catalyst and microstructure modules remain diagnostic until point-in-time
  historical datasets validate their contribution out of sample.
- A rolling report requires a survivorship-aware historical universe and enough
  unseen trades. Synthetic data validates the harness only, never the strategy.
- Passing backtests and Paper trading do not establish future profitability.
