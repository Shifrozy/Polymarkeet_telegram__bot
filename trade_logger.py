"""
╔══════════════════════════════════════════════════════════════╗
║   POLYMARKET TELEGRAM BOT — EXCEL TRADE LOGGER              ║
╚══════════════════════════════════════════════════════════════╝
Logs all trading activity to an Excel (.xlsx) file.

Sheets:
  1. Trades   — Every trade with entry/exit details, P&L
  2. Events   — Activity log (bot start, TP/SL, redeem, errors)
"""

import os
import threading
from datetime import datetime
from typing import Optional

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# File path for the Excel log
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_log.xlsx")

# Column headers
TRADE_HEADERS = [
    "Trade #", "Date", "Time", "Direction", "Market", "Timeframe",
    "Entry Price", "Exit Price", "Shares", "Stake ($)",
    "P&L ($)", "P&L (%)", "Close Reason", "Order ID", "Duration (min)"
]

EVENT_HEADERS = [
    "Date", "Time", "Event Type", "Details"
]

# Styles
HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
HEADER_FILL = PatternFill(start_color="1A1A2E", end_color="1A1A2E", fill_type="solid")
GREEN_FILL = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")
RED_FILL = PatternFill(start_color="FFEBEE", end_color="FFEBEE", fill_type="solid")
BORDER = Border(
    left=Side(style="thin", color="CCCCCC"),
    right=Side(style="thin", color="CCCCCC"),
    top=Side(style="thin", color="CCCCCC"),
    bottom=Side(style="thin", color="CCCCCC"),
)


class TradeLogger:
    """Logs all trades and events to an Excel file."""

    def __init__(self, file_path: str = None):
        self.file_path = file_path or LOG_FILE
        self._lock = threading.Lock()
        self._trade_count = 0
        self._ensure_workbook()

    def _ensure_workbook(self):
        """Create the workbook if it doesn't exist, or load existing."""
        if os.path.exists(self.file_path):
            try:
                wb = load_workbook(self.file_path)
                # Count existing trades
                if "Trades" in wb.sheetnames:
                    self._trade_count = wb["Trades"].max_row - 1  # minus header
                    if self._trade_count < 0:
                        self._trade_count = 0
                wb.close()
                return
            except Exception:
                pass  # File corrupted, recreate

        # Create new workbook
        wb = Workbook()

        # Trades sheet
        ws_trades = wb.active
        ws_trades.title = "Trades"
        ws_trades.append(TRADE_HEADERS)
        self._style_headers(ws_trades, len(TRADE_HEADERS))
        self._set_column_widths(ws_trades, [8, 12, 10, 10, 45, 10, 12, 12, 10, 10, 10, 10, 20, 25, 12])

        # Events sheet
        ws_events = wb.create_sheet("Events")
        ws_events.append(EVENT_HEADERS)
        self._style_headers(ws_events, len(EVENT_HEADERS))
        self._set_column_widths(ws_events, [12, 10, 18, 80])

        # Summary sheet
        ws_summary = wb.create_sheet("Summary")
        ws_summary.append(["Metric", "Value"])
        self._style_headers(ws_summary, 2)
        ws_summary.append(["Total Trades", 0])
        ws_summary.append(["Winning Trades", 0])
        ws_summary.append(["Losing Trades", 0])
        ws_summary.append(["Win Rate (%)", "0.0%"])
        ws_summary.append(["Total P&L ($)", 0])
        ws_summary.append(["Best Trade ($)", 0])
        ws_summary.append(["Worst Trade ($)", 0])
        ws_summary.append(["Avg P&L per Trade ($)", 0])
        ws_summary.append(["Total Volume ($)", 0])
        ws_summary.append(["First Trade", "N/A"])
        ws_summary.append(["Last Trade", "N/A"])
        self._set_column_widths(ws_summary, [22, 20])

        wb.save(self.file_path)
        wb.close()

    def _style_headers(self, ws, col_count):
        """Apply styles to header row."""
        for col in range(1, col_count + 1):
            cell = ws.cell(row=1, column=col)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(horizontal="center")
            cell.border = BORDER

    def _set_column_widths(self, ws, widths):
        """Set column widths."""
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    def log_trade(self, trade) -> None:
        """Log a completed trade to the Trades sheet."""
        threading.Thread(target=self._write_trade, args=(trade,), daemon=True).start()

    def _write_trade(self, trade):
        """Write trade data to Excel (thread-safe)."""
        with self._lock:
            try:
                wb = load_workbook(self.file_path)
                ws = wb["Trades"]
                self._trade_count += 1

                now = datetime.now()
                direction = trade.direction.value if hasattr(trade.direction, 'value') else str(trade.direction)

                # Calculate duration
                duration_min = 0
                if hasattr(trade, 'entry_time') and hasattr(trade, 'close_time'):
                    try:
                        if trade.close_time and trade.entry_time:
                            entry_dt = datetime.strptime(trade.entry_time, "%Y-%m-%d %H:%M:%S")
                            close_dt = datetime.strptime(trade.close_time, "%Y-%m-%d %H:%M:%S")
                            duration_min = (close_dt - entry_dt).total_seconds() / 60
                    except Exception:
                        pass

                # P&L percentage
                pnl_pct = 0
                if trade.amount > 0:
                    pnl_pct = (trade.pnl / trade.amount) * 100

                row_data = [
                    self._trade_count,
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M:%S"),
                    direction,
                    getattr(trade, 'market_question', '')[:45] or trade.timeframe,
                    getattr(trade, 'timeframe', 'N/A'),
                    round(trade.share_price, 4),
                    round(getattr(trade, 'result_price', trade.current_price or 0), 4),
                    round(trade.shares, 2),
                    round(trade.amount, 2),
                    round(trade.pnl, 2),
                    f"{pnl_pct:.1f}%",
                    trade.close_reason or "Unknown",
                    trade.order_id[:20] if trade.order_id else "N/A",
                    round(duration_min, 1),
                ]

                ws.append(row_data)
                row_num = ws.max_row

                # Color row based on P&L
                fill = GREEN_FILL if trade.pnl >= 0 else RED_FILL
                for col in range(1, len(TRADE_HEADERS) + 1):
                    cell = ws.cell(row=row_num, column=col)
                    cell.fill = fill
                    cell.border = BORDER
                    cell.alignment = Alignment(horizontal="center")

                # Update summary
                self._update_summary(wb)

                wb.save(self.file_path)
                wb.close()
            except Exception as e:
                print(f"Trade log error: {e}")

    def log_event(self, event_type: str, details: str) -> None:
        """Log an event to the Events sheet."""
        threading.Thread(target=self._write_event, args=(event_type, details), daemon=True).start()

    def _write_event(self, event_type: str, details: str):
        """Write event data to Excel (thread-safe)."""
        with self._lock:
            try:
                wb = load_workbook(self.file_path)
                ws = wb["Events"]
                now = datetime.now()
                ws.append([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M:%S"),
                    event_type,
                    details[:200],
                ])
                row_num = ws.max_row
                for col in range(1, len(EVENT_HEADERS) + 1):
                    cell = ws.cell(row=row_num, column=col)
                    cell.border = BORDER

                wb.save(self.file_path)
                wb.close()
            except Exception as e:
                print(f"Event log error: {e}")

    def _update_summary(self, wb):
        """Update the Summary sheet with latest stats."""
        try:
            ws_trades = wb["Trades"]
            ws_summary = wb["Summary"]

            # Collect all P&L values
            pnls = []
            volumes = []
            for row in ws_trades.iter_rows(min_row=2, values_only=True):
                if row[10] is not None:  # P&L column
                    try:
                        pnl = float(row[10])
                        pnls.append(pnl)
                    except (ValueError, TypeError):
                        pass
                if row[9] is not None:  # Stake column
                    try:
                        volumes.append(float(row[9]))
                    except (ValueError, TypeError):
                        pass

            total = len(pnls)
            wins = sum(1 for p in pnls if p >= 0)
            losses = sum(1 for p in pnls if p < 0)
            win_rate = (wins / total * 100) if total > 0 else 0
            total_pnl = sum(pnls)
            best = max(pnls) if pnls else 0
            worst = min(pnls) if pnls else 0
            avg_pnl = total_pnl / total if total > 0 else 0
            total_vol = sum(volumes)

            # First and last trade dates
            first_date = ws_trades.cell(row=2, column=2).value if total > 0 else "N/A"
            last_date = ws_trades.cell(row=ws_trades.max_row, column=2).value if total > 0 else "N/A"

            # Write summary
            summary_data = [
                total, wins, losses, f"{win_rate:.1f}%",
                round(total_pnl, 2), round(best, 2), round(worst, 2),
                round(avg_pnl, 2), round(total_vol, 2),
                first_date, last_date,
            ]
            for i, val in enumerate(summary_data, 2):
                ws_summary.cell(row=i, column=2, value=val)

        except Exception:
            pass
