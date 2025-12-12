#!/usr/bin/env bash
set -euo pipefail

#############################################
#  Multiplayer Game Automated Test Runner   #
#  Linux Version - Uses 'tc' for Impairment #
#############################################

### === CONFIGURATION === ###
SERVER_PORT=5005
SERVER_IP="127.0.0.1"
NUM_CLIENTS=${1:-4}       # Default to 4 clients if not provided
DURATION=${2:-30}         # Default to 30 seconds per test
CLAIMS_PER_SEC=20
OUTDIR_BASE="results"
IFACE="lo"                # Loopback interface (since we use 127.0.0.1)

### Directories ###
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

### Colors ###
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

#############################################
### Helper Functions
#############################################

# Safety Cleanup: Ensures we don't leave the network lagging if script crashes
cleanup() {
    echo -e "\n${YELLOW}[CLEANUP] Resetting network and killing processes...${NC}"
    # Stop Python processes
    pkill -f "server.py" || true
    pkill -f "test_client.py" || true
    
    # Reset Network (sudo required)
    if sudo tc qdisc show dev "$IFACE" | grep -q "netem"; then
        sudo tc qdisc del dev "$IFACE" root 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

start_server() {
    echo -e "${CYAN}[SERVER] Starting server...${NC}"
    mkdir -p "$OUTDIR"
    nohup python3 "$ROOT_DIR/server.py" --no-gui > "$OUTDIR/server.log" 2>&1 &
    SERVER_PID=$!
    sleep 1
    echo -e "${GREEN}[SERVER] Running with PID $SERVER_PID${NC}"
}

stop_server() {
    echo -e "${YELLOW}[SERVER] Stopping server...${NC}"
    if [ -n "${SERVER_PID-}" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}

start_clients() {
    local prefix="$1"
    echo -e "${CYAN}[CLIENTS] Launching $NUM_CLIENTS clients...${NC}"

    mkdir -p "$OUTDIR/$prefix"

    for i in $(seq 1 "$NUM_CLIENTS"); do
        nohup python3 "$SCRIPT_DIR/test_client.py" \
            --server-ip "$SERVER_IP" \
            --server-port "$SERVER_PORT" \
            --duration "$DURATION" \
            --send-rate "$CLAIMS_PER_SEC" \
            --client-idx "$i" \
            --out "$OUTDIR/$prefix" \
            > "$OUTDIR/${prefix}_client${i}.log" 2>&1 &
        sleep 0.05
    done
}

#############################################
### Test Scenario Runner
#############################################

scenario_runner() {
    SCENARIO_NAME="$1"
    NETEM_CMD="$2"

    OUTDIR="$ROOT_DIR/$OUTDIR_BASE/${SCENARIO_NAME}_$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$OUTDIR"

    echo -e "\n${CYAN}==========================================${NC}"
    echo -e "${CYAN}   Running Scenario: $SCENARIO_NAME${NC}"
    echo -e "${CYAN}==========================================${NC}"

    # 1. Clear any previous network rules first
    sudo tc qdisc del dev "$IFACE" root 2>/dev/null || true

    # 2. Apply Network Impairment (if any)
    if [ -n "$NETEM_CMD" ]; then
        echo -e "${RED}[NET] Applying: $NETEM_CMD on $IFACE${NC}"
        # We use 'add' because we cleared root above
        sudo tc qdisc add dev "$IFACE" root netem $NETEM_CMD
    else
        echo -e "${GREEN}[NET] No impairment (Baseline)${NC}"
    fi

    # 3. Run Test
    start_server
    start_clients "$SCENARIO_NAME"

    echo "[WAIT] Running for $DURATION seconds..."
    sleep "$DURATION"

    stop_server

    # 4. Reset Network Immediately after test
    if [ -n "$NETEM_CMD" ]; then
        echo "[NET] Resetting network rules..."
        sudo tc qdisc del dev "$IFACE" root 2>/dev/null || true
    fi

    # 5. Generate Plots (Optional - remove if not needed yet)
    if [ -f "$SCRIPT_DIR/generate_plots.py" ]; then
        echo "[PLOTS] Generating plots..."
        python3 "$SCRIPT_DIR/generate_plots.py" "$OUTDIR" || true
    fi

    echo -e "${GREEN}[DONE] Scenario '$SCENARIO_NAME' complete.${NC}"
}

#############################################
### Main Execution
#############################################

# Ensure script is run with permission to use sudo
if ! sudo -v; then
    echo -e "${RED}Error: This script requires sudo privileges to run 'tc' commands.${NC}"
    exit 1
fi

mkdir -p "$ROOT_DIR/$OUTDIR_BASE"

# Scenario 1: Baseline (No Lag)
scenario_runner "baseline" ""

# Scenario 2: 2% Packet Loss
scenario_runner "loss_2" "loss 2%"

# Scenario 3: 5% Packet Loss
scenario_runner "loss_5" "loss 5%"

# Scenario 4: High Latency (100ms ± 10ms jitter)
scenario_runner "delay_100ms" "delay 100ms 10ms distribution normal"

echo -e "\n${GREEN}[ALL TESTS COMPLETED] Results stored in $OUTDIR_BASE.${NC}\n"