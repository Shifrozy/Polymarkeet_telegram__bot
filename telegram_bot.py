"""
╔══════════════════════════════════════════════════════════════╗
║   POLYMARKET TELEGRAM BOT — TELEGRAM INTEGRATION v3.0       ║
╚══════════════════════════════════════════════════════════════╝
Manual trading + full parameter control via Telegram.

Trading Commands:
  /buy up [timeframe]      - Buy UP tokens
  /buy down [timeframe]    - Buy DOWN tokens
  /sell                    - Sell current position
  /auto up                 - Auto-repeat buying UP
  /auto down               - Auto-repeat buying DOWN
  /auto off                - Stop auto-repeat

Status Commands:
  /status   - Bot status, open positions, daily P&L
  /config   - Show ALL current parameters
  /pnl      - P&L summary
  /trades   - Recent trades
  /markets  - Available markets
  /balance  - Wallet balance

Parameter Commands:
  /set tp <value>          - Take-profit %
  /set sl <value>          - Stop-loss %
  /set amount <value>      - Trade amount ($)
  /set percent <value>     - Portfolio %
  /set size fixed|percent  - Sizing mode
  /set slippage <value>    - Max slippage ($)
  /set shareprice <value>  - Target share price
  /set market <5m,15m,...> - Market timeframes
  /set maxtrades <value>   - Max trades per day
  /set cooldown <value>    - Cooldown minutes
  /set tick <value>        - Tick interval (seconds)

Control:
  /start  - Resume bot
  /stop   - Pause bot
  /help   - All commands
"""

import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, trading_config


class TelegramNotifier:
    """Sends notifications to Telegram chat."""

    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self._enabled = bool(
            self.token and self.chat_id
            and self.token != "your_telegram_bot_token_here"
            and self.chat_id != "your_chat_id_here"
        )

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send a message to Telegram."""
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
        direction = "🟢 LONG (UP)" if trade.direction.value == "UP" else "🔴 SHORT (DOWN)"
        msg = (
            f"📈 <b>TRADE OPENED</b>\n\n"
            f"Direction: {direction}\n"
            f"Market: {trade.timeframe} timeframe\n"
            f"Stake: <b>${trade.amount:.2f}</b>\n"
            f"Entry Price: ${trade.share_price:.4f}/share\n"
            f"Shares: {trade.shares:.1f}\n"
            f"Order ID: <code>{trade.order_id[:20]}...</code>\n"
            f"Time: {trade.entry_time} UTC"
        )
        return self.send(msg)

    def send_trade_closed(self, trade) -> bool:
        pnl_emoji = "💰" if trade.pnl >= 0 else "💸"
        pnl_sign = "+" if trade.pnl >= 0 else ""
        direction = "🟢 UP" if trade.direction.value == "UP" else "🔴 DOWN"

        reason_map = {
            "TAKE_PROFIT|SOLD": "🎯 Take-Profit (Sold ✅)",
            "TAKE_PROFIT|SELL_FAILED": "🎯 Take-Profit (Sell ⚠️)",
            "STOP_LOSS|SOLD": "🛑 Stop-Loss (Sold ✅)",
            "STOP_LOSS|SELL_FAILED": "🛑 Stop-Loss (Sell ⚠️)",
            "MANUAL_SELL|SOLD": "📤 Manual Sell (Sold ✅)",
            "MANUAL_SELL|SELL_FAILED": "📤 Manual Sell (Sell ⚠️)",
            "MARKET_WIN": "✅ Market Resolved (WIN)",
            "MARKET_LOSS": "❌ Market Resolved (LOSS)",
            "WIN": "✅ WIN",
            "LOSS": "❌ LOSS",
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
            f"Market: {trade.timeframe} timeframe"
        )
        return self.send(msg)

    def send_status(self, trader, engine_state=None) -> bool:
        from trade_manager import TradeStatus

        status = "🟢 RUNNING" if trading_config.bot_running else "🔴 PAUSED"
        state_text = ""
        if engine_state:
            state_text = f"\nState: {engine_state.bot_state.value}"
            if engine_state.auto_repeat_active:
                dir_text = engine_state.auto_repeat_direction.value if engine_state.auto_repeat_direction else "?"
                state_text += f"\n🔄 Auto-Repeat: {dir_text}"

        open_trade_text = "None"
        if trader.current_trade and trader.current_trade.status == TradeStatus.OPEN:
            t = trader.current_trade
            dir_text = "UP 🟢" if t.direction.value == "UP" else "DOWN 🔴"
            upnl = t.unrealized_pnl
            upnl_sign = "+" if upnl >= 0 else ""
            open_trade_text = (
                f"\n  Direction: {dir_text}\n"
                f"  Stake: ${t.amount:.2f}\n"
                f"  Entry: ${t.share_price:.4f}\n"
                f"  Current: ${t.current_price:.4f}\n"
                f"  Unrealized P&L: {upnl_sign}${upnl:.2f} ({t.unrealized_pnl_pct:+.1f}%)"
            )

        msg = (
            f"📊 <b>BOT STATUS</b>\n\n"
            f"Status: {status}{state_text}\n\n"
            f"── Open Position ──\n{open_trade_text}\n\n"
            f"── Today ──\n"
            f"Daily P&L: <b>${trader.daily_pnl:+.2f}</b>\n"
            f"Trades Today: {engine_state.trades_today if engine_state else '?'}\n\n"
            f"── All Time ──\n"
            f"Total Trades: {trader.total_trades}\n"
            f"Win Rate: {trader.win_rate:.1f}%\n"
            f"Wins: {trader.wins} | Losses: {trader.losses}\n"
            f"Total P&L: <b>${trader.total_pnl:+.2f}</b>\n"
            f"Volume: ${trader.total_volume:.2f}"
        )
        return self.send(msg)

    def send_config(self) -> bool:
        cfg = trading_config
        size_text = (
            f"${cfg.trade_amount:.2f} (fixed)"
            if cfg.trade_size_mode == "fixed"
            else f"{cfg.trade_percent:.1f}% of portfolio"
        )
        auto_rpt = "ON" if cfg.auto_repeat else "OFF"

        msg = (
            f"⚙️ <b>ALL PARAMETERS</b>\n\n"
            f"── Trading ──\n"
            f"Trade Size: {size_text}\n"
            f"Take-Profit: {cfg.take_profit_pct:.1f}%\n"
            f"Stop-Loss: {cfg.stop_loss_pct:.1f}%\n"
            f"Share Price: ${cfg.share_price:.2f}\n"
            f"Max Slippage: ${cfg.max_slippage:.3f}\n\n"
            f"── Markets ──\n"
            f"Timeframes: {', '.join(cfg.market_timeframes)}\n\n"
            f"── Auto-Repeat ──\n"
            f"Auto-Repeat: {auto_rpt}\n"
            f"Max Trades/Day: {cfg.max_trades_per_day}\n\n"
            f"── Timing ──\n"
            f"Cooldown: {cfg.cooldown_minutes} min\n"
            f"Tick Interval: {cfg.tick_interval}s\n"
            f"Max Entry Wait: {cfg.max_entry_wait_minutes} min"
        )
        return self.send(msg)

    def send_pnl_summary(self, trader) -> bool:
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
                f"{t.close_reason[:15]}"
            )
        return self.send("\n".join(lines))

    def send_error(self, error_msg: str) -> bool:
        msg = f"⚠️ <b>BOT ERROR</b>\n\n<code>{error_msg[:500]}</code>"
        return self.send(msg)

    def send_bot_started(self) -> bool:
        from config import PAPER_MODE
        mode = "🔴 PAPER MODE" if PAPER_MODE else "🟢 LIVE TRADING"
        cfg = trading_config
        msg = (
            f"🚀 <b>BOT STARTED</b>\n\n"
            f"Mode: {mode}\n"
            f"Markets: {', '.join(cfg.market_timeframes)}\n"
            f"TP: {cfg.take_profit_pct}% | SL: {cfg.stop_loss_pct}%\n"
            f"Trade Size: ${cfg.trade_amount} | Slippage: ${cfg.max_slippage}\n\n"
            f"<b>Commands:</b>\n"
            f"/buy up — Buy UP tokens\n"
            f"/buy down — Buy DOWN tokens\n"
            f"/sell — Sell current position\n"
            f"/auto up — Auto-repeat UP\n"
            f"/help — All commands\n\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        return self.send(msg)

    def send_bot_stopped(self) -> bool:
        msg = f"🛑 <b>BOT STOPPED</b>\n\nTime: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        return self.send(msg)


class TelegramCommandHandler:
    """Polls Telegram for commands and executes them."""

    def __init__(self, notifier: TelegramNotifier, trader=None, engine=None, market_finder=None):
        self.notifier = notifier
        self.trader = trader
        self.engine = engine
        self.market_finder = market_finder
        self._last_update_id = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if not self.notifier.is_enabled:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self):
        while self._running:
            try:
                self._poll_updates()
            except Exception as e:
                print(f"Telegram poll error: {e}")
            time.sleep(2)

    def _poll_updates(self):
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
                if chat_id != self.notifier.chat_id:
                    continue
                text = message.get("text", "").strip()
                if text.startswith("/"):
                    self._handle_command(text)
        except Exception:
            pass

    def _handle_command(self, text: str):
        parts = text.split()
        cmd = parts[0].lower().split("@")[0]
        args = parts[1:]

        handlers = {
            "/buy": self._cmd_buy,
            "/sell": self._cmd_sell,
            "/auto": self._cmd_auto,
            "/status": self._cmd_status,
            "/config": self._cmd_config,
            "/set": self._cmd_set,
            "/start": self._cmd_start,
            "/stop": self._cmd_stop,
            "/pnl": self._cmd_pnl,
            "/trades": self._cmd_trades,
            "/markets": self._cmd_markets,
            "/balance": self._cmd_balance,
            "/help": self._cmd_help,
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                handler(args)
            except Exception as e:
                self.notifier.send(f"⚠️ Command error: {str(e)[:200]}")
        else:
            self.notifier.send(f"❓ Unknown: {cmd}\nType /help for commands.")

    # ── Trading Commands ─────────────────────────────

    def _cmd_buy(self, args):
        """Handle /buy up [timeframe] or /buy down [timeframe]"""
        if not args:
            self.notifier.send(
                "🛒 <b>BUY</b>\n\n"
                "Usage:\n"
                "/buy up — Buy UP (BTC will rise)\n"
                "/buy down — Buy DOWN (BTC will fall)\n"
                "/buy up 5m — Buy UP on 5-min market\n"
                "/buy down 1h — Buy DOWN on 1-hour market"
            )
            return

        if not self.engine:
            self.notifier.send("⚠️ Engine not initialized yet.")
            return

        direction_str = args[0].lower()
        if direction_str not in ("up", "down"):
            self.notifier.send("❌ Use: /buy up or /buy down")
            return

        from trade_manager import TradeDirection
        direction = TradeDirection.UP if direction_str == "up" else TradeDirection.DOWN

        # Optional timeframe
        timeframe = args[1] if len(args) > 1 else None
        if timeframe and timeframe not in ("5m", "15m", "1h", "1d"):
            self.notifier.send(f"❌ Invalid timeframe: {timeframe}. Use: 5m, 15m, 1h, 1d")
            return

        success, msg = self.engine.manual_buy(direction, timeframe)
        self.notifier.send(msg)

    def _cmd_sell(self, args):
        """Handle /sell"""
        if not self.engine:
            self.notifier.send("⚠️ Engine not initialized yet.")
            return

        success, msg = self.engine.manual_sell()
        self.notifier.send(msg)

    def _cmd_auto(self, args):
        """Handle /auto up, /auto down, /auto off"""
        if not self.engine:
            self.notifier.send("⚠️ Engine not initialized yet.")
            return

        if not args:
            self.notifier.send(
                "🔄 <b>AUTO-REPEAT</b>\n\n"
                "Usage:\n"
                "/auto up — Automatically re-buy UP after each market\n"
                "/auto down — Automatically re-buy DOWN after each market\n"
                "/auto off — Turn off auto-repeat\n\n"
                "When enabled, bot will automatically place the same\n"
                "direction trade on each new market after the previous\n"
                "one resolves."
            )
            return

        action = args[0].lower()
        if action == "up":
            from trade_manager import TradeDirection
            msg = self.engine.enable_auto_repeat(TradeDirection.UP)
            # Also auto-buy if currently idle
            if self.engine.state.bot_state.value == "IDLE" and not self.trader.has_open_trade():
                success, buy_msg = self.engine.manual_buy(TradeDirection.UP)
                if success:
                    msg += f"\n\n{buy_msg}"
            self.notifier.send(msg)
        elif action == "down":
            from trade_manager import TradeDirection
            msg = self.engine.enable_auto_repeat(TradeDirection.DOWN)
            if self.engine.state.bot_state.value == "IDLE" and not self.trader.has_open_trade():
                success, buy_msg = self.engine.manual_buy(TradeDirection.DOWN)
                if success:
                    msg += f"\n\n{buy_msg}"
            self.notifier.send(msg)
        elif action == "off":
            msg = self.engine.disable_auto_repeat()
            self.notifier.send(msg)
        else:
            self.notifier.send("❌ Use: /auto up, /auto down, or /auto off")

    # ── Status Commands ──────────────────────────────

    def _cmd_status(self, args):
        if self.trader:
            engine_state = self.engine.state if self.engine else None
            self.notifier.send_status(self.trader, engine_state)
        else:
            self.notifier.send("⚠️ Trader not initialized yet.")

    def _cmd_config(self, args):
        self.notifier.send_config()

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
            self.notifier.send("⚠️ Market finder not initialized.")
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
                lines.append(f"❌ <b>{tf}</b>: No active market")
        self.notifier.send("\n".join(lines))

    def _cmd_balance(self, args):
        """Show wallet balance."""
        from config import PAPER_MODE, FUNDER_ADDRESS
        if PAPER_MODE:
            self.notifier.send("💰 Paper mode — no real wallet connected")
            return
        try:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider("https://polygon-bor-rpc.publicnode.com"))
            wallet = Web3.to_checksum_address(FUNDER_ADDRESS)
            usdc_abi = [{"constant": True, "inputs": [{"name": "", "type": "address"}],
                "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view", "type": "function"}]
            usdc = w3.eth.contract(
                address=Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"),
                abi=usdc_abi,
            )
            usdc_bal = usdc.functions.balanceOf(wallet).call() / 1e6
            matic_bal = w3.eth.get_balance(wallet) / 1e18
            short_addr = f"{FUNDER_ADDRESS[:6]}...{FUNDER_ADDRESS[-4:]}"
            msg = (
                f"💰 <b>WALLET BALANCE</b>\n\n"
                f"Wallet: <code>{short_addr}</code>\n"
                f"USDC.e: <b>${usdc_bal:.2f}</b>\n"
                f"MATIC: {matic_bal:.4f} POL"
            )
            self.notifier.send(msg)
        except Exception as e:
            self.notifier.send(f"⚠️ Balance check failed: {str(e)[:200]}")

    # ── Parameter Commands ───────────────────────────

    def _cmd_set(self, args):
        """Handle /set commands for ALL parameters."""
        if len(args) < 2:
            msg = (
                "⚙️ <b>SET PARAMETERS</b>\n\n"
                "<b>Trading:</b>\n"
                "/set tp 90 — Take-profit %\n"
                "/set sl 30 — Stop-loss %\n"
                "/set amount 10 — Trade amount ($)\n"
                "/set percent 5 — Portfolio %\n"
                "/set size fixed — Fixed amount mode\n"
                "/set size percent — Portfolio % mode\n\n"
                "<b>Pricing:</b>\n"
                "/set slippage 0.05 — Max slippage ($)\n"
                "/set shareprice 0.50 — Target share price\n\n"
                "<b>Markets:</b>\n"
                "/set market 15m — Timeframe\n"
                "/set market 5m,15m — Multiple\n\n"
                "<b>Limits:</b>\n"
                "/set maxtrades 50 — Max trades/day\n"
                "/set cooldown 30 — Cooldown minutes\n"
                "/set tick 5 — Tick interval (sec)"
            )
            self.notifier.send(msg)
            return

        param = args[0].lower()
        value = args[1]

        try:
            if param == "tp":
                val = float(value)
                if val <= 0:
                    self.notifier.send("❌ TP must be > 0")
                    return
                changes = trading_config.update(take_profit_pct=val)
            elif param == "sl":
                val = float(value)
                if val <= 0:
                    self.notifier.send("❌ SL must be > 0")
                    return
                changes = trading_config.update(stop_loss_pct=val)
            elif param == "amount":
                val = float(value)
                if val <= 0:
                    self.notifier.send("❌ Amount must be > 0")
                    return
                changes = trading_config.update(trade_amount=val)
            elif param == "percent":
                val = float(value)
                if val <= 0 or val > 100:
                    self.notifier.send("❌ Percent must be 0-100")
                    return
                changes = trading_config.update(trade_percent=val)
            elif param == "size":
                mode = value.lower()
                if mode not in ("fixed", "percent"):
                    self.notifier.send("❌ Must be 'fixed' or 'percent'")
                    return
                changes = trading_config.update(trade_size_mode=mode)
            elif param == "slippage":
                val = float(value)
                if val < 0:
                    self.notifier.send("❌ Slippage must be >= 0")
                    return
                changes = trading_config.update(max_slippage=val)
            elif param == "shareprice":
                val = float(value)
                if val <= 0 or val >= 1:
                    self.notifier.send("❌ Share price must be 0-1 (e.g., 0.50)")
                    return
                changes = trading_config.update(share_price=val)
            elif param == "market":
                timeframes = [t.strip() for t in value.split(",")]
                valid_tfs = {"5m", "15m", "1h", "1d"}
                invalid = [t for t in timeframes if t not in valid_tfs]
                if invalid:
                    self.notifier.send(f"❌ Invalid: {invalid}. Use: {valid_tfs}")
                    return
                changes = trading_config.update(market_timeframes=timeframes)
            elif param == "maxtrades":
                val = int(value)
                if val <= 0:
                    self.notifier.send("❌ Must be > 0")
                    return
                changes = trading_config.update(max_trades_per_day=val)
            elif param == "cooldown":
                val = int(value)
                if val < 0:
                    self.notifier.send("❌ Must be >= 0")
                    return
                changes = trading_config.update(cooldown_minutes=val)
            elif param == "tick":
                val = int(value)
                if val < 1:
                    self.notifier.send("❌ Must be >= 1")
                    return
                changes = trading_config.update(tick_interval=val)
            else:
                self.notifier.send(f"❌ Unknown parameter: {param}\nType /set for list.")
                return

            if changes:
                self.notifier.send(f"✅ Updated:\n" + "\n".join(changes))
            else:
                self.notifier.send("⚠️ No changes made.")

        except ValueError:
            self.notifier.send(f"❌ Invalid value: {value}")

    # ── Control Commands ─────────────────────────────

    def _cmd_start(self, args):
        trading_config.update(bot_running=True)
        self.notifier.send("▶️ <b>Bot RESUMED</b>\nReady for /buy commands.")

    def _cmd_stop(self, args):
        trading_config.update(bot_running=False)
        self.notifier.send("⏸️ <b>Bot PAUSED</b>\nUse /start to resume.")

    def _cmd_help(self, args):
        msg = (
            "🤖 <b>POLYMARKET BOT COMMANDS</b>\n\n"
            "<b>🛒 Trading:</b>\n"
            "/buy up — Buy UP tokens\n"
            "/buy down — Buy DOWN tokens\n"
            "/buy up 5m — Buy UP on 5-min market\n"
            "/sell — Sell current position\n\n"
            "<b>🔄 Auto-Repeat:</b>\n"
            "/auto up — Auto re-buy UP each market\n"
            "/auto down — Auto re-buy DOWN each market\n"
            "/auto off — Stop auto-repeat\n\n"
            "<b>📊 Status:</b>\n"
            "/status — Bot + positions + P&L\n"
            "/config — All settings\n"
            "/pnl — P&L summary\n"
            "/trades — Recent trades\n"
            "/markets — Available markets\n"
            "/balance — Wallet balance\n\n"
            "<b>⚙️ Settings (ALL changeable):</b>\n"
            "/set tp <i>value</i> — Take-profit %\n"
            "/set sl <i>value</i> — Stop-loss %\n"
            "/set amount <i>value</i> — Stake ($)\n"
            "/set percent <i>value</i> — Portfolio %\n"
            "/set size <i>fixed/percent</i>\n"
            "/set slippage <i>value</i> — Max slippage\n"
            "/set shareprice <i>value</i> — Price target\n"
            "/set market <i>5m,15m,1h,1d</i>\n"
            "/set maxtrades <i>value</i> — Daily limit\n"
            "/set cooldown <i>value</i> — Cooldown min\n"
            "/set tick <i>value</i> — Check interval\n\n"
            "<b>🎮 Control:</b>\n"
            "/start — Resume\n"
            "/stop — Pause\n"
            "/help — This message"
        )
        self.notifier.send(msg)
