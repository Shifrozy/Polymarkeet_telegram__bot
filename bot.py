"""
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║      ₿  POLYMARKET TELEGRAM BOT  v2.0                               ║
║      ─────────────────────────────────                               ║
║      Configurable BTC Strategy Bot with Telegram Integration         ║
║                                                                      ║
║      • Choose LONG or SHORT direction                                ║
║      • Configurable TP% and SL%                                      ║
║      • Fixed amount or % of portfolio                                ║
║      • Multi-timeframe market selection (5m, 15m, 1h, 1d)           ║
║      • Continuous auto re-entry after trade closes                   ║
║      • Telegram notifications + live commands                        ║
║      • Terminal dashboard with Rich                                  ║
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
from datetime import datetime

# Force UTF-8 for Windows terminal (Rich uses emojis)
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.live import Live
from rich.text import Text
from rich.panel import Panel
from rich import box

import config
from config import trading_config
from candle_feed import CandleFeed
from trade_manager import TradeManager
from market_finder import MarketFinder
from strategy import StrategyEngine
from dashboard import Dashboard
from telegram_bot import TelegramNotifier, TelegramCommandHandler


# ── Globals ─────────────────────────────────────────
console = Console()
running = True


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    global running
    running = False


def print_banner():
    """Print startup banner."""
    banner = """
[bold bright_blue]
  ╔══════════════════════════════════════════════════════════╗
  ║                                                          ║
  ║   ₿  POLYMARKET TELEGRAM BOT  v2.0                      ║
  ║   ──────────────────────────────────                     ║
  ║   Configurable Strategy with Telegram                    ║
  ║   Notifications & Live Commands                          ║
  ║                                                          ║
  ╚══════════════════════════════════════════════════════════╝
[/bold bright_blue]
"""
    console.print(banner)


def print_strategy_summary():
    """Print a summary of the bot's strategy."""
    cfg = trading_config
    direction = "LONG (buy UP)" if cfg.strategy_direction == "LONG" else "SHORT (buy DOWN)"
    size = f"${cfg.trade_amount:.2f} fixed" if cfg.trade_size_mode == "fixed" else f"{cfg.trade_percent:.1f}% of portfolio"

    summary = f"""
[bold white]Strategy Summary:[/bold white]
  [yellow]A.[/yellow] Direction: [bold]{direction}[/bold]
  [yellow]B.[/yellow] Trade Size: {size}
  [yellow]C.[/yellow] Take-Profit: [green]{cfg.take_profit_pct:.0f}%[/green] | Stop-Loss: [red]{cfg.stop_loss_pct:.0f}%[/red]
  [yellow]D.[/yellow] Markets: {', '.join(cfg.market_timeframes)}
  [yellow]E.[/yellow] Continuous execution: auto re-entry after trade closes
  [yellow]F.[/yellow] Progressive entries on losses (up to candle #5)
  [yellow]G.[/yellow] Telegram notifications on trade open/close/P&L
  [yellow]H.[/yellow] Live commands: /status /config /set /stop /start
"""
    console.print(Panel(summary, title="🧠 Strategy", border_style="cyan"))


def validate_and_start():
    """Validate configuration and start the bot."""
    errors = config.validate_config()
    if errors:
        console.print("\n[bold red]❌ Configuration Errors:[/bold red]")
        for err in errors:
            console.print(f"  • {err}")
        console.print(
            "\n[dim]Copy .env.example to .env and fill in your credentials.[/dim]"
        )
        sys.exit(1)

    mode = "[red]🔴 PAPER MODE[/red]" if config.PAPER_MODE else "[green]🟢 LIVE TRADING[/green]"
    console.print(f"\n  Mode: {mode}")
    console.print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    console.print()


def run_bot():
    """Main bot loop."""
    global running
    signal.signal(signal.SIGINT, signal_handler)

    cfg = trading_config

    # Initialize Telegram
    console.print("[dim]Initializing Telegram...[/dim]")
    telegram = TelegramNotifier()
    if telegram.is_enabled:
        console.print("[green]✓[/green] Telegram connected")
    else:
        console.print("[yellow]⚠ Telegram not configured — notifications disabled[/yellow]")

    # Initialize components
    console.print("[dim]Initializing components...[/dim]")
    feed = CandleFeed(interval=cfg.get_candle_interval())
    trader = TradeManager()
    finder = MarketFinder()

    # Create strategy engine
    dashboard = None

    def on_log(msg: str):
        if dashboard:
            dashboard.add_log(msg)

    engine = StrategyEngine(
        candle_feed=feed,
        trade_manager=trader,
        market_finder=finder,
        telegram=telegram,
        on_log=on_log,
    )

    # Create dashboard
    dashboard_obj = Dashboard(engine=engine, feed=feed, trader=trader)
    dashboard = dashboard_obj

    # Start Telegram command handler
    cmd_handler = TelegramCommandHandler(
        notifier=telegram,
        trader=trader,
        engine=engine,
        market_finder=finder,
    )
    cmd_handler.start()
    if telegram.is_enabled:
        console.print("[green]✓[/green] Telegram command handler started")

    # Initial data fetch
    console.print("[dim]Fetching initial candle data...[/dim]")
    try:
        feed.fetch_recent(limit=10)
        btc = feed.get_btc_price()
        console.print(f"[green]✓[/green] BTC Price: ${btc:,.2f}")
        console.print(f"[green]✓[/green] Loaded {len(feed.get_closed_candles())} closed candles")
    except Exception as e:
        console.print(f"[red]✗ Failed to fetch candle data: {e}[/red]")
        console.print("[dim]Will retry when bot starts...[/dim]")

    # Check for market
    console.print("[dim]Searching for BTC markets on Polymarket...[/dim]")
    for tf in cfg.market_timeframes:
        market = finder.find_market_for_timeframe(tf)
        if market:
            console.print(f"[green]✓[/green] [{tf}] Found: {market.question[:60]}...")
        else:
            console.print(f"[yellow]⚠ [{tf}] No active market found[/yellow]")

    console.print("\n[bold green]✅ Bot started! Press Ctrl+C to stop.[/bold green]\n")

    # Send Telegram startup notification
    telegram.send_bot_started()

    time.sleep(2)

    # Main loop with live dashboard
    tick_interval = cfg.tick_interval
    last_tick = 0

    with Live(
        dashboard_obj.render(),
        console=console,
        refresh_per_second=1,
        screen=True,
    ) as live:
        while running:
            now = time.time()

            # Check if candle interval needs updating
            current_interval = cfg.get_candle_interval()
            if feed.interval != current_interval:
                feed.set_interval(current_interval)
                dashboard_obj.add_log(f"🔄 Candle interval changed to {current_interval}")

            # Process strategy tick
            if now - last_tick >= cfg.tick_interval:
                try:
                    engine.process_tick()
                except Exception as e:
                    dashboard_obj.add_log(f"[red]⚠ Error: {str(e)[:50]}[/red]")
                    telegram.send_error(str(e)[:200])
                last_tick = now

            # Update dashboard
            try:
                live.update(dashboard_obj.render())
            except Exception:
                pass

            time.sleep(0.5)

    # Shutdown
    cmd_handler.stop()
    telegram.send_bot_stopped()

    console.print("\n[yellow]🛑 Bot stopped by user.[/yellow]")
    console.print(f"[dim]Total trades: {trader.total_trades} | P&L: ${trader.total_pnl:+.2f}[/dim]")


def show_status():
    """Show current bot status and exit."""
    trader = TradeManager()
    console.print("\n[bold]📊 Bot Status[/bold]\n")
    console.print(f"  Total Trades:  {trader.total_trades}")
    console.print(f"  Wins:          {trader.wins}")
    console.print(f"  Losses:        {trader.losses}")
    console.print(f"  Win Rate:      {trader.win_rate:.1f}%")
    console.print(f"  Total P&L:     ${trader.total_pnl:+.2f}")
    console.print(f"  Daily P&L:     ${trader.daily_pnl:+.2f}")
    console.print(f"  Total Volume:  ${trader.total_volume:.2f}")

    if trader.recent_trades:
        console.print("\n[bold]Recent Trades:[/bold]")
        for t in trader.recent_trades:
            pnl_str = f"[green]+${t.pnl:.2f}[/green]" if t.pnl >= 0 else f"[red]${t.pnl:.2f}[/red]"
            console.print(f"  {t.status_emoji} {t.direction_emoji} | {t.entry_time} | {pnl_str} | {t.close_reason}")
    console.print()


def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Telegram Bot — Configurable BTC Strategy"
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
