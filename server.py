import socket
import struct
import time
import select
import threading
from gui import GameGUI
from protocol import (
    create_ack_packet, create_header, pack_grid_snapshot, parse_header,
    MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP,
    MSG_TYPE_CLAIM_REQ, MSG_TYPE_LEAVE, MSG_TYPE_BOARD_SNAPSHOT,
    MSG_TYPE_ACK, MSG_TYPE_GAME_START, MSG_TYPE_GAME_OVER, HEADER_SIZE
)


def current_time_ms():
    return int(time.time() * 1000)


class GameServer:
    def __init__(self, ip="127.0.0.1", port=5005):
        self.ip = ip
        self.port = port

        # Sockets & networking
        self.server_socket = None

        # Players
        self.clients = {}  # player_id -> (addr, last_seen)
        self.waiting_room_players = {}  # player_id -> addr

        # Sequence & snapshots
        self.seq_num = 0  # global seq (used when needed)
        self.snapshot_id = 0  # incremental snapshot ID

        # Game state
        self.grid_state = [[0] * 20 for _ in range(20)]
        self.game_active = False
        self.min_players = 2
        self.running = False
        self.grid_changed = False

        # Statistics
        self.stats = {'sent': 0, 'received': 0, 'dropped': 0, 'client_count': 0}

        # For late joiners (snapshot history)
        self.recent_snapshots = []
        self.max_snapshot_history = 10

        # SR ARQ per client
        self.N = 6  # window size
        self.client_windows = {}  # player_id -> {seq_num: packet}
        self.client_timers = {}   # player_id -> {seq_num: timestamp}
        self.client_next_seq = {} # player_id -> next seq num to use
        self.RTO = 200  # retransmission timeout in ms

        # GUI
        self.gui = GameGUI(title="Grid Game Server")
        self._setup_gui_callbacks()
        # reflect initial stats in GUI
        try:
            self.gui.update_stats(self.stats)
            self.gui.update_player_info("Server", False)
            self.gui.update_players(self.clients)
        except Exception:
            # GUI may not implement some functions exactly; safe-guard
            pass

    # ==================== Server Start/Stop ====================
    def start(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Optionally increase buffer for safety
            try:
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            except Exception:
                pass
            self.server_socket.setblocking(0)
            self.server_socket.bind((self.ip, self.port))
            self.running = True

            # Start server loop thread
            threading.Thread(target=self._server_loop, daemon=True).start()

            print(f"[INFO] Server started at {self.ip}:{self.port}")
            self.gui.log_message(f"Server started on {self.ip}:{self.port}", "success")
            self.gui.update_player_info("Server", True)
            self.stats['client_count'] = len(self.clients) + len(self.waiting_room_players)
            self.gui.update_stats(self.stats)
            return True

        except Exception as e:
            self.gui.log_message(f"Server start error: {e}", "error")
            return False

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

        # Clear state
        self.clients.clear()
        self.waiting_room_players.clear()
        self.client_windows.clear()
        self.client_timers.clear()
        self.client_next_seq.clear()

        print("[INFO] Server stopped.")
        self.gui.log_message("Server stopped", "info")
        self.gui.update_player_info("Server", False)
        self.gui.update_players(self.clients)
        self.stats['client_count'] = 0
        self.gui.update_stats(self.stats)

    # ==================== SR ARQ Sender ====================
    def _sr_send(self, player_id, msg_type, payload=b''):
        """Send a packet with SR ARQ reliability per client.
        Stores the raw packet in that client's window indexed by seq_num.
        """
        # Make sure player exists either active or waiting
        if player_id not in self.clients and player_id not in self.waiting_room_players:
            print(f"[ERROR] Player {player_id} not found")
            return False

        # Initialize per-client structures if needed
        if player_id not in self.client_next_seq:
            self.client_next_seq[player_id] = 0
            self.client_windows[player_id] = {}
            self.client_timers[player_id] = {}

        next_seq = self.client_next_seq[player_id]
        window = self.client_windows[player_id]

        # Check window space
        if len(window) < self.N:
            # Build header. Some headers accept snapshot_id; include if snapshot payload.
            # We use create_header(msg_type, seq, payload_len, optional snapshot_id)
            if msg_type == MSG_TYPE_BOARD_SNAPSHOT:
                # If snapshot is being sent, the caller should prepend snapshot_id in payload
                # but we'll still pass snapshot_id into header if API supports it.
                header = create_header(msg_type, next_seq, len(payload), self.snapshot_id)
            else:
                header = create_header(msg_type, next_seq, len(payload))
            packet = header + payload

            # Get address
            if player_id in self.clients:
                addr = self.clients[player_id][0]
            else:
                addr = self.waiting_room_players[player_id]

            # Send
            try:
                self.server_socket.sendto(packet, addr)
                window[next_seq] = packet
                self.client_timers[player_id][next_seq] = current_time_ms()
                self.client_next_seq[player_id] += 1
                self.stats['sent'] += 1
                # update GUI stats
                self.gui.update_stats(self.stats)
                print(f"[SEND] to player {player_id} seq={next_seq}, type={msg_type}, window={list(window.keys())}")
                return True
            except Exception as e:
                self.stats['dropped'] += 1
                self.gui.update_stats(self.stats)
                print(f"[ERROR] sendto failed for player {player_id}: {e}")
                return False
        else:
            # Window full: drop or return False
            self.stats['dropped'] += 1
            self.gui.update_stats(self.stats)
            print(f"[DROPPED] to player {player_id}, window full")
            return False

    def _retransmit(self):
        """Check all client timers and retransmit if RTO exceeded."""
        now = current_time_ms()
        for pid in list(self.client_timers.keys()):
            timers = self.client_timers.get(pid, {})
            window = self.client_windows.get(pid, {})
            # Determine address
            if pid in self.clients:
                addr = self.clients[pid][0]
            elif pid in self.waiting_room_players:
                addr = self.waiting_room_players[pid]
            else:
                continue

            for seq, ts in list(timers.items()):
                if now - ts >= self.RTO:
                    # retransmit
                    try:
                        self.server_socket.sendto(window[seq], addr)
                        timers[seq] = now
                        self.stats['sent'] += 1
                        self.gui.update_stats(self.stats)
                        print(f"[RETRANSMIT] to player {pid} seq={seq}")
                    except Exception as e:
                        self.stats['dropped'] += 1
                        self.gui.update_stats(self.stats)
                        print(f"[ERROR] retransmit to player {pid} seq={seq} failed: {e}")

    # ==================== Server Loop ====================
    def _server_loop(self):
        """Main server loop: receive messages, send snapshots on grid change, retransmit as needed."""
        while self.running:
            try:
                ready, _, _ = select.select([self.server_socket], [], [], 0.01)
                if ready:
                    try:
                        data, addr = self.server_socket.recvfrom(4096)
                        if len(data) < HEADER_SIZE:
                            continue
                        self._handle_message(data, addr)
                    except BlockingIOError:
                        pass
                    except Exception as e:
                        print(f"[ERROR] recvfrom error: {e}")
                        self.gui.log_message(f"Receive error: {e}", "error")

                # EVENT-DRIVEN SNAPSHOT: send only when grid changed and we have active clients
                if self.grid_changed and self.clients:
                    self._send_snapshot()
                    self.grid_changed = False

                # Handle retransmissions
                self._retransmit()

                # small sleep to prevent busy loop
                time.sleep(0.001)

            except Exception as e:
                # keep running unless fatal
                print(f"[ERROR] in server loop: {e}")
                self.gui.log_message(f"Server loop error: {e}", "error")
                time.sleep(0.01)

    # ==================== Handle Messages ====================
    def _handle_message(self, data, addr):
        """Parse header and handle message types."""
        try:
            header = parse_header(data)
            msg_type = header.get("msg_type")
            seq = header.get("seq_num", 0)
            self.stats['received'] += 1
            self.gui.update_stats(self.stats)
            print(f"[RECEIVED] seq={seq}, type={msg_type}, from={addr}")

            # Send ACK for reliability (ack the received seq)
            try:
                ack_packet = create_ack_packet(ack_num=seq)
                # Use server_socket (fixed bug from earlier version)
                self.server_socket.sendto(ack_packet, addr)
                print(f"[SEND ACK] seq={seq}, to={addr}")
            except Exception as e:
                print(f"[ERROR] sending ACK to {addr}: {e}")

            if msg_type == MSG_TYPE_JOIN_REQ:
                # Assign unique player id (avoid both waiting and active)
                new_pid = 1
                while new_pid in self.waiting_room_players or new_pid in self.clients:
                    new_pid += 1
                self.waiting_room_players[new_pid] = addr
                # Update stats
                self.stats['client_count'] = len(self.waiting_room_players) + len(self.clients)
                self.gui.log_message(f"Player {new_pid} joined waiting room", "success")
                self.gui.update_players(self.waiting_room_players)
                self.gui.update_stats(self.stats)

                # Send join response via SR ARQ to that waiting client
                payload = struct.pack("!B", new_pid)
                self._sr_send(new_pid, MSG_TYPE_JOIN_RESP, payload)
                # increment global seq if you want to track outgoing frames globally
                self.seq_num += 1

                # Auto-start if enough players and game not active
                if len(self.waiting_room_players) >= self.min_players and not self.game_active:
                    self._start_game()

            elif msg_type == MSG_TYPE_CLAIM_REQ:
                # Determine player id by address lookup (search both active and waiting)
                player_id = self._addr_to_pid(addr)
                if player_id:
                    # Use HEADER_SIZE to locate payload as in your protocol
                    pay = data[HEADER_SIZE:HEADER_SIZE + 2] if len(data) >= HEADER_SIZE + 2 else b''
                    if len(pay) >= 2:
                        r, c = struct.unpack("!BB", pay[:2])
                        if 0 <= r < 20 and 0 <= c < 20:
                            # Update grid and mark changed
                            old_owner = self.grid_state[r][c]
                            if old_owner != player_id:
                                self.grid_state[r][c] = player_id
                                self.grid_changed = True
                                if old_owner == 0:
                                    self.gui.log_message(f"Player {player_id} claimed cell ({r},{c})", "info")
                                else:
                                    self.gui.log_message(f"Player {player_id} stole cell ({r},{c}) from Player {old_owner}", "warning")
                                # update GUI grid
                                self.gui.update_grid(self.grid_state)
                        else:
                            self.gui.log_message(f"Invalid coordinates ({r},{c}) from player {player_id}", "error")

                    # If player is active, update their last_seen timestamp
                    if player_id in self.clients:
                        self.clients[player_id] = (addr, time.time())

                else:
                    # Player unknown; maybe send a "join" suggestion or ignore
                    self.gui.log_message(f"Claim from unknown addr {addr}", "warning")

            elif msg_type == MSG_TYPE_LEAVE:
                # Remove the player (search both active and waiting)
                removed = []
                for pid, (client_addr, _) in list(self.clients.items()):
                    if client_addr == addr:
                        removed.append(pid)
                for pid, waiting_addr in list(self.waiting_room_players.items()):
                    if waiting_addr == addr:
                        removed.append(pid)
                for pid in removed:
                    self._remove_player(pid)
                    self.gui.log_message(f"Player {pid} left", "info")

                self.stats['client_count'] = len(self.clients) + len(self.waiting_room_players)
                self.gui.update_players(self.clients if self.clients else self.waiting_room_players)
                self.gui.update_stats(self.stats)

            elif msg_type == MSG_TYPE_ACK:
                # ACK for previously sent SR packet - find which player acked it and drop from window
                player_id = self._addr_to_pid(addr)
                if player_id:
                    window = self.client_windows.get(player_id, {})
                    timers = self.client_timers.get(player_id, {})
                    # seq here is ack number, remove if in window
                    if seq in window:
                        try:
                            del window[seq]
                        except KeyError:
                            pass
                        try:
                            del timers[seq]
                        except KeyError:
                            pass
                        print(f"[ACK RECEIVED] from player {player_id} seq={seq}")
                # no GUI update for ACK specifically

            # update stats GUI periodically
            self.gui.update_stats(self.stats)

        except Exception as e:
            print(f"[ERROR] in handle_message: {e}")
            self.gui.log_message(f"Message handling error: {e}", "error")

    # ==================== Helper ====================
    def _addr_to_pid(self, addr):
        """Return pid for an address (search active clients then waiting room)."""
        for pid, (client_addr, _) in self.clients.items():
            if client_addr == addr:
                return pid
        for pid, waiting_addr in self.waiting_room_players.items():
            if waiting_addr == addr:
                return pid
        return None

    def _remove_player(self, player_id):
        """Remove a player from all data structures."""
        self.clients.pop(player_id, None)
        self.client_windows.pop(player_id, None)
        self.client_timers.pop(player_id, None)
        self.client_next_seq.pop(player_id, None)
        self.waiting_room_players.pop(player_id, None)
        # Update GUI & stats
        self.stats['client_count'] = len(self.clients) + len(self.waiting_room_players)
        self.gui.update_players(self.clients if self.clients else self.waiting_room_players)
        self.gui.update_stats(self.stats)

    # ==================== Snapshot ====================
    def _send_snapshot(self):
        """Send snapshot to all active clients (SR ARQ)."""
        try:
            # Pack snapshot (grid -> bytes)
            snapshot_bytes = pack_grid_snapshot(self.grid_state)
            # Prepend snapshot id so clients can detect which snapshot this is
            payload = struct.pack("!I", self.snapshot_id) + snapshot_bytes

            # Store snapshot history for late-joiners
            self.recent_snapshots.append((self.snapshot_id, snapshot_bytes))
            if len(self.recent_snapshots) > self.max_snapshot_history:
                self.recent_snapshots.pop(0)

            sent_count = 0
            for pid in list(self.clients.keys()):
                sent = self._sr_send(pid, MSG_TYPE_BOARD_SNAPSHOT, payload)
                if sent:
                    sent_count += 1
                # update last seen even if send fails? keep last seen unchanged on error

            if sent_count > 0:
                # Only increment snapshot id after attempted send
                self.snapshot_id += 1
                self.seq_num += 1
                self.stats['sent'] += 0  # already counted per send inside _sr_send
                self.gui.update_snapshot(self.snapshot_id)
                self.gui.update_stats(self.stats)
                if self.snapshot_id % 10 == 0:
                    self.gui.log_message(f"Snapshot {self.snapshot_id} sent to {sent_count} client(s)", "info")

            print(f"[SNAPSHOT] id={self.snapshot_id} sent_count={sent_count}")

        except Exception as e:
            self.gui.log_message(f"Snapshot error: {e}", "error")
            print(f"[ERROR] snapshot: {e}")

    # ==================== Start / End Game ====================
    def _start_game(self):
        """Move waiting players into active clients and notify them."""
        self.game_active = True
        # Convert waiting_room_players (pid->addr) to clients structure (pid->(addr, last_seen))
        for pid, addr in self.waiting_room_players.items():
            self.clients[pid] = (addr, time.time())
        self.waiting_room_players.clear()

        # Update stats & GUI
        self.stats['client_count'] = len(self.clients)
        self.gui.log_message(f"Game started with {len(self.clients)} players!", "success")
        self.gui.log_message("Players: " + ", ".join([f"Player {pid}" for pid in self.clients.keys()]), "info")
        self.gui.update_players(self.clients)
        self.gui.update_stats(self.stats)

        # Send GAME_START to all active clients (use SR ARQ)
        for pid in list(self.clients.keys()):
            try:
                self._sr_send(pid, MSG_TYPE_GAME_START, b'')
            except Exception as e:
                self.gui.log_message(f"Failed to send start to player {pid}: {e}", "error")
        print("[GAME STARTED]")

    def end_game(self):
        """Notify all clients that the game is over."""
        self.game_active = False
        for pid in list(self.clients.keys()):
            try:
                self._sr_send(pid, MSG_TYPE_GAME_OVER, b'')
            except Exception as e:
                self.gui.log_message(f"Failed to send game over to player {pid}: {e}", "error")
        print("[GAME OVER]")
        self.gui.log_message("Game over", "info")

    # ==================== GUI Integration ====================
    def _setup_gui_callbacks(self):
        """Setup GUI button callbacks for server (Start/Stop)."""
        try:
            self.gui.connect_button.config(text="Start Server", command=self.start)
            self.gui.disconnect_button.config(text="Stop Server", command=self.stop)
        except Exception:
            # Some GUI implementations may not expose those buttons; safe-guard
            pass

        # Provide references back from GUI if GUI expects these callables
        self.gui.on_connect_click = self.start
        self.gui.on_disconnect_click = self.stop

    def start_gui(self):
        """Start GUI main loop (delegates to GameGUI)."""
        try:
            self.gui.run()
        except Exception as e:
            print(f"[ERROR] GUI run failed: {e}")
            # fallback: try to start server headless
            self.start()
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()


# Main execution
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--no-gui":
        server = GameServer()
        server.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.stop()
    else:
        server = GameServer()
        server.start_gui()
