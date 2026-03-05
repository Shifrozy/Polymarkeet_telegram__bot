"""
╔══════════════════════════════════════════════════════════════╗
║   POLYMARKET TELEGRAM BOT — TELEGRAM INTEGRATION            ║
╚══════════════════════════════════════════════════════════════╝
Sends trade notifications and accepts commands via Telegram.

Commands:
  /status   - Current bot status, open positions, daily P&L
  /config   - Show current configuration
  /set      - Update config (e.g., /set tp 90, /set sl 30)
  /start    - Resume trading
  /stop     - Pause trading
  /pnl      - Show P&L summary
  /trades   - Show recent trades
  /markets  - Show available markets
  /help     - Show all commands
"""

import asyncio
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Optional, Callable

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, trading_config


class TelegramNotifier:
    """
    Handles Telegram notifications (sending messages).
    Uses synchronous requests for reliability in the bot loop.
    """

    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self._enabled = bool(self.token and self.chat_id
                             and self.token != "your_telegram_bot_token_here"
                             and self.chat_id != "your_chat_id_here")
        self._msg_queue: list[str] = []
        self._lock = threading.Lock()

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured Telegram chat."""
        if not self._enabled:
            return False
        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            print(f"Telegram send error: {e}")
            return False

    def send_trade_opened(self, trade) -> bool:
        """Send notification when a trade is opened."""
        direction = "🟢 LONG (UP)" if trade.direction.value == "UP" else "🔴 SHORT (DOWN)"
        msg = (
            f"📈 <b>TRADE OPENED</b>\n\n"
            f"Direction: {direction}\n"
            f"Market: {trade.timeframe} timeframe\n"
            f"Stake: <b>${trade.amount:.2f}</b>\n"
            f"Entry Price: ${trade.share_price:.4f}/share\n"
            f"Shares: {trade.shares:.1f}\n"
            f"Candle #: {trade.candle_number}\n"
            f"Order ID: <code>{trade.order_id[:20]}...</code>\n"
            f"Time: {trade.entry_time} UTC"
        )
        return self.send(msg)

    def send_trade_closed(self, trade) -> bool:
        """Send notification when a trade is closed."""
        pnl_emoji = "💰" if trade.pnl >= 0 else "💸"
        pnl_sign = "+" if trade.pnl >= 0 else ""
        direction = "🟢 UP" if trade.direction.value == "UP" else "🔴 DOWN"

        reason_map = {
            "TAKE_PROFIT": "🎯 Take-Profit Hit",
            "STOP_LOSS": "🛑 Stop-Loss Hit",
            "WIN": "✅ Market Resolved (WIN)",
            "LOSS": "❌ Market Resolved (LOSS)",
            "CANCELLED": "🚫 Cancelled",
        }
        reason_text = reason_map.get(trade.close_reason, trade.close_reason or "Closed")

        msg = (
            f"{pnl_emoji} <b>TRADE CLOSED</b>\n\n"
            f"Direction: {direction}\n"
            f"Reason: {reason_text}\n"
            f"Entry Price: ${trade.share_price:.4f}\n"
            f"Exit Price: ${trade.result_price:.4f}\n"
            f"P&L: <b>{pnl_sign}${trade.pnl:.2f}</b>\n"
            f"Market: {trade.timeframe} timeframe\n"
            f"Candle #: {trade.candle_number}"
        )
        return self.send(msg)

    def send_status(self, trader, engine_state=None) -> bool:
        """Send current bot status."""
        from trade_manager import TradeStatus

        status = "🟢 RUNNING" if trading_config.bot_running else "🔴 PAUSED"
        state_text = ""
        if engine_state:
            state_text = f"\nStrategy State: {engine_state.bot_state.value}"

        open_trade_text = "None"
        if trader.current_trade and trader.current_trade.status == TradeStatus.OPEN:
            t = trader.current_trade
            dir_text = "UP" if t.direction.value == "UP" else "DOWN"
            open_trade_text = (
                f"{dir_text} | ${t.amount:.2f} | "
                f"Entry ${t.share_price:.4f} | "
                f"P&L: ${t.unrealized_pnl:+.2f}"
            )

        msg = (
            f"📊 <b>BOT STATUS</b>\n\n"
            f"Status: {status}{state_text}\n"
            f"Open Position: {open_trade_text}\n\n"
            f"── Today's Stats ──\n"
            f"Daily P&L: <b>${trader.daily_pnl:+.2f}</b>\n\n"
            f"── All Time ──\n"
            f"Total Trades: {trader.total_trades}\n"
            f"Win Rate: {trader.win_rate:.1f}%\n"
            f"Wins: {trader.wins} | Losses: {trader.losses}\n"
            f"Total P&L: <b>${trader.total_pnl:+.2f}</b>\n"
            f"Volume: ${trader.total_volume:.2f}"
        )
        return self.send(msg)

    def send_config(self) -> bool:
        """Send current configuration."""
        cfg = trading_config
        direction = "🟢 LONG" if cfg.strategy_direction == "LONG" else "🔴 SHORT"
        size_text = (
            f"${cfg.trade_amount:.2f} (fixed)"
            if cfg.trade_size_mode == "fixed"
            else f"{cfg.trade_percent:.1f}% of portfolio"
        )

        msg = (
            f"⚙️ <b>CONFIGURATION</b>\n\n"
            f"Strategy: {direction}\n"
            f"Trade Size: {size_text}\n"
            f"Take-Profit: {cfg.take_profit_pct:.1f}%\n"
            f"Stop-Loss: {cfg.stop_loss_pct:.1f}%\n"
            f"Markets: {', '.join(cfg.market_timeframes)}\n"
            f"Share Price: ${cfg.share_price:.2f}\n"
            f"Max Slippage: ${cfg.max_slippage:.2f}\n"
            f"Cooldown: {cfg.cooldown_minutes} min\n"
            f"Tick Interval: {cfg.tick_interval}s"
        )
        return self.send(msg)

    def send_pnl_summary(self, trader) -> bool:
        """Send P&L summary."""
        pnl_emoji = "📈" if trader.total_pnl >= 0 else "📉"
        daily_emoji = "📈" if trader.daily_pnl >= 0 else "📉"

        msg = (
            f"{pnl_emoji} <b>P&L SUMMARY</b>\n\n"
            f"── Today ──\n"
            f"{daily_emoji} Daily P&L: <b>${trader.daily_pnl:+.2f}</b>\n\n"
            f"── All Time ──\n"
            f"Total P&L: <b>${trader.total_pnl:+.2f}</b>\n"
            f"Total Volume: ${trader.total_volume:.2f}\n"
            f"Total Trades: {trader.total_trades}\n"
            f"Win Rate: {trader.win_rate:.1f}%\n"
            f"Wins: {trader.wins} | Losses: {trader.losses}"
        )
        return self.send(msg)

    def send_recent_trades(self, trader) -> bool:
        """Send recent trades list."""
        trades = trader.recent_trades
        if not trades:
            return self.send("📜 <b>RECENT TRADES</b>\n\nNo trades yet.")

        lines = ["📜 <b>RECENT TRADES (Last 10)</b>\n"]
        for i, t in enumerate(trades, 1):
            dir_icon = "🟢" if t.direction.value == "UP" else "🔴"
            pnl_sign = "+" if t.pnl >= 0 else ""
            lines.append(
                f"{i}. {dir_icon} {t.entry_time} | "
                f"${t.amount:.2f} | "
                f"{pnl_sign}${t.pnl:.2f} | "
                f"{t.status_emoji} {t.close_reason}"
            )

        return self.send("\n".join(lines))

    def send_error(self, error_msg: str) -> bool:
        """Send error notification."""
        msg = f"⚠️ <b>BOT ERROR</b>\n\n<code>{error_msg[:500]}</code>"
        return self.send(msg)

    def send_bot_started(self) -> bool:
        """Send bot started notification."""
        from config import PAPER_MODE
        mode = "🔴 PAPER MODE" if PAPER_MODE else "🟢 LIVE TRADING"
        cfg = trading_config
        direction = "LONG" if cfg.strategy_direction == "LONG" else "SHORT"

        msg = (
            f"🚀 <b>BOT STARTED</b>\n\n"
            f"Mode: {mode}\n"
            f"Strategy: {direction}\n"
            f"Markets: {', '.join(cfg.market_timeframes)}\n"
            f"TP: {cfg.take_profit_pct}% | SL: {cfg.stop_loss_pct}%\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        return self.send(msg)

    def send_bot_stopped(self) -> bool:
        """Send bot stopped notification."""
        msg = f"🛑 <b>BOT STOPPED</b>\n\nTime: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        return self.send(msg)


class TelegramCommandHandler:
    """
    Polls for Telegram commands and executes them.
    Runs in a separate thread.
    """

    def __init__(self, notifier: TelegramNotifier, trader=None, engine=None, market_finder=None):
        self.notifier = notifier
        self.trader = trader
        self.engine = engine
        self.market_finder = market_finder
        self._last_update_id = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the command handler in a background thread."""
        if not self.notifier.is_enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the command handler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self):
        """Main polling loop for Telegram updates."""
        while self._running:
            try:
                self._poll_updates()
            except Exception as e:
                print(f"Telegram poll error: {e}")
            time.sleep(2)

    def _poll_updates(self):
        """Poll for new messages/commands."""
        try:
            resp = requests.get(
                f"{self.notifier.base_url}/getUpdates",
                params={
                    "offset": self._last_update_id + 1,
                    "timeout": 5,
                    "allowed_updates": '["message"]',
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return

            data = resp.json()
            if not data.get("ok"):
                return

            for update in data.get("result", []):
                self._last_update_id = update["update_id"]
                message = update.get("message", {})
                chat_id = str(message.get("chat", {}).get("id", ""))

                # Only accept commands from the configured chat
                if chat_id != self.notifier.chat_id:
                    continue

                text = message.get("text", "").strip()
                if text.startswith("/"):
                    self._handle_command(text)

        except Exception:
            pass

    def _handle_command(self, text: str):
        """Route a command to the appropriate handler."""
        parts = text.split()
        cmd = parts[0].lower().split("@")[0]  # Remove @botname suffix
        args = parts[1:]

        handlers = {
            "/status": self._cmd_status,
            "/config": self._cmd_config,
            "/set": self._cmd_set,
            "/start": self._cmd_start,
            "/stop": self._cmd_stop,
            "/pnl": self._cmd_pnl,
            "/trades": self._cmd_trades,
            "/markets": self._cmd_markets,
            "/help": self._cmd_help,
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                handler(args)
            except Exception as e:
                self.notifier.send(f"⚠️ Command error: {str(e)[:200]}")
        else:
            self.notifier.send(
                f"❓ Unknown command: {cmd}\n"
                f"Type /help for available commands."
            )

    def _cmd_status(self, args):
        if self.trader:
            engine_state = self.engine.state if self.engine else None
            self.notifier.send_status(self.trader, engine_state)
        else:
            self.notifier.send("⚠️ Trader not initialized yet.")

    def _cmd_config(self, args):
        self.notifier.send_config()

    def _cmd_set(self, args):
        """Handle /set commands like /set tp 90, /set sl 30, /set direction long"""
        if len(args) < 2:
            msg = (
                "⚙️ <b>SET PARAMETERS</b>\n\n"
                "Usage:\n"
                "/set tp 90 — Set take-profit to 90%\n"
                "/set sl 30 — Set stop-loss to 30%\n"
                "/set amount 10 — Set trade amount to $10\n"
                "/set percent 5 — Set trade to 5% of portfolio\n"
                "/set direction long — Set strategy to LONG\n"
                "/set direction short — Set strategy to SHORT\n"
                "/set market 15m — Set market timeframe\n"
                "/set market 5m,15m — Set multiple timeframes\n"
                "/set size fixed — Use fixed amount\n"
                "/set size percent — Use portfolio percentage"
            )
            self.notifier.send(msg)
            return

        param = args[0].lower()
        value = args[1]

        try:
            if param == "tp":
                changes = trading_config.update(take_profit_pct=float(value))
            elif param == "sl":
                changes = trading_config.update(stop_loss_pct=float(value))
            elif param == "amount":
                changes = trading_config.update(trade_amount=float(value))
            elif param == "percent":
                changes = trading_config.update(trade_percent=float(value))
            elif param == "direction":
                direction = value.upper()
                if direction not in ("LONG", "SHORT"):
                    self.notifier.send("❌ Direction must be LONG or SHORT")
                    return
                changes = trading_config.update(strategy_direction=direction)
            elif param == "market":
                timeframes = [t.strip() for t in value.split(",")]
                valid_tfs = {"5m", "15m", "1h", "1d"}
                invalid = [t for t in timeframes if t not in valid_tfs]
                if invalid:
                    self.notifier.send(f"❌ Invalid timeframes: {invalid}. Valid: {valid_tfs}")
                    return
                changes = trading_config.update(market_timeframes=timeframes)
            elif param == "size":
                mode = value.lower()
                if mode not in ("fixed", "percent"):
                    self.notifier.send("❌ Size mode must be 'fixed' or 'percent'")
                    return
                changes = trading_config.update(trade_size_mode=mode)
            else:
                self.notifier.send(f"❌ Unknown parameter: {param}")
                return

            if changes:
                self.notifier.send(f"✅ Updated:\n" + "\n".join(changes))
            else:
                self.notifier.send("⚠️ No changes made.")

        except ValueError:
            self.notifier.send(f"❌ Invalid value: {value}")

    def _cmd_start(self, args):
        trading_config.update(bot_running=True)
        self.notifier.send("▶️ <b>Bot RESUMED</b>\nTrading is now active.")

    def _cmd_stop(self, args):
        trading_config.update(bot_running=False)
        self.notifier.send("⏸️ <b>Bot PAUSED</b>\nTrading is paused. Use /start to resume.")

    def _cmd_pnl(self, args):
        if self.trader:
            self.notifier.send_pnl_summary(self.trader)
        else:
            self.notifier.send("⚠️ Trader not initialized yet.")

    def _cmd_trades(self, args):
        if self.trader:
            self.notifier.send_recent_trades(self.trader)
        else:
            self.notifier.send("⚠️ Trader not initialized yet.")

    def _cmd_markets(self, args):
        if not self.market_finder:
            self.notifier.send("⚠️ Market finder not initialized yet.")
            return

        markets = self.market_finder.find_all_markets()
        lines = ["🏪 <b>AVAILABLE MARKETS</b>\n"]

        for tf, market in markets.items():
            if market:
                lines.append(
                    f"✅ <b>{tf}</b>: {market.question[:50]}\n"
                    f"   UP: ${market.price_up:.3f} | DOWN: ${market.price_down:.3f}\n"
                    f"   Closes in: {market.minutes_until_close:.0f} min"
                )
            else:
                lines.append(f"❌ <b>{tf}</b>: No active market found")

        self.notifier.send("\n".join(lines))

    def _cmd_help(self, args):
        msg = (
            "🤖 <b>POLYMARKET BOT COMMANDS</b>\n\n"
            "/status — Bot status & open positions\n"
            "/config — Current configuration\n"
            "/pnl — P&L summary\n"
            "/trades — Recent trade history\n"
            "/markets — Available markets\n\n"
            "<b>Configuration:</b>\n"
            "/set tp <i>value</i> — Set take-profit %\n"
            "/set sl <i>value</i> — Set stop-loss %\n"
            "/set amount <i>value</i> — Set trade amount ($)\n"
            "/set percent <i>value</i> — Set portfolio %\n"
            "/set direction <i>long/short</i>\n"
            "/set market <i>5m,15m,1h,1d</i>\n"
            "/set size <i>fixed/percent</i>\n\n"
            "<b>Control:</b>\n"
            "/start — Resume trading\n"
            "/stop — Pause trading\n"
            "/help — Show this message"
        )
        self.notifier.send(msg)
