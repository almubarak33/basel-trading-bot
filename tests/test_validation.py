from app.backtest.validation import ValidationThresholds, evaluate_holdout


def summary(trades=40,expectancy=.3,pf=1.8,sharpe=1.1,drawdown=6.0):
    return {"trades":{"count":trades,"expectancy_r":expectancy,"profit_factor":pf},
            "equity":{"sharpe":sharpe,"max_drawdown_pct":drawdown}}


def test_strong_unseen_period_passes_every_gate():
    verdict=evaluate_holdout(summary(expectancy=.5),summary(expectancy=.3))
    assert verdict["status"] == "PASS"
    assert all(verdict["criteria"].values())


def test_small_sample_is_reported_honestly():
    verdict=evaluate_holdout(summary(),summary(trades=3))
    assert verdict["status"] == "INSUFFICIENT_SAMPLE"


def test_backtest_degradation_fails_even_when_it_stays_slightly_profitable():
    thresholds=ValidationThresholds(min_expectancy_retention=.5)
    verdict=evaluate_holdout(summary(expectancy=.8),summary(expectancy=.1),thresholds)
    assert verdict["status"] == "FAIL"
    assert verdict["criteria"]["expectancy_retention"] is False
