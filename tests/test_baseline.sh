import subprocess
import time
import psutil
import os
import statistics

# Paths (adjust if needed)
SERVER_CMD = ["python3", "server.py"]
CLIENT_CMD = ["python3", "client.py"]
RESULTS_DIR = "./results"
os.makedirs(RESULTS_DIR, exist_ok=True)

def measure_cpu(pid, duration=5):
    """Measure average CPU usage of process PID over 'duration' seconds."""
    proc = psutil.Process(pid)
    samples = []
    for _ in range(duration * 2):  # sample every 0.5 sec
        samples.append(proc.cpu_percent(interval=0.5))
    return statistics.mean(samples)

def run_baseline_test():
    print("[TEST] Starting Baseline (no impairment) test scenario")

    # Start the server
    server = subprocess.Popen(SERVER_CMD, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(1)

    # Start the client
    client = subprocess.Popen(CLIENT_CMD, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    # Measure server CPU for a few seconds during active test
    cpu_usage = measure_cpu(server.pid, duration=10)

    # Wait for client to complete
    client.wait(timeout=40)
    client_output, _ = client.communicate()
    print("[INFO] Client finished execution")

    # Collect server output (stop server)
    server.terminate()
    try:
        server_output, _ = server.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
        server_output, _ = server.communicate()

    # Save logs
    with open(f"{RESULTS_DIR}/server_baseline.log", "w") as f:
        f.write(server_output or "")
    with open(f"{RESULTS_DIR}/client_baseline.log", "w") as f:
        f.write(client_output or "")

    # Parse latency lines from client logs
    latencies = []
    for line in client_output.splitlines():
        parts = line.strip().split()
        if len(parts) >= 5 and parts[0].isdigit():
            try:
                send_ts = float(parts[3])
                recv_ts = float(parts[4])
                latency = recv_ts - send_ts
                latencies.append(latency)
            except ValueError:
                continue

    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        print(f"[METRIC] Average Latency: {avg_latency:.2f} ms")
    else:
        avg_latency = float('inf')
        print("[WARN] No latency data found")

    print(f"[METRIC] Average Server CPU Usage: {cpu_usage:.2f}%")

    # Acceptance criteria
    criteria_met = (
        avg_latency <= 50 and
        cpu_usage < 60
    )

    if criteria_met:
        print("[PASS] ✅ Baseline test passed acceptance criteria.")
    else:
        print("[FAIL] ❌ Baseline test failed acceptance criteria.")
        print(f"Details: latency={avg_latency:.2f} ms, CPU={cpu_usage:.2f}%")

if __name__ == "__main__":
    run_baseline_test()
