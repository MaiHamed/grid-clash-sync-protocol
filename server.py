# server.py - SR ARQ with snapshot_id for late-joining clients
import socket
import struct
import time
import select
import threading
from protocol import (
    create_header, pack_grid_snapshot, parse_header,
    MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP,
    MSG_TYPE_CLAIM_REQ, MSG_TYPE_LEAVE, MSG_TYPE_BOARD_SNAPSHOT,
    MSG_TYPE_ACK, MSG_TYPE_GAME_START, MSG_TYPE_GAME_OVER
)

def current_time_ms():
    return int(time.time() * 1000)

class GameServer:
    def __init__(self, ip="127.0.0.1", port=5005):
        self.ip = ip
        self.port = port
        self.server_socket = None
        self.clients = {}  # player_id -> (addr, last_seen)
        self.waiting_room_players = {}  # player_id -> addr
        self.seq_num = 0  # overall seq num
        self.snapshot_id = 0  # incremental snapshot ID
        self.grid_state = [[0]*20 for _ in range(20)]
        self.game_active = False
        self.min_players = 2
        self.running = False
        self.SNAPSHOT_INTERVAL = 0.033
        self.last_snapshot_time = time.time()
        self.stats = {'sent':0,'received':0,'dropped':0,'client_count':0}

        # SR ARQ per client
        self.N = 6
        self.client_windows = {}  # player_id -> {seq_num: packet}
        self.client_timers = {}   # player_id -> {seq_num: timestamp}
        self.client_next_seq = {} # player_id -> next seq num
        self.RTO = 200  # default RTO ms

    # ==================== Server Start/Stop ====================
    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_socket.setblocking(0)
        self.server_socket.bind((self.ip,self.port))
        self.running = True
        threading.Thread(target=self._server_loop, daemon=True).start()
        print(f"[INFO] Server started at {self.ip}:{self.port}")

    def stop(self):
        self.running = False
        if self.server_socket: self.server_socket.close()
        self.clients.clear()
        self.waiting_room_players.clear()
        print("[INFO] Server stopped.")

    # ==================== SR ARQ Sender ====================
    def _sr_send(self, player_id, msg_type, payload=b''):
        """Send a packet with SR ARQ reliability per client"""
        if player_id not in self.client_next_seq:
            self.client_next_seq[player_id] = 0
            self.client_windows[player_id] = {}
            self.client_timers[player_id] = {}

        next_seq = self.client_next_seq[player_id]
        window = self.client_windows[player_id]

        if len(window) < self.N:
            packet = create_header(msg_type, next_seq, len(payload)) + payload
            addr = self.clients[player_id][0]
            self.server_socket.sendto(packet, addr)
            window[next_seq] = packet
            self.client_timers[player_id][next_seq] = current_time_ms()
            self.client_next_seq[player_id] += 1
            self.stats['sent'] += 1
            print(f"[SEND] to player {player_id} seq={next_seq}, type={msg_type}, window={list(window.keys())}")
        else:
            self.stats['dropped'] += 1
            print(f"[DROPPED] to player {player_id}, window full")

    def _retransmit(self):
        """Check all client timers and retransmit if RTO exceeded"""
        now = current_time_ms()
        for pid in list(self.client_timers.keys()):
            timers = self.client_timers[pid]
            window = self.client_windows[pid]
            addr = self.clients.get(pid, (None,))[0]
            if not addr: continue
            for seq, ts in list(timers.items()):
                if now - ts >= self.RTO:
                    self.server_socket.sendto(window[seq], addr)
                    timers[seq] = now
                    self.stats['sent'] += 1
                    print(f"[RETRANSMIT] to player {pid} seq={seq}")

    # ==================== Server Loop ====================
    def _server_loop(self):
        while self.running:
            try:
                ready, _, _ = select.select([self.server_socket], [], [], 0.01)
                if ready:
                    data, addr = self.server_socket.recvfrom(2048)
                    if len(data) < 22: continue
                    self._handle_message(data, addr)

                # periodic snapshot
                if self.clients and time.time() - self.last_snapshot_time >= self.SNAPSHOT_INTERVAL:
                    self._send_snapshot()
                    self.last_snapshot_time = time.time()

                # handle retransmissions
                self._retransmit()
            except:
                time.sleep(0.01)

    # ==================== Handle Messages ====================
    def _handle_message(self, data, addr):
        header = parse_header(data)
        msg_type = header["msg_type"]
        seq = header["seq_num"]
        self.stats['received'] += 1
        print(f"[RECEIVED] seq={seq}, type={msg_type}, from={addr}")

        # Send ACK for reliability
        ack_packet = create_header(MSG_TYPE_ACK, seq, 0)
        self.server_socket.sendto(ack_packet, addr)
        print(f"[SEND ACK] seq={seq}, to={addr}")

        if msg_type == MSG_TYPE_JOIN_REQ:
            # Assign new player_id
            new_pid = 1
            while new_pid in self.waiting_room_players: new_pid += 1
            self.waiting_room_players[new_pid] = addr
            self.stats['client_count'] = len(self.waiting_room_players)
            payload = struct.pack("!B", new_pid)
            self._sr_send(new_pid, MSG_TYPE_JOIN_RESP, payload)
            self.seq_num += 1

            if len(self.waiting_room_players) >= self.min_players and not self.game_active:
                self._start_game()

        elif msg_type == MSG_TYPE_CLAIM_REQ:
            player_id = self._addr_to_pid(addr)
            if player_id:
                r, c = struct.unpack("!BB", data[22:24])
                self.grid_state[r][c] = player_id
                print(f"[CLAIM] player {player_id} -> cell ({r},{c})")

        elif msg_type == MSG_TYPE_LEAVE:
            player_id = self._addr_to_pid(addr)
            if player_id:
                self._remove_player(player_id)
                print(f"[LEAVE] player {player_id}")

        elif msg_type == MSG_TYPE_ACK:
            player_id = self._addr_to_pid(addr)
            if player_id:
                window = self.client_windows.get(player_id, {})
                timers = self.client_timers.get(player_id, {})
                if seq in window:
                    del window[seq]
                    del timers[seq]
                    print(f"[ACK RECEIVED] from player {player_id} seq={seq}")

    # ==================== Helper ====================
    def _addr_to_pid(self, addr):
        for pid, a in self.clients.items():
            if a[0] == addr:
                return pid
        for pid, a in self.waiting_room_players.items():
            if a == addr:
                return pid
        return None

    def _remove_player(self, player_id):
        self.clients.pop(player_id, None)
        self.client_windows.pop(player_id, None)
        self.client_timers.pop(player_id, None)
        self.client_next_seq.pop(player_id, None)

    # ==================== Snapshot ====================
    def _send_snapshot(self):
        snapshot_bytes = pack_grid_snapshot(self.grid_state)
        payload = struct.pack("!I", self.snapshot_id) + snapshot_bytes
        for pid in self.clients.keys():
            self._sr_send(pid, MSG_TYPE_BOARD_SNAPSHOT, payload)
        self.snapshot_id += 1
        print(f"[SNAPSHOT] id={self.snapshot_id}")

    # ==================== Start Game ====================
    def _start_game(self):
        self.game_active = True
        self.clients.update(self.waiting_room_players)
        self.waiting_room_players.clear()
        for pid in self.clients.keys():
            self._sr_send(pid, MSG_TYPE_GAME_START)
        print("[GAME STARTED]")

    # ==================== End Game ====================
    def end_game(self):
        self.game_active = False
        for pid in self.clients.keys():
            self._sr_send(pid, MSG_TYPE_GAME_OVER)
        print("[GAME OVER]")
