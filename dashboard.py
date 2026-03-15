"""
╔══════════════════════════════════════════════════════════════╗
║   POLYMARKET TELEGRAM BOT — TERMINAL DASHBOARD              ║
╚══════════════════════════════════════════════════════════════╝
Clean, beautiful terminal dashboard using Rich.
Shows BTC price, strategy state, P&L, wallet, and activity log.
"""

import time
import threading
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.live import Live
from rich.columns import Columns
from rich.align import Align
from rich import box

try:
    from web3 import Web3
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False

from candle_feed import CandleFeed, Candle
from trade_manager import TradeManager, Trade, TradeStatus, TradeDirection
from strategy import StrategyEngine, BotState
from config import (
    FUNDER_ADDRESS, trading_config,
)


class Dashboard:
    """Rich terminal dashboard for the bot."""

    def __init__(
        self,
        engine: StrategyEngine,
        feed: CandleFeed,
        trader: TradeManager,
    ):
        self.engine = engine
        self.feed = feed
        self.trader = trader
        self.console = Console()
        self.log_lines: list[str] = []
        self.max_log_lines = 12
        self._start_time = time.time()

        # Wallet data cache (refreshed every 60s)
        self._wallet_cache = {
            "usdc": 0.0,
            "matic": 0.0,
            "positions": [],
            "last_fetch": 0,
        }
        self._wallet_lock = threading.Lock()
        self._WALLET_REFRESH_SEC = 60

    def add_log(self, message: str):
        """Add a log line to the activity feed."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_lines.append(f"[dim]{ts}[/dim]  {message}")
        if len(self.log_lines) > self.max_log_lines:
            self.log_lines = self.log_lines[-self.max_log_lines:]

    def _build_header(self) -> Panel:
        """Build the header panel."""
        mode = "[bold red]🔴 PAPER MODE[/bold red]" if cfg.paper_mode else "[bold green]🟢 LIVE TRADING[/bold green]"
        uptime = time.time() - self._start_time
        h, remainder = divmod(int(uptime), 3600)
        m, s = divmod(remainder, 60)

        cfg = trading_config
        direction = "[green]LONG[/green]" if cfg.strategy_direction == "LONG" else "[red]SHORT[/red]"
        bot_status = "[green]RUNNING[/green]" if cfg.bot_running else "[red]PAUSED[/red]"

        header_text = Text()
        header_text.append("  ₿  POLYMARKET TELEGRAM BOT  ", style="bold white on blue")
        header_text.append(f"  {mode}  ", style="")
        header_text.append(f"  ⏱ {h:02d}:{m:02d}:{s:02d}", style="dim")

        return Panel(
            Align.center(header_text),
            box=box.DOUBLE,
            style="bright_blue",
            height=3,
        )

    def _build_btc_panel(self) -> Panel:
        """Build the BTC price & candle panel."""
        btc_price = self.feed.get_btc_price()
        progress = self.feed.candle_progress_pct()
        remaining = self.feed.seconds_until_candle_close()
        remaining_min = int(remaining // 60)
        remaining_sec = int(remaining % 60)

        current = self.feed.get_current_candle()
        current_color = current.color if current else "—"
        current_change = f"{current.change_pct:+.2f}%" if current else "—"

        bar_len = 20
        filled = int(bar_len * progress / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        bar_color = "green" if current_color == "green" else "red" if current_color == "red" else "white"

        cfg = trading_config
        direction_text = f"[green]LONG ▲[/green]" if cfg.strategy_direction == "LONG" else f"[red]SHORT ▼[/red]"

        lines = [
            f"[bold yellow]BTC Price:[/bold yellow]  [bold white]${btc_price:,.2f}[/bold white]",
            f"[bold]Current Candle:[/bold]  [{bar_color}]{current_color.upper()}[/{bar_color}]  {current_change}",
            f"[bold]Progress:[/bold]      [{bar_color}]{bar}[/{bar_color}] {progress:.0f}%",
            f"[bold]Closes in:[/bold]     {remaining_min}m {remaining_sec}s",
            f"[bold]Strategy:[/bold]      {direction_text}  |  TF: {', '.join(cfg.market_timeframes)}",
        ]

        return Panel(
            "\n".join(lines),
            title="[bold yellow]₿ BTC Market[/bold yellow]",
            border_style="yellow",
            height=9,
        )

    def _build_candle_history(self) -> Panel:
        """Build recent candle history panel."""
        closed = self.feed.get_closed_candles()[-6:]

        table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold cyan")
        table.add_column("Time", style="dim", width=12)
        table.add_column("Open", justify="right", width=10)
        table.add_column("Close", justify="right", width=10)
        table.add_column("Change", justify="right", width=8)
        table.add_column("Color", justify="center", width=6)

        for c in closed:
            color = "green" if c.color == "green" else "red"
            icon = "🟢" if c.color == "green" else "🔴"
            table.add_row(
                c.open_dt.strftime("%H:%M"),
                f"${c.open_price:,.0f}",
                f"${c.close_price:,.0f}",
                f"[{color}]{c.change_pct:+.2f}%[/{color}]",
                icon,
            )

        return Panel(
            table,
            title="[bold cyan]🕯 Recent Candles[/bold cyan]",
            border_style="cyan",
        )

    def _build_strategy_panel(self) -> Panel:
        """Build the strategy status panel."""
        state = self.engine.state
        cfg = trading_config

        state_colors = {
            BotState.IDLE: ("💤", "white"),
            BotState.IN_TRADE: ("📊", "green"),
            BotState.WAITING_MARKET: ("⏳", "yellow"),
            BotState.PAUSED: ("⏸️", "red"),
        }
        icon, color = state_colors.get(state.bot_state, ("❓", "white"))

        lines = [
            f"[bold]State:[/bold]          [{color}]{icon} {state.bot_state.value}[/{color}]",
            f"[bold]TP / SL:[/bold]        [green]{cfg.take_profit_pct:.0f}%[/green] / [red]{cfg.stop_loss_pct:.0f}%[/red]",
        ]

        if cfg.trade_size_mode == "fixed":
            lines.append(f"[bold]Trade Size:[/bold]    ${cfg.trade_amount:.2f} (fixed)")
        else:
            lines.append(f"[bold]Trade Size:[/bold]    {cfg.trade_percent:.1f}% of portfolio")

        lines.append(f"[bold]Share Price:[/bold]  ${cfg.share_price:.2f}")
        lines.append(f"[bold]Slippage:[/bold]     ${cfg.max_slippage:.3f}")

        # Auto-repeat status
        if state.auto_repeat_active:
            dir_text = state.auto_repeat_direction.value if state.auto_repeat_direction else "?"
            dir_color = "green" if dir_text == "UP" else "red"
            lines.append(f"\n[bold]Auto-Repeat:[/bold]  [bold {dir_color}]ON → {dir_text}[/bold {dir_color}]")
        else:
            lines.append(f"\n[bold]Auto-Repeat:[/bold]  [dim]OFF[/dim]")

        lines.append(f"[bold]Trades Today:[/bold] {state.trades_today} / {cfg.max_trades_per_day}")
        lines.append(f"[bold]Total Buys:[/bold]   {state.total_buys}")
        lines.append(f"[bold]Total Sells:[/bold]  {state.total_sells}")

        return Panel(
            "\n".join(lines),
            title="[bold magenta]🧠 Strategy[/bold magenta]",
            border_style="magenta",
            height=14,
        )

    def _build_pnl_panel(self) -> Panel:
        """Build the P&L and statistics panel."""
        pnl = self.trader.total_pnl
        pnl_color = "green" if pnl >= 0 else "red"
        pnl_icon = "📈" if pnl >= 0 else "📉"

        daily = self.trader.daily_pnl
        daily_color = "green" if daily >= 0 else "red"
        daily_icon = "📈" if daily >= 0 else "📉"

        wr = self.trader.win_rate
        wr_color = "green" if wr >= 50 else "yellow" if wr >= 30 else "red"

        lines = [
            f"[bold]Daily P&L:[/bold]    [{daily_color}]{daily_icon} ${daily:+.2f}[/{daily_color}]",
            f"[bold]Total P&L:[/bold]    [{pnl_color}]{pnl_icon} ${pnl:+.2f}[/{pnl_color}]",
            f"[bold]Total Trades:[/bold] {self.trader.total_trades}",
            f"[bold]Win Rate:[/bold]     [{wr_color}]{wr:.1f}%[/{wr_color}]",
            f"[bold]Wins:[/bold]         [green]{self.trader.wins}[/green]",
            f"[bold]Losses:[/bold]       [red]{self.trader.losses}[/red]",
            f"[bold]Volume:[/bold]       ${self.trader.total_volume:.2f}",
        ]

        # Current open trade
        if self.trader.current_trade:
            t = self.trader.current_trade
            dir_color = "green" if t.direction == TradeDirection.UP else "red"
            upnl = t.unrealized_pnl
            upnl_color = "green" if upnl >= 0 else "red"
            lines.append(f"\n[bold]Open Trade:[/bold]  [{dir_color}]{t.direction_emoji}[/{dir_color}]")
            lines.append(f"[bold]Amount:[/bold]      ${t.amount:.2f}")
            lines.append(f"[bold]Candle #:[/bold]    {t.candle_number}")
            lines.append(f"[bold]Unreal P&L:[/bold] [{upnl_color}]${upnl:+.2f}[/{upnl_color}]")
        else:
            lines.append(f"\n[dim]No open trade[/dim]")

        return Panel(
            "\n".join(lines),
            title="[bold green]💰 Performance[/bold green]",
            border_style="green",
        )

    def _build_trade_history(self) -> Panel:
        """Build recent trade history table."""
        table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=3)
        table.add_column("Time", width=8)
        table.add_column("Dir", width=6)
        table.add_column("Candle", justify="center", width=6)
        table.add_column("Amount", justify="right", width=7)
        table.add_column("P&L", justify="right", width=8)
        table.add_column("Reason", justify="center", width=8)

        for i, t in enumerate(self.trader.recent_trades, 1):
            pnl_color = "green" if t.pnl >= 0 else "red"
            dir_icon = "🟢" if t.direction == TradeDirection.UP else "🔴"
            table.add_row(
                str(i),
                t.entry_time,
                dir_icon,
                str(t.candle_number),
                f"${t.amount:.2f}",
                f"[{pnl_color}]${t.pnl:+.2f}[/{pnl_color}]",
                t.close_reason[:8] if t.close_reason else t.status_emoji,
            )

        return Panel(
            table,
            title="[bold]📜 Trade History (Last 10)[/bold]",
            border_style="white",
        )

    def _build_activity_log(self) -> Panel:
        """Build the activity log panel."""
        if not self.log_lines:
            content = "[dim]Waiting for activity...[/dim]"
        else:
            content = "\n".join(self.log_lines)

        return Panel(
            content,
            title="[bold]📋 Activity Log[/bold]",
            border_style="bright_black",
        )

    def _fetch_wallet_data(self):
        """Fetch wallet balance and positions (cached, refreshes every 60s)."""
        now = time.time()
        if now - self._wallet_cache["last_fetch"] < self._WALLET_REFRESH_SEC:
            return

        try:
            if HAS_WEB3 and FUNDER_ADDRESS and not trading_config.paper_mode:
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

                with self._wallet_lock:
                    self._wallet_cache["usdc"] = usdc_bal
                    self._wallet_cache["matic"] = matic_bal

                try:
                    r = requests.get(
                        f"https://data-api.polymarket.com/positions?user={FUNDER_ADDRESS.lower()}",
                        timeout=8,
                    )
                    if r.status_code == 200:
                        with self._wallet_lock:
                            self._wallet_cache["positions"] = r.json()
                except Exception:
                    pass

            with self._wallet_lock:
                self._wallet_cache["last_fetch"] = now
        except Exception:
            with self._wallet_lock:
                self._wallet_cache["last_fetch"] = now

    def _build_wallet_panel(self) -> Panel:
        """Build the wallet balance and positions panel."""
        self._fetch_wallet_data()

        with self._wallet_lock:
            usdc = self._wallet_cache["usdc"]
            matic = self._wallet_cache["matic"]
            positions = self._wallet_cache["positions"]

        if trading_config.paper_mode:
            lines = ["[dim]Wallet info not available in Paper Mode[/dim]"]
            return Panel(
                "\n".join(lines),
                title="[bold bright_cyan]👛 Wallet[/bold bright_cyan]",
                border_style="bright_cyan",
                height=6,
            )

        addr = FUNDER_ADDRESS
        short_addr = f"{addr[:6]}...{addr[-4:]}" if len(addr) > 10 else addr

        total_value = sum(float(p.get("currentValue", 0)) for p in positions)
        total_cost = sum(float(p.get("initialValue", 0)) for p in positions)
        total_pnl = total_value - total_cost
        pnl_color = "green" if total_pnl >= 0 else "red"

        lines = [
            f"[bold]Wallet:[/bold]      [dim]{short_addr}[/dim]",
            f"[bold]USDC.e:[/bold]      [bold white]${usdc:.2f}[/bold white]",
            f"[bold]MATIC:[/bold]       [dim]{matic:.4f}[/dim]",
        ]

        if positions:
            lines.append("")
            lines.append(f"[bold]Positions:[/bold]   {len(positions)} active")
            lines.append(f"[bold]Holdings:[/bold]    [bold white]${total_value:.2f}[/bold white]")
            lines.append(f"[bold]Pos. PnL:[/bold]    [{pnl_color}]${total_pnl:+.2f}[/{pnl_color}]")
            lines.append(f"[bold]Total Equity:[/bold][bold yellow] ${usdc + total_value:.2f}[/bold yellow]")
        else:
            lines.append("")
            lines.append("[dim]No active positions[/dim]")

        return Panel(
            "\n".join(lines),
            title="[bold bright_cyan]👛 Wallet & Holdings[/bold bright_cyan]",
            border_style="bright_cyan",
        )

    def _build_config_bar(self) -> Panel:
        """Build the configuration bar."""
        cfg = trading_config
        state = self.engine.state
        size = f"${cfg.trade_amount}" if cfg.trade_size_mode == "fixed" else f"{cfg.trade_percent}%"
        status = "RUNNING" if cfg.bot_running else "PAUSED"

        auto_rpt = "AUTO" if state.auto_repeat_active else "MANUAL"

        items = [
            f"Status: {status}",
            f"Mode: {auto_rpt}",
            f"Size: {size}",
            f"TP: {cfg.take_profit_pct}%",
            f"SL: {cfg.stop_loss_pct}%",
            f"Slip: ${cfg.max_slippage}",
            f"TF: {','.join(cfg.market_timeframes)}",
        ]
        config_text = "  │  ".join(items)

        return Panel(
            Align.center(Text(config_text, style="dim")),
            box=box.ROUNDED,
            style="dim",
            height=3,
        )

    def render(self) -> Layout:
        """Build the full dashboard layout."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="config", size=3),
            Layout(name="body"),
            Layout(name="bottom"),
            Layout(name="log", size=self.max_log_lines + 4),
        )

        layout["body"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1),
        )

        layout["left"].split_column(
            Layout(name="btc", size=9),
            Layout(name="candles"),
        )

        layout["right"].split_column(
            Layout(name="strategy", size=14),
            Layout(name="pnl"),
        )

        layout["bottom"].split_row(
            Layout(name="wallet", ratio=1),
            Layout(name="trades", ratio=2),
        )

        layout["header"].update(self._build_header())
        layout["config"].update(self._build_config_bar())
        layout["btc"].update(self._build_btc_panel())
        layout["candles"].update(self._build_candle_history())
        layout["strategy"].update(self._build_strategy_panel())
        layout["pnl"].update(self._build_pnl_panel())
        layout["wallet"].update(self._build_wallet_panel())
        layout["trades"].update(self._build_trade_history())
        layout["log"].update(self._build_activity_log())

        return layout
