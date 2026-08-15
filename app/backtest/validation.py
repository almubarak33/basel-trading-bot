"""Rolling out-of-sample validation and explicit deployment-readiness gates."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from statistics import mean

from .metrics import summarize
from .runner import run_backtest


@dataclass(frozen=True)
class ValidationThresholds:
    min_out_of_sample_trades: int = 10
    min_expectancy_r: float = 0.0
    min_profit_factor: float = 1.10
    min_sharpe: float = 0.0
    max_drawdown_pct: float = 12.0
    min_expectancy_retention: float = 0.25


def evaluate_holdout(in_sample: dict, out_of_sample: dict,
                     thresholds: ValidationThresholds | None = None) -> dict:
    thresholds = thresholds or ValidationThresholds()
    inside = in_sample.get("trades") or {}
    outside = out_of_sample.get("trades") or {}
    outside_equity = out_of_sample.get("equity") or {}
    in_expectancy = float(inside.get("expectancy_r") or 0)
    out_expectancy = float(outside.get("expectancy_r") or 0)
    retention = out_expectancy / in_expectancy if in_expectancy > 0 else None
    criteria = {
        "sample_size": int(outside.get("count") or 0) >= thresholds.min_out_of_sample_trades,
        "positive_expectancy": out_expectancy > thresholds.min_expectancy_r,
        "profit_factor": float(outside.get("profit_factor") or 0) >= thresholds.min_profit_factor,
        "sharpe": float(outside_equity.get("sharpe") or 0) >= thresholds.min_sharpe,
        "drawdown": float(outside_equity.get("max_drawdown_pct") or 0) <= thresholds.max_drawdown_pct,
        "expectancy_retention": retention is None or retention >= thresholds.min_expectancy_retention,
    }
    status = "PASS" if all(criteria.values()) else (
        "INSUFFICIENT_SAMPLE" if not criteria["sample_size"] else "FAIL"
    )
    return {
        "status": status,
        "criteria": criteria,
        "thresholds": asdict(thresholds),
        "measurements": {
            "in_sample_expectancy_r": in_expectancy,
            "out_of_sample_expectancy_r": out_expectancy,
            "expectancy_retention": round(retention, 3) if retention is not None else None,
            "out_of_sample_trades": int(outside.get("count") or 0),
            "out_of_sample_profit_factor": float(outside.get("profit_factor") or 0),
            "out_of_sample_sharpe": float(outside_equity.get("sharpe") or 0),
            "out_of_sample_drawdown_pct": float(outside_equity.get("max_drawdown_pct") or 0),
        },
    }


def run_rolling_validation(store, cfg, *, train_sessions: int = 60,
                           test_sessions: int = 20, step_sessions: int = 20,
                           thresholds: ValidationThresholds | None = None) -> dict:
    """Evaluate a fixed strategy on consecutive unseen chronological windows.

    This intentionally performs no parameter search.  It is a robustness check,
    not an optimizer that can quietly select the best-looking backtest.
    """
    thresholds = thresholds or ValidationThresholds()
    sessions = [day for day in store.sessions() if cfg.start <= day <= cfg.end]
    required = train_sessions + test_sessions
    if len(sessions) < required:
        return {
            "status": "INSUFFICIENT_HISTORY", "folds": [],
            "required_sessions": required, "available_sessions": len(sessions),
        }

    folds = []
    for test_start in range(train_sessions, len(sessions) - test_sessions + 1, max(step_sessions, 1)):
        train = sessions[test_start - train_sessions:test_start]
        test = sessions[test_start:test_start + test_sessions]
        train_cfg = replace(cfg, start=train[0], end=train[-1])
        test_cfg = replace(cfg, start=test[0], end=test[-1])
        in_summary = summarize(run_backtest(store, train_cfg))
        out_summary = summarize(run_backtest(store, test_cfg))
        verdict = evaluate_holdout(in_summary, out_summary, thresholds)
        folds.append({
            "train": {"start": str(train[0]), "end": str(train[-1]), "summary": in_summary},
            "test": {"start": str(test[0]), "end": str(test[-1]), "summary": out_summary},
            "verdict": verdict,
        })

    measurements = [fold["verdict"]["measurements"] for fold in folds]
    passed = sum(fold["verdict"]["status"] == "PASS" for fold in folds)
    pass_rate = passed / len(folds) if folds else 0.0
    total_oos_trades = sum(item["out_of_sample_trades"] for item in measurements)
    avg_expectancy = mean(item["out_of_sample_expectancy_r"] for item in measurements) if measurements else 0.0
    status = "READY_FOR_PAPER_PILOT" if (
        folds and pass_rate >= 0.67 and total_oos_trades >= thresholds.min_out_of_sample_trades * 2
        and avg_expectancy > 0
    ) else "NOT_VALIDATED"
    return {
        "status": status,
        "fold_count": len(folds),
        "passed_folds": passed,
        "pass_rate_pct": round(pass_rate * 100, 1),
        "out_of_sample_trades": total_oos_trades,
        "average_out_of_sample_expectancy_r": round(avg_expectancy, 3),
        "thresholds": asdict(thresholds),
        "folds": folds,
    }


def format_validation_report(report: dict) -> str:
    if report.get("status") == "INSUFFICIENT_HISTORY":
        return ("\nROLLING VALIDATION: INSUFFICIENT HISTORY "
                f"({report.get('available_sessions', 0)}/{report.get('required_sessions', 0)} sessions)")
    return "\n".join([
        "", "=" * 62, "  ROLLING OUT-OF-SAMPLE VALIDATION", "=" * 62,
        f"  Status             {report.get('status')}",
        f"  Passed folds       {report.get('passed_folds', 0)}/{report.get('fold_count', 0)} ({report.get('pass_rate_pct', 0):.1f}%)",
        f"  OOS trades         {report.get('out_of_sample_trades', 0)}",
        f"  OOS expectancy     {report.get('average_out_of_sample_expectancy_r', 0):+.3f} R",
        "  No parameters are optimized inside this command.",
        "=" * 62,
    ])
