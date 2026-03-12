"""
╔══════════════════════════════════════════════════════════════╗
║   POLYMARKET TELEGRAM BOT — STRATEGY ENGINE v3.0            ║
╚══════════════════════════════════════════════════════════════╝
Manual BUY/SELL via Telegram + Auto-Repeat on market resolution.

Modes:
  MANUAL:      User sends /buy up or /buy down via Telegram
  AUTO-REPEAT: When market resolves, auto-places same bet on next market
  
Flow:
  1. User sends /buy up → Bot BUYs UP tokens
  2. Bot monitors TP/SL every tick
  3. TP hit → SELL tokens → profit locked
  4. SL hit → SELL tokens → loss cut
  5. Market resolves → Win/Loss recorded
  6. If AUTO_REPEAT=true → same bet on next market automatically
  7. User can /sell anytime to exit manually
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Callable
from enum import Enum

from candle_feed import CandleFeed
from trade_manager import TradeManager, Trade, TradeDirection, TradeStatus
from market_finder import MarketFinder, BTCMarket
from telegram_bot import TelegramNotifier
from config import trading_config


class BotState(Enum):
    IDLE = "IDLE"                        # Waiting for manual command
    IN_TRADE = "IN_TRADE"                # Active trade open — monitoring TP/SL
    WAITING_MARKET = "WAITING_MARKET"    # Auto-repeat: waiting for next market
    PAUSED = "PAUSED"                    # Bot paused by user


@dataclass
class StrategyState:
    """Tracks the current strategy state."""
    bot_state: BotState = BotState.IDLE
    last_direction: Optional[TradeDirection] = None
    last_timeframe: str = "15m"
    trades_today: int = 0
    last_trade_time: float = 0.0
    auto_repeat_active: bool = False
    auto_repeat_direction: Optional[TradeDirection] = None
    waiting_market_since: float = 0.0
    total_buys: int = 0
    total_sells: int = 0
    scheduled_time: Optional[str] = None          # e.g. "14:30"
    scheduled_direction: Optional[TradeDirection] = None
    scheduled_timeframe: Optional[str] = None


class StrategyEngine:
    """
    Manual trading engine.
    User controls BUY/SELL via Telegram. Bot handles TP/SL monitoring
    and auto-repeat when markets resolve.
    """

    def __init__(
        self,
        candle_feed: CandleFeed,
        trade_manager: TradeManager,
        market_finder: MarketFinder,
        telegram: Optional[TelegramNotifier] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ):
        self.feed = candle_feed
        self.trader = trade_manager
        self.market = market_finder
        self.telegram = telegram
        self.state = StrategyState()
        self._log = on_log or (lambda msg: None)
        self._current_market: Optional[BTCMarket] = None

        # Excel trade logger
        from trade_logger import TradeLogger
        self.logger = TradeLogger()
        self.logger.log_event("BOT_START", "Strategy engine initialized")

    # ── Main Tick ────────────────────────────────────

    def process_tick(self):
        """
        Called every few seconds. Handles:
        1. TP/SL monitoring for open trades
        2. Market resolution detection
        3. Auto-repeat logic
        """
        cfg = trading_config

        # Check if bot is paused
        if not cfg.bot_running:
            if self.state.bot_state != BotState.PAUSED:
                self.state.bot_state = BotState.PAUSED
                self._log("⏸️ Bot paused by user")
            return

        if self.state.bot_state == BotState.PAUSED:
            self.state.bot_state = BotState.IDLE
            self._log("▶️ Bot resumed — waiting for commands")

        # 1. Refresh candle data for BTC price display
        try:
            self.feed.fetch_recent(limit=5)
        except Exception:
            pass

        # 2. Check scheduled trades
        self._check_scheduled_trade()

        # 3. Monitor TP/SL if we have an open trade
        if self.trader.has_open_trade():
            self.state.bot_state = BotState.IN_TRADE
            self._monitor_tp_sl()
            self._check_market_resolution()

        # 4. Auto-repeat: waiting for next market
        elif self.state.auto_repeat_active and self.state.bot_state == BotState.WAITING_MARKET:
            self._handle_auto_repeat()

    # ── Manual BUY (called from Telegram) ────────────

    def manual_buy(self, direction: TradeDirection, timeframe: str = None) -> tuple[bool, str]:
        """
        Place a manual BUY order. Called from Telegram /buy command.
        Returns (success, message).
        """
        cfg = trading_config

        if not cfg.bot_running:
            return False, "⏸️ Bot is paused. Use /start first."

        if self.trader.has_open_trade():
            return False, "⚠️ Already have an open trade. /sell first or wait for resolution."

        # Check daily trade limit
        if self.state.trades_today >= cfg.max_trades_per_day:
            return False, f"⛔ Daily limit reached ({cfg.max_trades_per_day} trades/day)"

        tf = timeframe or cfg.market_timeframes[0]

        # Find market
        market = self.market.find_market_for_timeframe(tf)
        if not market:
            return False, f"❌ No active {tf} market found on Polymarket right now."

        # Refresh prices
        market = self.market.refresh_market_prices(market)
        self._current_market = market

        # Get token and price
        if direction == TradeDirection.UP:
            token_id = market.token_id_up
            current_price = market.price_up
        else:
            token_id = market.token_id_down
            current_price = market.price_down

        # Place trade
        trade = self.trader.place_trade(
            direction=direction,
            token_id=token_id,
            candle_number=1,
            current_price=current_price,
            timeframe=tf,
        )

        if trade:
            self.state.bot_state = BotState.IN_TRADE
            self.state.last_direction = direction
            self.state.last_timeframe = tf
            self.state.last_trade_time = time.time()
            self.state.trades_today += 1
            self.state.total_buys += 1

            self._log(
                f"🛒 BUY {trade.direction_emoji} | ${trade.amount:.2f} | "
                f"{trade.shares:.1f} shares @ ${trade.share_price:.4f} | "
                f"Market: {tf}"
            )

            # Telegram notification is sent by the command handler
            # (not here, to avoid double messages)
            dir_str = direction.value
            self.logger.log_event("BUY", f"{dir_str} | ${trade.amount:.2f} | {trade.shares:.1f} shares @ ${trade.share_price:.4f} | {tf}")

            dir_text = "UP 🟢" if direction == TradeDirection.UP else "DOWN 🔴"
            return True, (
                f"✅ BUY {dir_text} placed!\n\n"
                f"💰 Stake: ${trade.amount:.2f}\n"
                f"📊 Shares: {trade.shares:.1f} @ ${trade.share_price:.4f}\n"
                f"⏱ Market: {tf}\n"
                f"🎯 TP: {cfg.take_profit_pct:.0f}% | 🛑 SL: {cfg.stop_loss_pct:.0f}%\n"
                f"📝 Order: {trade.order_id[:20]}..."
            )
        else:
            err = self.trader._last_error or "Unknown error"
            return False, f"❌ Trade failed: {err}"

    # ── Manual BUY on Custom Market ──────────────────

    def manual_buy_custom(self, event, outcome_index: int) -> tuple[bool, str]:
        """
        Place a manual BUY on any Polymarket event.
        outcome_index: 0 = first outcome (Yes/Up), 1 = second (No/Down), etc.
        Returns (success, message).
        """
        from market_finder import PolymarketEvent
        cfg = trading_config

        if not cfg.bot_running:
            return False, "⏸️ Bot is paused. Use /start first."

        if self.trader.has_open_trade():
            return False, "⚠️ Already have an open trade. /sell first or wait for resolution."

        if self.state.trades_today >= cfg.max_trades_per_day:
            return False, f"⛔ Daily limit reached ({cfg.max_trades_per_day} trades/day)"

        token_id = event.get_token_for_outcome(outcome_index)
        if not token_id:
            return False, f"❌ Invalid outcome index: {outcome_index}"

        current_price = event.get_price_for_outcome(outcome_index)
        outcome_name = event.outcomes[outcome_index] if outcome_index < len(event.outcomes) else f"#{outcome_index}"

        # Store the custom market for monitoring
        self.market.custom_market = event

        # Determine direction for tracking
        direction = TradeDirection.UP if outcome_index == 0 else TradeDirection.DOWN

        trade = self.trader.place_trade(
            direction=direction,
            token_id=token_id,
            candle_number=1,
            current_price=current_price,
            timeframe="custom",
        )

        if trade:
            self.state.bot_state = BotState.IN_TRADE
            self.state.last_direction = direction
            self.state.last_timeframe = "custom"
            self.state.last_trade_time = time.time()
            self.state.trades_today += 1
            self.state.total_buys += 1

            self._log(
                f"🛒 BUY '{outcome_name}' | ${trade.amount:.2f} | "
                f"{trade.shares:.1f} shares @ ${trade.share_price:.4f} | "
                f"Market: {event.question[:40]}"
            )

            # Telegram notification is sent by the command handler

            return True, (
                f"✅ BUY <b>{outcome_name}</b> placed!\n\n"
                f"📋 Market: {event.question[:60]}\n"
                f"💰 Stake: ${trade.amount:.2f}\n"
                f"📊 Shares: {trade.shares:.1f} @ ${trade.share_price:.4f}\n"
                f"🎯 TP: {cfg.take_profit_pct:.0f}% | 🛑 SL: {cfg.stop_loss_pct:.0f}%\n"
                f"📝 Order: {trade.order_id[:20]}..."
            )
        else:
            err = self.trader._last_error or "Unknown error"
            return False, f"❌ Trade failed: {err}"

    # ── Manual SELL (called from Telegram) ───────────

    def manual_sell(self) -> tuple[bool, str]:
        """
        Manually sell/close the current position. Called from Telegram /sell command.
        Returns (success, message).
        """
        trade = self.trader.current_trade
        if not trade or trade.status != TradeStatus.OPEN:
            return False, "⚠️ No open trade to sell."

        # Get current price
        live_price = self.market.get_live_price(trade.token_id)
        if live_price is None:
            live_price = trade.current_price or trade.share_price

        # Place SELL order
        sold = self.trader.close_trade_tp(trade, live_price)

        # Override the close reason to MANUAL_SELL
        trade.close_reason = f"MANUAL_SELL{'|SOLD' if sold else '|SELL_FAILED'}"
        trade.status = TradeStatus.TP_HIT if trade.pnl >= 0 else TradeStatus.SL_HIT

        self.state.total_sells += 1
        self.state.auto_repeat_active = False  # Stop auto-repeat on manual sell

        pnl_sign = "+" if trade.pnl >= 0 else ""
        pnl_emoji = "💰" if trade.pnl >= 0 else "💸"

        self._log(
            f"📤 MANUAL SELL | {trade.direction_emoji} | "
            f"P&L: {pnl_sign}${trade.pnl:.2f} | "
            f"{'SOLD ✅' if sold else 'SELL FAILED ⚠️'}"
        )

        # Telegram notification is sent by the command handler

        self.logger.log_trade(trade)
        self.logger.log_event("MANUAL_SELL", f"P&L: {pnl_sign}${trade.pnl:.2f} | {'Sold' if sold else 'Failed'}")

        self.state.bot_state = BotState.IDLE

        return True, (
            f"{pnl_emoji} Position SOLD!\n\n"
            f"Direction: {trade.direction_emoji}\n"
            f"Entry: ${trade.share_price:.4f}\n"
            f"Exit: ${live_price:.4f}\n"
            f"P&L: <b>{pnl_sign}${trade.pnl:.2f}</b>\n"
            f"{'✅ Sell order filled' if sold else '⚠️ Sell order may have failed'}"
        )

    # ── Scheduled Trading ─────────────────────────────

    def schedule_trade(self, time_str: str, direction: TradeDirection, timeframe: str = None) -> tuple[bool, str]:
        """
        Schedule a trade at a specific time (HH:MM format).
        Returns (success, message).
        """
        # Validate time format
        try:
            parts = time_str.split(":")
            hour = int(parts[0])
            minute = int(parts[1])
            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                return False, "Invalid time. Use HH:MM format (e.g., 14:30)"
        except (ValueError, IndexError):
            return False, "Invalid time format. Use HH:MM (e.g., 14:30 or 2:24)"

        formatted_time = f"{hour:02d}:{minute:02d}"
        tf = timeframe or trading_config.market_timeframes[0]
        dir_text = "UP" if direction == TradeDirection.UP else "DOWN"

        self.state.scheduled_time = formatted_time
        self.state.scheduled_direction = direction
        self.state.scheduled_timeframe = tf

        self._log(f"Scheduled: BUY {dir_text} at {formatted_time} on {tf} market")

        return True, (
            f"⏰ <b>TRADE SCHEDULED</b>\n\n"
            f"Time: <b>{formatted_time}</b>\n"
            f"Direction: {'UP 🟢' if direction == TradeDirection.UP else 'DOWN 🔴'}\n"
            f"Market: {tf}\n\n"
            f"Bot will auto-buy at {formatted_time}.\n"
            f"Cancel with /schedule off"
        )

    def cancel_schedule(self) -> str:
        """Cancel any scheduled trade."""
        if self.state.scheduled_time:
            old_time = self.state.scheduled_time
            self.state.scheduled_time = None
            self.state.scheduled_direction = None
            self.state.scheduled_timeframe = None
            self._log(f"Cancelled scheduled trade at {old_time}")
            return f"Scheduled trade at {old_time} cancelled."
        return "No trade scheduled."

    def _check_scheduled_trade(self):
        """Check if a scheduled trade time has arrived."""
        if not self.state.scheduled_time or not self.state.scheduled_direction:
            return

        # Don't execute if already in a trade
        if self.trader.has_open_trade():
            return

        now = datetime.now()
        current_time = f"{now.hour:02d}:{now.minute:02d}"

        if current_time == self.state.scheduled_time:
            direction = self.state.scheduled_direction
            tf = self.state.scheduled_timeframe
            dir_text = "UP" if direction == TradeDirection.UP else "DOWN"

            self._log(f"⏰ Scheduled time {self.state.scheduled_time} reached! Placing {dir_text} trade...")

            # Clear schedule before executing (prevent double execution)
            self.state.scheduled_time = None
            self.state.scheduled_direction = None
            self.state.scheduled_timeframe = None

            success, msg = self.manual_buy(direction, tf)

            if success:
                self._log(f"Scheduled trade placed successfully!")
                if self.telegram:
                    self.telegram.send(f"⏰ <b>SCHEDULED TRADE EXECUTED</b>\n\n{msg}")
            else:
                self._log(f"Scheduled trade failed: {msg}")
                if self.telegram:
                    self.telegram.send(f"⏰ Scheduled trade FAILED:\n{msg}")

    # ── Auto-Repeat Logic ────────────────────────────

    def enable_auto_repeat(self, direction: TradeDirection) -> str:
        """Enable auto-repeat for a direction."""
        self.state.auto_repeat_active = True
        self.state.auto_repeat_direction = direction
        dir_text = "UP 🟢" if direction == TradeDirection.UP else "DOWN 🔴"
        self._log(f"🔄 Auto-repeat ENABLED for {dir_text}")
        return f"🔄 Auto-repeat enabled: will keep buying {dir_text} on each new market"

    def disable_auto_repeat(self) -> str:
        """Disable auto-repeat."""
        self.state.auto_repeat_active = False
        self.state.auto_repeat_direction = None
        self._log("⏹️ Auto-repeat DISABLED")
        return "⏹️ Auto-repeat disabled"

    def _handle_auto_repeat(self):
        """When waiting for next market, try to place the auto-repeat trade."""
        if not self.state.auto_repeat_direction:
            self.state.auto_repeat_active = False
            self.state.bot_state = BotState.IDLE
            return

        cfg = trading_config
        if self.state.trades_today >= cfg.max_trades_per_day:
            self._log(f"⛔ Daily limit ({cfg.max_trades_per_day}) — auto-repeat paused")
            return

        tf = self.state.last_timeframe or cfg.market_timeframes[0]
        market = self.market.find_market_for_timeframe(tf)

        if not market:
            # No market yet — keep waiting
            wait_sec = time.time() - self.state.waiting_market_since
            if int(wait_sec) % 60 == 0 and int(wait_sec) > 0:
                self._log(f"⏳ Auto-repeat: waiting for next {tf} market ({int(wait_sec)}s)...")
            return

        # Check if this is a NEW market (not the same one we just traded)
        if self._current_market and market.condition_id == self._current_market.condition_id:
            return  # Same market — still waiting

        self._log(f"🔄 Auto-repeat: New market found! Placing {self.state.auto_repeat_direction.value} trade...")

        success, msg = self.manual_buy(
            direction=self.state.auto_repeat_direction,
            timeframe=tf,
        )

        if success:
            self._log(f"✅ Auto-repeat trade placed!")
        else:
            self._log(f"⚠️ Auto-repeat failed: {msg}")
            # Will retry next tick

    # ── TP/SL Monitoring ─────────────────────────────

    def _monitor_tp_sl(self):
        """Monitor the open trade for TP/SL conditions."""
        if not self.trader.current_trade:
            return

        trade = self.trader.current_trade
        if trade.status != TradeStatus.OPEN:
            return

        # Get live price
        live_price = self.market.get_live_price(trade.token_id)
        if live_price is None:
            return

        # Update current price
        self.trader.update_current_price(live_price)

        # Check TP/SL
        result = self.trader.check_tp_sl(live_price)

        if result == "TP":
            self._log(
                f"🎯 TAKE-PROFIT HIT! Price: ${live_price:.4f} | "
                f"Entry: ${trade.share_price:.4f}"
            )
            sold = self.trader.close_trade_tp(trade, live_price)
            if sold:
                self._log(f"💰 SOLD {trade.shares:.1f} shares @ ${live_price:.4f} — Profit locked!")
            else:
                self._log(f"⚠️ SELL order failed — tokens may still be held")

            self.state.total_sells += 1

            if self.telegram:
                self.telegram.send_trade_closed(trade)

            self.logger.log_trade(trade)
            self.logger.log_event("TAKE_PROFIT", f"TP hit @ {live_price:.4f} | P&L: ${trade.pnl:+.2f}")

            self._after_trade_close()

        elif result == "SL":
            self._log(
                f"🛑 STOP-LOSS HIT! Price: ${live_price:.4f} | "
                f"Entry: ${trade.share_price:.4f}"
            )
            sold = self.trader.close_trade_sl(trade, live_price)
            if sold:
                self._log(f"📤 SOLD {trade.shares:.1f} shares @ ${live_price:.4f} — Loss cut!")
            else:
                self._log(f"⚠️ SELL order failed — tokens may still be held")

            self.state.total_sells += 1

            if self.telegram:
                self.telegram.send_trade_closed(trade)

            self.logger.log_trade(trade)
            self.logger.log_event("STOP_LOSS", f"SL hit @ {live_price:.4f} | P&L: ${trade.pnl:+.2f}")

            self._after_trade_close()

    def _check_market_resolution(self):
        """Check if the current market has resolved (expired)."""
        if not self._current_market:
            return

        trade = self.trader.current_trade
        if not trade or trade.status != TradeStatus.OPEN:
            return

        # Check if market expired
        if self._current_market.is_expired:
            self._log("⏰ Market resolved! Checking result...")

            # Get final price
            live_price = self.market.get_live_price(trade.token_id)

            if live_price is not None and live_price > 0.5:
                # Won (price > 0.5 means our side won)
                self.trader.resolve_trade(trade, won=True, reason="MARKET_WIN")
                self._log(f"🎉 MARKET WIN! Token worth ${live_price:.4f} → P&L: +${trade.pnl:.2f}")
            else:
                # Lost or unknown
                self.trader.resolve_trade(trade, won=False, reason="MARKET_LOSS")
                self._log(f"💔 MARKET LOSS! Token worth ${live_price:.4f if live_price else 0:.4f} → P&L: ${trade.pnl:.2f}")

            if self.telegram:
                self.telegram.send_trade_closed(trade)

            self.logger.log_trade(trade)
            self.logger.log_event("MARKET_RESOLVED", f"{trade.close_reason} | P&L: ${trade.pnl:+.2f}")

            self._after_trade_close()

    def _after_trade_close(self):
        """Handle post-trade logic: auto-redeem if profitable, then auto-repeat or go idle."""
        import threading

        # Auto-redeem winning tokens back to USDC
        trade = self.trader.current_trade
        if trade and trade.pnl >= 0:
            self._log("🔄 Auto-redeem: converting winning tokens to USDC...")
            threading.Thread(target=self._run_auto_redeem, daemon=True).start()

        if self.state.auto_repeat_active and self.state.auto_repeat_direction:
            self.state.bot_state = BotState.WAITING_MARKET
            self.state.waiting_market_since = time.time()
            self._log(
                f"🔄 Auto-repeat: waiting for next market to place "
                f"{self.state.auto_repeat_direction.value} trade..."
            )
        else:
            self.state.bot_state = BotState.IDLE
            self._log("Trade closed. Waiting for /buy command...")

    def _run_auto_redeem(self):
        """Background task: redeem winning tokens to USDC."""
        try:
            # Wait a few seconds for market to fully settle
            time.sleep(5)

            if self.trader._redeem_manager:
                redeemed = self.trader._redeem_manager.auto_redeem()
                if redeemed > 0:
                    self._log(f"✅ Auto-redeem: {redeemed} position(s) redeemed to USDC!")
                    if self.telegram:
                        bal = self.trader._redeem_manager.get_usdc_balance()
                        self.telegram.send(
                            f"✅ <b>AUTO-REDEEM</b>\n\n"
                            f"Redeemed {redeemed} position(s) to USDC\n"
                            f"Balance: <b>${bal:.2f}</b>"
                        )
                else:
                    self._log("Auto-redeem: no positions to redeem (may settle later)")
            else:
                self._log("Auto-redeem: redeem manager not available")
        except Exception as e:
            self._log(f"Auto-redeem error: {str(e)[:100]}")

