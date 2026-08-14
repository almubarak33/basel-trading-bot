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
    # Shared secret for the dashboard/API. Generated per-process when unset.
    api_token: str = os.getenv("API_TOKEN", "")
    paper: bool = as_bool("ALPACA_PAPER", True)
    enable_orders: bool = as_bool("ENABLE_PAPER_ORDERS", False)
    auto_paper_trading: bool = as_bool("AUTO_PAPER_TRADING", False)
    scan_interval_seconds: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))

    option_alpha_webhook_url: str = os.getenv("OPTION_ALPHA_WEBHOOK_URL", "")
    option_alpha_enabled: bool = as_bool("OPTION_ALPHA_ENABLED", False)

    paper_equity: float = float(os.getenv("PAPER_EQUITY", "20000"))
    risk_per_trade: float = float(os.getenv("RISK_PER_TRADE", "0.0035"))
    max_daily_loss: float = float(os.getenv("MAX_DAILY_LOSS", "0.015"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "2"))

    min_price: float = float(os.getenv("MIN_PRICE", "2"))
    max_price: float = float(os.getenv("MAX_PRICE", "30"))
    min_change_pct: float = float(os.getenv("MIN_CHANGE_PCT", "4"))
    max_change_pct: float = float(os.getenv("MAX_CHANGE_PCT", "35"))
    min_score: float = float(os.getenv("MIN_SCORE", "85"))
    max_spread_pct: float = float(os.getenv("MAX_SPREAD_PCT", "0.45"))
    screener_top: int = int(os.getenv("SCREENER_TOP", "25"))

    # Entry quality / anti-FOMO
    max_vwap_extension_pct: float = float(os.getenv("MAX_VWAP_EXTENSION_PCT", "2.5"))
    max_ema20_extension_pct: float = float(os.getenv("MAX_EMA20_EXTENSION_PCT", "2.0"))
    max_one_bar_move_pct: float = float(os.getenv("MAX_ONE_BAR_MOVE_PCT", "2.5"))
    min_bars: int = int(os.getenv("MIN_INTRADAY_BARS", "25"))
    min_stop_pct: float = float(os.getenv("MIN_STOP_PCT", "0.8"))
    max_stop_pct: float = float(os.getenv("MAX_STOP_PCT", "4.0"))
    reward_r_multiple: float = float(os.getenv("REWARD_R_MULTIPLE", "2.0"))
    symbol_cooldown_minutes: int = int(os.getenv("SYMBOL_COOLDOWN_MINUTES", "30"))

    # Quality filters
    min_rvol: float = float(os.getenv("MIN_RVOL", "2.0"))
    opening_delay_minutes: int = int(os.getenv("OPENING_DELAY_MINUTES", "10"))

    # Autonomous trade management (PAPER only)
    auto_manage_positions: bool = as_bool("AUTO_MANAGE_POSITIONS", True)
    manager_interval_seconds: int = int(os.getenv("MANAGER_INTERVAL_SECONDS", "20"))
    thesis_fail_checks: int = int(os.getenv("THESIS_FAIL_CHECKS", "2"))
    protect_profit_after_r: float = float(os.getenv("PROTECT_PROFIT_AFTER_R", "1.0"))
    protected_floor_r: float = float(os.getenv("PROTECTED_FLOOR_R", "0.15"))
    max_hold_minutes: int = int(os.getenv("MAX_HOLD_MINUTES", "90"))
    close_on_daily_guard: bool = as_bool("CLOSE_ON_DAILY_GUARD", True)

    # End of day. Bracket legs are day orders, so anything still open when they
    # expire carries overnight unprotected. Disabling the flatten accepts that.
    eod_flatten_enabled: bool = as_bool("EOD_FLATTEN_ENABLED", True)
    eod_flatten_minutes: int = int(os.getenv("EOD_FLATTEN_MINUTES_BEFORE_CLOSE", "10"))
    no_entry_minutes_before_close: int = int(os.getenv("NO_ENTRY_MINUTES_BEFORE_CLOSE", "30"))

settings = Settings()
