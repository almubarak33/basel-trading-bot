"""Command line entry point:  python -m app.backtest.cli --help"""
from __future__ import annotations
import argparse
import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import BacktestConfig, ExecutionModel
from .data import BarStore, fetch_history
from .metrics import format_report, summarize
from .runner import run_backtest
from .validation import format_validation_report, run_rolling_validation

ASSUMPTION_NOTES = [
    "Quotes are not in minute bars: the spread filter uses a tick-based estimate.",
    "Fills are modelled from OHLC only; sub-minute price paths are not observed.",
    "A position is managed from the bar after its fill, so no bar both opens and closes a trade.",
    "When one bar spans both stop and target, the stop is assumed to fill first.",
    "The screener is reconstructed from the supplied universe, not Alpaca's live market-wide movers list.",
]


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _load_symbols(args) -> list[str]:
    if args.symbols:
        return [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if args.symbols_file:
        return [line.strip().upper() for line in Path(args.symbols_file).read_text().splitlines()
                if line.strip() and not line.startswith("#")]
    raise SystemExit("Provide --symbols or --symbols-file (or use --synthetic).")


def _synthetic_store(cfg_days: int):
    from .synthetic import build_store
    start = date(2024, 3, 4)
    days = [start + timedelta(days=i) for i in range(cfg_days) if (start + timedelta(days=i)).weekday() < 5]
    store = build_store(days, momentum_symbols={"AAAA": 9.0, "BBBB": 14.0}, quiet_symbols={"CCCC": 22.0})
    return store, days[0], days[-1], ["AAAA", "BBBB", "CCCC"]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replay the Basel strategy over historical data.")
    parser.add_argument("--start", type=_parse_date, help="YYYY-MM-DD")
    parser.add_argument("--end", type=_parse_date, help="YYYY-MM-DD")
    parser.add_argument("--symbols", help="Comma separated universe")
    parser.add_argument("--symbols-file", help="File with one symbol per line")
    parser.add_argument("--equity", type=float, default=20000.0)
    parser.add_argument("--cache", type=Path, help="Bar cache directory")
    parser.add_argument("--load", type=Path, help="Replay a previously saved BarStore JSON")
    parser.add_argument("--save", type=Path, help="Save the downloaded BarStore JSON here")
    parser.add_argument("--synthetic", type=int, metavar="DAYS",
                        help="Run on generated data (no API keys needed); validates the harness only")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="Override a strategy setting, e.g. --set min_score=80")
    parser.add_argument("--legacy-risk-assumption", action="store_true",
                        help="Measure R against a flat 1.5%% of entry, as the manager did before the stop was read from the broker")
    parser.add_argument("--legacy-screener-change", action="store_true",
                        help="Hardcode most-actives day change to 0, as the scanner did before it derived the real value")
    parser.add_argument("--json", type=Path, help="Write the full summary as JSON")
    parser.add_argument("--walk-forward", action="store_true",
                        help="Run rolling chronological out-of-sample validation")
    parser.add_argument("--train-sessions", type=int, default=60)
    parser.add_argument("--test-sessions", type=int, default=20)
    parser.add_argument("--step-sessions", type=int, default=20)
    args = parser.parse_args(argv)

    if args.synthetic:
        store, start, end, symbols = _synthetic_store(args.synthetic)
    elif args.load:
        store = BarStore.from_json(args.load)
        symbols = _load_symbols(args) if (args.symbols or args.symbols_file) else store.symbols()
        start = args.start or store.sessions()[0]
        end = args.end or store.sessions()[-1]
    else:
        if not (args.start and args.end):
            raise SystemExit("--start and --end are required when downloading history.")
        symbols, start, end = _load_symbols(args), args.start, args.end
        store = asyncio.run(fetch_history(symbols, start, end, cache_dir=args.cache))
        if args.save:
            store.to_json(args.save)

    overrides = {}
    for item in args.set:
        key, _, value = item.partition("=")
        overrides[key.strip()] = _coerce(value)

    cfg = BacktestConfig(
        start=start, end=end, symbols=symbols, starting_equity=args.equity,
        overrides=overrides, execution=ExecutionModel(),
        use_true_initial_risk=not args.legacy_risk_assumption,
        legacy_screener_change=args.legacy_screener_change,
    )

    result = run_backtest(store, cfg, progress=lambda day, count: print(f"  … {day}  trades={count}", flush=True))
    summary = summarize(result)
    print(format_report(summary, ASSUMPTION_NOTES))

    if args.walk_forward:
        validation=run_rolling_validation(
            store,cfg,train_sessions=args.train_sessions,test_sessions=args.test_sessions,
            step_sessions=args.step_sessions,
        )
        summary["validation"]=validation
        print(format_validation_report(validation))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(summary, indent=2))
        print(f"\nSummary written to {args.json}")
    return summary


def _coerce(value: str):
    """Turn a --set value into the type the setting expects.

    Booleans are handled explicitly: without this, `--set x=false` would pass the
    string "false", which is truthy, and silently leave the flag on.
    """
    text = value.strip()
    lowered = text.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    try:
        return float(text)
    except ValueError:
        return text


if __name__ == "__main__":
    main()
