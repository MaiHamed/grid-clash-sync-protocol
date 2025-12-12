import glob
import pandas as pd
import matplotlib.pyplot as plt
import os
import sys

def load_all(path_pattern):
    files = glob.glob(path_pattern)
    if not files:
        print("No CSV files found:", path_pattern)
        return None
    dfs = []
    for f in files:
        df = pd.read_csv(f)
        df['srcfile'] = os.path.basename(f)
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)

def main(results_dir):
    pattern = os.path.join(results_dir, "*.csv")
    all_df = load_all(pattern)
    if all_df is None:
        return

    # FIX 1: Parse time_ms to seconds correctly (divide by 1000.0, not 100.0)
    # Aligning start time to 0
    start_time = all_df['time_ms'].min()
    all_df['t_s'] = (all_df['time_ms'] - start_time) / 1000.0

    # Get list of clients for iterating
    clients = sorted(all_df['client_idx'].unique())

    # --- PLOT 1: Average RTT over Time (Separate lines per client) ---
    plt.figure(figsize=(10, 6))
    for c in clients:
        # Extract data for this client and sort by time
        client_data = all_df[all_df['client_idx'] == c].sort_values('t_s')
        plt.plot(client_data['t_s'], client_data['avg_rtt_ms'], label=f'Client {c}')
    
    plt.xlabel("Time (s)")
    plt.ylabel("Average RTT (ms)")
    plt.title("Average RTT over Time (Per Client)")
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "avg_rtt.png"))

    # --- PLOT 2: Snapshots received over time (Separate lines) ---
    plt.figure(figsize=(10, 6))
    for c in clients:
        client_data = all_df[all_df['client_idx'] == c].sort_values('t_s')
        plt.plot(client_data['t_s'], client_data['snapshots_received'], label=f'Client {c}')
        
    plt.xlabel("Time (s)")
    plt.ylabel("Snapshots Received (Cumulative)")
    plt.title("Snapshots Received over Time")
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "snapshots_over_time.png"))

    # --- PLOT 3: Retransmissions over time (Separate lines) ---
    plt.figure(figsize=(10, 6))
    for c in clients:
        client_data = all_df[all_df['client_idx'] == c].sort_values('t_s')
        plt.plot(client_data['t_s'], client_data['retransmissions'], label=f'Client {c}')

    plt.xlabel("Time (s)")
    plt.ylabel("Retransmissions (Cumulative)")
    plt.title("Retransmissions over Time")
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "retransmissions.png"))

    # --- SUMMARY CSV & BAR PLOTS ---
    summary = []
    for c in clients:
        sub = all_df[all_df['client_idx'] == c]
        summary.append({
            'client': c,
            'mean_rtt': sub['avg_rtt_ms'].mean(),
            'snapshots': sub['snapshots_received'].max(),
            'retrans': sub['retransmissions'].max()
        })
    s_df = pd.DataFrame(summary).sort_values('client')
    s_df.to_csv(os.path.join(results_dir, "summary_per_client.csv"), index=False)

    # Bar Plot: Mean RTT
    plt.figure()
    plt.bar(s_df['client'].astype(str), s_df['mean_rtt'], color='skyblue', edgecolor='black')
    plt.xlabel("Client")
    plt.ylabel("Mean RTT (ms)")
    plt.title("Mean RTT per Client")
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "mean_rtt_per_client.png"))

    # Bar Plot: Snapshots
    plt.figure()
    plt.bar(s_df['client'].astype(str), s_df['snapshots'], color='lightgreen', edgecolor='black')
    plt.xlabel("Client")
    plt.ylabel("Total Snapshots")
    plt.title("Total Snapshots Received per Client")
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "snapshots_per_client.png"))

    print(f"Plots and summary saved to: {results_dir}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 generate_plots.py <results_dir>")
        sys.exit(1)
    main(sys.argv[1])