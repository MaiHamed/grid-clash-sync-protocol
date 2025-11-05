import pandas as pd
import os, sys, subprocess

def analyze_pcap(pcap_path):
    csv_path = pcap_path.replace(".pcap", ".csv")
    subprocess.run([
        "tshark", "-r", pcap_path, "-T", "fields",
        "-e", "frame.time_epoch", "-e", "udp.srcport", "-e", "udp.dstport",
        "-e", "ip.len", "-E", "header=y", "-E", "separator=,", "-E", "quote=d",
        "-E", "occurrence=f"
    ], stdout=open(csv_path, "w"))

    df = pd.read_csv(csv_path)
    df['frame.time_epoch'] = pd.to_numeric(df['frame.time_epoch'], errors='coerce')
    df = df.dropna(subset=['frame.time_epoch'])
    duration = df['frame.time_epoch'].max() - df['frame.time_epoch'].min()
    packet_rate = len(df) / duration if duration > 0 else 0
    avg_size = df['ip.len'].mean()
    return {"packets": len(df), "duration_s": duration, "rate_pps": packet_rate, "avg_size": avg_size}

if __name__ == "__main__":
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "./results"
    summary = []
    for scenario in os.listdir(results_dir):
        pcap = os.path.join(results_dir, scenario, f"{scenario}.pcap")
        if not os.path.exists(pcap): continue
        metrics = analyze_pcap(pcap)
        metrics["scenario"] = scenario
        summary.append(metrics)
    df = pd.DataFrame(summary)
    print(df)
    df.to_csv(os.path.join(results_dir, "summary.csv"), index=False)
