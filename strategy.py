"""
╔══════════════════════════════════════════════════════════════╗
║   POLYMARKET TELEGRAM BOT — STRATEGY ENGINE                 ║
╚══════════════════════════════════════════════════════════════╝
Implements configurable long/short strategy with TP/SL,
progressive entries, and continuous re-entry after close.

Strategy Rules:
  - LONG mode:  2 red candles → BUY UP   (contrarian)
  - SHORT mode: 2 green candles → BUY DOWN (contrarian)
  - Or: LONG=always buy UP, SHORT=always buy DOWN (manual mode)
  - Progressive entries on losses (3rd, 4th, 5th candle)
  - TP/SL monitoring on every tick
  - Auto re-entry after position closes
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Callable
from enum import Enum

from candle_feed import Candle, CandleFeed
from trade_manager import TradeManager, Trade, TradeDirection, TradeStatus
from market_finder import MarketFinder, BTCMarket
from telegram_bot import TelegramNotifier
from config import trading_config


class BotState(Enum):
    SCANNING = "SCANNING"                # Watching candles for a signal
    SIGNAL_DETECTED = "SIGNAL_DETECTED"  # 2 same-color candles detected
    WAITING_ENTRY = "WAITING_ENTRY"      # Waiting for right price to enter
    IN_TRADE = "IN_TRADE"                # Active trade open
    PROGRESSIVE = "PROGRESSIVE"          # In progressive entry sequence
    COOLDOWN = "COOLDOWN"                # Cooldown after max entries
    PAUSED = "PAUSED"                    # Bot paused by user


@dataclass
class StrategyState:
    """Tracks the current strategy state."""
    bot_state: BotState = BotState.SCANNING
    signal_direction: Optional[TradeDirection] = None
    signal_candle_color: Optional[str] = None
    consecutive_count: int = 0
    current_candle_number: int = 0
    progressive_entry: int = 0
    cooldown_until: float = 0.0
    entry_wait_start: float = 0.0
    last_signal_time: float = 0.0
    last_processed_candle_time: float = 0.0
    total_signals: int = 0
    skipped_signals: int = 0
    trades_today: int = 0
    last_trade_time: float = 0.0

    @property
    def is_cooldown_active(self) -> bool:
        return self.bot_state == BotState.COOLDOWN and time.time() < self.cooldown_until

    @property
    def cooldown_remaining_sec(self) -> float:
        if not self.is_cooldown_active:
            return 0.0
        return max(0, self.cooldown_until - time.time())

    @property
    def entry_wait_elapsed_sec(self) -> float:
        if self.entry_wait_start == 0:
            return 0.0
        return time.time() - self.entry_wait_start


class StrategyEngine:
    """
    The core strategy engine.
    Processes candle data, generates trade signals, monitors TP/SL.
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

    def process_tick(self):
        """
        Called every few seconds. Drives the strategy FSM.
        Handles scanning, entries, TP/SL monitoring, and re-entries.
        """
        cfg = trading_config

        # Check if bot is paused
        if not cfg.bot_running:
            if self.state.bot_state != BotState.PAUSED:
                self.state.bot_state = BotState.PAUSED
                self._log("⏸️ Bot paused by user")
            return

        if self.state.bot_state == BotState.PAUSED:
            self.state.bot_state = BotState.SCANNING
            self._log("▶️ Bot resumed — scanning for signals")

        # 1. Refresh candle data
        try:
            self.feed.fetch_recent(limit=10)
        except Exception as e:
            self._log(f"⚠ Candle fetch error: {e}")
            return

        # 2. Monitor TP/SL for open trades
        if self.trader.has_open_trade():
            self._monitor_tp_sl()

        # 3. Check cooldown
        if self.state.is_cooldown_active:
            return

        if self.state.bot_state == BotState.COOLDOWN and not self.state.is_cooldown_active:
            self._log("✅ Cooldown ended — resuming scanning")
            self._reset_state()

        # 4. Check for new closed candle
        closed = self.feed.get_closed_candles()
        if not closed:
            return

        latest_closed = closed[-1]

        # Avoid reprocessing the same candle
        if latest_closed.close_time <= self.state.last_processed_candle_time:
            if self.state.bot_state == BotState.WAITING_ENTRY:
                if self._check_entry_timeout():
                    return
                self._attempt_trade()
            return

        # New candle closed!
        self.state.last_processed_candle_time = latest_closed.close_time
        self._log(f"🕯 Candle closed: {latest_closed}")

        # 5. State machine
        if self.state.bot_state == BotState.SCANNING:
            self._handle_scanning(closed)

        elif self.state.bot_state == BotState.SIGNAL_DETECTED:
            self._handle_signal(closed)

        elif self.state.bot_state == BotState.IN_TRADE:
            self._handle_trade_result(latest_closed)

        elif self.state.bot_state == BotState.PROGRESSIVE:
            self._handle_trade_result(latest_closed)

        elif self.state.bot_state == BotState.WAITING_ENTRY:
            if not self._check_entry_timeout():
                self._attempt_trade()

    def _monitor_tp_sl(self):
        """Monitor the open trade for TP/SL conditions."""
        if not self.trader.current_trade:
            return

        trade = self.trader.current_trade
        if trade.status != TradeStatus.OPEN:
            return

        # Get live price for the token we bought
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

            if self.telegram:
                self.telegram.send_trade_closed(trade)

            # Auto re-entry: reset and look for new signal
            self._reset_state()
            self._log("🔄 Auto re-entry — scanning for new signal")

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

            if self.telegram:
                self.telegram.send_trade_closed(trade)

            # Auto re-entry: reset and look for new signal
            self._reset_state()
            self._log("🔄 Auto re-entry — scanning for new signal")

    def _get_signal_direction(self) -> tuple[Optional[TradeDirection], str]:
        """
        Determine trade direction based on strategy config.
        Returns (direction, reason_text).
        """
        cfg = trading_config
        if cfg.strategy_direction == "LONG":
            return TradeDirection.UP, "LONG strategy"
        else:
            return TradeDirection.DOWN, "SHORT strategy"

    def _handle_scanning(self, closed: list[Candle]):
        """Look for entry signals based on candle patterns."""
        cfg = trading_config
        signal_count = cfg.consecutive_candles_signal

        if len(closed) < signal_count:
            return

        last_n = closed[-signal_count:]
        colors = [c.color for c in last_n]

        direction = None
        reason = ""

        if cfg.strategy_direction == "LONG":
            # LONG mode: 2 red candles → BUY UP (contrarian)
            if all(c == "red" for c in colors):
                direction = TradeDirection.UP
                reason = "🔴🔴 RED candles → BUY UP (LONG contrarian)"
            # Also enter on 2 green candles (momentum)
            elif all(c == "green" for c in colors):
                direction = TradeDirection.UP
                reason = "🟢🟢 GREEN candles → BUY UP (LONG momentum)"

        elif cfg.strategy_direction == "SHORT":
            # SHORT mode: 2 green candles → BUY DOWN (contrarian)
            if all(c == "green" for c in colors):
                direction = TradeDirection.DOWN
                reason = "🟢🟢 GREEN candles → BUY DOWN (SHORT contrarian)"
            # Also enter on 2 red candles (momentum)
            elif all(c == "red" for c in colors):
                direction = TradeDirection.DOWN
                reason = "🔴🔴 RED candles → BUY DOWN (SHORT momentum)"

        if direction:
            self._log(f"🎯 Signal: {reason}")
            self.state.signal_direction = direction
            self.state.signal_candle_color = colors[-1]
            self.state.consecutive_count = signal_count
            self.state.current_candle_number = signal_count
            self.state.bot_state = BotState.SIGNAL_DETECTED
            self.state.total_signals += 1
            self.state.last_signal_time = time.time()
            self._attempt_trade()

    def _handle_signal(self, closed: list[Candle]):
        """Signal was detected — waiting for entry or processing."""
        self._attempt_trade()

    def _attempt_trade(self):
        """Try to place a trade based on current signal."""
        if self.trader.has_open_trade():
            self._log("⚠ Trade already open — skipping overlap")
            return

        direction = self.state.signal_direction
        if not direction:
            return

        # Find the current Polymarket market
        self._current_market = self.market.find_current_market()

        timeframe = trading_config.market_timeframes[0]

        if self._current_market:
            # Refresh live prices from CLOB
            self._current_market = self.market.refresh_market_prices(self._current_market)
            timeframe = self._current_market.timeframe

            # Determine which token to buy
            if direction == TradeDirection.UP:
                token_id = self._current_market.token_id_up
                current_price = self._current_market.price_up
            else:
                token_id = self._current_market.token_id_down
                current_price = self._current_market.price_down

            candle_num = self.state.current_candle_number + 1

            self._log(
                f"📈 Attempting {direction.value} trade "
                f"(candle #{candle_num}) @ ${current_price:.4f}/share | "
                f"Market: {self._current_market.question[:50]}"
            )

            trade = self.trader.place_trade(
                direction=direction,
                token_id=token_id,
                candle_number=candle_num,
                current_price=current_price,
                timeframe=timeframe,
            )

            if trade:
                self._log(
                    f"✅ LIVE trade placed: {trade.direction_emoji} | "
                    f"${trade.amount:.2f} | {trade.shares:.1f} shares | "
                    f"Order: {trade.order_id[:20]}..."
                )
                self.state.bot_state = BotState.IN_TRADE
                self.state.entry_wait_start = 0
                self.state.last_trade_time = time.time()
                self.state.trades_today += 1

                # Send Telegram notification
                if self.telegram:
                    self.telegram.send_trade_opened(trade)
            else:
                err = self.trader._last_error or "Price not right"
                self._log(f"⏳ Trade not placed: {err}")
                self.state.bot_state = BotState.WAITING_ENTRY
                if self.state.entry_wait_start == 0:
                    self.state.entry_wait_start = time.time()
                self._check_entry_timeout()
        else:
            # No market found — use paper simulation
            self._log("📋 No Polymarket market found — using paper simulation")
            candle_num = self.state.current_candle_number + 1

            trade = self.trader.place_trade(
                direction=direction,
                token_id=f"PAPER-{direction.value}-{int(time.time())}",
                candle_number=candle_num,
                current_price=trading_config.share_price,
                timeframe=timeframe,
            )

            if trade:
                self._log(
                    f"📝 Paper trade: {trade.direction_emoji} | "
                    f"${trade.amount:.2f} | Candle #{candle_num}"
                )
                self.state.bot_state = BotState.IN_TRADE
                self.state.last_trade_time = time.time()
                self.state.trades_today += 1

                if self.telegram:
                    self.telegram.send_trade_opened(trade)

    def _check_entry_timeout(self) -> bool:
        """Check if we've waited too long for the right price."""
        cfg = trading_config
        if self.state.entry_wait_elapsed_sec > cfg.max_entry_wait_minutes * 60:
            self._log(
                f"⏰ Entry timeout ({cfg.max_entry_wait_minutes}min) — "
                f"skipping this signal"
            )
            self.state.skipped_signals += 1
            self._reset_state()
            return True
        return False

    def _handle_trade_result(self, latest_closed: Candle):
        """Check if the current trade won or lost based on candle close."""
        trade = self.trader.current_trade
        if not trade:
            self._reset_state()
            return

        # If trade was already closed by TP/SL, skip
        if trade.status not in (TradeStatus.OPEN, TradeStatus.PENDING):
            self._reset_state()
            return

        candle_color = latest_closed.color
        won = False

        if trade.direction == TradeDirection.UP:
            needed_color = "green"
            won = (candle_color == "green")
        else:
            needed_color = "red"
            won = (candle_color == "red")

        self.trader.resolve_trade(trade, won, "WIN" if won else "LOSS")

        dir_label = trade.direction.value
        candle_icon = "🟢" if candle_color == "green" else "🔴"

        if won:
            self._log(
                f"🎉 WIN! Bet {dir_label} (needed {needed_color}) → "
                f"Candle closed {candle_icon}{candle_color.upper()} ✅ | "
                f"P&L: +${trade.pnl:.2f} | #{trade.candle_number}"
            )
            if self.telegram:
                self.telegram.send_trade_closed(trade)
            # Win → reset and auto re-enter
            self._reset_state()
            self._log("🔄 Auto re-entry — scanning for new signal")
        else:
            self._log(
                f"💔 LOSS! Bet {dir_label} (needed {needed_color}) → "
                f"Candle closed {candle_icon}{candle_color.upper()} ❌ | "
                f"P&L: ${trade.pnl:.2f} | #{trade.candle_number}"
            )
            if self.telegram:
                self.telegram.send_trade_closed(trade)
            # Check progressive entry logic
            self._handle_progressive_loss(trade)

    def _handle_progressive_loss(self, trade: Trade):
        """Handle progressive entries after a loss."""
        cfg = trading_config
        candle_num = trade.candle_number

        if candle_num < cfg.max_progressive_entries:
            self.state.current_candle_number = candle_num
            self.state.bot_state = BotState.PROGRESSIVE
            self.state.progressive_entry = candle_num + 1

            self._log(
                f"📊 Progressive entry → will trade candle "
                f"#{self.state.progressive_entry}"
            )
            self._attempt_trade()
        else:
            self.state.cooldown_until = time.time() + (cfg.cooldown_minutes * 60)
            self.state.bot_state = BotState.COOLDOWN
            self._log(
                f"❄️ Max progressive entries reached (candle #{candle_num}) — "
                f"Cooldown for {cfg.cooldown_minutes} minutes"
            )

    def _reset_state(self):
        """Reset to scanning mode."""
        self.state.bot_state = BotState.SCANNING
        self.state.signal_direction = None
        self.state.signal_candle_color = None
        self.state.consecutive_count = 0
        self.state.current_candle_number = 0
        self.state.progressive_entry = 0
        self.state.entry_wait_start = 0.0
