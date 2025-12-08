import socket
import struct
import time
import sys
import threading
from gui import GameGUI
from protocol import (
    create_ack_packet, create_header, parse_header, HEADER_SIZE,
    MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP,
    MSG_TYPE_CLAIM_REQ, MSG_TYPE_BOARD_SNAPSHOT, MSG_TYPE_LEAVE,
    MSG_TYPE_GAME_START, MSG_TYPE_GAME_OVER,
    unpack_grid_snapshot, MSG_TYPE_ACK
)

def current_time_ms():
    return int(time.time() * 1000)

class GameClient:
    def __init__(self, server_ip="127.0.0.1", server_port=5005, player_id=None):
        self.server_ip = server_ip
        self.server_port = server_port
        self.player_id = player_id
        self.client_socket = None
        self.running = False

        # SR ARQ - Sender side
        self.N = 6
        self.base = 0
        self.nextSeqNum = 0
        self.window = {}
        self.timers = {}
        self.send_timestamp = {}

        # SR ARQ - Receiver side
        self.receive_buffer = {}
        self.expected_seq = 0

        # RTT estimation
        self.estimatedRTT = 100
        self.devRTT = 50
        self.alpha = 0.125
        self.beta = 0.25
        self.RTO = self.estimatedRTT + 4*self.devRTT

        # Game state
        self.game_active = False
        self.waiting_for_game = True
        self.game_start_time = None
        self.game_duration = 60

        # Grid
        self.local_grid = [[0]*20 for _ in range(20)]
        self.claimed_cells = set()
        self.active_players = set()

        # Statistics
        self.stats = {'sent':0, 'received':0, 'dropped':0, 'retransmissions':0, 'latency_sum':0, 'latency_count':0}

        # GUI
        self.gui = GameGUI(title=f"Grid Game Client{' - Player '+str(self.player_id) if self.player_id else ''}")
        self._setup_gui_callbacks()
        self.game_timer_id = None

        # Automatically connect when GUI starts
        self.gui.root.after(500, self.connect)

    # ==================== GUI CALLBACKS ====================
    def _setup_gui_callbacks(self):
        self.gui.connect_button.config(command=self.connect)
        self.gui.disconnect_button.config(command=self.disconnect)
        self.gui.set_cell_click_handler(self.on_cell_click)
        self.gui.log_message("Waiting for game to start...", "info")
        self.gui.update_player_info("Waiting...", True)

    def on_cell_click(self, row, col):
        if not self.player_id:
            self.gui.log_message("Not connected to server", "error")
            return
        if not self.game_active:
            self.gui.log_message("Game hasn't started yet", "warning")
            return
        self.gui.highlight_cell(row, col)
        if self.send_claim(row, col):
            self.gui.log_message(f"Claimed cell ({row},{col})", "success")

    # ==================== SR ARQ SENDER ====================
    def _sr_send(self, msg_type, payload=b''):
        if self.nextSeqNum < self.base + self.N:
            seq = self.nextSeqNum
            packet = create_header(msg_type, seq, len(payload)) + payload
            self.client_socket.sendto(packet, (self.server_ip, self.server_port))
            self.window[seq] = packet
            self.timers[seq] = current_time_ms()
            self.send_timestamp[seq] = current_time_ms()
            self.nextSeqNum += 1
            self.stats['sent'] += 1
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
            self.stats['retransmissions'] += 1

    def _timer_loop(self):
        while self.running:
            now = current_time_ms()
            for seq in list(self.timers.keys()):
                if now - self.timers[seq] >= self.RTO:
                    self._retransmit(seq)
            time.sleep(0.01)

    # ==================== NETWORK ====================
    def connect(self):
        if self.client_socket:
            return
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.client_socket.settimeout(1.0)
            self.running = True

            threading.Thread(target=self._timer_loop, daemon=True).start()
            threading.Thread(target=self._receive_loop, daemon=True).start()

            self._sr_send(MSG_TYPE_JOIN_REQ, payload=b'')

            self.gui.log_message(f"Connecting to {self.server_ip}:{self.server_port}...", "info")
            self.gui.update_player_info("Connecting...", True)
            return True
        except Exception as e:
            self.gui.log_message(f"Connection error: {e}", "error")
            return False

    def disconnect(self):
        self.running = False
        self.game_active = False
        if self.game_timer_id:
            self.gui.root.after_cancel(self.game_timer_id)
        if self.client_socket:
            self._sr_send(MSG_TYPE_LEAVE)
            time.sleep(0.1)
            self.client_socket.close()
            self.client_socket = None
        self.player_id = None
        self.active_players.clear()
        self.gui.update_player_info(None, False)
        self.gui.update_players({})
        self.gui.log_message("Disconnected from server", "info")

    # ==================== RECEIVE LOOP ====================
    def _receive_loop(self):
        while self.running:
            try:
                data, addr = self.client_socket.recvfrom(2048)
                recv_ms = current_time_ms()
                if len(data) < HEADER_SIZE:
                    continue
                header = parse_header(data)
                seq = header["seq_num"]
                msg_type = header["msg_type"]
                payload = data[HEADER_SIZE:]

                if msg_type == MSG_TYPE_ACK:
                    self._handle_ack(seq, recv_ms)
                    continue

                ack_packet = create_ack_packet(seq)
                self.client_socket.sendto(ack_packet, addr)
                self._handle_data_packet(seq, msg_type, payload, header)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.gui.log_message(f"Receive error: {e}", "error")
                    time.sleep(0.1)

    # ==================== PACKET HANDLING ====================
    def _handle_ack(self, seq, recv_ms):
        if seq in self.window:
            sent_time = self.send_timestamp.get(seq, recv_ms)
            sampleRTT = recv_ms - sent_time
            self.estimatedRTT = (1 - self.alpha) * self.estimatedRTT + self.alpha * sampleRTT
            self.devRTT = (1 - self.beta) * self.devRTT + self.beta * abs(sampleRTT - self.estimatedRTT)
            self.RTO = self.estimatedRTT + 4*self.devRTT
            del self.window[seq]; del self.timers[seq]; del self.send_timestamp[seq]
            while self.base not in self.window and self.base < self.nextSeqNum:
                self.base += 1

    def _handle_data_packet(self, seq, msg_type, payload, header):
        if seq == self.expected_seq:
            self._process_packet(msg_type, payload, header)
            self.expected_seq += 1
            while self.expected_seq in self.receive_buffer:
                buffered = self.receive_buffer.pop(self.expected_seq)
                self._process_packet(*buffered)
                self.expected_seq += 1
        elif seq > self.expected_seq:
            self.receive_buffer[seq] = (msg_type, payload, header)

    def _process_packet(self, msg_type, payload, header):
        if msg_type == MSG_TYPE_JOIN_RESP:
            self.player_id = struct.unpack("!B", payload)[0]
            self.gui.update_player_info(f"Player {self.player_id} (Waiting)", True)
            self.gui.log_message(f"Joined as Player {self.player_id}", "success")
        elif msg_type == MSG_TYPE_GAME_START:
            self.game_active = True
            self.waiting_for_game = False
            self.game_start_time = time.time()
            self.gui.log_message("GAME STARTED! 🎮", "success")
            self.gui.update_player_info(f"Player {self.player_id} (Playing)", True)
            self._start_game_timer()
        elif msg_type == MSG_TYPE_GAME_OVER:
            self.game_active = False
            self.gui.log_message("GAME OVER! 🏁", "info")
        elif msg_type == MSG_TYPE_BOARD_SNAPSHOT:
            self.local_grid = unpack_grid_snapshot(payload)
            self.gui.update_grid(self.local_grid)

    # ==================== GAME ACTIONS ====================
    def send_claim(self, row, col):
        if not self.game_active or not self.player_id:
            return False
        if not (0 <= row < 20 and 0 <= col < 20):
            return False
        payload = struct.pack("!BB", row, col)
        return self._sr_send(MSG_TYPE_CLAIM_REQ, payload)

    def _start_game_timer(self):
        if not self.game_active or not self.game_start_time:
            return
        elapsed = time.time() - self.game_start_time
        remaining = max(0, self.game_duration - elapsed)
        minutes, seconds = divmod(int(remaining), 60)
        self.gui.root.title(f"Grid Game Client - Time: {minutes:02d}:{seconds:02d}")
        if remaining <= 0:
            self.game_active = False
            self.gui.log_message("Time's up! Game ended.", "info")
            self.gui.root.title("Grid Game Client - Game Over")
            return
        self.game_timer_id = self.gui.root.after(1000, self._start_game_timer)

    # ==================== START GUI ====================
    def start(self):
        self.gui.run()


if __name__ == "__main__":
    player_id = None
    if len(sys.argv) > 1:
        try:
            player_id = int(sys.argv[1])
        except:
            pass
    client = GameClient(player_id=player_id)
    client.start()
