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
    trading_profile: str = os.getenv("TRADING_PROFILE", "AGGRESSIVE").upper()
    scan_interval_seconds: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))
    scan_extended_hours: bool = as_bool("SCAN_EXTENDED_HOURS", True)

    option_alpha_webhook_url: str = os.getenv("OPTION_ALPHA_WEBHOOK_URL", "")
    option_alpha_enabled: bool = as_bool("OPTION_ALPHA_ENABLED", False)

    paper_equity: float = float(os.getenv("PAPER_EQUITY", "20000"))
    risk_per_trade: float = float(os.getenv("RISK_PER_TRADE", "0.005"))
    max_daily_loss: float = float(os.getenv("MAX_DAILY_LOSS", "0.02"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "4"))
    max_position_notional_pct: float = float(os.getenv("MAX_POSITION_NOTIONAL_PCT", "0.20"))

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
    min_bars: int = int(os.getenv("MIN_INTRADAY_BARS", "8"))
    min_stop_pct: float = float(os.getenv("MIN_STOP_PCT", "0.8"))
    max_stop_pct: float = float(os.getenv("MAX_STOP_PCT", "7.5"))
    # Kept as an informational 2R reference on the UI/backtest reports. Runner
    # mode does not submit this as a hard take-profit to the broker.
    reward_r_multiple: float = float(os.getenv("REWARD_R_MULTIPLE", "2.0"))
    symbol_cooldown_minutes: int = int(os.getenv("SYMBOL_COOLDOWN_MINUTES", "30"))

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

    # End of day. Stop legs are day orders in the current PAPER implementation,
    # so anything still open near the bell is flattened intentionally.
    eod_flatten_enabled: bool = as_bool("EOD_FLATTEN_ENABLED", True)
    eod_flatten_minutes: int = int(os.getenv("EOD_FLATTEN_MINUTES_BEFORE_CLOSE", "10"))
    no_entry_minutes_before_close: int = int(os.getenv("NO_ENTRY_MINUTES_BEFORE_CLOSE", "30"))

settings = Settings()
