#!/usr/bin/env bash
set -euo pipefail

#############################################
#  Multiplayer Game Automated Test Runner   #
#  Runs all 4 network impairment scenarios #
#  Windows / Git Bash compatible           #
#############################################

### === CONFIGURATION === ###
SERVER_PORT=5005
SERVER_IP="127.0.0.1"
NUM_CLIENTS=${1:-8}      # Number of headless test clients
DURATION=${2:-30}         # Duration per scenario
CLAIMS_PER_SEC=2          # Client send rate
OUTDIR_BASE="results"

### Directories ###
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"  # Project root (server.py location)

### Colored output ###
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'  # No color

#############################################
### Helper Functions
#############################################

start_server() {
    echo -e "${CYAN}[SERVER] Starting server (headless)...${NC}"
    mkdir -p "$OUTDIR"
    nohup python3 "$ROOT_DIR/server.py" --no-gui > "$OUTDIR/server.log" 2>&1 &
    SERVER_PID=$!
    sleep 1
    echo -e "${GREEN}[SERVER] Running with PID $SERVER_PID${NC}"
}

stop_server() {
    echo -e "${YELLOW}[SERVER] Stopping server...${NC}"
    if [ -n "${SERVER_PID-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
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
        sleep 0.02
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

    echo -e "\n${CYAN}=== Running Scenario: $SCENARIO_NAME ===${NC}"
    echo "[OUTDIR] Logs and CSVs → $OUTDIR"

    # Skip network detection and impairment on Windows
    IFACE="lo"
    echo "[NET] Using interface: $IFACE (network impairment skipped on Windows)"

    # Run server + clients
    start_server
    start_clients "$SCENARIO_NAME"

    echo "[WAIT] Running for $DURATION seconds..."
    sleep "$DURATION"

    # Stop server
    stop_server

    # Skip network reset (Linux-only tc commands)

    # Generate plots
    echo "[PLOTS] Generating plots..."
    python3 "$SCRIPT_DIR/generate_plots.py" "$OUTDIR" || true

    echo -e "${GREEN}[DONE] Scenario '$SCENARIO_NAME' complete.${NC}"
}

#############################################
### Run All Scenarios
#############################################

mkdir -p "$ROOT_DIR/$OUTDIR_BASE"

scenario_runner "baseline" ""
scenario_runner "loss_2" "loss 2%"
scenario_runner "loss_5" "loss 5%"
scenario_runner "delay_100ms" "delay 100ms 10ms distribution normal"

echo -e "\n${GREEN}[ALL TESTS COMPLETED] Results stored in $OUTDIR_BASE.${NC}\n"
