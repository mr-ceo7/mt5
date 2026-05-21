#!/bin/bash
# ============================================
#  MT5 Hedging Bot — Startup Script
#  Checks all dependencies, offers to install
#  missing ones, then launches everything.
#
#  Usage:  ./start_bot.sh
# ============================================

set -e

# --- Configuration ---
WINEPREFIX="/home/qassim/.gemini2_home/.mt5"
MT5_EXE="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe"
WINE_PYTHON="$WINEPREFIX/drive_c/Python311/python.exe"
BOT_DIR="/home/qassim/mt5"
FLASK_PORT=5001
RPYC_PORT=18812

export WINEPREFIX

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}  MT5 Hedging Bot — Startup${NC}"
echo -e "${CYAN}==========================================${NC}"

# =============================================
#  PHASE 1: Dependency Checks
# =============================================
echo ""
echo -e "${CYAN}[Phase 1] Checking dependencies...${NC}"

MISSING_APT=()
MISSING_PIP=()
ERRORS=()

# --- Check: Wine ---
echo -n "  Wine .................. "
if command -v wine >/dev/null 2>&1; then
    echo -e "${GREEN}OK${NC} ($(wine --version 2>/dev/null || echo 'unknown version'))"
else
    echo -e "${RED}MISSING${NC}"
    MISSING_APT+=("wine")
fi

# --- Check: Xvfb (only required if headless) ---
echo -n "  Xvfb ................. "
if command -v Xvfb >/dev/null 2>&1; then
    echo -e "${GREEN}OK${NC}"
else
    if [ -z "$DISPLAY" ] || ! xdpyinfo >/dev/null 2>&1; then
        echo -e "${RED}MISSING${NC} (required — no display detected)"
        MISSING_APT+=("xvfb")
    else
        echo -e "${YELLOW}NOT INSTALLED${NC} (not needed — display detected)"
    fi
fi

# --- Check: Python 3 ---
echo -n "  Python 3 ............. "
if command -v python3 >/dev/null 2>&1; then
    echo -e "${GREEN}OK${NC} ($(python3 --version 2>&1))"
else
    echo -e "${RED}MISSING${NC}"
    MISSING_APT+=("python3")
fi

# --- Check: pip ---
echo -n "  pip .................. "
if python3 -m pip --version >/dev/null 2>&1; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}MISSING${NC}"
    MISSING_APT+=("python3-pip")
fi

# --- Check: ss (iproute2) ---
echo -n "  ss (iproute2) ........ "
if command -v ss >/dev/null 2>&1; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}MISSING${NC}"
    MISSING_APT+=("iproute2")
fi

# --- Check: Flask (Python package) ---
echo -n "  Flask ................ "
if python3 -c "import flask" 2>/dev/null; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}MISSING${NC}"
    MISSING_PIP+=("flask")
fi

# --- Check: mt5linux (Python package) ---
echo -n "  mt5linux ............. "
if python3 -c "import mt5linux" 2>/dev/null; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}MISSING${NC}"
    MISSING_PIP+=("mt5linux")
fi

# --- Check: MetaTrader 5 installation ---
echo -n "  MetaTrader 5 ......... "
if [ -f "$MT5_EXE" ]; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}NOT FOUND${NC}"
    ERRORS+=("MetaTrader 5 not found at: $MT5_EXE")
fi

# --- Check: Wine Python installation ---
echo -n "  Wine Python 3.11 ..... "
if [ -f "$WINE_PYTHON" ]; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}NOT FOUND${NC}"
    ERRORS+=("Wine Python not found at: $WINE_PYTHON")
fi

# --- Check: Bot files ---
echo -n "  trading_bot.py ....... "
if [ -f "$BOT_DIR/trading_bot.py" ]; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}NOT FOUND${NC}"
    ERRORS+=("trading_bot.py not found at: $BOT_DIR/trading_bot.py")
fi

echo -n "  app.py ............... "
if [ -f "$BOT_DIR/app.py" ]; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}NOT FOUND${NC}"
    ERRORS+=("app.py not found at: $BOT_DIR/app.py")
fi

# --- Check: Port conflicts ---
echo -n "  Port $RPYC_PORT (RPyC) .... "
if ss -tlnp 2>/dev/null | grep -q ":$RPYC_PORT"; then
    echo -e "${YELLOW}IN USE${NC} (RPyC may already be running)"
else
    echo -e "${GREEN}FREE${NC}"
fi

echo -n "  Port $FLASK_PORT (Flask) .... "
if ss -tlnp 2>/dev/null | grep -q ":$FLASK_PORT"; then
    echo -e "${YELLOW}IN USE${NC} (Flask may already be running)"
else
    echo -e "${GREEN}FREE${NC}"
fi

# =============================================
#  PHASE 2: Install Missing Dependencies
# =============================================

# Handle fatal errors first (things we can't auto-install)
if [ ${#ERRORS[@]} -gt 0 ]; then
    echo ""
    echo -e "${RED}[ERROR] The following issues cannot be auto-fixed:${NC}"
    for err in "${ERRORS[@]}"; do
        echo -e "  ${RED}•${NC} $err"
    done
    echo ""
    echo "Please resolve these manually before running this script again."
    exit 1
fi

# Handle apt packages
if [ ${#MISSING_APT[@]} -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}[Phase 2] Missing system packages: ${MISSING_APT[*]}${NC}"
    read -rp "  Install them now? (y/n): " REPLY
    if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        echo "  Running: sudo apt update && sudo apt install -y ${MISSING_APT[*]}"
        sudo apt update -qq
        sudo apt install -y "${MISSING_APT[@]}"
        echo -e "  ${GREEN}System packages installed.${NC}"
    else
        echo -e "  ${RED}Skipped. Cannot continue without required packages.${NC}"
        exit 1
    fi
fi

# Handle pip packages
if [ ${#MISSING_PIP[@]} -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}[Phase 2] Missing Python packages: ${MISSING_PIP[*]}${NC}"
    read -rp "  Install them now? (y/n): " REPLY
    if [[ "$REPLY" =~ ^[Yy]$ ]]; then
        echo "  Running: pip install ${MISSING_PIP[*]}"
        python3 -m pip install "${MISSING_PIP[@]}"
        echo -e "  ${GREEN}Python packages installed.${NC}"
    else
        echo -e "  ${RED}Skipped. Cannot continue without required packages.${NC}"
        exit 1
    fi
fi

# =============================================
#  PHASE 3: Display Setup
# =============================================
echo ""
echo -e "${CYAN}[Phase 3] Setting up display...${NC}"

USING_XVFB=false

if [ -z "$DISPLAY" ] || ! xdpyinfo >/dev/null 2>&1; then
    echo "  No display detected — starting virtual framebuffer."

    # Find a free display number
    XVFB_DISPLAY=":99"
    for i in 99 100 101 102; do
        if [ ! -e "/tmp/.X${i}-lock" ]; then
            XVFB_DISPLAY=":${i}"
            break
        fi
    done

    Xvfb "$XVFB_DISPLAY" -screen 0 1024x768x24 >/dev/null 2>&1 &
    XVFB_PID=$!
    export DISPLAY="$XVFB_DISPLAY"
    USING_XVFB=true
    sleep 1

    if kill -0 "$XVFB_PID" 2>/dev/null; then
        echo -e "  ${GREEN}Xvfb running (PID: $XVFB_PID, DISPLAY=$DISPLAY)${NC}"
    else
        echo -e "  ${RED}ERROR: Xvfb failed to start.${NC}"
        exit 1
    fi
else
    echo -e "  Display detected (${GREEN}$DISPLAY${NC}) — using desktop mode."
fi

# =============================================
#  PHASE 4: Launch Services
# =============================================
echo ""
echo -e "${CYAN}[Phase 4] Launching services...${NC}"

# --- Step 1: Start MetaTrader 5 ---
echo ""
echo "  [1/3] Starting MetaTrader 5..."
wine "$MT5_EXE" >/dev/null 2>&1 &
MT5_PID=$!
echo "         PID: $MT5_PID"
echo "         Waiting 15 seconds for broker connection..."
sleep 15

# --- Step 2: Start RPyC Bridge Server ---
echo ""
echo "  [2/3] Starting RPyC bridge server on port $RPYC_PORT..."
wine "$WINE_PYTHON" -m mt5linux >/dev/null 2>&1 &
RPYC_PID=$!
echo "         PID: $RPYC_PID"
echo "         Waiting 5 seconds for initialization..."
sleep 5

if ss -tlnp 2>/dev/null | grep -q ":$RPYC_PORT"; then
    echo -e "         ${GREEN}RPyC server is listening on port $RPYC_PORT.${NC}"
else
    echo -e "         ${YELLOW}WARNING: Could not confirm RPyC on port $RPYC_PORT.${NC}"
fi

# --- Step 3: Start Flask Web App ---
echo ""
echo "  [3/3] Starting Flask web app on port $FLASK_PORT..."
cd "$BOT_DIR"
python3 app.py >/dev/null 2>&1 &
FLASK_PID=$!
sleep 2

if ss -tlnp 2>/dev/null | grep -q ":$FLASK_PORT"; then
    echo -e "         ${GREEN}Flask app is running on port $FLASK_PORT.${NC}"
else
    echo -e "         ${YELLOW}WARNING: Could not confirm Flask on port $FLASK_PORT.${NC}"
fi

# =============================================
#  PHASE 5: Summary
# =============================================
echo ""
echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}  All services started successfully.${NC}"
echo -e "${GREEN}==========================================${NC}"
echo ""
if [ "$USING_XVFB" = true ]; then
    echo -e "  Mode:           ${CYAN}HEADLESS${NC} (Xvfb on $DISPLAY)"
else
    echo -e "  Mode:           ${CYAN}DESKTOP${NC}"
fi
echo -e "  Control Panel:  ${CYAN}http://127.0.0.1:$FLASK_PORT${NC}"
echo ""
echo "  PIDs:"
if [ "$USING_XVFB" = true ]; then
    echo "    Xvfb:   $XVFB_PID"
fi
echo "    MT5:    $MT5_PID"
echo "    RPyC:   $RPYC_PID"
echo "    Flask:  $FLASK_PID"
echo ""

# Build the kill command
ALL_PIDS="$MT5_PID $RPYC_PID $FLASK_PID"
if [ "$USING_XVFB" = true ]; then
    ALL_PIDS="$XVFB_PID $ALL_PIDS"
fi
echo "  To stop everything:"
echo "    kill $ALL_PIDS"
echo -e "${GREEN}==========================================${NC}"

# Keep the script alive so background processes stay running
wait
