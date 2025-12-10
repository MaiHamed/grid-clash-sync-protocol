import socket
import struct
import time
import sys
import threading
from gui import GameGUI, calculate_scores_from_grid
from leaderboard import LeaderboardGUI
from protocol import (
    MSG_TYPE_LEADERBOARD, create_ack_packet, create_header, parse_header, HEADER_SIZE,
    MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP,
    MSG_TYPE_CLAIM_REQ, MSG_TYPE_BOARD_SNAPSHOT, MSG_TYPE_LEAVE,
    MSG_TYPE_GAME_START, MSG_TYPE_GAME_OVER,
    unpack_grid_snapshot, MSG_TYPE_ACK, unpack_leaderboard_data
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
        self.seq_num = 0      
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
        self._game_over_handled = False
        self.final_scores = []




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
        self.gui.set_restart_callback(self.restart_game)


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
        
        # Check if cell is already claimed (by anyone)
        if self.local_grid[row][col] != 0:
            self.gui.log_message(f"Cell ({row},{col}) already claimed!", "warning")
            return
        
        # OPTIMISTIC UPDATE: Immediately update local grid and GUI with player color
        self.local_grid[row][col] = self.player_id
        self.claimed_cells.add((row, col))
        
        # Update GUI to show player color immediately
        self.gui.update_grid(self.local_grid)
        
        # Send claim request to server
        if self._send_claim_request(row, col):
            self.gui.log_message(f"Request to claim ({row},{col}) sent.", "claim")
        else:
            # If send failed, revert the optimistic update
            self.local_grid[row][col] = 0
            self.claimed_cells.discard((row, col))
            self.gui.update_grid(self.local_grid)

    # ==================== SR ARQ SENDER ====================
    def _sr_send(self, msg_type, payload=b''):
        if self.nextSeqNum < self.base + self.N:
            seq = self.nextSeqNum  # Get the sequence number
            packet = create_header(msg_type, seq, len(payload)) + payload
            try:
                self.client_socket.sendto(packet, (self.server_ip, self.server_port))
            except Exception as e:
                self.gui.log_message(f"Send error: {e}", "error")
                self.stats['dropped'] += 1
                return False
            self.window[seq] = packet
            now_ms = current_time_ms()
            self.timers[seq] = now_ms
            self.send_timestamp[seq] = now_ms
            self.nextSeqNum += 1
            self.stats['sent'] += 1
            return seq
        else:
            self.stats['dropped'] += 1
            return False
  
    def _retransmit(self, seq):
        packet = self.window.get(seq)
        if packet:
            try:
                self.client_socket.sendto(packet, (self.server_ip, self.server_port))
            except Exception as e:
                self.gui.log_message(f"Retransmit error: {e}", "error")
                return

            self.timers[seq] = current_time_ms()
            self.stats['sent'] += 1
            self.stats['retransmissions'] += 1

            # Mark this seq as retransmitted
            if not hasattr(self, "_retransmitted_seqs"):
                self._retransmitted_seqs = set()
            self._retransmitted_seqs.add(seq)

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

    def disconnect(self, leave_timeout_ms=2000):
        # If not connected, simple cleanup
        if not self.client_socket:
            self.running = False
            self.game_active = False
            self.player_id = None
            self.active_players.clear()
            self.gui.update_player_info(None, False)
            self.gui.update_players({})
            self.gui.log_message("Disconnected (no socket)", "info")
            return

        # Ensure the receiver/timer threads keep running while we wait for ACK
        # Send LEAVE using SR-ARQ (will be retransmitted by _timer_loop)
        leave_seq = self._sr_send(MSG_TYPE_LEAVE, payload=b'')
        if leave_seq is False:
            # Couldn't send (window full or socket error) — fallback: try raw send once
            try:
                packet = create_header(MSG_TYPE_LEAVE, 0, 0)
                self.client_socket.sendto(packet, (self.server_ip, self.server_port))
            except Exception:
                pass
            # proceed to shutdown after a short delay
            time.sleep(0.05)
        else:
            # Wait for ACK of the leave_seq (or until timeout)
            start = time.monotonic()
            timeout_sec = leave_timeout_ms / 1000.0
            while True:
                # If leave_seq no longer in window, ACK was received for it
                if leave_seq not in self.window:
                    # ACK received — graceful
                    break
                if time.monotonic() - start >= timeout_sec:
                    # timeout waiting for ACK — give up and close anyway
                    self.gui.log_message(f"Timeout waiting for LEAVE ACK (seq={leave_seq}). Closing.", "warning")
                    break
                time.sleep(0.01)  # small sleep to yield to receive thread

        # Now stop the client loops and close the socket
        self.running = False
        self.game_active = False
        if self.game_timer_id:
            try:
                self.gui.root.after_cancel(self.game_timer_id)
            except Exception:
                pass
            self.game_timer_id = None

        try:
            self.client_socket.close()
        except Exception:
            pass
        self.client_socket = None

        # Clear local state
        self.player_id = None
        self.window.clear()
        self.timers.clear()
        self.send_timestamp.clear()
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
                try:
                    self.client_socket.sendto(ack_packet, addr)
                except:
                    pass  # ignore ACK send failure
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
            # Only update RTT if this packet was never retransmitted
            if self.stats.get('retransmissions', 0) and seq in self.timers:
                # Check if it was retransmitted
                retransmitted = False
                if hasattr(self, "_retransmitted_seqs"):
                    retransmitted = seq in self._retransmitted_seqs
                else:
                    self._retransmitted_seqs = set()
                    retransmitted = False
            else:
                retransmitted = False

            sent_time = self.send_timestamp.get(seq, recv_ms)

            if not retransmitted:
                sampleRTT = recv_ms - sent_time
                self.estimatedRTT = (1 - self.alpha) * self.estimatedRTT + self.alpha * sampleRTT
                self.devRTT = (1 - self.beta) * self.devRTT + self.beta * abs(sampleRTT - self.estimatedRTT)
                self.RTO = self.estimatedRTT + 4*self.devRTT

            # Clean up
            del self.window[seq]
            del self.timers[seq]
            del self.send_timestamp[seq]
            if hasattr(self, "_retransmitted_seqs"):
                self._retransmitted_seqs.discard(seq)

            # Slide base
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
            # Store that we received game over, but wait for leaderboard
            self.game_active = False
            self.received_game_over = True  # Add this flag
            self.gui.log_message("Game Over! Waiting for final scores...", "info")
            
            # Start a timer to check if leaderboard arrives within timeout
            if hasattr(self, '_leaderboard_timeout_id'):
                self.gui.root.after_cancel(self._leaderboard_timeout_id)
            self._leaderboard_timeout_id = self.gui.root.after(2000, self._handle_leaderboard_timeout)
        
        elif msg_type == MSG_TYPE_LEADERBOARD:
            # Cancel the timeout timer
            if hasattr(self, '_leaderboard_timeout_id'):
                self.gui.root.after_cancel(self._leaderboard_timeout_id)
            
            try:
                self.final_scores = unpack_leaderboard_data(payload)
                self.gui.log_message(f"Received final scores from server", "success")
                
                # Show leaderboard on GUI thread
                self.gui.root.after(0, self._show_server_leaderboard)
                
            except Exception as e:
                self.gui.log_message(f"Failed to parse leaderboard: {e}", "error")
                # Fallback to local calculation
                self.gui.root.after(0, self._handle_game_over)
        
        elif msg_type == MSG_TYPE_BOARD_SNAPSHOT:
                try:
                    # Extract snapshot ID
                    if len(payload) >= 4:
                        snapshot_id = struct.unpack("!I", payload[:4])[0]
                        grid_payload = payload[4:]
                    else:
                        grid_payload = payload
                        
                    # Unpack snapshot from server
                    grid = unpack_grid_snapshot(grid_payload)
                    self.local_grid = [row[:] for row in grid]

                    # Determine ALL active players from snapshot
                    players_in_grid = set()
                    for r in range(20):
                        for c in range(20):
                            pid = grid[r][c]
                            if pid != 0:
                                players_in_grid.add(pid)

                    # Include ourselves in active players if we're in the game
                    if self.player_id:
                        players_in_grid.add(self.player_id)
                        
                    self.active_players = players_in_grid

                    # Track claimed cells for this client
                    self.claimed_cells.clear()
                    for r in range(20):
                        for c in range(20):
                            if grid[r][c] == self.player_id:
                                self.claimed_cells.add((r, c))

                    # Update GUI with complete grid
                    self.gui.root.after(0, lambda: self.gui._update_grid_display(grid))
                    
                    # Update player list in GUI
                    self.gui.root.after(0, lambda: self.gui._update_players_display(players_in_grid))
                    
                    # Update statistics
                    self.stats['received'] += 1
                    self.gui.root.after(0, lambda: self.gui._update_stats_display(self.stats))
                    
                    # Log snapshot receipt
                    if snapshot_id % 10 == 0:
                        self.gui.log_message(f"Snapshot {snapshot_id} received with {len(players_in_grid)} players", "info")

                except Exception as e:
                    self.gui.log_message(f"Failed to process snapshot: {e}", "error")

                players_map = {pid: None for pid in sorted(players_in_grid)}
                self.gui.update_players(players_map)


    # ==================== GAME ACTIONS ====================
    def _send_claim_request(self, row, col):
        """Send claim request using SR-ARQ (via _sr_send)"""
        if not self.client_socket or not self.player_id:
            self.gui.log_message("Not connected to server", "error")
            return False
        if not self.game_active:
            self.gui.log_message("Game hasn't started yet", "warning")
            return False

        try:
            payload = struct.pack("!BB", row, col)
            success = self._sr_send(MSG_TYPE_CLAIM_REQ, payload)
            
            if success:
                return True
            else:
                self.gui.log_message(f"Claim request for ({row},{col}) dropped (window full).", "warning")
                return False

        except Exception as e:
            self.gui.log_message(f"Claim preparation error: {e}", "error")
            return False
        
    def _start_game_timer(self):
        if not self.game_active or not self.game_start_time:
            return

        elapsed = time.time() - self.game_start_time
        remaining = max(0, self.game_duration - elapsed)
        minutes, seconds = divmod(int(remaining), 60)
        self.gui.root.title(f"Grid Game Client - Time: {minutes:02d}:{seconds:02d}")

        if remaining <= 0:
            # Stop timer and trigger game over
            if self.game_timer_id:
                self.gui.root.after_cancel(self.game_timer_id)
                self.game_timer_id = None
            # Trigger game over safely
            self.gui.root.after(0, self._handle_game_over)
            return

        # Continue countdown
        self.game_timer_id = self.gui.root.after(1000, self._start_game_timer)

    def _handle_game_over(self):
        # Prevent multiple calls
        if not self.game_active and hasattr(self, '_game_over_handled') and self._game_over_handled:
            return
        
        self._game_over_handled = True
        self.game_active = False
        
        # Cancel any existing game timer
        if self.game_timer_id:
            try:
                self.gui.root.after_cancel(self.game_timer_id)
            except:
                pass
            self.game_timer_id = None
        
        self.gui.log_message("GAME OVER! 🏁", "info")
        self.gui.root.title("Grid Game Client - Game Over")
        
        # Calculate scores from CURRENT grid (which has all players)
        final_grid = [row[:] for row in self.local_grid]
        scores = calculate_scores_from_grid(final_grid)
        
        # Log all players found
        player_ids = set()
        for row in final_grid:
            for cell in row:
                if cell != 0:
                    player_ids.add(cell)
        
        self.gui.log_message(f"Found players in final grid: {sorted(player_ids)}", "info")
        
        # Show leaderboard with all players
        self._show_leaderboard(scores)
    
    def _show_server_leaderboard(self):
            if self.final_scores:
                # Use the scores from server
                self.gui.root.after(0, lambda: self._show_leaderboard(self.final_scores))
            else:
                # Fallback to local calculation
                self.gui.root.after(0, self._handle_game_over)

    def _show_leaderboard(self, scores):
        """Show leaderboard with given scores"""
        self.leaderboard = LeaderboardGUI(
            self.gui.root,
            scores,
            play_again_callback=self.restart_game
        )
    
    def restart_game(self):
        self._game_over_handled = False
        self.waiting_for_game = True
        
        # Reset local state
        self.local_grid = [[0]*20 for _ in range(20)]
        self.claimed_cells.clear()
        self.final_scores = []
        
        # Update GUI
        self.gui.update_grid(self.local_grid)
        self.gui.update_player_info(f"Player {self.player_id} (Waiting)", True)
        self.gui.log_message("Ready for new game...", "info")
        
        # Request to join new game
        if self.client_socket and self.running:
            self._sr_send(MSG_TYPE_JOIN_REQ, payload=b'')
            self.gui.log_message("Requested to join new game", "info")

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