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
    paper: bool = as_bool("ALPACA_PAPER", True)
    enable_orders: bool = as_bool("ENABLE_PAPER_ORDERS", False)
    paper_equity: float = float(os.getenv("PAPER_EQUITY", "20000"))
    risk_per_trade: float = float(os.getenv("RISK_PER_TRADE", "0.005"))
    max_daily_loss: float = float(os.getenv("MAX_DAILY_LOSS", "0.02"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "3"))
    min_price: float = float(os.getenv("MIN_PRICE", "1"))
    max_price: float = float(os.getenv("MAX_PRICE", "20"))
    min_change_pct: float = float(os.getenv("MIN_CHANGE_PCT", "5"))
    min_score: float = float(os.getenv("MIN_SCORE", "80"))
    max_spread_pct: float = float(os.getenv("MAX_SPREAD_PCT", "0.7"))
    screener_top: int = int(os.getenv("SCREENER_TOP", "30"))

settings = Settings()
