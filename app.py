from flask import Flask, render_template, request, redirect, url_for, jsonify
import multiprocessing
import time
from mt5linux import MetaTrader5

# Create the mt5linux proxy object
mt5 = MetaTrader5(host='127.0.0.1', port=18812)

# Import the refactored bot logic
from trading_bot import start_bot_process, SymbolConfig, get_pip_size

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_flask'

# Global variables to hold the bot process and the log queue
bot_process = None
log_queue = None

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
        lot_sizes = [float(x) for x in request.form.getlist('lot_size')]
        pip_thresholds = [float(x) for x in request.form.getlist('pip_threshold')]
        tp_usds = [float(x) for x in request.form.getlist('tp_usd')]
        sl_usds = [float(x) for x in request.form.getlist('sl_usd')]
        trailing_stop_pips_list = [float(x) for x in request.form.getlist('trailing_stop_pips')]
        stealth_tp_pips_list = [float(x) for x in request.form.getlist('stealth_tp_pips')]
        stealth_mode = 'stealth_mode' in request.form
        min_margin_level = float(request.form.get('min_margin_level', 200.0))

        # --- Validate Parameter List Lengths ---
        param_lists = [
            lot_sizes, pip_thresholds, tp_usds, sl_usds, 
            trailing_stop_pips_list, stealth_tp_pips_list
        ]
        if not all(len(p_list) == len(symbols) for p_list in param_lists):
            log_queue.put("ERROR: Mismatched number of parameters. Ensure every symbol row is fully filled out.")
            return redirect(url_for('index'))

        # --- Build Configs ---
        configs = []
        # Temporarily connect to MT5 to validate symbols and get pip sizes
        if not mt5.initialize():
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
                stealth_tp_pips=stealth_tp_pips_list[i]
            )
            configs.append(config)
        
        mt5.shutdown() # Shutdown the temporary connection

        if not configs:
            log_queue.put("ERROR: No valid symbol configurations provided. Bot not started.")
            return redirect(url_for('index'))

        # --- Start Process ---
        log_queue.put("Configuration successful. Starting bot process...")
        bot_process = multiprocessing.Process(target=start_bot_process, args=(configs, log_queue, min_margin_level))
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

if __name__ == '__main__':
    # Note: debug=True can cause issues with multiprocessing on some systems.
    # It's useful for development but should be False in a production-like environment.
    app.run(debug=False, host='0.0.0.0', port=5001)
