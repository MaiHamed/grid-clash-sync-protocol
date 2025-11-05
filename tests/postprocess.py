import os
import re
import pandas as pd

results_dir = "./results"
os.makedirs(results_dir, exist_ok=True)

summary = []

# Regex patterns for parsing
claim_pattern = re.compile(r"\[CLAIM\].*cell\s+\((\d+),\s*(\d+)\)")
snapshot_pattern = re.compile(r"\[SNAPSHOT\].*SnapshotID\s+(\d+)")

print("[INFO] Parsing result logs...")

for filename in os.listdir(results_dir):
    if filename.endswith(".log") or filename.endswith(".txt"):
        filepath = os.path.join(results_dir, filename)
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        claims = claim_pattern.findall(content)
        snapshots = snapshot_pattern.findall(content)

        summary.append({
            "file": filename,
            "total_claims": len(claims),
            "unique_cells": len(set(claims)),
            "snapshots_received": len(snapshots),
            "last_snapshot_id": snapshots[-1] if snapshots else None
        })

# Create DataFrame
df = pd.DataFrame(summary)
if df.empty:
    print("[WARN] No data extracted — check if log files exist in ./results/")
else:
    print(df)

# Save summary to CSV
summary_path = os.path.join(results_dir, "summary.csv")
df.to_csv(summary_path, index=False)
print(f"[INFO] Summary saved to {summary_path}")
