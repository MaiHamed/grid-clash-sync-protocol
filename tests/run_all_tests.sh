#!/bin/bash
# Automated test runner for Multiplayer_Network with reliability metrics

# -------------------- CONFIG --------------------
VETH0="veth0"
VETH1="veth1"
SERVER_IP="10.0.0.1"
CLIENT_IP="10.0.0.2"
SERVER_CMD="python3 ../server.py"
CLIENT_CMD="python3 ../client.py"
OUTDIR="./results"
RUN_TIME=30
NUM_CLIENTS=4
SCENARIOS=("baseline" "loss2" "loss5" "delay100")

# -------------------- SETUP VETH --------------------
sudo ip link add $VETH0 type veth peer name $VETH1 2>/dev/null || true
sudo ip addr add $SERVER_IP/24 dev $VETH0 2>/dev/null || true
sudo ip addr add $CLIENT_IP/24 dev $VETH1 2>/dev/null || true
sudo ip link set $VETH0 up
sudo ip link set $VETH1 up

mkdir -p "$OUTDIR"

# -------------------- FUNCTIONS --------------------
start_server() {
    echo "[INFO] Starting server..."
    IP=$SERVER_IP $SERVER_CMD > server.log 2>&1 &
    SERVER_PID=$!
    sleep 1
}

start_clients() {
    echo "[INFO] Launching $NUM_CLIENTS clients..."
    for i in $(seq 1 $NUM_CLIENTS); do
        IP=$CLIENT_IP $CLIENT_CMD > client_${i}.log 2>&1 &
    done
}

stop_all() {
    echo "[INFO] Stopping server and clients..."
    pkill -f server.py
    pkill -f client.py
}

apply_netem() {
    local scenario=$1
    echo "[INFO] Applying netem profile: $scenario"
    sudo tc qdisc del dev $VETH0 root 2>/dev/null || true
    case "$scenario" in
        baseline) ;;
        loss2) sudo tc qdisc add dev $VETH0 root netem loss 2% ;;
        loss5) sudo tc qdisc add dev $VETH0 root netem loss 5% ;;
        delay100) sudo tc qdisc add dev $VETH0 root netem delay 100ms ;;
    esac
}

capture_traffic() {
    local scenario=$1
    echo "[INFO] Capturing packets..."
    sudo tcpdump -i $VETH0 -w "$OUTDIR/${scenario}.pcap" udp port 5005 > /dev/null 2>&1 &
    TCPDUMP_PID=$!
}

summarize_logs() {
    local scenario=$1
    echo "====== Summary for $scenario ======"
    echo "Packets Sent: $(grep -h "\[SEND\]" "$OUTDIR/$scenario"/*.log | wc -l)"
    echo "ACKs Received: $(grep -h "\[ACK RECEIVED\]" "$OUTDIR/$scenario"/*.log | wc -l)"
    echo "Retransmits: $(grep -h "\[RETRANSMIT\]" "$OUTDIR/$scenario"/*.log | wc -l)"
    echo "Dropped: $(grep -h "\[DROPPED\]" "$OUTDIR/$scenario"/*.log | wc -l)"
    echo "==================================="
}

# -------------------- MAIN LOOP --------------------
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
    sudo tc qdisc del dev $VETH0 root 2>/dev/null || true

    echo "[INFO] Logs and PCAP saved for scenario: $scenario"
    mkdir -p "$OUTDIR/$scenario"
    mv ./*.log "$OUTDIR/$scenario"/

    # Summarize results automatically
    summarize_logs "$OUTDIR/$scenario"
done

echo "[DONE] All tests completed. Results stored in $OUTDIR/"
