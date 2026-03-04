# MetaTrader 5 Hedging & Trailing Stop Bot

This is a Python-based trading bot that connects to the MetaTrader 5 platform. It implements a specific hedging strategy combined with multiple risk management features, all configurable via the command line.

## Core Trading Strategy

1.  **Initial Buy:** The bot starts by placing a single BUY order for a given symbol.
2.  **Hedging Sell:** If the price drops by a specified number of pips below the initial buy price, the bot opens a SELL order.
3.  **Dynamic Hedge:** If the price moves *above* the most recent SELL order by a specified number of pips, the bot closes that SELL order and immediately opens a new one at the current, higher price. This process repeats, moving the hedge upwards with the price.
4.  **Portfolio Exits:** All positions for a symbol are closed when either the total profit in USD reaches a take-profit target, or the total loss reaches a stop-loss limit.

## Features

- **Multi-Symbol Trading:** Trade multiple currency pairs simultaneously, with unique settings for each.
- **Configurable Hedging:** Set the pip distance that triggers the hedging orders.
- **Portfolio-Level TP/SL:** Set an overall Take Profit and Stop Loss in your account's currency for all trades on a symbol.
- **Stealth Mode:**
    - Run the bot without sending Stop Loss or Take Profit levels to the broker, hiding your exit strategy.
    - **Trailing Stop Loss (Pips):** Automatically trail the price with a stealth stop-loss to lock in profits.
    - **Stealth Take Profit (Pips):** Set a per-trade Take Profit in pips that is managed internally by the bot.
- **Flexible Configuration:** All parameters are controlled via command-line arguments, allowing for easy testing and use.
- **Robust Connection:** The bot automatically tries to find and enable symbols in your Market Watch.

## Requirements

- Python 3.6+
- MetaTrader 5 Terminal
- An active MetaTrader 5 trading account
- The `MetaTrader5` Python library:
  ```bash
  pip install MetaTrader5
  ```

## Setup

Before running the bot, you must provide your account credentials. It is **strongly recommended** to use environment variables for security.

Set the following environment variables in your system:

- `MT5_LOGIN`: Your MT5 account number.
- `MT5_PASSWORD`: Your MT5 account password.
- `MT5_SERVER`: The name of your broker's server.

**Example (Linux/macOS):**
```bash
export MT5_LOGIN="12345678"
export MT5_PASSWORD="your_secret_password"
export MT5_SERVER="YourBroker-Server"
```

**Example (Windows PowerShell):**
```powershell
$env:MT5_LOGIN="12345678"
$env:MT5_PASSWORD="your_secret_password"
$env:MT5_SERVER="YourBroker-Server"
```

## Usage

Run the bot from your terminal using `python trading_bot.py`.

### Basic Example (Single Symbol)

This will run the bot on EURUSD with default settings.

```bash
python trading_bot.py
```

### Custom Parameters (Single Symbol)

```bash
python trading_bot.py \
  --symbol "GBPUSD" \
  --lot-size 0.02 \
  --pip-threshold 5 \
  --tp-usd 100 \
  --sl-usd 40
```

### Multi-Symbol Trading

Provide a list of arguments for each parameter, in the same order as the symbols.

```bash
python trading_bot.py \
  --symbol "EURUSD" "AUDJPY" \
  --lot-size 0.01 0.05 \
  --pip-threshold 3 10 \
  --tp-usd 50 200 \
  --sl-usd 25 100
```
*You can also provide a single value for a parameter (e.g., `--lot-size 0.01`), and it will be applied to all symbols.*

### Stealth Mode with Trailing Stop

This example uses stealth mode with a 15-pip trailing stop and a 30-pip stealth take profit.

```bash
python trading_bot.py \
  --symbol "XAUUSD" \
  --lot-size 0.01 \
  --pip-threshold 10 \
  --tp-usd 200 \
  --sl-usd 75 \
  --stealth-mode \
  --trailing-stop-pips 15 \
  --stealth-tp-pips 30
```

### All Command-Line Arguments

| Argument                | Description                                                 | Default   |
|-------------------------|-------------------------------------------------------------|-----------|
| `--symbol`              | List of symbols to trade.                                   | `EURUSD`  |
| `--lot-size`            | List of lot sizes for each symbol.                          | `0.01`    |
| `--pip-threshold`       | Pip distance to trigger a hedge order.                      | `3.0`     |
| `--tp-usd`              | Portfolio take profit in USD.                               | `50.0`    |
| `--sl-usd`              | Portfolio stop loss in USD.                                 | `25.0`    |
| `--stealth-mode`        | Enable stealth mode (hides SL/TP from broker).              | `False`   |
| `--trailing-stop-pips`  | Pip distance for the stealth trailing stop. (Requires stealth mode) | `0.0`     |
| `--stealth-tp-pips`     | Pip distance for the stealth per-trade take profit. (Requires stealth mode) | `0.0`     |


## ⚠️ Disclaimer ⚠️

This bot is provided for educational and experimental purposes only. Trading foreign exchange on margin carries a high level of risk and may not be suitable for all investors. The high degree of leverage can work against you as well as for you. Before deciding to trade foreign exchange you should carefully consider your investment objectives, level of experience, and risk appetite. The possibility exists that you could sustain a loss of some or all of your initial investment and therefore you should not invest money that you cannot afford to lose. You should be aware of all the risks associated with foreign exchange trading, and seek advice from an independent financial advisor if you have any doubts. The author of this bot is not responsible for any financial losses. **Use at your own risk.**
