# ₿ Polymarket Telegram Bot v2.0

A fully configurable **Polymarket BTC trading bot** with **Telegram integration** for notifications and live configuration.

Trades BTC UP/DOWN prediction markets on Polymarket with configurable strategy, take-profit, stop-loss, and continuous auto re-entry.

---

## ✨ Features

### 🎯 Strategy Selection
- **LONG mode** — Buys UP tokens (betting BTC will rise)
- **SHORT mode** — Buys DOWN tokens (betting BTC will fall)
- Change direction instantly via Telegram (`/set direction long`)

### 💰 Trade Sizing
- **Fixed amount** — Trade a specific USDC amount (e.g., $5, $10, $50)
- **Portfolio percentage** — Trade a % of your wallet balance (e.g., 5%)
- Switch modes via Telegram (`/set size fixed` or `/set size percent`)

### 📊 Take-Profit & Stop-Loss
- Configurable TP% (default: 80%)
- Configurable SL% (default: 50%)
- Monitored on every tick — auto-closes when hit
- Adjust live: `/set tp 90` or `/set sl 30`

### 🕐 Multi-Timeframe Markets
- Supports: **5m, 15m, 1h, 1d** BTC UP/DOWN markets
- Select one or multiple timeframes
- Change via config or Telegram: `/set market 15m` or `/set market 5m,15m`

### 🔄 Continuous Execution
- **24/7 autonomous operation** — no manual confirmation needed
- Auto re-enters after position closes
- Progressive entries on losses (up to 5th candle, then cooldown)
- Configurable cooldown period

### 📱 Telegram Notifications
- ✅ Trade opened (market, direction, stake, entry price)
- ✅ Trade closed (exit price, P&L, reason: TP/SL/win/loss)
- ✅ Current status (running/paused, open positions, daily P&L)
- ✅ Error alerts

### 🤖 Telegram Commands
| Command | Description |
|---------|-------------|
| `/status` | Bot status, open positions, daily P&L |
| `/config` | Current configuration |
| `/pnl` | P&L summary (daily + all-time) |
| `/trades` | Recent trade history |
| `/markets` | Available Polymarket BTC markets |
| `/set tp <value>` | Set take-profit % |
| `/set sl <value>` | Set stop-loss % |
| `/set amount <value>` | Set trade amount ($) |
| `/set percent <value>` | Set portfolio % |
| `/set direction <long/short>` | Change strategy direction |
| `/set market <5m,15m,1h,1d>` | Change market timeframe(s) |
| `/set size <fixed/percent>` | Switch between fixed/% sizing |
| `/start` | Resume trading |
| `/stop` | Pause trading |
| `/help` | Show all commands |

### 🖥️ Terminal Dashboard
- Rich terminal UI with live-updating panels
- BTC price, candle history, strategy state
- P&L tracking, wallet balance, trade history
- Activity log

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.10+
- MetaMask wallet with USDC on Polygon
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Your Telegram Chat ID (from [@userinfobot](https://t.me/userinfobot))

### 2. Install
```bash
cd Polymarket_telegram_Bot
pip install -r requirements.txt
```

### 3. Configure
```bash
# Copy the template
copy .env.example .env

# Edit .env with your values:
# - PRIVATE_KEY (MetaMask)
# - FUNDER_ADDRESS (MetaMask)
# - TELEGRAM_BOT_TOKEN
# - TELEGRAM_CHAT_ID
# - Trading parameters (TP, SL, direction, etc.)
```

### 4. Wallet Setup (First Time Only)
```bash
# Approve token allowances on Polymarket
python setup_allowances.py
```

> **Important:** Your MetaMask wallet must:
> 1. Be connected to Polymarket (visit polymarket.com, connect wallet)
> 2. Have accepted terms of service
> 3. Have USDC deposited on Polygon network
> 4. Have a small amount of MATIC/POL for gas (~0.01 POL)

### 5. Run
```bash
# Paper mode (default — no real trades)
python -X utf8 bot.py

# Live trading
python -X utf8 bot.py --live

# Check status
python bot.py --status
```

---

## ⚙️ Configuration

All settings are in `.env`. Here are the key parameters:

### Credentials
| Variable | Description |
|----------|-------------|
| `PRIVATE_KEY` | MetaMask wallet private key (0x...) |
| `FUNDER_ADDRESS` | MetaMask wallet address |
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram user ID |

### Trading Parameters
| Variable | Default | Description |
|----------|---------|-------------|
| `STRATEGY_DIRECTION` | `LONG` | `LONG` or `SHORT` |
| `TRADE_SIZE_MODE` | `fixed` | `fixed` or `percent` |
| `TRADE_AMOUNT` | `5.0` | Fixed USDC amount per trade |
| `TRADE_PERCENT` | `5.0` | Portfolio % per trade |
| `TAKE_PROFIT_PCT` | `80.0` | Take-profit percentage |
| `STOP_LOSS_PCT` | `50.0` | Stop-loss percentage |
| `MARKET_TIMEFRAMES` | `15m` | Comma-separated: `5m,15m,1h,1d` |
| `MAX_SLIPPAGE` | `0.05` | Max slippage in USDC |
| `SHARE_PRICE` | `0.50` | Target entry price |
| `COOLDOWN_MINUTES` | `30` | Cooldown after max progressive entries |
| `PAPER_MODE` | `false` | Set `true` for simulation |

---

## 📁 Project Structure

```
├── bot.py              # Main entry point
├── config.py           # Configuration (loads .env, runtime-mutable)
├── strategy.py         # Strategy engine (signals, TP/SL, re-entry)
├── trade_manager.py    # Trade execution & tracking
├── market_finder.py    # Multi-timeframe market discovery
├── candle_feed.py      # BTC price data from Binance
├── telegram_bot.py     # Telegram notifications & commands
├── dashboard.py        # Rich terminal dashboard
├── redeem_manager.py   # Redeem winning positions
├── setup_allowances.py # One-time wallet setup
├── .env.example        # Configuration template
├── requirements.txt    # Python dependencies
└── README.md           # This file
```

---

## 🔧 How It Works

1. **Bot starts** → Fetches BTC candle data from Binance
2. **Scans** for entry signals (consecutive same-color candles)
3. **Places trade** on Polymarket (UP or DOWN token based on strategy)
4. **Monitors** TP/SL on every tick via live CLOB prices
5. **Closes trade** when TP/SL hit or market resolves
6. **Notifies** via Telegram on every trade event
7. **Auto re-enters** — scans for next signal immediately
8. **Progressive entries** — on loss, enters next candle (up to 5th)
9. **Cooldown** — 30-min pause after 5th candle loss
10. **Repeats** 24/7 continuously

---

## ⚠️ Disclaimer

This bot is for educational purposes. Trading on prediction markets involves risk. Always use paper mode first to understand behavior. Never trade with funds you can't afford to lose.

---

## 📄 License

MIT
