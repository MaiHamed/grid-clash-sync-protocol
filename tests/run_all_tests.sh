#!/bin/bash
# Automated test runner for Multiplayer_Network
# ---------------------------------------------
IFACE="lo"                            # Change if not using loopback
SERVER_CMD="python3 ../server.py"
CLIENT_CMD="python3 ../client.py"
OUTDIR="./results"
RUN_TIME=30                           # seconds per test
NUM_CLIENTS=4                         # clients per test
SCENARIOS=("baseline" "loss2" "loss5" "delay100")

mkdir -p "$OUTDIR"

start_server() {
    echo "[INFO] Starting server..."
    $SERVER_CMD > server.log 2>&1 &
    SERVER_PID=$!
    sleep 1
}

start_clients() {
    echo "[INFO] Launching $NUM_CLIENTS clients..."
    for i in $(seq 1 $NUM_CLIENTS); do
        $CLIENT_CMD > client_${i}.log 2>&1 &
    done
}
stop_all() {
    echo "[INFO] Stopping server and clients..."
    # Forcefully terminate Python processes running server.py or client.py
    taskkill //F //IM python.exe //T >nul 2>&1 || true

}

apply_netem() {
    local scenario=$1
    echo "[INFO] Applying netem profile: $scenario"
    sudo tc qdisc del dev $IFACE root 2>/dev/null || true
    case "$scenario" in
        baseline) ;;
    esac
}

capture_traffic() {
    local scenario=$1
    echo "[INFO] Capturing packets..."
    sudo tcpdump -i $IFACE -w "$OUTDIR/${scenario}.pcap" udp port 5005 > /dev/null 2>&1 &
    TCPDUMP_PID=$!
}
for scenario in "${SCENARIOS[@]}"; do
    echo "======================================"
    echo " Running Scenario: $scenario"
    echo "======================================"

    apply_netem "$scenario"
    capture_traffic "$scenario"

    start_server
    start_clients

    echo "[INFO] Running for $RUN_TIME seconds..."
    sleep $RUN_TIME

    stop_all
    sudo kill $TCPDUMP_PID 2>/dev/null || true
    sudo tc qdisc del dev $IFACE root 2>/dev/null || true

    echo "[INFO] Logs and PCAP saved for scenario: $scenario"
    mkdir -p "$OUTDIR/$scenario"
    mv ./*.log "$OUTDIR/$scenario"/
done

echo "[DONE] All tests completed. Results stored in $OUTDIR/"
