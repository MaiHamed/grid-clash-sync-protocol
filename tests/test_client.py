# test_client.py
import os
import sys
import argparse
import socket
import struct
import time
import threading
import random
import csv

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
from protocol import (
    parse_packet, create_packet, create_ack_packet,
    MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP, MSG_TYPE_CLAIM_REQ,
    MSG_TYPE_BOARD_SNAPSHOT, MSG_TYPE_ACK, MSG_TYPE_GAME_START, MSG_TYPE_GAME_OVER,
    HEADER_SIZE
)

def current_time_ms():
    return int(time.time() * 1000)


class HeadlessClient:

    def __init__(self, server_ip, server_port, duration, send_rate, client_idx, out_prefix):
        self.server_ip = server_ip
        self.server_port = server_port
        self.duration = duration
        self.send_rate = send_rate
        self.client_idx = client_idx
        self.out_prefix = out_prefix

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(1.0)
        self.running = False

        # SR-ish tracking
        self.next_seq = 0
        self.window = {}
        self.send_timestamp = {}
        self.retransmissions = 0
        self.sent = 0
        self.received = 0
        self.dropped = 0

        # stats
        self.sample_rtts = []
        self.snapshots_received = 0

        self.player_id = None
        self.last_ack_received_from_server = 0

        self.start_time = time.time()
        # thread sync
        self.lock = threading.Lock()

    def start(self):
        self.running = True
        threading.Thread(target=self._receive_loop, daemon=True).start()

        # send join
        self._sr_send(MSG_TYPE_JOIN_REQ, b'')

        # start claim sender
        threading.Thread(target=self._claim_loop, daemon=True).start()

        # start retransmit timer thread
        threading.Thread(target=self._retransmit_loop, daemon=True).start()
        
        # log to CSV
        csv_path = f"{self.out_prefix}_client{self.client_idx}.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["time_ms","sent","received","retransmissions","avg_rtt_ms","snapshots_received","client_idx"])
            
            try:
                while time.time() - self.start_time < self.duration and self.running:
                    with self.lock:
                        avg_rtt = int(sum(self.sample_rtts)/len(self.sample_rtts)) if self.sample_rtts else 0
                        row = [current_time_ms(), self.sent, self.received, self.retransmissions, avg_rtt, self.snapshots_received, self.client_idx]
                    writer.writerow(row)
                    f.flush()
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            finally:
                self.running = False
                self.sock.close()

    def _sr_send(self, msg_type, payload=b''):
        seq = self.next_seq
        try:
            packet = create_packet(msg_type, seq, payload, ack_num=self.last_ack_received_from_server)
            self.sock.sendto(packet, (self.server_ip, self.server_port))
        except Exception as e:
            self.dropped += 1
            return False
           
        with self.lock:
            self.window[seq] = packet
            self.send_timestamp[seq] = current_time_ms()
            self.sent += 1
        self.next_seq += 1
        return seq

    def _retransmit_loop(self):
        RTO = 500  # ms
        while self.running and time.time() - self.start_time < self.duration:
            now = current_time_ms()
            to_retx = []
            with self.lock:
                for seq, ts in list(self.send_timestamp.items()):
                    if now - ts > RTO:
                        to_retx.append(seq)
            for seq in to_retx:
                pkt = None
                with self.lock:
                    pkt = self.window.get(seq)
                if pkt:
                    try:
                        self.sock.sendto(pkt, (self.server_ip, self.server_port))
                        self.retransmissions += 1
                        self.send_timestamp[seq] = current_time_ms()
                    except:
                        pass
            time.sleep(0.05)

    def _claim_loop(self):
        interval = 1.0 / max(1, self.send_rate)
        while self.running and time.time() - self.start_time < self.duration - 1:
            if self.player_id is not None:
                # random row/col
                r = random.randint(0, 19)
                c = random.randint(0, 19)
                # ack_num (optional) 0 for headless clients
                payload = struct.pack("!BBH", r, c, self.last_ack_received_from_server)
                self._sr_send(MSG_TYPE_CLAIM_REQ, payload)
            time.sleep(interval)

    def _receive_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except Exception:
                break

            # 1 Parse Packet
            header, payload, valid = parse_packet(data)
            if not valid or not header:
                continue

            msg_type = header['msg_type']
            seq = header['seq_num']
            ack_n = header.get('ack_num', 0)  # <--- DEFINE THIS EARLY

            # 2 Update Piggyback Tracker
            self.last_ack_received_from_server = seq

            # 3 Send Immediate ACK
            try:
                ack_packet = create_ack_packet(ack_num=seq)
                self.sock.sendto(ack_packet, addr)
            except:
                pass

            with self.lock:
                self.received += 1

            # 4 Process the ACK we received
            with self.lock:
                if ack_n in self.window:
                    ts = self.send_timestamp.pop(ack_n, None)
                    if ts:
                        rtt = current_time_ms() - ts
                        self.sample_rtts.append(rtt)
                    del self.window[ack_n]    

            # 5 Handle Game Logic (Join/Snapshot)
            if msg_type == MSG_TYPE_JOIN_RESP:
                if len(payload) >= 1:
                    pid = struct.unpack("!B", payload[:1])[0]
                    self.player_id = pid
           
            elif msg_type == MSG_TYPE_BOARD_SNAPSHOT:
                self.snapshots_received += 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--server-ip", default="127.0.0.1")
    p.add_argument("--server-port", type=int, default=5005)
    p.add_argument("--duration", type=int, default=30)
    p.add_argument("--send-rate", type=float, default=1.0, help="claims/sec")
    p.add_argument("--client-idx", type=int, default=1)
    p.add_argument("--out", default="results/test")
    args = p.parse_args()

    client = HeadlessClient(args.server_ip, args.server_port, args.duration, args.send_rate, args.client_idx, args.out)
    client.start()
