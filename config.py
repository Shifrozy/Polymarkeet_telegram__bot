"""
╔══════════════════════════════════════════════════════════════╗
║     POLYMARKET TELEGRAM BOT — CONFIGURATION                 ║
╚══════════════════════════════════════════════════════════════╝
Loads all settings from .env and exposes them as typed constants.
Supports runtime updates via Telegram commands.
"""

import os
import json
import threading
from dotenv import load_dotenv

load_dotenv()


# ── Polymarket Credentials ──────────────────────────
PRIVATE_KEY: str = os.getenv("PRIVATE_KEY", "")
FUNDER_ADDRESS: str = os.getenv("FUNDER_ADDRESS", "")
SIGNATURE_TYPE: int = int(os.getenv("SIGNATURE_TYPE", "0"))

# ── API Endpoints ───────────────────────────────────
CLOB_HOST = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
CHAIN_ID = 137  # Polygon

# ── Binance (free BTC price data) ───────────────────
BINANCE_API = "https://api.binance.com"
BINANCE_KLINE_ENDPOINT = f"{BINANCE_API}/api/v3/klines"
BTC_SYMBOL = "BTCUSDT"

# ── Telegram ────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Mode ────────────────────────────────────────────
PAPER_MODE: bool = os.getenv("PAPER_MODE", "true").lower() == "true"
AUTO_RESTART: bool = os.getenv("AUTO_RESTART", "true").lower() == "true"


class TradingConfig:
    """
    Runtime-mutable trading configuration.
    Thread-safe. Can be updated via Telegram commands.
    """

    _lock = threading.Lock()

    def __init__(self):
        # ── Strategy Direction ──────────────────────
        self.strategy_direction: str = os.getenv("STRATEGY_DIRECTION", "LONG").upper()

        # ── Trade Sizing ────────────────────────────
        self.trade_size_mode: str = os.getenv("TRADE_SIZE_MODE", "fixed").lower()
        self.trade_amount: float = float(os.getenv("TRADE_AMOUNT", "5.0"))
        self.trade_percent: float = float(os.getenv("TRADE_PERCENT", "5.0"))

        # ── Take-Profit & Stop-Loss ─────────────────
        self.take_profit_pct: float = float(os.getenv("TAKE_PROFIT_PCT", "80.0"))
        self.stop_loss_pct: float = float(os.getenv("STOP_LOSS_PCT", "50.0"))

        # ── Market Selection ────────────────────────
        raw_tf = os.getenv("MARKET_TIMEFRAMES", "15m")
        self.market_timeframes: list[str] = [t.strip() for t in raw_tf.split(",")]

        # ── Pricing ─────────────────────────────────
        self.share_price: float = float(os.getenv("SHARE_PRICE", "0.50"))
        self.max_slippage: float = float(os.getenv("MAX_SLIPPAGE", "0.05"))

        # ── Timing ──────────────────────────────────
        self.cooldown_minutes: int = int(os.getenv("COOLDOWN_MINUTES", "30"))
        self.max_entry_wait_minutes: int = int(os.getenv("MAX_ENTRY_WAIT_MINUTES", "5"))
        self.tick_interval: int = int(os.getenv("TICK_INTERVAL", "5"))

        # ── Strategy Parameters ─────────────────────
        self.consecutive_candles_signal: int = 2
        self.max_progressive_entries: int = 5
        self.progressive_start: int = 3

        # ── Candle interval mapping ─────────────────
        self._interval_map = {
            "5m": "5m",
            "15m": "15m",
            "1h": "1h",
            "1d": "1d",
        }

        # ── Runtime State ───────────────────────────
        self.bot_running: bool = True

    def get_candle_interval(self, timeframe: str = None) -> str:
        """Get Binance candle interval for the given timeframe."""
        tf = timeframe or self.market_timeframes[0]
        return self._interval_map.get(tf, "15m")

    def get_market_slug_prefix(self, timeframe: str = None) -> str:
        """Get the Polymarket slug prefix for a given timeframe."""
        tf = timeframe or self.market_timeframes[0]
        slug_map = {
            "5m": "btc-updown-5m",
            "15m": "btc-updown-15m",
            "1h": "btc-updown-1h",
            "1d": "btc-updown-1d",
        }
        return slug_map.get(tf, "btc-updown-15m")

    def get_interval_seconds(self, timeframe: str = None) -> int:
        """Get the interval in seconds for slug boundary calculation."""
        tf = timeframe or self.market_timeframes[0]
        seconds_map = {
            "5m": 5 * 60,
            "15m": 15 * 60,
            "1h": 60 * 60,
            "1d": 24 * 60 * 60,
        }
        return seconds_map.get(tf, 15 * 60)

    def update(self, **kwargs) -> list[str]:
        """
        Update config values. Returns list of changes made.
        Thread-safe.
        """
        changes = []
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    old_val = getattr(self, key)
                    setattr(self, key, value)
                    changes.append(f"{key}: {old_val} → {value}")
        return changes

    def to_dict(self) -> dict:
        """Return current config as a dictionary."""
        with self._lock:
            return {
                "strategy_direction": self.strategy_direction,
                "trade_size_mode": self.trade_size_mode,
                "trade_amount": self.trade_amount,
                "trade_percent": self.trade_percent,
                "take_profit_pct": self.take_profit_pct,
                "stop_loss_pct": self.stop_loss_pct,
                "market_timeframes": self.market_timeframes,
                "share_price": self.share_price,
                "max_slippage": self.max_slippage,
                "cooldown_minutes": self.cooldown_minutes,
                "max_entry_wait_minutes": self.max_entry_wait_minutes,
                "tick_interval": self.tick_interval,
                "bot_running": self.bot_running,
            }

    def __repr__(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ── Global Config Instance ──────────────────────────
trading_config = TradingConfig()


# ── Validation ──────────────────────────────────────
def validate_config() -> list[str]:
    """Return a list of config errors (empty = all good)."""
    errors = []
    if not PAPER_MODE:
        if not PRIVATE_KEY or PRIVATE_KEY == "0x_your_private_key_here":
            errors.append("PRIVATE_KEY is not set in .env")
        if not FUNDER_ADDRESS or FUNDER_ADDRESS == "0x_your_wallet_address_here":
            errors.append("FUNDER_ADDRESS is not set in .env")
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        errors.append("TELEGRAM_BOT_TOKEN is not set in .env")
    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "your_chat_id_here":
        errors.append("TELEGRAM_CHAT_ID is not set in .env")
    if trading_config.trade_amount <= 0:
        errors.append("TRADE_AMOUNT must be > 0")
    if not (0 < trading_config.share_price < 1):
        errors.append("SHARE_PRICE must be between 0 and 1")
    if trading_config.max_slippage < 0:
        errors.append("MAX_SLIPPAGE must be >= 0")
    if trading_config.strategy_direction not in ("LONG", "SHORT"):
        errors.append("STRATEGY_DIRECTION must be LONG or SHORT")
    if trading_config.trade_size_mode not in ("fixed", "percent"):
        errors.append("TRADE_SIZE_MODE must be 'fixed' or 'percent'")
    return errors
