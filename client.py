# client.py - Updated with SR ARQ and waiting room support
import socket
import struct
import time
import random
import threading
import tkinter as tk
from protocol import (
    create_header, parse_header,
    MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP,
    MSG_TYPE_CLAIM_REQ, MSG_TYPE_BOARD_SNAPSHOT, MSG_TYPE_LEAVE,
    MSG_TYPE_GAME_START, MSG_TYPE_GAME_OVER,
    unpack_grid_snapshot, MSG_TYPE_ACK
)

def current_time_ms():
    return int(time.time() * 1000)

class GameClient:
    def __init__(self, server_ip="127.0.0.1", server_port=5005):
        self.server_ip = server_ip
        self.server_port = server_port
        self.client_socket = None
        self.running = False

        # SR ARQ variables
        self.N = 6
        self.base = 0
        self.nextSeqNum = 0
        self.window = {}          # seq -> packet
        self.timers = {}          # seq -> timestamp
        self.send_timestamp = {}  # seq -> timestamp for RTO
        self.estimatedRTT = 100
        self.devRTT = 50
        self.alpha = 0.125
        self.beta = 0.25
        self.RTO = self.estimatedRTT + 4*self.devRTT

        # Game info
        self.seq_num = 0
        self.player_id = None
        self.game_active = False
        self.waiting_for_game = True
        self.game_start_time = None
        self.game_duration = 60
        self.claimed_cells = set()
        self.stats = {'sent':0,'received':0,'dropped':0,'latency_sum':0,'latency_count':0}
        self.active_players = set()
        self.last_log_time = 0
        self.game_timer_id = None

        from gui import GameGUI
        self.gui = GameGUI(title="Grid Game Client")
        self._setup_gui_callbacks()

    # ==================== GUI Callbacks ====================
    def _setup_gui_callbacks(self):
        self.gui.connect_button.config(command=self.connect)
        self.gui.disconnect_button.config(command=self.disconnect)
        self.gui.on_connect_click = self.connect
        self.gui.on_disconnect_click = self.disconnect
        self.gui.on_auto_claim_toggle = self._on_auto_claim_toggle
        self.setup_click_handler()
        self.gui.log_message("Waiting for game to start...", "info")
        self.gui.update_player_info("Waiting...", True)

    def setup_click_handler(self):
        self.gui.set_cell_click_handler(self.on_cell_click)

    def on_cell_click(self, row, col):
        if not self.player_id:
            self.gui.log_message("Not connected to server", "error")
            return
        if not self.game_active:
            self.gui.log_message("Game hasn't started yet", "warning")
            return
        self.gui.highlight_cell(row, col)
        self._send_claim_request(row, col)

    # ==================== SR ARQ ====================
    def _sr_send(self, msg_type, payload=b''):
        if self.nextSeqNum < self.base + self.N:
            seq = self.nextSeqNum
            packet = create_header(msg_type, seq, len(payload)) + payload
            self.window[seq] = packet
            self.timers[seq] = current_time_ms()
            self.send_timestamp[seq] = current_time_ms()
            self.client_socket.sendto(packet, (self.server_ip, self.server_port))
            self.stats['sent'] += 1
            self.nextSeqNum += 1
            return True
        else:
            self.stats['dropped'] += 1
            return False

    def _retransmit(self, seq):
        packet = self.window.get(seq)
        if packet:
            self.client_socket.sendto(packet, (self.server_ip, self.server_port))
            self.timers[seq] = current_time_ms()
            self.stats['sent'] += 1

    def _timer_loop(self):
        while self.running:
            now = current_time_ms()
            for seq in list(self.timers.keys()):
                if now - self.timers[seq] >= self.RTO:
                    self._retransmit(seq)
            time.sleep(0.01)

    def _update_rto(self, sampleRTT):
        self.estimatedRTT = (1-self.alpha)*self.estimatedRTT + self.alpha*sampleRTT
        self.devRTT = (1-self.beta)*self.devRTT + self.beta*abs(sampleRTT - self.estimatedRTT)
        self.RTO = self.estimatedRTT + 4*self.devRTT
        self.RTO = max(50, min(self.RTO, 2000))

    # ==================== Network ====================
    def connect(self):
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.client_socket.settimeout(1.0)
            self.running = True

            threading.Thread(target=self._timer_loop, daemon=True).start()
            threading.Thread(target=self._receive_loop, daemon=True).start()

            self._sr_send(MSG_TYPE_JOIN_REQ)
            self.gui.log_message(f"Connecting to {self.server_ip}:{self.server_port}...", "info")
            self.gui.update_player_info("Connecting...", True)
            return True
        except Exception as e:
            self.gui.log_message(f"Connection error: {e}", "error")
            return False

    def disconnect(self):
        self.running = False
        self.game_active = False
        if self.auto_claim_thread and self.auto_claim_thread.is_alive():
            self.auto_claim_thread.join(timeout=1)
        if self.game_timer_id:
            self.gui.root.after_cancel(self.game_timer_id)
        if self.client_socket:
            self._sr_send(MSG_TYPE_LEAVE)
            self.client_socket.close()
            self.client_socket = None
        self.player_id = None
        self.active_players.clear()
        self.gui.update_player_info(None, False)
        self.gui.update_players({})
        self.gui.log_message("Disconnected from server", "info")

    def _send_claim_request(self, row, col):
        if not self.client_socket or not self.player_id or not self.game_active:
            return False
        payload = struct.pack("!BB", row, col)
        if self._sr_send(MSG_TYPE_CLAIM_REQ, payload):
            self.claimed_cells.add((row, col))
        return True

    # ==================== Auto-Claim ====================
    def _start_auto_claim(self):
        def loop():
            while self.running and self.gui.auto_claim_var.get() and self.game_active:
                for _ in range(10):
                    r, c = random.randint(0,19), random.randint(0,19)
                    if (r,c) not in self.claimed_cells:
                        self._send_claim_request(r,c)
                        break
                time.sleep(random.uniform(0.1,0.5))
        self.auto_claim_thread = threading.Thread(target=loop, daemon=True)
        self.auto_claim_thread.start()

   # ==================== Receive Loop ====================
def _receive_loop(self):
    while self.running:
        try:
            data, addr = self.client_socket.recvfrom(2048)
            recv_ms = current_time_ms()
            header = parse_header(data)
            self.stats['received'] += 1

            seq = header["seq_num"]
            msg_type = header["msg_type"]

            # === Handle ACKs ===
            if msg_type == MSG_TYPE_ACK:
                if seq in self.window:
                    sampleRTT = recv_ms - self.send_timestamp.get(seq, recv_ms)
                    self._update_rto(sampleRTT)
                    del self.window[seq]
                    del self.timers[seq]
                    del self.send_timestamp[seq]
                    while self.base not in self.window and self.base < self.nextSeqNum:
                        self.base += 1
                continue

            # Send ACK for received packet
            ack_packet = create_header(MSG_TYPE_ACK, seq, 0)
            self.client_socket.sendto(ack_packet, addr)

            # === Original message handling ===
            if msg_type == MSG_TYPE_JOIN_RESP and self.player_id is None:
                if len(data) >= 23:
                    self.player_id = struct.unpack("!B", data[22:23])[0]
                    self.gui.update_player_info(f"Player {self.player_id} (Waiting)", True)
                    self.gui.log_message(f"Joined as Player {self.player_id}", "success")
                    self.active_players.add(self.player_id)
                    self.gui.update_players(self.active_players)

            elif msg_type == MSG_TYPE_GAME_START:
                self.game_active = True
                self.waiting_for_game = False
                self.game_start_time = time.time()
                self.gui.log_message("GAME STARTED! 🎮", "success")
                if self.gui.auto_claim_var.get():
                    self._start_auto_claim()
                self._start_game_timer()

            elif msg_type == MSG_TYPE_GAME_OVER:
                self.game_active = False
                self.gui.log_message("GAME OVER! 🏁", "info")
                self.gui.auto_claim_var.set(False)

            elif msg_type == MSG_TYPE_BOARD_SNAPSHOT and self.game_active:
                # Extract snapshot_id (first 4 bytes of payload)
                payload = data[22:]
                if len(payload) < 4:
                    continue
                snapshot_id = struct.unpack("!I", payload[:4])[0]

                # Ignore old snapshots
                if snapshot_id <= self.last_snapshot_id:
                    continue
                self.last_snapshot_id = snapshot_id

                # Process grid snapshot
                try:
                    grid_bytes = payload[4:]
                    grid = unpack_grid_snapshot(grid_bytes)
                    self.gui.update_grid(grid)
                    # Update active players
                    new_active = set()
                    for r in range(20):
                        for c in range(20):
                            pid = grid[r][c]
                            if 1 <= pid <= 4:
                                new_active.add(pid)
                    if new_active != self.active_players:
                        self.active_players = new_active
                        self.gui.update_players(self.active_players)
                except:
                    pass
                self.gui.update_stats(self.stats)

        except socket.timeout:
            continue
        except Exception as e:
            if self.running:
                self.gui.log_message(f"Receive error: {e}", "error")
                time.sleep(0.1)

    # ==================== Game Timer ====================
    def _start_game_timer(self):
        if not self.game_active or not self.game_start_time:
            return
        remaining = max(0, self.game_duration - (time.time() - self.game_start_time))
        mins, secs = int(remaining)//60, int(remaining)%60
        self.gui.root.title(f"Grid Game Client - Time: {mins:02d}:{secs:02d}")
        if remaining <= 0:
            self.game_active = False
            self.gui.log_message("Time's up! Game ended.", "info")
            self.gui.root.title("Grid Game Client - Game Over")
            return
        self.game_timer_id = self.gui.root.after(1000, self._start_game_timer)

    # ==================== Auto-claim toggle ====================
    def _on_auto_claim_toggle(self):
        if self.gui.auto_claim_var.get():
            if not self.game_active:
                self.gui.log_message("Game hasn't started yet", "warning")
                self.gui.auto_claim_var.set(False)
                return
            self.gui.log_message("Auto-claim enabled", "info")
            self._start_auto_claim()
        else:
            self.gui.log_message("Auto-claim disabled", "info")

    def start(self):
        self.gui.run()
