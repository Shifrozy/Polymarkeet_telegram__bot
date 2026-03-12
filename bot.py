"""
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║      ₿  POLYMARKET TELEGRAM BOT  v3.0                               ║
║      ──────────────────────────────────────                          ║
║      Manual BUY/SELL via Telegram + Auto-Repeat                      ║
║                                                                      ║
║      • /buy up, /buy down — trade BTC UP/DOWN markets               ║
║      • /search, /trade — trade any Polymarket event                 ║
║      • /sell — close position anytime                               ║
║      • /auto up — auto-repeat on market resolution                  ║
║      • /set — change all parameters live via Telegram               ║
║      • TP/SL monitoring every tick                                  ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝

Usage:
  python bot.py              # Run bot (paper mode by default)
  python bot.py --live       # Run bot in live mode
  python bot.py --status     # Show current status and exit
"""

import sys
import os
import time
import signal
import argparse
import atexit
from datetime import datetime

# Force UTF-8 for Windows terminal
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import config
from config import trading_config
from candle_feed import CandleFeed
from trade_manager import TradeManager
from market_finder import MarketFinder
from strategy import StrategyEngine
from telegram_bot import TelegramNotifier, TelegramCommandHandler


# ── Globals ─────────────────────────────────────────
running = True
_engine_ref = None  # Store engine reference for shutdown logging
_stop_logged = False  # Prevent duplicate stop entries


def _log_stop():
    """Write BOT_STOP event to Excel (called on exit)."""
    global _stop_logged
    if _stop_logged or _engine_ref is None:
        return
    _stop_logged = True
    try:
        _engine_ref.logger._write_event("BOT_STOP", "Bot stopped")
    except Exception:
        pass


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    global running
    running = False
    _log_stop()  # Write stop event immediately on Ctrl+C


def log(msg: str):
    """Print a timestamped log message."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}]  {msg}")


def print_banner():
    """Print startup banner."""
    print()
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║                                                          ║")
    print("  ║   ₿  POLYMARKET TELEGRAM BOT  v3.0                      ║")
    print("  ║   ──────────────────────────────────                     ║")
    print("  ║   Manual Trading via Telegram                            ║")
    print("  ║   + Auto-Repeat on Market Resolution                     ║")
    print("  ║                                                          ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print()


def print_strategy_summary():
    """Print a summary of the trading setup."""
    cfg = trading_config
    size = f"${cfg.trade_amount:.2f} fixed" if cfg.trade_size_mode == "fixed" else f"{cfg.trade_percent:.1f}% of portfolio"

    print("  ┌─────────────────────────────────────────────┐")
    print("  │             Trading Setup                    │")
    print("  ├─────────────────────────────────────────────┤")
    print(f"  │  Mode:        Manual via Telegram            │")
    print(f"  │  Trade Size:  {size:<30s}│")
    print(f"  │  TP / SL:     {cfg.take_profit_pct:.0f}% / {cfg.stop_loss_pct:.0f}%{' ' * (27 - len(f'{cfg.take_profit_pct:.0f}% / {cfg.stop_loss_pct:.0f}%'))}│")
    print(f"  │  Markets:     {', '.join(cfg.market_timeframes):<30s}│")
    print(f"  │  Slippage:    ${cfg.max_slippage:.3f}{' ' * (28 - len(f'${cfg.max_slippage:.3f}'))}│")
    print(f"  │  Auto-Repeat: {'ON' if cfg.auto_repeat else 'OFF':<30s}│")
    print(f"  │  Daily Limit: {cfg.max_trades_per_day} trades/day{' ' * (20 - len(str(cfg.max_trades_per_day)))}│")
    print("  │  Commands:    /help for full list            │")
    print("  └─────────────────────────────────────────────┘")
    print()


def validate_and_start():
    """Validate configuration and start the bot."""
    errors = config.validate_config()
    if errors:
        print("\n  ❌ Configuration Errors:")
        for err in errors:
            print(f"    • {err}")
        print("\n  Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    mode = "PAPER MODE" if config.PAPER_MODE else "LIVE TRADING"
    mode_icon = "🔴" if config.PAPER_MODE else "🟢"
    print(f"  Mode: {mode_icon} {mode}")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


def run_bot():
    """Main bot loop."""
    global running
    signal.signal(signal.SIGINT, signal_handler)

    cfg = trading_config

    # Initialize Telegram
    log("Initializing Telegram...")
    telegram = TelegramNotifier()
    if telegram.is_enabled:
        log("✓ Telegram connected")
    else:
        log("⚠ Telegram not configured — notifications disabled")

    # Initialize components
    log("Initializing components...")
    feed = CandleFeed(interval=cfg.get_candle_interval())
    trader = TradeManager()
    finder = MarketFinder()

    # Create strategy engine with console logging
    global _engine_ref
    engine = StrategyEngine(
        candle_feed=feed,
        trade_manager=trader,
        market_finder=finder,
        telegram=telegram,
        on_log=log,
    )
    _engine_ref = engine
    atexit.register(_log_stop)  # Safety net: also log on process exit

    # Start Telegram command handler
    cmd_handler = TelegramCommandHandler(
        notifier=telegram,
        trader=trader,
        engine=engine,
        market_finder=finder,
    )
    cmd_handler.start()
    if telegram.is_enabled:
        log("✓ Telegram command handler started")

    # Initial data fetch
    log("Fetching BTC price data...")
    try:
        feed.fetch_recent(limit=10)
        btc = feed.get_btc_price()
        log(f"✓ BTC Price: ${btc:,.2f}")
        log(f"✓ Loaded {len(feed.get_closed_candles())} closed candles")
    except Exception as e:
        log(f"✗ Failed to fetch candle data: {e}")
        log("  Will retry when bot starts...")

    # Check for market
    log("Searching for BTC markets on Polymarket...")
    for tf in cfg.market_timeframes:
        market = finder.find_market_for_timeframe(tf)
        if market:
            log(f"✓ [{tf}] Found: {market.question[:60]}")
        else:
            log(f"⚠ [{tf}] No active market found")

    print()
    print("  ✅ Bot started! Waiting for Telegram commands.")
    print("  ── Send /help in Telegram for all commands ──")
    print("  ── Press Ctrl+C to stop ──")
    print()

    # Send Telegram startup notification
    telegram.send_bot_started()

    # Main loop — simple console logging
    last_tick = 0
    last_status = 0
    STATUS_INTERVAL = 60  # Print status every 60 seconds

    while running:
        now = time.time()

        # Check if candle interval needs updating
        current_interval = cfg.get_candle_interval()
        if feed.interval != current_interval:
            feed.set_interval(current_interval)
            log(f"Candle interval changed to {current_interval}")

        # Process strategy tick
        if now - last_tick >= cfg.tick_interval:
            try:
                engine.process_tick()
            except Exception as e:
                log(f"⚠ Error: {str(e)[:100]}")
                telegram.send_error(str(e)[:200])
            last_tick = now

        # Print periodic status
        if now - last_status >= STATUS_INTERVAL:
            state = engine.state
            trade_info = ""
            if trader.has_open_trade():
                t = trader.current_trade
                upnl = t.unrealized_pnl
                sign = "+" if upnl >= 0 else ""
                trade_info = f" | Open: {t.direction_emoji} ${t.amount:.2f} P&L:{sign}${upnl:.2f}"

            auto_info = ""
            if state.auto_repeat_active:
                auto_info = f" | Auto: {state.auto_repeat_direction.value}" if state.auto_repeat_direction else ""

            try:
                btc = feed.get_btc_price()
                btc_text = f"BTC: ${btc:,.0f}" if btc > 0 else "BTC: ---"
            except Exception:
                btc_text = "BTC: ---"

            log(
                f"[{state.bot_state.value}] {btc_text} | "
                f"Trades: {state.trades_today}/{cfg.max_trades_per_day} | "
                f"P&L: ${trader.total_pnl:+.2f}{trade_info}{auto_info}"
            )
            last_status = now

        time.sleep(0.5)

    # Shutdown
    cmd_handler.stop()
    telegram.send_bot_stopped()
    _log_stop()  # Write BOT_STOP to Excel

    print()
    log("🛑 Bot stopped by user.")
    log(f"Total trades: {trader.total_trades} | P&L: ${trader.total_pnl:+.2f}")


def show_status():
    """Show current bot status and exit."""
    trader = TradeManager()
    print()
    print("  📊 Bot Status")
    print("  ─────────────")
    print(f"  Total Trades:  {trader.total_trades}")
    print(f"  Wins:          {trader.wins}")
    print(f"  Losses:        {trader.losses}")
    print(f"  Win Rate:      {trader.win_rate:.1f}%")
    print(f"  Total P&L:     ${trader.total_pnl:+.2f}")
    print(f"  Daily P&L:     ${trader.daily_pnl:+.2f}")
    print(f"  Total Volume:  ${trader.total_volume:.2f}")

    if trader.recent_trades:
        print()
        print("  Recent Trades:")
        for t in trader.recent_trades:
            pnl_sign = "+" if t.pnl >= 0 else ""
            print(f"    {t.status_emoji} {t.direction_emoji} | {t.entry_time} | {pnl_sign}${t.pnl:.2f} | {t.close_reason}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Telegram Bot - Manual Trading via Telegram"
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Run in live trading mode (requires .env credentials)"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show current status and exit"
    )
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    # Override paper mode if --live is passed
    if args.live:
        config.PAPER_MODE = False

    print_banner()
    print_strategy_summary()
    validate_and_start()
    run_bot()


if __name__ == "__main__":
    main()
