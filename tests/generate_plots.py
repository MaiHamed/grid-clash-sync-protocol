# generate_plots.py
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
    # parse time_ms to seconds (relative)
    all_df['t_s'] = (all_df['time_ms'] - all_df['time_ms'].min())/1000.0

    # Plot average RTT per second (averaged across clients)
    df_rtt = all_df.groupby('t_s')['avg_rtt_ms'].mean().reset_index()
    plt.figure()
    plt.plot(df_rtt['t_s'], df_rtt['avg_rtt_ms'])
    plt.xlabel("Time (s)")
    plt.ylabel("Average RTT (ms)")
    plt.title("Average RTT over Time")
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "avg_rtt.png"))

    # Snapshots received per client over time (sum across clients)
    df_snap = all_df.groupby('t_s')['snapshots_received'].sum().reset_index()
    plt.figure()
    plt.plot(df_snap['t_s'], df_snap['snapshots_received'])
    plt.xlabel("Time (s)")
    plt.ylabel("Snapshots received (sum across clients)")
    plt.title("Snapshots received over time")
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "snapshots_over_time.png"))

    # Retransmissions (sum)
    df_retx = all_df.groupby('t_s')['retransmissions'].sum().reset_index()
    plt.figure()
    plt.plot(df_retx['t_s'], df_retx['retransmissions'])
    plt.xlabel("Time (s)")
    plt.ylabel("Retransmissions (sum)")
    plt.title("Retransmissions over time")
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "retransmissions.png"))

    # Per-client summary
    clients = all_df['client_idx'].unique()
    summary = []
    for c in clients:
        sub = all_df[all_df['client_idx']==c]
        summary.append({
            'client': c,
            'mean_rtt': sub['avg_rtt_ms'].mean(),
            'snapshots': sub['snapshots_received'].max(),
            'retrans': sub['retransmissions'].max()
        })
    s_df = pd.DataFrame(summary).sort_values('client')
    s_df.to_csv(os.path.join(results_dir, "summary_per_client.csv"), index=False)
    # bar plots
    plt.figure()
    plt.bar(s_df['client'].astype(str), s_df['mean_rtt'])
    plt.xlabel("Client")
    plt.ylabel("Mean RTT (ms)")
    plt.title("Mean RTT per Client")
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "mean_rtt_per_client.png"))

    plt.figure()
    plt.bar(s_df['client'].astype(str), s_df['snapshots'])
    plt.xlabel("Client")
    plt.ylabel("Snapshots received")
    plt.title("Snapshots received per Client")
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "snapshots_per_client.png"))

    print("Plots and summary saved to", results_dir)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 generate_plots.py <results_dir>")
        sys.exit(1)
    main(sys.argv[1])
