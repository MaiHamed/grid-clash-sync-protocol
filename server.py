import socket
import struct
import time
import select
import threading
from gui import GameGUI
from protocol import (
    MSG_TYPE_LEADERBOARD, create_ack_packet, create_packet, pack_grid_snapshot, pack_leaderboard_data, parse_packet,
    MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP,
    MSG_TYPE_CLAIM_REQ, MSG_TYPE_LEAVE, MSG_TYPE_BOARD_SNAPSHOT,
    MSG_TYPE_ACK, MSG_TYPE_GAME_START, MSG_TYPE_GAME_OVER, HEADER_SIZE
)


def current_time_ms():
    return int(time.time() * 1000)

def calculate_scores_from_grid(grid):
    scores = {}
    for row in grid:
        for cell in row:
            if cell != 0:  # 0 means unclaimed
                scores[cell] = scores.get(cell, 0) + 1
    # Convert to list of tuples and sort by score (highest first)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


class GameServer:
    def __init__(self, ip="127.0.0.1", port=5005):
        self.ip = ip
        self.port = port

        # Sockets & networking
        self.server_socket = None

        # Players
        self.clients = {}  # player_id -> (addr, last_seen)
        self.waiting_room_players = {}  # player_id -> addr
        self.client_base = {}   # player_id -> base of SR window

        # Sequence & snapshots
        self.seq_num = 0  # global seq (used when needed)
        self.snapshot_id = 0  # incremental snapshot ID

        # Game state
        self.grid_state = [[0] * 20 for _ in range(20)]
        self.grid_claim_time = [[0] * 20 for _ in range(20)]
        self.game_active = False
        self.min_players = 2
        self.running = False
        self.grid_changed = False
        self._should_send_snapshots = False  # Control flag for snapshots
        self.game_duration = 60  # 60 seconds game duration
        self.game_start_time = None

        # leaderboard data storage
        self.final_scores = []

        # Start game timer thread
        threading.Thread(target=self._game_timer_thread, daemon=True).start()
        # Start player timeout checker thread
        threading.Thread(target=self._player_timeout_thread, daemon=True).start()

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
        self.client_base = {}   # player_id -> base of SR window
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
        self._should_send_snapshots = False  #Stop all snapshots
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
        self.game_active = False  # Ensure game is marked as inactive


        print("[INFO] Server stopped.")
        self.gui.log_message("Server stopped", "info")
        self.gui.update_player_info("Server", False)
        self.gui.update_players(self.clients)
        self.stats['client_count'] = 0
        self.gui.update_stats(self.stats)

    # ==================== SR ARQ Sender ====================
    def _sr_send(self, player_id, msg_type, payload=b''):
       # Check if player exists before sending
        if player_id not in self.clients and player_id not in self.waiting_room_players:
            print(f"[ERROR] Player {player_id} not found, not sending")
            return False

        # Don't send to clients if game is over and it's a snapshot
        if msg_type == MSG_TYPE_BOARD_SNAPSHOT and not self._should_send_snapshots:
            print(f"[INFO] Skipping snapshot for player {player_id}, snapshots disabled")
            return False

        # Initialize structures if needed
        if player_id not in self.client_next_seq:
            self.client_next_seq[player_id] = 0      # nextSeqNum
            self.client_base[player_id] = 0          # base
            self.client_windows[player_id] = {}      # seq → packet
            self.client_timers[player_id] = {}       # seq → timestamp

        next_seq = self.client_next_seq[player_id]
        base = self.client_base[player_id]
        window = self.client_windows[player_id]

        window_size = len(window)
    
        print(f"[SEND DEBUG] Player {player_id}: base={base}, next_seq={next_seq}, window_size={window_size}, N={self.N}")
        
        # Protocol rule: "The sender may send packets while nextSeqNum < base + N"
        if next_seq >= base + self.N:
            # Window is full according to protocol
            print(f"[WINDOW FULL] Player {player_id}: nextSeqNum={next_seq} >= base+N={base}+{self.N}")
            
            # Check if we can slide window (force slide if stuck)
            if window_size == self.N:
                # All packets in window, check oldest timer
                oldest_seq = min(window.keys()) if window else base
                oldest_time = self.client_timers.get(player_id, {}).get(oldest_seq, 0)
                
                if current_time_ms() - oldest_time > 3 * self.RTO:
                    # Force slide window (packet likely lost)
                    print(f"[FORCE SLIDE] Player {player_id}: Force sliding window past seq={oldest_seq}")
                    self.client_base[player_id] = oldest_seq + 1
                    # Remove from window
                    if oldest_seq in window:
                        del window[oldest_seq]
                    if player_id in self.client_timers and oldest_seq in self.client_timers[player_id]:
                        del self.client_timers[player_id][oldest_seq]
                    
                    # Try sending again
                    return self._sr_send(player_id, msg_type, payload)
            
            self.stats['dropped'] += 1
            self.gui.update_stats(self.stats)
            return False
    

        # Build packet (Header + Payload)
        # Note: create_packet now returns the FULL packet with checksum
        if msg_type == MSG_TYPE_BOARD_SNAPSHOT:
            packet = create_packet(msg_type, next_seq, payload, self.snapshot_id)
        else:
            packet = create_packet(msg_type, next_seq, payload)

        # Resolve address
        if player_id in self.clients:
            addr = self.clients[player_id][0]
        else:
            addr = self.waiting_room_players[player_id]

        # Send
        try:
            self.server_socket.sendto(packet, addr)

            # Store packet in window
            window[next_seq] = packet
            self.client_timers[player_id][next_seq] = current_time_ms()

            # Advance nextSeq
            self.client_next_seq[player_id] += 1

            self.stats['sent'] += 1
            self.gui.update_stats(self.stats)
            print(f"[SEND] PID={player_id} seq={next_seq} base={base} window={list(window.keys())}")
            return True

        except Exception as e:
            self.stats['dropped'] += 1
            self.gui.update_stats(self.stats)
            print(f"[ERROR] sendto failed for PID={player_id}: {e}")
            return False

    def _retransmit(self):
        now = current_time_ms()
        for pid in list(self.client_timers.keys()):
            # NEW: Skip if player no longer exists
            if pid not in self.clients and pid not in self.waiting_room_players:
                # Clean up orphaned timer entries
                if pid in self.client_timers:
                    del self.client_timers[pid]
                if pid in self.client_windows:
                    del self.client_windows[pid]
                continue

            timers = self.client_timers.get(pid, {})
            window = self.client_windows.get(pid, {})

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
        last_timeout_check = time.time()
        
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

    # ==================== Player Timeout Thread ====================
    def _player_timeout_thread(self):
        """Background thread to check for inactive players"""
        while self.running:
            try:
                self._check_player_timeouts()
                time.sleep(5)  # Check every 5 seconds
            except Exception as e:
                print(f"[ERROR] in player timeout thread: {e}")
                time.sleep(5)

    def _check_player_timeouts(self):
        """Check for inactive players and remove them."""
        if not self.running or not self.clients:
            return
        
        current_time = time.time()
        players_to_remove = []
        
        # Check active clients
        for player_id, (addr, last_seen) in list(self.clients.items()):
            if current_time - last_seen > 10:  # 10 seconds timeout
                players_to_remove.append(player_id)
                self.gui.log_message(f"Player {player_id} timed out (no activity for 10s)", "warning")
        
        # Remove timed out players
        for player_id in players_to_remove:
            self._remove_player(player_id)
            self.gui.log_message(f"Removed Player {player_id} due to timeout", "info")

    # ==================== Handle Messages ====================
    def _handle_message(self, data, addr):
        try:
            # Parse packet and validate checksum
            header, payload, valid = parse_packet(data)
            if not header:
                 return # Dropped (too short)
            
            if not valid:
                print(f"[CHECKSUM ERROR] from {addr}")
                self.stats['dropped'] += 1
                return
            
            msg_type = header.get("msg_type")
            seq = header.get("seq_num", 0)
            self.stats['received'] += 1
            self.gui.update_stats(self.stats)
            print(f"[RECEIVED] seq={seq}, type={msg_type}, from={addr}")

            # Send ACK for reliability (ack the received seq)
            try:
                ack_packet = create_ack_packet(ack_num=seq)
                # Use server_socket (fixed bug from earlier version)
                #self.server_socket.sendto(ack_packet, addr)  #####
                print(f"[SEND ACK] seq={seq}, to={addr}")
            except Exception as e:
                print(f"[ERROR] sending ACK to {addr}: {e}")

            if msg_type == MSG_TYPE_JOIN_REQ:
                existing_pid = self._addr_to_pid(addr)
                if existing_pid is not None:
                    print(f"[INFO] Duplicate join request from {addr} (Player {existing_pid})")
                    # If they are already joined, just resend the Join Response 
                    # (The client might have missed the first ACK/Response)
                    payload = struct.pack("!B", existing_pid)
                    self._sr_send(existing_pid, MSG_TYPE_JOIN_RESP, payload)
                    return # Stop here, do not create a new player
                # --- FIX END ---
                # Assign unique player id 
                new_pid = 1
                while new_pid in self.waiting_room_players or new_pid in self.clients:
                    new_pid += 1

                # Add to waiting room first
                self.waiting_room_players[new_pid] = addr

                # Update stats
                self.stats['client_count'] = len(self.waiting_room_players) + len(self.clients)
                self.gui.log_message(f"Player {new_pid} joined waiting room", "success")
                self.gui.update_players(self.waiting_room_players)
                self.gui.update_stats(self.stats)

                # Send join response via SR ARQ to that waiting client
                payload = struct.pack("!B", new_pid)
                self._sr_send(new_pid, MSG_TYPE_JOIN_RESP, payload)
                self.seq_num += 1

                # If game is active and we have less than 4 active players, move waiting player in
                if self.game_active:
                    if len(self.clients) < 4:
                        # Reset all existing players' windows to prevent blocking
                        #for pid in list(self.clients.keys()):
                           # if pid in self.client_windows:
                               # self.client_windows[pid].clear()
                               # self.client_timers[pid].clear()
                                #self.client_next_seq[pid] = 0
                                #self.client_base[pid] = 0      
                        
                        # NOW add the new player to active game
                        self.clients[new_pid] = (addr, time.time())
                        del self.waiting_room_players[new_pid]
                        self.gui.log_message(f"Player {new_pid} joined active game", "info")
                        self.gui.update_players(self.clients)
                        
                        # Send GAME_START immediately to this player
                        self._sr_send(new_pid, MSG_TYPE_GAME_START, b'')
                        # Send latest snapshot so player sees current grid
                        self._send_snapshot()
                else:
                    if len(self.waiting_room_players) >= 1:
                        self._start_game()

            elif msg_type == MSG_TYPE_CLAIM_REQ:
                player_id = self._addr_to_pid(addr)
                self.server_socket.sendto(ack_packet, addr) #####
                if player_id:
                    # Payload is now returned by parse_packet
                    pay = payload if len(payload) >= 4 else b''
                    if len(pay) >= 4:
                        r, c, client_ack_num = struct.unpack("!BBH", pay[:4])
                        
                        # Process the ACK from client
                        self._handle_ack(player_id, client_ack_num)

                        if 0 <= r < 20 and 0 <= c < 20:

                            # --- TIMESTAMP FIX STARTS HERE ---
                            claim_time = header.get("timestamp", 0)

                            # If this is the first time using timestamps, initialize matrix
                            if not hasattr(self, "grid_claim_time"):
                                self.grid_claim_time = [[0] * 20 for _ in range(20)]

                            # Accept only newer claims
                            if claim_time > self.grid_claim_time[r][c]:

                                old_owner = self.grid_state[r][c]

                                # Update grid & timestamp
                                self.grid_state[r][c] = player_id
                                self.grid_claim_time[r][c] = claim_time
                                self.grid_changed = True

                                # Logging
                                if old_owner == 0:
                                    self.gui.log_message(
                                        f"Player {player_id} claimed cell ({r},{c})",
                                        "info"
                                    )
                                else:
                                    self.gui.log_message(
                                        f"Player {player_id} stole cell ({r},{c}) from Player {old_owner}",
                                        "warning"
                                    )

                                # Update GUI
                                self.gui.update_grid(self.grid_state)

                            else:
                                # Late / outdated claim — ignore
                                self.gui.log_message(
                                    f"Outdated claim ignored at ({r},{c}) from Player {player_id} "
                                    f"(claim ts={claim_time}, current ts={self.grid_claim_time[r][c]})",
                                    "warning"
                                )

                        else:
                            self.gui.log_message(
                                f"Invalid coordinates ({r},{c}) from player {player_id}",
                                "error"
                            )

                    # Update player last_seen time
                    if player_id in self.clients:
                        self.clients[player_id] = (addr, time.time())

                else:
                    self.gui.log_message(f"Claim from unknown addr {addr}", "warning")
            
            elif msg_type == MSG_TYPE_LEAVE:
                # ACK the LEAVE message
                client_seq = header['seq_num']
                ack_packet = create_ack_packet(ack_num=client_seq)
                self.server_socket.sendto(ack_packet, addr)

                # Find the player ID for this address
                player_id = self._addr_to_pid(addr)
                
                if player_id:
                    # Check if game is active before removing player
                    was_game_active = self.game_active
                    # Remove the player and their claimed cells
                    self._remove_player_and_cells(player_id)
                    self.gui.log_message(f"Player {player_id} left gracefully", "info")
                    
                    # Check if game should end (less than min_players during active game)
                    if was_game_active and self.game_active:
                        active_players = len(self.clients)
                        if active_players < self.min_players:
                            self.gui.log_message(f"Less than {self.min_players} players remaining. Ending game...", "warning")
                            self._end_game_with_scores()
                else:
                    self.gui.log_message(f"Unknown player from {addr} left", "warning")

            elif msg_type == MSG_TYPE_ACK:
                player_id = self._addr_to_pid(addr)
                if player_id:
                    ack_val = header.get("ack_num", 0)
                    self._handle_ack(player_id, ack_val)
                    # Update last_seen for active players when they send ACK
                    if player_id in self.clients:
                        self.clients[player_id] = (addr, time.time())


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

    def _remove_player_and_cells(self, player_id):
        """Remove a player and all their claimed cells from the grid."""
        # Check if player was in active game before removing
        was_in_active_game = player_id in self.clients
        
        # Count cells owned by this player before removal
        cells_removed = 0
        if was_in_active_game:
            # Remove player's claimed cells from the grid
            for r in range(20):
                for c in range(20):
                    if self.grid_state[r][c] == player_id:
                        self.grid_state[r][c] = 0  # Reset to unclaimed
                        self.grid_claim_time[r][c] = 0  # Reset timestamp
                        cells_removed += 1
        
        # Remove player from all data structures
        self.clients.pop(player_id, None)
        self.client_windows.pop(player_id, None)
        self.client_timers.pop(player_id, None)
        self.client_next_seq.pop(player_id, None)
        self.client_base.pop(player_id, None)
        self.waiting_room_players.pop(player_id, None)
        
        # Mark grid as changed if we removed any cells
        if cells_removed > 0:
            self.grid_changed = True
            self.gui.update_grid(self.grid_state)
            self.gui.log_message(f"Removed {cells_removed} cells claimed by Player {player_id}", "info")
        
        self.gui.log_message(f"Player {player_id} removed from server", "info")
        
        # Check if game should end (active game with less than min_players)
        if self.game_active and was_in_active_game:
            active_players = len(self.clients)
            if active_players < self.min_players:
                self.gui.log_message(f"Less than {self.min_players} players remaining. Ending game...", "warning")
                self._end_game_with_scores()
        
        # If no more active players at all, stop sending snapshots AND reset grid
        if not self.clients and not self.waiting_room_players:
            self._should_send_snapshots = False
            
            # Reset grid when all players have left
            self.grid_state = [[0] * 20 for _ in range(20)]
            self.grid_claim_time = [[0] * 20 for _ in range(20)]
            self.grid_changed = True  # This will trigger a snapshot if new players join
            
            # Update GUI to show empty grid
            self.gui.update_grid(self.grid_state)
            self.gui.log_message("All players left. Grid reset.", "info")

        # Update GUI & stats
        self.stats['client_count'] = len(self.clients) + len(self.waiting_room_players)
        self.gui.update_players(self.clients if self.clients else self.waiting_room_players)
        self.gui.update_stats(self.stats)

    def _remove_player(self, player_id):
        """Wrapper for backward compatibility - calls _remove_player_and_cells."""
        return self._remove_player_and_cells(player_id)


    def _handle_ack(self, player_id, ack_num):
        """
        Handle ACK from client according to SR ARQ protocol.
        """
        if player_id not in self.client_windows:
            print(f"[ACK] Player {player_id} not found in client_windows")
            return

        window = self.client_windows[player_id]
        base = self.client_base.get(player_id, 0)
        next_seq = self.client_next_seq.get(player_id, 0)

        print(f"[ACK] Player {player_id}: ack={ack_num}, base={base}, next={next_seq}, window={list(window.keys())}")

        # SELECTIVE REPEAT: Only remove the specific packet acknowledged
        if ack_num in window:
            del window[ack_num]
            if player_id in self.client_timers and ack_num in self.client_timers[player_id]:
                del self.client_timers[player_id][ack_num]
            
            print(f"[ACK] Player {player_id}: Removed seq {ack_num}")
            
            # Slide window base forward if the base packet has been acknowledged
            new_base = base
            while new_base not in window and new_base < next_seq:
                new_base += 1
            
            if new_base != base:
                self.client_base[player_id] = new_base
                print(f"[ACK] Player {player_id}: Window slid base={base} -> {new_base}")
        
        elif ack_num < base:
             print(f"[ACK] Player {player_id}: Ignoring duplicate/old ACK {ack_num} (current base={base})")
        else:
             print(f"[ACK] Player {player_id}: Ignoring ACK {ack_num} (not in window usually means already ACKed)")

    # ==================== Snapshot ====================
    def _send_snapshot(self):
        """Send snapshot to all active clients (SR ARQ)."""
        # Check if we should send snapshots
        if not self._should_send_snapshots:
            print(f"[INFO] Snapshots disabled, skipping")
            return
            
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
    
    def _game_timer_thread(self):
        """Background thread to manage game duration"""
        while self.running:
            if self.game_active and self.game_start_time:
                elapsed = time.time() - self.game_start_time
                if elapsed >= self.game_duration:
                    self._end_game_with_scores()
                    self.game_start_time = None
                elif self.game_duration - elapsed <= 10:
                    # Send warning when 10 seconds remaining
                    if int(self.game_duration - elapsed) == 10:
                        self.gui.log_message("10 seconds remaining!", "warning")
            time.sleep(1)
    
    def _start_game(self):
        self.game_active = True
        self._should_send_snapshots = True
        self.game_start_time = time.time()  # Track when game started
        
        # Convert waiting_room_players (pid->addr) to clients structure (pid->(addr, last_seen))
        for pid, addr in self.waiting_room_players.items():
            self.clients[pid] = (addr, time.time())
        self.waiting_room_players.clear()

        # Update stats & GUI
        self.stats['client_count'] = len(self.clients)
        self.gui.log_message(f"Game started with {len(self.clients)} players! (Duration: {self.game_duration}s)", "success")
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

        # Send an initial snapshot
        try:
            self._send_snapshot()
        except Exception as e:
            self.gui.log_message(f"Failed to send initial snapshot after game start: {e}", "error")
    
    def _end_game_with_scores(self):
        """End the game, send scores, and reset for new players"""
        if not self.game_active:
            print("[DEBUG] Game already ended, skipping _end_game_with_scores")
            return
            
        print("[GAME END] Starting game end process...")
        self.game_active = False
        self._should_send_snapshots = False
        
        # Send game over to all clients
        print(f"[GAME END] Sending GAME_OVER to {len(self.clients)} clients")
        for pid in list(self.clients.keys()):
            try:
                self._sr_send(pid, MSG_TYPE_GAME_OVER, b'')
            except Exception as e:
                print(f"[ERROR] Failed to send game over to player {pid}: {e}")
        
        # Wait a bit for clients to process game over
        time.sleep(0.5)
        
        # Calculate scores
        self.final_scores = calculate_scores_from_grid(self.grid_state)
        print(f"[GAME END] Final scores: {self.final_scores}")
        
        # Send leaderboard
        leaderboard_payload = pack_leaderboard_data(self.final_scores)
        for pid in list(self.clients.keys()):
            try:
                self._sr_send(pid, MSG_TYPE_LEADERBOARD, leaderboard_payload)
            except Exception as e:
                print(f"[ERROR] Failed to send leaderboard to player {pid}: {e}")
        
        # Wait for leaderboard to be sent
        time.sleep(1)
        
        # Update server GUI with final scores
        score_str = ", ".join([f"Player {pid}: {score}" for pid, score in self.final_scores])
        self.gui.log_message(f"Game Over! Final scores: {score_str}", "info")
        
        # Show leaderboard on server
        self._show_server_leaderboard()
        
        # Schedule reset after 5 seconds (give clients time to see scores)
        print("[GAME END] Scheduling auto-reset in 5 seconds")
        self.gui.root.after(5000, self._reset_for_new_game)

    def _show_server_leaderboard(self):
        """Show leaderboard on server GUI"""
        try:
            # This assumes your server GUI has access to show leaderboard
            if hasattr(self.gui, 'root'):
                # Import LeaderboardGUI here to avoid circular imports
                from leaderboard import LeaderboardGUI
                
                # Create leaderboard on main thread
                def show_lb():
                    LeaderboardGUI(
                        self.gui.root,
                        self.final_scores,
                        play_again_callback=self._restart_game
                    )
                
                self.gui.root.after(0, show_lb)
        except Exception as e:
            print(f"[ERROR] Could not show server leaderboard: {e}")

    def _reset_for_new_game(self):
        """Reset server for new game without stopping"""
        print("[SERVER] Resetting for new game...")
        
        # 1. Send disconnect/reset message to any remaining clients
        for pid in list(self.clients.keys()):
            try:
                # Send a reset message (optional)
                self._sr_send(pid, MSG_TYPE_GAME_OVER, b'')
            except:
                pass
        
        # 2. Clear all game state but keep server running
        self._reset_game_state()
        
        # 3. Log that server is ready for new players
        self.gui.log_message("Server reset complete. Ready for new players!", "success")
        
        # 4. Keep server socket open and listening
        print("[SERVER] Reset complete. Waiting for new players...")

    def _reset_game_state(self):
        """Reset all game state while keeping server running"""
        print("[SERVER] Resetting game state...")
        
        # Reset grid
        self.grid_state = [[0] * 20 for _ in range(20)]
        self.grid_claim_time = [[0] * 20 for _ in range(20)]
        self.grid_changed = False
        
        # Reset game state
        self.game_active = False
        self._should_send_snapshots = False
        self.game_start_time = None
        
        # Clear all players
        self.clients.clear()
        self.waiting_room_players.clear()
        
        # Clear SR ARQ windows
        self.client_windows.clear()
        self.client_timers.clear()
        self.client_next_seq.clear()
        self.client_base.clear()
        
        # Reset sequence numbers (optional, you might want to keep them)
        self.snapshot_id = 0
        self.seq_num = 0
        
        # Clear final scores
        self.final_scores = []
        
        # Update GUI
        self.gui.update_grid(self.grid_state)
        self.gui.update_players({})
        self.gui.update_stats(self.stats)
        self.gui.log_message("Game state cleared. Ready for new players!", "info")

    def _restart_game(self):
        """Reset server for new game (called from leaderboard Play Again button)"""
        print("[SERVER] Manual restart requested from leaderboard")
        
        # Instead of auto-restarting (which stops and starts), just reset
        self.gui.log_message("Resetting for new game...", "info")
        self._reset_for_new_game()

    def end_game(self):
            self.game_active = False
            self._should_send_snapshots = False  #Disable snapshots when game ends

            # Send game over message to all clients
            for pid in list(self.clients.keys()):
                try:
                    self._sr_send(pid, MSG_TYPE_GAME_OVER, b'')
                except Exception as e:
                    self.gui.log_message(f"Failed to send game over to player {pid}: {e}", "error")
            
            # Clear game state
            self.grid_state = [[0] * 20 for _ in range(20)]
            self.grid_claim_time = [[0] * 20 for _ in range(20)]
            self.grid_changed = False
            
            print("[GAME OVER]")
            self.gui.log_message("Game over", "info")
            
            # Update GUI to show empty grid
            self.gui.update_grid(self.grid_state)
            self._end_game_with_scores()

    # ==================== GUI Integration ====================
    def _setup_gui_callbacks(self):
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