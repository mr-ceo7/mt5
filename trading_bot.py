import MetaTrader5 as mt5
import time
import os
import argparse
from collections import namedtuple
import multiprocessing
import threading

# --- Account credentials ---
MT5_LOGIN = int(os.getenv('MT5_LOGIN', '12345678'))
MT5_PASSWORD = os.getenv('MT5_PASSWORD', 'your_password')
MT5_SERVER = os.getenv('MT5_SERVER', 'your_server')

# --- Data Structures ---
SymbolConfig = namedtuple('SymbolConfig', [
    'name', 'lot_size', 'pip_threshold', 'tp_usd', 'sl_usd', 
    'pip_move_threshold', 'trailing_stop_pips', 'stealth_mode', 'stealth_tp_pips'
])

# --- Bot Logic (Queue-based Logging) ---

def initialize_mt5(log_queue):
    """Initializes and connects to the MetaTrader 5 terminal."""
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        log_queue.put(f"initialize() failed, error code = {mt5.last_error()}")
        return False
    log_queue.put("MetaTrader 5 initialized successfully.")
    return True

def get_pip_size(symbol):
    """Gets the pip size for a given symbol."""
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None: return None
    return symbol_info.point * 10

def modify_position_sl(position, new_sl, log_queue):
    """Modifies the stop loss of an open position."""
    request = {"action": mt5.TRADE_ACTION_SLTP, "position": position.ticket, "sl": new_sl}
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        log_queue.put(f"[{position.symbol}] Position {position.ticket} SL modified to {new_sl:.5f}")
    else:
        log_queue.put(f"[{position.symbol}] Failed to modify SL for position {position.ticket}, retcode={result.retcode}")

def handle_trailing_stop(position, trailing_stop_pips, stealth_mode, log_queue):
    """Manages the trailing stop for a single position."""
    if not stealth_mode or trailing_stop_pips <= 0: return

    symbol = position.symbol
    pip_size = get_pip_size(symbol)
    point = mt5.symbol_info(symbol).point
    trailing_stop_distance = trailing_stop_pips * pip_size

    if position.type == mt5.ORDER_TYPE_BUY:
        current_price = mt5.symbol_info_tick(symbol).bid
        new_sl = current_price - trailing_stop_distance
        if new_sl > position.sl or position.sl == 0.0:
            if new_sl < current_price - point:
                modify_position_sl(position, new_sl, log_queue)
    elif position.type == mt5.ORDER_TYPE_SELL:
        current_price = mt5.symbol_info_tick(symbol).ask
        new_sl = current_price + trailing_stop_distance
        if new_sl < position.sl or position.sl == 0.0:
            if new_sl > current_price + point:
                modify_position_sl(position, new_sl, log_queue)

def handle_stealth_tp(position, stealth_tp_pips, log_queue):
    """Manages the stealth take profit for a single position."""
    if stealth_tp_pips <= 0: return

    symbol = position.symbol
    pip_size = get_pip_size(symbol)
    tp_distance = stealth_tp_pips * pip_size

    if position.type == mt5.ORDER_TYPE_BUY:
        current_price = mt5.symbol_info_tick(symbol).bid
        tp_price = position.price_open + tp_distance
        if current_price >= tp_price:
            log_queue.put(f"[{symbol}] Stealth TP hit for BUY position {position.ticket}. Closing.")
            close_position(position, log_queue, "Stealth TP")
    elif position.type == mt5.ORDER_TYPE_SELL:
        current_price = mt5.symbol_info_tick(symbol).ask
        tp_price = position.price_open - tp_distance
        if current_price <= tp_price:
            log_queue.put(f"[{symbol}] Stealth TP hit for SELL position {position.ticket}. Closing.")
            close_position(position, log_queue, "Stealth TP")

def place_order(symbol, order_type, lot_size, log_queue, price=None, magic=202403, stealth_mode=False):
    """Places a trade order."""
    request = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lot_size, "type": order_type,
        "price": price if price is not None else mt5.symbol_info_tick(symbol).ask if order_type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).bid,
        "deviation": 10, "magic": magic, "comment": "trading_bot", "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
        "sl": 0.0 if stealth_mode else None, "tp": 0.0 if stealth_mode else None,
    }
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log_queue.put(f"[{symbol}] order_send failed, retcode={result.retcode}")
        return None
    log_queue.put(f"[{symbol}] Order placed successfully: Ticket {result.order}")
    return result

def close_position(position, log_queue, comment="closing position"):
    """Closes a specific position."""
    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = mt5.symbol_info_tick(position.symbol).bid if position.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(position.symbol).ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL, "position": position.ticket, "symbol": position.symbol,
        "volume": position.volume, "type": order_type, "price": price, "deviation": 10,
        "magic": 202403, "comment": comment, "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        log_queue.put(f"[{position.symbol}] Position {position.ticket} closed successfully.")
    else:
        log_queue.put(f"[{position.symbol}] Failed to close position {position.ticket}, retcode={result.retcode}")

def close_all_positions(symbol, log_queue, comment="closing all"):
    """Closes all open positions for a given symbol."""
    positions = mt5.positions_get(symbol=symbol)
    if positions is None or len(positions) == 0: return
    log_queue.put(f"[{symbol}] Closing all {len(positions)} positions...")
    for position in positions:
        close_position(position, log_queue, comment)
    time.sleep(1)

def get_open_positions(symbol):
    """Gets all open positions for a symbol, categorized by type."""
    positions = mt5.positions_get(symbol=symbol)
    if positions is None: return [], [], 0.0
    buy_orders = [p for p in positions if p.type == mt5.ORDER_TYPE_BUY]
    sell_orders = [p for p in positions if p.type == mt5.ORDER_TYPE_SELL]
    total_profit = sum(p.profit for p in positions)
    return buy_orders, sell_orders, total_profit

def process_symbol_logic(config: SymbolConfig, log_queue):
    """Runs the trading logic for a single symbol."""
    symbol = config.name
    buy_orders, sell_orders, total_profit = get_open_positions(symbol)

    if config.stealth_mode:
        for p in buy_orders + sell_orders:
            handle_trailing_stop(p, config.trailing_stop_pips, config.stealth_mode, log_queue)
            handle_stealth_tp(p, config.stealth_tp_pips, log_queue)

    if total_profit >= config.tp_usd:
        log_queue.put(f"[{symbol}] Portfolio TP of ${config.tp_usd} reached. Profit: ${total_profit:.2f}. Closing positions.")
        close_all_positions(symbol, log_queue, "Portfolio TP")
        return
    
    if total_profit <= -config.sl_usd:
        log_queue.put(f"[{symbol}] Portfolio SL of ${config.sl_usd} reached. Loss: ${total_profit:.2f}. Closing positions.")
        close_all_positions(symbol, log_queue, "Portfolio SL")
        return

    if not buy_orders and not sell_orders:
        log_queue.put(f"[{symbol}] No open positions. Placing initial buy order.")
        place_order(symbol, mt5.ORDER_TYPE_BUY, config.lot_size, log_queue, stealth_mode=config.stealth_mode)
    
    elif buy_orders and not sell_orders:
        initial_buy = buy_orders[0]
        current_bid_price = mt5.symbol_info_tick(symbol).bid
        if current_bid_price < initial_buy.price_open - config.pip_move_threshold:
            log_queue.put(f"[{symbol}] Price dropped below buy. Placing initial sell order.")
            place_order(symbol, mt5.ORDER_TYPE_SELL, config.lot_size, log_queue, stealth_mode=config.stealth_mode)

    elif sell_orders:
        latest_sell = max(sell_orders, key=lambda p: p.price_open)
        current_ask_price = mt5.symbol_info_tick(symbol).ask
        if current_ask_price > latest_sell.price_open + config.pip_move_threshold:
            log_queue.put(f"[{symbol}] Price moved above latest sell. Hedging new sell.")
            close_position(latest_sell, log_queue, "hedging new sell")
            place_order(symbol, mt5.ORDER_TYPE_SELL, config.lot_size, log_queue, stealth_mode=config.stealth_mode)

def run_bot(configs, log_queue):
    """The main trading bot loop."""
    log_queue.put("--- Starting Bot ---")
    for config in configs:
        log_queue.put(f"  - Symbol: {config.name}, Lot: {config.lot_size}, Pips: {config.pip_threshold}, TP: ${config.tp_usd}, SL: ${config.sl_usd}")
        if config.stealth_mode:
            log_queue.put(f"    Stealth Mode: ON, Trailing SL: {config.trailing_stop_pips} pips, Stealth TP: {config.stealth_tp_pips} pips")
    log_queue.put("--------------------")

    try:
        while True:
            for config in configs:
                process_symbol_logic(config, log_queue)
            time.sleep(5)
    except KeyboardInterrupt:
        log_queue.put("\nBot stopped by user.")
    finally:
        log_queue.put("Closing all positions for all symbols...")
        for config in configs:
            close_all_positions(config.name, log_queue, "Bot shutdown")

def start_bot_process(configs, log_queue):
    """The main entry point for the bot process."""
    if not initialize_mt5(log_queue):
        log_queue.put("Could not initialize MT5. Bot process terminated.")
        return

    run_bot(configs, log_queue)

    mt5.shutdown()
    log_queue.put("MetaTrader 5 connection closed.")

# --- CLI-specific functionality ---

def log_consumer(log_queue, stop_event):
    """Consumes logs from the queue and prints them to the console."""
    while not stop_event.is_set():
        try:
            log = log_queue.get(timeout=0.1)
            print(log)
        except multiprocessing.queues.Empty:
            continue

def main_cli():
    """Parses CLI arguments and runs the bot in command-line mode."""
    parser = argparse.ArgumentParser(description="MetaTrader 5 Hedging Bot.")
    # ... (all argparse definitions are the same as before)
    parser.add_argument('--symbol', type=str, nargs='+', default=["EURUSD"], help="List of symbols to trade")
    parser.add_argument('--lot-size', type=float, nargs='+', default=[0.01], help="List of lot sizes")
    parser.add_argument('--pip-threshold', type=float, nargs='+', default=[3.0], help="List of pip thresholds for hedging")
    parser.add_argument('--tp-usd', type=float, nargs='+', default=[50.0], help="List of portfolio take profits in USD")
    parser.add_argument('--sl-usd', type=float, nargs='+', default=[25.0], help="List of portfolio stop losses in USD")
    parser.add_argument('--stealth-mode', action='store_true', help="Enable stealth mode (internal SL/TP management)")
    parser.add_argument('--trailing-stop-pips', type=float, nargs='+', default=[0.0], help="Trailing stop in pips (requires stealth mode)")
    parser.add_argument('--stealth-tp-pips', type=float, nargs='+', default=[0.0], help="Per-trade take profit in pips (requires stealth mode)")
    
    args = parser.parse_args()

    param_lists = {
        'lot_size': args.lot_size, 'pip_threshold': args.pip_threshold,
        'tp_usd': args.tp_usd, 'sl_usd': args.sl_usd,
        'trailing_stop_pips': args.trailing_stop_pips, 'stealth_tp_pips': args.stealth_tp_pips,
    }

    num_symbols = len(args.symbol)
    for param, values in param_lists.items():
        if len(values) == 1:
            vars(args)[param] = values * num_symbols
        elif len(values) != num_symbols:
            print(f"Error: --{param.replace('_', '-')} args must match --symbol args or be 1.")
            return

    # --- Symbol Discovery ---
    print("Attempting to connect to MT5 for symbol discovery...")
    if mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        print("MT5 connection successful for discovery.")
        
        print("Discovering symbols by index:")
        for i in range(100):
            symbol_info = mt5.symbol_info(i)
            if symbol_info is not None:
                print(f"  - Index {i}: {symbol_info.name}")
            
        mt5.shutdown()
        print("MT5 connection closed after discovery.")
        return # Stop execution after listing symbols
    else:
        print(f"Could not connect to MT5 for symbol discovery. Error: {mt5.last_error()}")
        return

    # The rest of the main_cli function is now unreachable because of the return,
    # which is what we want for this debugging step.
    # ...
    
    args = parser.parse_args()
    # ... (The original logic remains below but won't be executed)
    param_lists = {
        'lot_size': args.lot_size, 'pip_threshold': args.pip_threshold,
        'tp_usd': args.tp_usd, 'sl_usd': args.sl_usd,
        'trailing_stop_pips': args.trailing_stop_pips, 'stealth_tp_pips': args.stealth_tp_pips,
    }
    # ...
    return

if __name__ == "__main__":
    main_cli()
