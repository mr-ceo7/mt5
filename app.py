from flask import Flask, render_template, request, redirect, url_for, jsonify
import multiprocessing
import time
import os
import json
from mt5linux import MetaTrader5

# Create the mt5linux proxy object
mt5 = MetaTrader5(host='127.0.0.1', port=18812)

# Import the refactored bot logic
from trading_bot import start_bot_process, SymbolConfig, get_pip_size

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_flask'

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

def initialize_mt5_connection():
    """Initializes connection to MT5 terminal using persisted credentials or falling back to environment/active terminal."""
    creds = load_credentials()
    if creds:
        login, password, server = creds
        return mt5.initialize(login=login, password=password, server=server)
        
    MT5_LOGIN = os.getenv('MT5_LOGIN')
    MT5_PASSWORD = os.getenv('MT5_PASSWORD')
    MT5_SERVER = os.getenv('MT5_SERVER')
    if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
        return mt5.initialize(login=int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER)
        
    return mt5.initialize()

# Global variables to hold the bot process, log queue, and shared session P&L
bot_process = None
log_queue = None
shared_pnl = multiprocessing.Value('d', 0.0)

@app.route('/')
def index():
    """Renders the main control panel UI."""
    global bot_process
    bot_running = bot_process.is_alive() if bot_process else False
    return render_template('index.html', bot_running=bot_running)

@app.route('/start', methods=['POST'])
def start_bot():
    """Parses the form, validates data, and starts the trading bot in a background process."""
    global bot_process, log_queue
    
    if bot_process and bot_process.is_alive():
        return redirect(url_for('index'))

    log_queue = multiprocessing.Queue()

    try:
        # --- Parse Form Data ---
        symbols = request.form.getlist('symbol')
        strategy_types = request.form.getlist('strategy_type')
        lot_sizes = [float(x) for x in request.form.getlist('lot_size')]
        pip_thresholds = [float(x) for x in request.form.getlist('pip_threshold')]
        tp_usds = [float(x) for x in request.form.getlist('tp_usd')]
        sl_usds = [float(x) for x in request.form.getlist('sl_usd')]
        trailing_stop_pips_list = [float(x) for x in request.form.getlist('trailing_stop_pips')]
        stealth_tp_pips_list = [float(x) for x in request.form.getlist('stealth_tp_pips')]
        risk_usds = [float(x) if x else 1.0 for x in request.form.getlist('risk_usd')]
        target_usds = [float(x) if x else 2.5 for x in request.form.getlist('target_usd')]
        
        stealth_mode = 'stealth_mode' in request.form
        min_margin_level = float(request.form.get('min_margin_level', 200.0))

        # --- Validate Parameter List Lengths ---
        param_lists = [
            lot_sizes, pip_thresholds, tp_usds, sl_usds, 
            trailing_stop_pips_list, stealth_tp_pips_list,
            strategy_types, risk_usds, target_usds
        ]
        if not all(len(p_list) == len(symbols) for p_list in param_lists):
            log_queue.put("ERROR: Mismatched number of parameters. Ensure every symbol row is fully filled out.")
            return redirect(url_for('index'))

        # --- Build Configs ---
        configs = []
        # Temporarily connect to MT5 to validate symbols and get pip sizes
        if not initialize_mt5_connection():
            log_queue.put("ERROR: Could not initialize MT5 to validate symbols.")
            return redirect(url_for('index'))

        for i, symbol_name in enumerate(symbols):
            if not symbol_name: continue # Skip empty symbol rows

            if not mt5.symbol_select(symbol_name, True):
                log_queue.put(f"WARNING: Failed to enable symbol {symbol_name}. Please enable it in Market Watch. Skipping.")
                continue
            time.sleep(0.1)

            pip_size = get_pip_size(symbol_name)
            if not pip_size:
                log_queue.put(f"WARNING: Could not determine pip size for {symbol_name}. Skipping.")
                continue
            
            config = SymbolConfig(
                name=symbol_name,
                lot_size=lot_sizes[i],
                pip_threshold=pip_thresholds[i],
                tp_usd=tp_usds[i],
                sl_usd=sl_usds[i],
                pip_move_threshold=pip_thresholds[i] * pip_size,
                trailing_stop_pips=trailing_stop_pips_list[i],
                stealth_mode=stealth_mode,
                stealth_tp_pips=stealth_tp_pips_list[i],
                strategy_type=strategy_types[i],
                risk_usd=risk_usds[i],
                target_usd=target_usds[i]
            )
            configs.append(config)
        
        mt5.shutdown() # Shutdown the temporary connection

        if not configs:
            log_queue.put("ERROR: No valid symbol configurations provided. Bot not started.")
            return redirect(url_for('index'))

        # --- Start Process ---
        log_queue.put("Configuration successful. Starting bot process...")
        shared_pnl.value = 0.0
        bot_process = multiprocessing.Process(target=start_bot_process, args=(configs, log_queue, min_margin_level, shared_pnl))
        bot_process.start()

    except Exception as e:
        log_queue.put(f"ERROR: Failed to start bot. {str(e)}")

    return redirect(url_for('index'))

@app.route('/stop', methods=['POST'])
def stop_bot():
    """Stops the running trading bot process."""
    global bot_process, log_queue
    if bot_process and bot_process.is_alive():
        log_queue.put("--- Stop command received. Terminating bot process... ---")
        bot_process.terminate()
        bot_process.join() # Wait for the process to terminate
        log_queue.put("--- Bot process terminated. ---")
    bot_process = None
    return redirect(url_for('index'))

@app.route('/logs')
def get_logs():
    """Fetches logs from the queue to display in the UI."""
    logs = []
    if log_queue:
        while not log_queue.empty():
            logs.append(log_queue.get_nowait())
    return jsonify(logs)

@app.route('/status')
def get_status():
    """Fetches the current status of the bot, session P&L, and logged-in account info."""
    global bot_process
    bot_running = bot_process.is_alive() if bot_process else False
    pnl = shared_pnl.value if bot_running else 0.0
    
    account_details = None
    try:
        if initialize_mt5_connection():
            acc_info = mt5.account_info()
            if acc_info is not None:
                account_details = {
                    "login": acc_info.login,
                    "name": acc_info.name,
                    "server": acc_info.server,
                    "balance": acc_info.balance,
                    "equity": acc_info.equity,
                    "margin_level": acc_info.margin_level,
                    "profit": acc_info.profit,
                    "currency": acc_info.currency
                }
            mt5.shutdown()
    except Exception:
        pass

    return jsonify({
        "bot_running": bot_running,
        "session_pnl": pnl,
        "account": account_details
    })

@app.route('/login', methods=['POST'])
def login_account():
    """Attempts to log in to MT5 with new credentials and saves them on success."""
    global bot_process
    if bot_process and bot_process.is_alive():
        return jsonify({"success": False, "error": "Cannot change account while the trading bot is running. Please stop the bot first."}), 400

    try:
        login = request.form.get('login')
        password = request.form.get('password')
        server = request.form.get('server')
        
        if not login or not password or not server:
            return jsonify({"success": False, "error": "All fields (Login, Password, Server) are required."}), 400
        
        login_val = int(login)
        
        # Test connection with these credentials
        if not mt5.initialize():
            return jsonify({"success": False, "error": "Could not initialize MT5 terminal connection."}), 500
        
        success = mt5.login(login_val, password=password, server=server)
        if success:
            # Save credentials to json file
            with open(CREDENTIALS_FILE, 'w') as f:
                json.dump({
                    "login": login_val,
                    "password": password,
                    "server": server
                }, f, indent=4)
            
            # Fetch account info to return
            acc_info = mt5.account_info()
            acc_name = acc_info.name if acc_info else "Unknown"
            balance = acc_info.balance if acc_info else 0.0
            currency = acc_info.currency if acc_info else "USD"
            
            mt5.shutdown()
            
            return jsonify({
                "success": True, 
                "message": f"Successfully logged into account {login_val} ({acc_name}). Balance: {balance} {currency}",
                "account": {
                    "login": login_val,
                    "name": acc_name,
                    "server": server,
                    "balance": balance,
                    "currency": currency
                }
            })
        else:
            err = mt5.last_error()
            mt5.shutdown()
            return jsonify({"success": False, "error": f"Login failed. Error details: {err}"}), 400
            
    except ValueError:
        return jsonify({"success": False, "error": "Login ID must be a numeric value."}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}), 500

@app.route('/clear_credentials', methods=['POST'])
def clear_credentials():
    """Deletes saved account credentials and falls back to default active account."""
    global bot_process
    if bot_process and bot_process.is_alive():
        return jsonify({"success": False, "error": "Cannot change account while the trading bot is running. Please stop the bot first."}), 400

    if os.path.exists(CREDENTIALS_FILE):
        try:
            os.remove(CREDENTIALS_FILE)
        except Exception as e:
            return jsonify({"success": False, "error": f"Failed to delete credentials file: {str(e)}"}), 500
    
    # Try initializing default
    if mt5.initialize():
        acc_info = mt5.account_info()
        acc_name = acc_info.name if acc_info else "Default Account"
        login_val = acc_info.login if acc_info else "Default"
        mt5.shutdown()
        return jsonify({
            "success": True,
            "message": f"Cleared saved credentials. Now using active terminal account: {login_val} ({acc_name})"
        })
    else:
        return jsonify({"success": False, "error": "Failed to initialize default MT5 connection."}), 500

if __name__ == '__main__':
    # Note: debug=True can cause issues with multiprocessing on some systems.
    # It's useful for development but should be False in a production-like environment.
    app.run(debug=False, host='0.0.0.0', port=5001)
