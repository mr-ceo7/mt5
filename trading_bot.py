from mt5linux import MetaTrader5
import time
import os
import argparse
from collections import namedtuple
import multiprocessing
import threading
import json

# Create the mt5linux proxy object that connects to the rpyc server
mt5 = MetaTrader5(host='127.0.0.1', port=18812)

# --- State Persistence Helpers ---
STATE_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot_state.json')

def load_bot_state():
    """Loads the bot state from bot_state.json."""
    if not os.path.exists(STATE_FILE_PATH):
        return {}
    try:
        with open(STATE_FILE_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_bot_state(state):
    """Saves the bot state to bot_state.json."""
    try:
        with open(STATE_FILE_PATH, 'w') as f:
            json.dump(state, f, indent=4)
    except Exception:
        pass

def get_open_position_by_ticket(ticket):
    """Checks if a position with the given ticket is open, returning the position object or None."""
    if not ticket:
        return None
    try:
        positions = mt5.positions_get()
        if positions is not None:
            for p in positions:
                if p.ticket == ticket:
                    return p
    except Exception:
        pass
    return None

def ensure_connection(log_queue):
    """Ensures connection to the MetaTrader 5 RPyC server and the MT5 terminal IPC."""
    global mt5
    
    # 1. Verify RPyC proxy socket connection is alive
    rpyc_alive = False
    try:
        conn = getattr(mt5, "_MetaTrader5__conn", None)
        if conn is not None:
            conn.ping()
            rpyc_alive = True
    except Exception as e:
        log_queue.put(f"RPyC proxy connection lost: {str(e)}. Reconnecting socket...")

    # If proxy is dead, we must recreate the MetaTrader5 object
    if not rpyc_alive:
        for attempt in range(1, 6):
            try:
                log_queue.put(f"Reconnecting RPyC proxy socket (attempt {attempt}/5)...")
                mt5 = MetaTrader5(host='127.0.0.1', port=18812)
                if initialize_mt5(log_queue):
                    log_queue.put("Reconnected successfully to RPyC proxy.")
                    return True
            except Exception as ex:
                log_queue.put(f"Proxy socket reconnection failed: {str(ex)}")
            time.sleep(3)
        log_queue.put("CRITICAL ERROR: Failed to reconnect to RPyC proxy.")
        return False

    # 2. RPyC proxy is alive. Verify MT5 Terminal IPC is connected.
    try:
        info = mt5.terminal_info()
        if info is not None:
            return True
        
        # If terminal_info returned None, check error
        err = mt5.last_error()
        log_queue.put(f"MT5 Terminal IPC unresponsive or disconnected (last_error: {err}). Re-initializing IPC connection...")
    except Exception as e:
        log_queue.put(f"Error checking terminal IPC: {str(e)}. Re-initializing...")

    # Re-initialize MT5 connection using existing proxy object
    if initialize_mt5(log_queue):
        log_queue.put("Reconnected successfully to MT5 Terminal IPC.")
        return True
        
    return False

def check_margin_safeguard(min_margin_level, log_queue):
    """Checks the account margin level against the configured threshold.
    Returns True if margin is safe, False if it is below the threshold.
    """
    try:
        acc_info = mt5.account_info()
        if acc_info is None:
            log_queue.put("WARNING: Failed to retrieve account info to check margin level.")
            return True
        
        if acc_info.margin_level == 0.0:
            return True
            
        if acc_info.margin_level < min_margin_level:
            log_queue.put(f"CRITICAL WARNING: Account Margin Level ({acc_info.margin_level:.2f}%) is below minimum threshold ({min_margin_level:.2f}%). TRADING PAUSED.")
            return False
    except Exception as e:
        log_queue.put(f"WARNING: Exception in margin safeguard check: {str(e)}")
    return True

# --- Account credentials ---
MT5_LOGIN = int(os.getenv('MT5_LOGIN', '12345678'))
MT5_PASSWORD = os.getenv('MT5_PASSWORD', 'your_password')
MT5_SERVER = os.getenv('MT5_SERVER', 'your_server')

CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'account_credentials.json')

def load_credentials():
    """Loads account credentials from account_credentials.json."""
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, 'r') as f:
                data = json.load(f)
                if 'login' in data and 'password' in data and 'server' in data:
                    return int(data['login']), data['password'], data['server']
        except Exception:
            pass
    return None

# --- Data Structures ---
SymbolConfig = namedtuple('SymbolConfig', [
    'name', 'lot_size', 'pip_threshold', 'tp_usd', 'sl_usd', 
    'pip_move_threshold', 'trailing_stop_pips', 'stealth_mode', 'stealth_tp_pips',
    'strategy_type', 'risk_usd', 'target_usd'
])

# --- Bot Logic (Queue-based Logging) ---

def initialize_mt5(log_queue):
    """Initializes and connects to the MetaTrader 5 terminal using persisted or environment credentials."""
    creds = load_credentials()
    if creds:
        login, password, server = creds
        log_queue.put(f"Initializing MT5 with persisted credentials for account {login} on server {server}...")
        success = mt5.initialize(login=login, password=password, server=server)
    elif MT5_SERVER == 'your_server':
        # Use active terminal account if no credentials are provided via env
        log_queue.put("Initializing MT5 using active terminal account...")
        success = mt5.initialize()
    else:
        log_queue.put(f"Initializing MT5 with environment credentials for account {MT5_LOGIN}...")
        success = mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
        
    if not success:
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
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log_queue.put(f"[{symbol}] order_send failed: Failed to get tick info for price calculation.")
        return None

    order_price = price if price is not None else tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

    # Determine correct filling mode dynamically
    info = mt5.symbol_info(symbol)
    filling_mode = mt5.ORDER_FILLING_FOK
    if info is not None:
        if info.filling_mode & 1:
            filling_mode = mt5.ORDER_FILLING_FOK
        elif info.filling_mode & 2:
            filling_mode = mt5.ORDER_FILLING_IOC
        else:
            filling_mode = mt5.ORDER_FILLING_RETURN

    request = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lot_size, "type": order_type,
        "price": order_price,
        "deviation": 10, "magic": magic, "comment": "trading_bot", "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
        "sl": 0.0, "tp": 0.0,
    }
    result = mt5.order_send(request)
    if result is None:
        log_queue.put(f"[{symbol}] order_send failed and returned None. last_error: {mt5.last_error()}")
        return None
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log_queue.put(f"[{symbol}] order_send failed, retcode={result.retcode}")
        return None
    log_queue.put(f"[{symbol}] Order placed successfully: Ticket {result.order}")
    return result

def close_position(position, log_queue, comment="closing position"):
    """Closes a specific position. Returns the position's profit at the time of closing, or 0.0 on failure."""
    realized = position.profit  # Capture profit before closing
    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    
    tick = mt5.symbol_info_tick(position.symbol)
    if tick is None:
        log_queue.put(f"[{position.symbol}] close_position failed: Failed to get tick info.")
        return 0.0

    price = tick.bid if position.type == mt5.ORDER_TYPE_BUY else tick.ask

    # Determine correct filling mode dynamically
    info = mt5.symbol_info(position.symbol)
    filling_mode = mt5.ORDER_FILLING_FOK
    if info is not None:
        if info.filling_mode & 1:
            filling_mode = mt5.ORDER_FILLING_FOK
        elif info.filling_mode & 2:
            filling_mode = mt5.ORDER_FILLING_IOC
        else:
            filling_mode = mt5.ORDER_FILLING_RETURN

    request = {
        "action": mt5.TRADE_ACTION_DEAL, "position": position.ticket, "symbol": position.symbol,
        "volume": position.volume, "type": order_type, "price": price, "deviation": 10,
        "magic": 202403, "comment": comment, "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
    }
    result = mt5.order_send(request)
    if result is None:
        log_queue.put(f"[{position.symbol}] close_position failed and returned None. last_error: {mt5.last_error()}")
        return 0.0
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        log_queue.put(f"[{position.symbol}] Position {position.ticket} closed successfully. Realized: ${realized:.2f}")
        return realized
    else:
        log_queue.put(f"[{position.symbol}] Failed to close position {position.ticket}, retcode={result.retcode}")
        return 0.0

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

def process_hedging_logic(config: SymbolConfig, log_queue, margin_safe=True, realized_pnl_accumulator=None):
    """Runs the trading logic for a single symbol using state persistence (HEDGING STRATEGY)."""
    symbol = config.name
    
    # Load state
    state = load_bot_state()
    symbol_state = state.get(symbol, {"initial_buy_ticket": None, "active_hedge_ticket": None})
    
    initial_buy_ticket = symbol_state.get("initial_buy_ticket")
    active_hedge_ticket = symbol_state.get("active_hedge_ticket")
    
    # Verify positions exist in MT5
    initial_buy = get_open_position_by_ticket(initial_buy_ticket)
    active_hedge = get_open_position_by_ticket(active_hedge_ticket)
    
    # Sync state if positions were closed externally
    state_changed = False
    if initial_buy_ticket and not initial_buy:
        log_queue.put(f"[{symbol}] Tracked initial buy position {initial_buy_ticket} no longer active. Clearing from state.")
        symbol_state["initial_buy_ticket"] = None
        initial_buy_ticket = None
        state_changed = True
        
    if active_hedge_ticket and not active_hedge:
        log_queue.put(f"[{symbol}] Tracked active hedge position {active_hedge_ticket} no longer active. Clearing from state.")
        symbol_state["active_hedge_ticket"] = None
        active_hedge_ticket = None
        state_changed = True
        
    if state_changed:
        state[symbol] = symbol_state
        save_bot_state(state)
        
    # Calculate total profit ONLY for tracked positions
    total_profit = 0.0
    if initial_buy:
        total_profit += initial_buy.profit
    if active_hedge:
        total_profit += active_hedge.profit
        
    # Manage trailing stop and stealth TP for tracked positions
    if config.stealth_mode:
        if initial_buy:
            handle_trailing_stop(initial_buy, config.trailing_stop_pips, config.stealth_mode, log_queue)
            handle_stealth_tp(initial_buy, config.stealth_tp_pips, log_queue)
        if active_hedge:
            handle_trailing_stop(active_hedge, config.trailing_stop_pips, config.stealth_mode, log_queue)
            handle_stealth_tp(active_hedge, config.stealth_tp_pips, log_queue)

    # Check portfolio take profit and stop loss
    if (initial_buy or active_hedge):
        if total_profit >= config.tp_usd:
            log_queue.put(f"[{symbol}] Portfolio TP of ${config.tp_usd} reached. Profit: ${total_profit:.2f}. Closing positions.")
            if initial_buy:
                r = close_position(initial_buy, log_queue, "Portfolio TP")
                if realized_pnl_accumulator is not None: realized_pnl_accumulator[0] += r
            if active_hedge:
                r = close_position(active_hedge, log_queue, "Portfolio TP")
                if realized_pnl_accumulator is not None: realized_pnl_accumulator[0] += r
            symbol_state["initial_buy_ticket"] = None
            symbol_state["active_hedge_ticket"] = None
            state[symbol] = symbol_state
            save_bot_state(state)
            return total_profit
        
        if total_profit <= -config.sl_usd:
            log_queue.put(f"[{symbol}] Portfolio SL of ${config.sl_usd} reached. Loss: ${total_profit:.2f}. Closing positions.")
            if initial_buy:
                r = close_position(initial_buy, log_queue, "Portfolio SL")
                if realized_pnl_accumulator is not None: realized_pnl_accumulator[0] += r
            if active_hedge:
                r = close_position(active_hedge, log_queue, "Portfolio SL")
                if realized_pnl_accumulator is not None: realized_pnl_accumulator[0] += r
            symbol_state["initial_buy_ticket"] = None
            symbol_state["active_hedge_ticket"] = None
            state[symbol] = symbol_state
            save_bot_state(state)
            return total_profit

    # Check margin safeguard before taking action
    if not margin_safe:
        return total_profit

    # Case A: No open tracked positions (No Buy, No Sell/Hedge)
    if not initial_buy and not active_hedge:
        log_queue.put(f"[{symbol}] No active tracked positions. Placing initial buy order.")
        res = place_order(symbol, mt5.ORDER_TYPE_BUY, config.lot_size, log_queue, stealth_mode=config.stealth_mode)
        if res:
            symbol_state["initial_buy_ticket"] = res.order
            state[symbol] = symbol_state
            save_bot_state(state)
            
    # Case B: Only Buy is active (No Sell/Hedge)
    elif initial_buy and not active_hedge:
        current_bid_price = mt5.symbol_info_tick(symbol).bid
        if current_bid_price < initial_buy.price_open - config.pip_move_threshold:
            log_queue.put(f"[{symbol}] Price dropped below buy. Placing initial sell order.")
            res = place_order(symbol, mt5.ORDER_TYPE_SELL, config.lot_size, log_queue, stealth_mode=config.stealth_mode)
            if res:
                symbol_state["active_hedge_ticket"] = res.order
                state[symbol] = symbol_state
                save_bot_state(state)

    # Case C: Active Sell/Hedge is active
    elif active_hedge:
        current_ask_price = mt5.symbol_info_tick(symbol).ask
        if current_ask_price > active_hedge.price_open + config.pip_move_threshold:
            log_queue.put(f"[{symbol}] Price moved above active hedge. Hedging new sell.")
            r = close_position(active_hedge, log_queue, "hedging new sell")
            if realized_pnl_accumulator is not None: realized_pnl_accumulator[0] += r
            
            # Instantly clear state for active hedge
            symbol_state["active_hedge_ticket"] = None
            state[symbol] = symbol_state
            save_bot_state(state)
            
            res = place_order(symbol, mt5.ORDER_TYPE_SELL, config.lot_size, log_queue, stealth_mode=config.stealth_mode)
            if res:
                symbol_state["active_hedge_ticket"] = res.order
                state[symbol] = symbol_state
                save_bot_state(state)

    return total_profit

def process_dual_buy_sell_logic(config: SymbolConfig, log_queue, margin_safe=True, realized_pnl_accumulator=None):
    """Runs the trading logic for a single symbol using Dual Buy-Sell Cycle strategy."""
    symbol = config.name
    
    # Load state
    state = load_bot_state()
    symbol_state = state.get(symbol, {
        "strategy_type": "dual_buy_sell",
        "buy_ticket": None,
        "sell_ticket": None,
        "stage": 1
    })
    
    buy_ticket = symbol_state.get("buy_ticket")
    sell_ticket = symbol_state.get("sell_ticket")
    
    # Verify positions exist in MT5
    buy_pos = get_open_position_by_ticket(buy_ticket)
    sell_pos = get_open_position_by_ticket(sell_ticket)
    
    # Sync state if positions were closed externally
    state_changed = False
    if buy_ticket and not buy_pos:
        log_queue.put(f"[{symbol}] Tracked BUY position {buy_ticket} no longer active. Clearing from state.")
        symbol_state["buy_ticket"] = None
        buy_ticket = None
        state_changed = True
        
    if sell_ticket and not sell_pos:
        log_queue.put(f"[{symbol}] Tracked SELL position {sell_ticket} no longer active. Clearing from state.")
        symbol_state["sell_ticket"] = None
        sell_ticket = None
        state_changed = True
        
    if state_changed:
        state[symbol] = symbol_state
        save_bot_state(state)
        
    # Check for incomplete Stage 1 setup (e.g. if one of the orders failed to place or was closed externally in stage 1)
    if symbol_state.get("stage", 1) == 1 and (buy_pos or sell_pos) and (not buy_pos or not sell_pos):
        log_queue.put(f"[{symbol}] Incomplete Stage 1 setup detected (BUY: {buy_pos.ticket if buy_pos else 'None'}, SELL: {sell_pos.ticket if sell_pos else 'None'}). Aborting cycle to reset.")
        if buy_pos:
            r = close_position(buy_pos, log_queue, "Aborting incomplete cycle")
            if realized_pnl_accumulator is not None:
                realized_pnl_accumulator[0] += r
        if sell_pos:
            r = close_position(sell_pos, log_queue, "Aborting incomplete cycle")
            if realized_pnl_accumulator is not None:
                realized_pnl_accumulator[0] += r
                
        symbol_state["buy_ticket"] = None
        symbol_state["sell_ticket"] = None
        symbol_state["stage"] = 1
        state[symbol] = symbol_state
        save_bot_state(state)
        return 0.0
        
    # Calculate current unrealized total profit of tracked positions
    total_unrealized = 0.0
    if buy_pos:
        total_unrealized += buy_pos.profit
    if sell_pos:
        total_unrealized += sell_pos.profit

    # Check margin safeguard before taking action
    if not margin_safe:
        return total_unrealized

    # Case 1: No open tracked positions (Start of a new cycle)
    if not buy_pos and not sell_pos:
        log_queue.put(f"[{symbol}] Starting new Dual Buy-Sell cycle. Placing BUY and SELL orders.")
        
        # Place Buy order
        buy_res = place_order(symbol, mt5.ORDER_TYPE_BUY, config.lot_size, log_queue, stealth_mode=config.stealth_mode)
        # Place Sell order
        sell_res = place_order(symbol, mt5.ORDER_TYPE_SELL, config.lot_size, log_queue, stealth_mode=config.stealth_mode)
        
        if buy_res or sell_res:
            symbol_state["buy_ticket"] = buy_res.order if buy_res else None
            symbol_state["sell_ticket"] = sell_res.order if sell_res else None
            symbol_state["stage"] = 1
            state[symbol] = symbol_state
            save_bot_state(state)
            
    # Case 2: Both Buy and Sell positions are open (Stage 1)
    elif buy_pos and sell_pos:
        # Monitor losing leg
        # If BUY profit <= -risk_usd
        if buy_pos.profit <= -config.risk_usd:
            log_queue.put(f"[{symbol}] BUY position {buy_pos.ticket} hit risk limit of -${config.risk_usd:.2f} (Profit: ${buy_pos.profit:.2f}). Closing.")
            r = close_position(buy_pos, log_queue, "Risk limit hit")
            if realized_pnl_accumulator is not None:
                realized_pnl_accumulator[0] += r
                
            symbol_state["buy_ticket"] = None
            symbol_state["stage"] = 2
            state[symbol] = symbol_state
            save_bot_state(state)
            
        # If SELL profit <= -risk_usd
        elif sell_pos.profit <= -config.risk_usd:
            log_queue.put(f"[{symbol}] SELL position {sell_pos.ticket} hit risk limit of -${config.risk_usd:.2f} (Profit: ${sell_pos.profit:.2f}). Closing.")
            r = close_position(sell_pos, log_queue, "Risk limit hit")
            if realized_pnl_accumulator is not None:
                realized_pnl_accumulator[0] += r
                
            symbol_state["sell_ticket"] = None
            symbol_state["stage"] = 2
            state[symbol] = symbol_state
            save_bot_state(state)
            
    # Case 3: Only one position is open (Stage 2)
    else:
        active_pos = buy_pos if buy_pos else sell_pos
        pos_type = "BUY" if buy_pos else "SELL"
        
        # If the remaining position hits target_usd profit
        if active_pos.profit >= config.target_usd:
            log_queue.put(f"[{symbol}] Active {pos_type} position {active_pos.ticket} reached target profit of ${config.target_usd:.2f} (Profit: ${active_pos.profit:.2f}). Closing.")
            r = close_position(active_pos, log_queue, "Target profit hit")
            if realized_pnl_accumulator is not None:
                realized_pnl_accumulator[0] += r
                
            symbol_state["buy_ticket"] = None
            symbol_state["sell_ticket"] = None
            symbol_state["stage"] = 1
            state[symbol] = symbol_state
            save_bot_state(state)
            
        # If the remaining position reverses and hits -risk_usd to prevent whipsaw losses
        elif active_pos.profit <= -config.risk_usd:
            log_queue.put(f"[{symbol}] Active {pos_type} position {active_pos.ticket} hit stop loss/risk limit of -${config.risk_usd:.2f} (Profit: ${active_pos.profit:.2f}). Closing.")
            r = close_position(active_pos, log_queue, "Position reversed")
            if realized_pnl_accumulator is not None:
                realized_pnl_accumulator[0] += r
                
            symbol_state["buy_ticket"] = None
            symbol_state["sell_ticket"] = None
            symbol_state["stage"] = 1
            state[symbol] = symbol_state
            save_bot_state(state)

    return total_unrealized

def process_symbol_logic(config: SymbolConfig, log_queue, margin_safe=True, realized_pnl_accumulator=None):
    """Routes the trading logic for a symbol to the configured strategy."""
    strat = getattr(config, 'strategy_type', 'hedge')
    if strat == 'dual_buy_sell':
        return process_dual_buy_sell_logic(config, log_queue, margin_safe, realized_pnl_accumulator)
    else:
        return process_hedging_logic(config, log_queue, margin_safe, realized_pnl_accumulator)

def run_bot(configs, log_queue, min_margin_level=200.0, shared_pnl=None):
    """The main trading bot loop."""
    log_queue.put("--- Starting Bot ---")
    for config in configs:
        log_queue.put(f"  - Symbol: {config.name}, Lot: {config.lot_size}, Pips: {config.pip_threshold}, TP: ${config.tp_usd}, SL: ${config.sl_usd}")
        if config.stealth_mode:
            log_queue.put(f"    Stealth Mode: ON, Trailing SL: {config.trailing_stop_pips} pips, Stealth TP: {config.stealth_tp_pips} pips")
    log_queue.put(f"  - Min Margin Level safeguard: {min_margin_level}%")
    log_queue.put("--------------------")

    # Accumulator for realized P&L (profits from closed positions)
    realized_pnl = [0.0]

    try:
        while True:
            # 1. Auto-Reconnection check before each trading iteration
            if not ensure_connection(log_queue):
                log_queue.put("Bot is waiting for RPyC connection to recover...")
                time.sleep(10)
                continue

            # 2. Check margin safeguard
            margin_safe = check_margin_safeguard(min_margin_level, log_queue)

            # 3. Process each configured symbol and collect unrealized P&L
            unrealized_pnl = 0.0
            for config in configs:
                try:
                    symbol_unrealized = process_symbol_logic(config, log_queue, margin_safe, realized_pnl)
                    if symbol_unrealized is not None:
                        unrealized_pnl += symbol_unrealized
                except Exception as e:
                    log_queue.put(f"ERROR: Exception while processing symbol {config.name}: {str(e)}")

            # 4. Update shared session P&L (realized + unrealized)
            if shared_pnl is not None:
                shared_pnl.value = realized_pnl[0] + unrealized_pnl

            time.sleep(5)
    except KeyboardInterrupt:
        log_queue.put("\nBot stopped by user.")
    finally:
        log_queue.put("Closing tracked positions for all symbols on shutdown...")
        try:
            if ensure_connection(log_queue):
                state = load_bot_state()
                for config in configs:
                    symbol = config.name
                    symbol_state = state.get(symbol, {})
                    
                    # Close open tracked positions for all potential keys across strategies
                    for tk_key in ["initial_buy_ticket", "active_hedge_ticket", "buy_ticket", "sell_ticket"]:
                        ticket = symbol_state.get(tk_key)
                        if ticket:
                            pos = get_open_position_by_ticket(ticket)
                            if pos:
                                close_position(pos, log_queue, "Bot shutdown")
                            symbol_state[tk_key] = None
                    
                    state[symbol] = symbol_state
                save_bot_state(state)
        except Exception as e:
            log_queue.put(f"ERROR: Exception during bot shutdown cleanup: {str(e)}")

def start_bot_process(configs, log_queue, min_margin_level=200.0, shared_pnl=None):
    """The main entry point for the bot process."""
    global mt5
    try:
        log_queue.put("Creating dedicated MT5 RPyC connection for bot process...")
        mt5 = MetaTrader5(host='127.0.0.1', port=18812)
    except Exception as e:
        log_queue.put(f"ERROR: Failed to establish dedicated RPyC connection in bot process: {str(e)}")
        return

    if not initialize_mt5(log_queue):
        log_queue.put("Could not initialize MT5. Bot process terminated.")
        return

    run_bot(configs, log_queue, min_margin_level, shared_pnl)

    try:
        mt5.shutdown()
    except Exception:
        pass
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
    parser.add_argument('--symbol', type=str, nargs='+', default=["EURUSD"], help="List of symbols to trade")
    parser.add_argument('--lot-size', type=float, nargs='+', default=[0.01], help="List of lot sizes")
    parser.add_argument('--pip-threshold', type=float, nargs='+', default=[3.0], help="List of pip thresholds for hedging")
    parser.add_argument('--tp-usd', type=float, nargs='+', default=[50.0], help="List of portfolio take profits in USD")
    parser.add_argument('--sl-usd', type=float, nargs='+', default=[25.0], help="List of portfolio stop losses in USD")
    parser.add_argument('--stealth-mode', action='store_true', help="Enable stealth mode (internal SL/TP management)")
    parser.add_argument('--trailing-stop-pips', type=float, nargs='+', default=[0.0], help="Trailing stop in pips (requires stealth mode)")
    parser.add_argument('--stealth-tp-pips', type=float, nargs='+', default=[0.0], help="Per-trade take profit in pips (requires stealth mode)")
    parser.add_argument('--min-margin-level', type=float, default=200.0, help="Minimum account margin level percentage to allow trading")
    
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

    # --- Initialize MT5 and build configs ---
    log_queue = multiprocessing.Queue()
    stop_event = threading.Event()
    log_thread = threading.Thread(target=log_consumer, args=(log_queue, stop_event), daemon=True)
    log_thread.start()

    if not initialize_mt5(log_queue):
        print("Could not initialize MT5. Exiting.")
        stop_event.set()
        return

    configs = []
    for i, symbol_name in enumerate(args.symbol):
        if not mt5.symbol_select(symbol_name, True):
            print(f"WARNING: Failed to enable symbol {symbol_name}. Please enable it in Market Watch. Skipping.")
            continue
        time.sleep(0.1)

        pip_size = get_pip_size(symbol_name)
        if not pip_size:
            print(f"WARNING: Could not determine pip size for {symbol_name}. Skipping.")
            continue
        
        config = SymbolConfig(
            name=symbol_name,
            lot_size=args.lot_size[i],
            pip_threshold=args.pip_threshold[i],
            tp_usd=args.tp_usd[i],
            sl_usd=args.sl_usd[i],
            pip_move_threshold=args.pip_threshold[i] * pip_size,
            trailing_stop_pips=args.trailing_stop_pips[i],
            stealth_mode=args.stealth_mode,
            stealth_tp_pips=args.stealth_tp_pips[i]
        )
        configs.append(config)

    if not configs:
        print("ERROR: No valid symbol configurations provided. Exiting.")
        mt5.shutdown()
        stop_event.set()
        return

    run_bot(configs, log_queue, args.min_margin_level)

    mt5.shutdown()
    stop_event.set()
    log_thread.join(timeout=2)
    print("MetaTrader 5 connection closed.")

if __name__ == "__main__":
    main_cli()

