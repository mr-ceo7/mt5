# MetaTrader 5 Hedging Bot: Complete Strategy & Configuration Guide

Welcome to the comprehensive guide for the Python-based MetaTrader 5 Hedging Bot. This document outlines the inner workings of the bot's mathematical strategy, details how different settings interact, and provides a clear breakdown of potential market scenarios to help you understand your risks and rewards.

---

## 1. Core Trading Strategy

The bot utilizes a **dynamic grid-hedging strategy** designed to protect capital and navigate market trends without predicting direction. Rather than closing losing trades immediately, it offsets them with opposing trades (hedges) to neutralize market movement.

### Step-by-Step Execution Flow

1. **Initial Position:** The bot enters the market by opening a standard **BUY** order at the current market price.
2. **The Grid Hedge:** If the market moves against the BUY (drops in price) by a specified **Pip Threshold**, the bot places an offsetting **SELL** order. At this exact moment, your net loss is "locked" or frozen. Further price drops will not increase your loss.
3. **Dynamic Re-Hedging:** If the price reverses and begins to rise *above* your latest SELL order, the bot closes the old SELL and places a **new, higher SELL** order. This dynamically slides the hedge upward with the rising market, allowing the initial BUY order to capture more profit.
4. **Basket Exit:** The bot continuously monitors the combined profit and loss of all open positions in real-time. It closes the entire basket of trades only when the target profit or risk limit is reached.

---

## 2. Parameter Reference Guide

Every parameter in the dashboard or command-line interface drastically changes the behavior of your bot. Use the table below to configure your risk profile:

| Setting Name | Type / Units | Default | Description & Operational Impact |
| :--- | :--- | :--- | :--- |
| **Symbol** | String | `EURUSD` | The specific market asset you are trading. The bot dynamically reads contract specifications (like points and tick sizes) directly from MT5. |
| **Lot Size** | Float | `0.01` | The volume of each trade. `0.01` represents 1,000 units of currency (a micro lot). Increasing this increases both the profit velocity and drawdown rate. |
| **Pip Threshold** | Float (Pips) | `3.0` | The distance the price must move to trigger a hedge. **Smaller values** trigger hedges quickly (safer, but higher transaction costs). **Larger values** give the trade more breathing room before hedging. |
| **TP USD** | USD ($) | `50.0` | The profit target for the *entire basket* of trades on this symbol. Once the net profit hits this, the bot closes all trades and resets. |
| **SL USD** | USD ($) | `25.0` | The maximum loss allowed for the *entire basket* of trades. If the net loss drops to this level, the bot closes everything to prevent account wipeout. |
| **Stealth Mode** | Checkbox | `False` | When enabled, individual TP and Trailing Stops are managed privately in Python memory. The broker **cannot see** your exit levels on the public order book. |
| **Trailing Stop Pips** | Float (Pips) | `0.0` | *Requires Stealth Mode.* Automatically trails the price at this distance behind your peak profit. Closes the trade if the market pulls back by this distance. |
| **Stealth TP Pips** | Float (Pips) | `0.0` | *Requires Stealth Mode.* The take-profit target for *individual positions* in pips, closed silently in Python memory. |

---

## 3. Scenario Analysis

Understanding what happens during different market structures is vital for setting your configurations.

### Scenario A: The Clean Uptrend (Easy Profit)
* **Market Action:** The price moves straight up from your entry point.
* **Bot Behavior:**
  * Placing the initial BUY succeeds.
  * The price never drops by the **Pip Threshold**, so no SELL order is placed.
  * The trade hits your **TP USD** (or **Stealth TP Pips** if using Stealth Mode) and closes cleanly.

### Scenario B: High Volatility & Consolidation (Active Hedging)
* **Market Action:** The price chops up and down within a range.
* **Bot Behavior:**
  * Initial BUY opens at `1.1620`.
  * Price drops to `1.1617` (3 pips down). The bot places a **SELL** hedge.
  * Price rises to `1.1621`. The bot closes the old SELL, and places a **new SELL** at the new high.
  * *Result:* Your risk is safely controlled, but multiple transaction fees (spreads) are paid. Keeping the **Pip Threshold** too tight during high volatility can lead to "churning" (excessive trading costs).

### Scenario C: Trailing Stop and Stealth TP are set to `0`
* **Market Action:** Any market structure.
* **Bot Behavior:**
  * The bot **never** closes individual trades early.
  * All open BUY and SELL positions are held open together.
  * The bot relies **exclusively** on the **TP USD** and **SL USD** parameters to close the trade basket. 
  * *Recommended Use:* This is the preferred configuration if you want the hedging grid to run as a complete, unified system.

---

## 4. Advanced Technical Details

### Dynamic Filling Mode Support (Automatic)
Brokers have strict rules on how orders must be filled. The bot contains a built-in auto-detection mechanism:
* **FOK (Fill Or Kill):** The order must be executed immediately in its entirety, or it is cancelled. (Used by Deriv Major Pairs).
* **IOC (Immediate Or Cancel):** Any part of the order that can be filled is executed immediately, and the remaining part is cancelled.
* **RETURN:** Standard exchange execution mode.
> [!NOTE]
> The bot automatically queries the `symbol_info` from your specific broker and selects the correct filling mode dynamically. You do not need to manually configure this.

### Global Trading Permission Safeguard
If the bot fails with a **`10027`** error, algorithmic trading has been disabled globally by the client. To resolve:
1. Ensure the **Algo Trading** button in the top menu of MT5 is **Green**.
2. Navigate to `Tools` > `Options` > `Expert Advisors` and verify **Allow algorithmic trading** is checked.
