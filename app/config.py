import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def as_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}

@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("ALPACA_API_KEY", "")
    api_secret: str = os.getenv("ALPACA_API_SECRET", "")
    api_token: str = os.getenv("API_TOKEN", "")
    sec_user_agent: str = os.getenv(
        "SEC_USER_AGENT",
        "BaselTrader/1.0 https://github.com/almubarak33/basel-trading-bot",
    )
    paper: bool = as_bool("ALPACA_PAPER", True)
    # PAPER execution is enabled by default. Live trading remains blocked by the
    # explicit paper check throughout the order path.
    enable_orders: bool = as_bool("ENABLE_PAPER_ORDERS", True)
    auto_paper_trading: bool = as_bool("AUTO_PAPER_TRADING", True)
    # STANDARD refuses to enter while SPY/QQQ are risk-off. Measured over 125
    # sessions it beat AGGRESSIVE on every metric — return +14.96% vs +13.05%,
    # drawdown 3.60% vs 6.51%, Sharpe 2.79 vs 1.99, Calmar 9.01 vs 4.31.
    trading_profile: str = os.getenv("TRADING_PROFILE", "STANDARD").upper()
    scan_interval_seconds: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))
    scan_extended_hours: bool = as_bool("SCAN_EXTENDED_HOURS", True)

    option_alpha_webhook_url: str = os.getenv("OPTION_ALPHA_WEBHOOK_URL", "")
    option_alpha_enabled: bool = as_bool("OPTION_ALPHA_ENABLED", False)

    paper_equity: float = float(os.getenv("PAPER_EQUITY", "20000"))
    risk_per_trade: float = float(os.getenv("RISK_PER_TRADE", "0.005"))
    max_daily_loss: float = float(os.getenv("MAX_DAILY_LOSS", "0.02"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "4"))
    max_position_notional_pct: float = float(os.getenv("MAX_POSITION_NOTIONAL_PCT", "0.20"))
    # Portfolio-level controls include both filled positions and working entries.
    max_gross_exposure_pct: float = float(os.getenv("MAX_GROSS_EXPOSURE_PCT", "0.60"))
    max_portfolio_heat_pct: float = float(os.getenv("MAX_PORTFOLIO_HEAT_PCT", "0.02"))
    buying_power_buffer_pct: float = float(os.getenv("BUYING_POWER_BUFFER_PCT", "0.05"))
    # Do not become a material part of a thin one-minute bar or daily volume.
    max_bar_participation_pct: float = float(os.getenv("MAX_BAR_PARTICIPATION_PCT", "0.05"))
    max_daily_participation_pct: float = float(os.getenv("MAX_DAILY_PARTICIPATION_PCT", "0.001"))
    require_liquidity_for_orders: bool = as_bool("REQUIRE_LIQUIDITY_FOR_ORDERS", True)

    # Discovery is open across the price spectrum. A max of 0 means no cap.
    min_price: float = float(os.getenv("MIN_PRICE", "0.01"))
    max_price: float = float(os.getenv("MAX_PRICE", "0"))
    min_change_pct: float = float(os.getenv("MIN_CHANGE_PCT", "1.5"))
    min_execution_change_pct: float = float(os.getenv("MIN_EXECUTION_CHANGE_PCT", "3.0"))
    # A max of 0 keeps large movers visible instead of discarding them.
    max_change_pct: float = float(os.getenv("MAX_CHANGE_PCT", "0"))
    min_score: float = float(os.getenv("MIN_SCORE", "72"))
    min_intel_score: float = float(os.getenv("MIN_INTEL_SCORE", "72"))
    max_spread_pct: float = float(os.getenv("MAX_SPREAD_PCT", "0.65"))
    max_spread_low_price_pct: float = float(os.getenv("MAX_SPREAD_LOW_PRICE_PCT", "1.50"))
    max_spread_penny_pct: float = float(os.getenv("MAX_SPREAD_PENNY_PCT", "3.00"))
    movers_top: int = int(os.getenv("MOVERS_TOP", "50"))
    actives_top: int = int(os.getenv("ACTIVES_TOP", "100"))
    screener_universe_limit: int = int(os.getenv("SCREENER_UNIVERSE_LIMIT", "100"))
    # Kept for older backtest/config consumers.
    screener_top: int = int(os.getenv("SCREENER_TOP", "50"))

    # Entry quality / anti-FOMO
    max_vwap_extension_pct: float = float(os.getenv("MAX_VWAP_EXTENSION_PCT", "4.5"))
    max_ema20_extension_pct: float = float(os.getenv("MAX_EMA20_EXTENSION_PCT", "6.0"))
    max_one_bar_move_pct: float = float(os.getenv("MAX_ONE_BAR_MOVE_PCT", "5.0"))
    # EMA20 needs at least its own period of bars to mean anything. Below that
    # the trend filters pass on a seeding artefact rather than on the trend.
    min_bars: int = int(os.getenv("MIN_INTRADAY_BARS", "25"))
    min_stop_pct: float = float(os.getenv("MIN_STOP_PCT", "0.8"))
    max_stop_pct: float = float(os.getenv("MAX_STOP_PCT", "7.5"))
    # Kept as an informational 2R reference on the UI/backtest reports. Runner
    # mode does not submit this as a hard take-profit to the broker.
    reward_r_multiple: float = float(os.getenv("REWARD_R_MULTIPLE", "2.0"))
    symbol_cooldown_minutes: int = int(os.getenv("SYMBOL_COOLDOWN_MINUTES", "30"))

    # Point-in-time data integrity. Degraded symbols remain visible on the radar,
    # but the autonomous execution path will not trade them.
    require_fresh_market_data: bool = as_bool("REQUIRE_FRESH_MARKET_DATA", True)
    max_market_data_age_seconds: int = int(os.getenv("MAX_MARKET_DATA_AGE_SECONDS", "90"))
    max_intraday_bar_age_seconds: int = int(os.getenv("MAX_INTRADAY_BAR_AGE_SECONDS", "180"))

    # Circuit breakers. The daily equity limit never fired across 44 backtested
    # sessions while a losing exit bucket bled $3,514 in instalments, so these
    # judge the recent record instead of the day's equity.
    protections_enabled: bool = as_bool("PROTECTIONS_ENABLED", True)
    guard_loss_trades: int = int(os.getenv("GUARD_LOSS_TRADES", "4"))
    guard_loss_lookback_minutes: int = int(os.getenv("GUARD_LOSS_LOOKBACK_MINUTES", "120"))
    guard_loss_lock_minutes: int = int(os.getenv("GUARD_LOSS_LOCK_MINUTES", "90"))
    guard_drawdown_pct: float = float(os.getenv("GUARD_DRAWDOWN_PCT", "0.02"))
    guard_drawdown_lookback_minutes: int = int(os.getenv("GUARD_DRAWDOWN_LOOKBACK_MINUTES", "390"))
    guard_drawdown_min_trades: int = int(os.getenv("GUARD_DRAWDOWN_MIN_TRADES", "5"))
    guard_drawdown_lock_minutes: int = int(os.getenv("GUARD_DRAWDOWN_LOCK_MINUTES", "180"))
    guard_symbol_trades: int = int(os.getenv("GUARD_SYMBOL_TRADES", "3"))
    guard_symbol_lookback_minutes: int = int(os.getenv("GUARD_SYMBOL_LOOKBACK_MINUTES", "1440"))
    guard_symbol_lock_minutes: int = int(os.getenv("GUARD_SYMBOL_LOCK_MINUTES", "240"))

    # Quality filters
    min_rvol: float = float(os.getenv("MIN_RVOL", "1.2"))
    opening_delay_minutes: int = int(os.getenv("OPENING_DELAY_MINUTES", "2"))

    # Autonomous trade management (PAPER only)
    auto_manage_positions: bool = as_bool("AUTO_MANAGE_POSITIONS", True)
    manager_interval_seconds: int = int(os.getenv("MANAGER_INTERVAL_SECONDS", "20"))
    thesis_fail_checks: int = int(os.getenv("THESIS_FAIL_CHECKS", "2"))
    regime_exit_enabled: bool = as_bool("REGIME_EXIT_ENABLED", True)
    runner_mode: bool = as_bool("RUNNER_MODE", True)
    runner_activate_r: float = float(os.getenv("RUNNER_ACTIVATE_R", "2.0"))
    runner_giveback_fraction: float = float(os.getenv("RUNNER_GIVEBACK_FRACTION", "0.35"))
    runner_min_lock_r: float = float(os.getenv("RUNNER_MIN_LOCK_R", "1.0"))
    runner_exit_checks: int = int(os.getenv("RUNNER_EXIT_CHECKS", "2"))
    protect_profit_after_r: float = float(os.getenv("PROTECT_PROFIT_AFTER_R", "1.0"))
    protected_floor_r: float = float(os.getenv("PROTECTED_FLOOR_R", "0.15"))
    max_hold_minutes: int = int(os.getenv("MAX_HOLD_MINUTES", "90"))
    close_on_daily_guard: bool = as_bool("CLOSE_ON_DAILY_GUARD", True)
    flatten_unprotected_positions: bool = as_bool("FLATTEN_UNPROTECTED_POSITIONS", True)
    unprotected_position_grace_checks: int = int(os.getenv("UNPROTECTED_POSITION_GRACE_CHECKS", "3"))

    # Extended sessions are controlled in New York market time, so DST is
    # handled automatically by ZoneInfo("America/New_York") in app/session.py.
    # Alpaca only accepts plain extended-hours limit orders outside 09:30-16:00;
    # the bot therefore enforces protective stops in software in those windows.
    trade_after_hours: bool = as_bool("TRADE_AFTER_HOURS", True)
    trade_pre_market: bool = as_bool("TRADE_PRE_MARKET", True)

    eod_flatten_enabled: bool = as_bool("EOD_FLATTEN_ENABLED", True)
    eod_flatten_minutes: int = int(os.getenv("EOD_FLATTEN_MINUTES_BEFORE_CLOSE", "10"))
    no_entry_minutes_before_close: int = int(os.getenv("NO_ENTRY_MINUTES_BEFORE_CLOSE", "30"))

settings = Settings()
