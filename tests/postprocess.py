#!/usr/bin/env python3
import os
import pandas as pd
import numpy as np
from pathlib import Path

# ==========================
# Utility Functions
# ==========================

def parse_log_line(line):
    """
    Parse a log line that may be in Python list format:
    [0, 0, 1, 0, ...] or space-separated numbers.
    Expects at least 8 numeric fields:
    client_id snapshot_id seq_num server_timestamp_ms recv_time_ms cpu_percent perceived_position_error bandwidth_per_client_kbps
    """
    line = line.strip()
    if not line or line.startswith("[SNAPSHOT]") or line.startswith("client_id"):
        return None

    # Remove brackets and split by comma or space
    line = line.replace('[', '').replace(']', '').replace(',', ' ')
    parts = line.split()
    if len(parts) < 8:
        print(f"[DEBUG] Skipping line (not enough fields): {line}")
        return None
    try:
        return {
            "client_id": int(parts[0]),
            "snapshot_id": int(parts[1]),
            "seq_num": int(parts[2]),
            "server_timestamp_ms": float(parts[3]),
            "recv_time_ms": float(parts[4]),
            "cpu_percent": float(parts[5]),
            "perceived_position_error": float(parts[6]),
            "bandwidth_per_client_kbps": float(parts[7])
        }
    except ValueError as e:
        print(f"[DEBUG] Skipping line (parse error): {line} -> {e}")
        return None


def load_log_file(file_path):
    rows = []
    try:
        with open(file_path, "r") as f:
            for line in f:
                if line.strip():
                    entry = parse_log_line(line)
                    if entry:
                        rows.append(entry)
    except Exception as e:
        print(f"[WARN] Could not read {file_path}: {e}")
    df = pd.DataFrame(rows)
    if not df.empty:
        df["latency_ms"] = df["recv_time_ms"] - df["server_timestamp_ms"]
        df["jitter_ms"] = df["latency_ms"].diff().abs().fillna(0)
    return df


def compute_statistics(df):
    """Compute mean, median, and 95th percentile for key metrics."""
    stats = {
        "mean_latency_ms": df["latency_ms"].mean(),
        "median_latency_ms": df["latency_ms"].median(),
        "p95_latency_ms": np.percentile(df["latency_ms"], 95),
        "mean_jitter_ms": df["jitter_ms"].mean(),
        "median_jitter_ms": df["jitter_ms"].median(),
        "p95_jitter_ms": np.percentile(df["jitter_ms"], 95),
        "mean_error": df["perceived_position_error"].mean(),
        "median_error": df["perceived_position_error"].median(),
        "p95_error": np.percentile(df["perceived_position_error"], 95),
        "mean_cpu_percent": df["cpu_percent"].mean(),
        "mean_bandwidth_kbps": df["bandwidth_per_client_kbps"].mean()
    }
    return stats


# ==========================
# Main Processing Logic
# ==========================

def main():
    results_dir = Path("./results")
    summary_csv = results_dir / "summary.csv"

    all_rows = []

    # Recursively find all .log files
    log_files = list(results_dir.rglob("*.log"))
    if not log_files:
        print(f"[ERROR] No log files found under {results_dir}")
        return

    for file_path in sorted(log_files):
        test_name = file_path.stem
        print(f"[INFO] Processing log file: {file_path}")

        df = load_log_file(file_path)
        if df.empty:
            print(f"[WARN] No valid rows in {file_path}, skipping.")
            continue

        # Save detailed metrics
        detailed_csv = results_dir / f"{test_name}_metrics.csv"
        df.to_csv(detailed_csv, index=False)
        print(f"[INFO] Saved detailed metrics to {detailed_csv}")

        # Compute stats for summary
        stats = compute_statistics(df)
        stats["file"] = test_name
        all_rows.append(stats)

    if not all_rows:
        print("[ERROR] No valid results found to generate summary!")
        return

    # Generate summary CSV
    summary_df = pd.DataFrame(all_rows)
    summary_df = summary_df[
        [
            "file",
            "mean_latency_ms", "median_latency_ms", "p95_latency_ms",
            "mean_jitter_ms", "median_jitter_ms", "p95_jitter_ms",
            "mean_error", "median_error", "p95_error",
            "mean_cpu_percent", "mean_bandwidth_kbps"
        ]
    ]
    summary_df.to_csv(summary_csv, index=False)
    print(f"\n Summary written to {summary_csv}")
    print(summary_df)


if __name__ == "__main__":
    main()
