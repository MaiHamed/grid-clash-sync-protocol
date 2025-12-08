# client.py - Updated with waiting room support
import socket
import struct
import time
import random
import threading
import tkinter as tk
from tkinter import messagebox
from protocol import (
    create_header, parse_header,
    MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP,
    MSG_TYPE_CLAIM_REQ, MSG_TYPE_BOARD_SNAPSHOT, MSG_TYPE_LEAVE,
    MSG_TYPE_GAME_START, MSG_TYPE_GAME_OVER,
    unpack_grid_snapshot
)

class GameClient:
    def __init__(self, server_ip="127.0.0.1", server_port=5005):
        self.server_ip = server_ip
        self.server_port = server_port
        self.client_socket = None
        self.seq_num = 0
        self.player_id = None
        self.running = False
        self.receive_thread = None
        self.auto_claim_thread = None
        
        # Game state
        self.game_active = False
        self.waiting_for_game = True
        self.game_start_time = None
        self.game_duration = 60  # 60 seconds game
        
        # Statistics
        self.stats = {
            'sent': 0,
            'received': 0,
            'dropped': 0,
            'latency_sum': 0,
            'latency_count': 0
        }
        
        from gui import GameGUI
        self.gui = GameGUI(title="Grid Game Client")
        self.claimed_cells = set()
        
        # Track active players (inferred from grid)
        self.active_players = set()
        
        # Callback setup
        self._setup_gui_callbacks()
        
        # Track last snapshot for logging
        self.last_log_time = 0
        
        # Game timer
        self.game_timer_id = None
    
    def _setup_gui_callbacks(self):
        """Setup GUI button callbacks"""
        self.gui.connect_button.config(command=self.connect)
        self.gui.disconnect_button.config(command=self.disconnect)
        self.gui.on_connect_click = self.connect
        self.gui.on_disconnect_click = self.disconnect
        self.gui.on_auto_claim_toggle = self._on_auto_claim_toggle
        
        # Setup click handler for grid
        self.setup_click_handler()
        
        # Update GUI to show waiting state
        self.gui.log_message("Waiting for game to start...", "info")
        self.gui.update_player_info("Waiting...", True)
    
    def setup_click_handler(self):
        """Setup click handler for the GUI"""
        self.gui.set_cell_click_handler(self.on_cell_click)
    
    def on_cell_click(self, row, col):
        """Handle cell click from GUI"""
        if not self.player_id:
            self.gui.log_message("Not connected to server", "error")
            return
        
        if not self.game_active:
            self.gui.log_message("Game hasn't started yet", "warning")
            return
        
        # Highlight the cell temporarily
        self.gui.highlight_cell(row, col)
        
        # Send claim request
        if self._send_claim_request(row, col):
            self.gui.log_message(f"Claimed cell ({row}, {col})", "success")
    
    def connect(self):
        """Connect to server"""
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.client_socket.settimeout(1.0)
            
            # Send join request
            join_req = create_header(MSG_TYPE_JOIN_REQ, self.seq_num, 0)
            self.client_socket.sendto(join_req, (self.server_ip, self.server_port))
            self.seq_num += 1
            self.stats['sent'] += 1
            
            self.gui.log_message(f"Connecting to {self.server_ip}:{self.server_port}...", "info")
            self.gui.update_player_info("Connecting...", True)
            
            # Start receive thread
            self.running = True
            self.receive_thread = threading.Thread(target=self._receive_loop)
            self.receive_thread.daemon = True
            self.receive_thread.start()
            
            return True
            
        except Exception as e:
            self.gui.log_message(f"Connection error: {e}", "error")
            return False
    
    def disconnect(self):
        """Disconnect from server"""
        self.running = False
        self.game_active = False
        
        # Stop auto-claim thread
        if self.auto_claim_thread and self.auto_claim_thread.is_alive():
            self.auto_claim_thread.join(timeout=1)
        
        # Stop game timer
        if self.game_timer_id:
            self.gui.root.after_cancel(self.game_timer_id)
        
        if self.client_socket:
            # Send leave message
            leave_msg = create_header(MSG_TYPE_LEAVE, self.seq_num, 0)
            try:
                self.client_socket.sendto(leave_msg, (self.server_ip, self.server_port))
                self.seq_num += 1
                self.stats['sent'] += 1
            except:
                pass
            
            self.client_socket.close()
            self.client_socket = None
        
        self.player_id = None
        self.active_players.clear()
        self.gui.update_player_info(None, False)
        self.gui.update_players({})  # Clear player list
        self.gui.log_message("Disconnected from server", "info")
    
    def _send_claim_request(self, row, col):
        """Send claim request to server"""
        if not self.client_socket or not self.player_id:
            self.gui.log_message("Not connected to server", "error")
            return False
        
        if not self.game_active:
            self.gui.log_message("Game hasn't started yet", "warning")
            return False
        
        try:
            payload = struct.pack("!BB", row, col)
            claim_req = create_header(MSG_TYPE_CLAIM_REQ, self.seq_num, len(payload)) + payload
            self.client_socket.sendto(claim_req, (self.server_ip, self.server_port))
            self.seq_num += 1
            self.stats['sent'] += 1
            
            # Add to claimed set
            self.claimed_cells.add((row, col))
            
            return True
            
        except Exception as e:
            self.gui.log_message(f"Claim error: {e}", "error")
            return False
    
    def _start_auto_claim(self):
        """Start auto-claiming random cells"""
        def auto_claim_loop():
            while self.running and self.gui.auto_claim_var.get() and self.game_active:
                try:
                    # Try to claim a random unclaimed cell
                    for _ in range(10):
                        row, col = random.randint(0, 19), random.randint(0, 19)
                        if (row, col) not in self.claimed_cells:
                            self._send_claim_request(row, col)
                            break
                    
                    # Wait a bit before next claim
                    time.sleep(random.uniform(0.1, 0.5))
                    
                except Exception as e:
                    self.gui.log_message(f"Auto-claim error: {e}", "error")
                    time.sleep(1)
        
        self.auto_claim_thread = threading.Thread(target=auto_claim_loop)
        self.auto_claim_thread.daemon = True
        self.auto_claim_thread.start()
    
    def _receive_loop(self):
        """Receive messages from server"""
        while self.running and self.client_socket:
            try:
                data, addr = self.client_socket.recvfrom(2048)
                recv_time_ms = int(time.time() * 1000)
                
                if len(data) < 22:
                    continue
                    
                header = parse_header(data)
                self.stats['received'] += 1
                
                if header["msg_type"] == MSG_TYPE_JOIN_RESP and self.player_id is None:
                    if len(data) >= 23:
                        self.player_id = struct.unpack("!B", data[22:23])[0]
                        self.gui.update_player_info(f"Player {self.player_id} (Waiting)", True)
                        self.gui.log_message(f"Joined as Player {self.player_id}", "success")
                        self.gui.log_message("Waiting for other players... Minimum 2 required.", "info")
                        
                        # Add ourselves to active players
                        if self.player_id:
                            self.active_players.add(self.player_id)
                            self.gui.update_players(self.active_players)
                
                elif header["msg_type"] == MSG_TYPE_GAME_START:
                    # Game is starting!
                    self.game_active = True
                    self.waiting_for_game = False
                    self.game_start_time = time.time()
                    
                    self.gui.log_message("GAME STARTED! 🎮", "success")
                    self.gui.log_message(f"You are Player {self.player_id}", "info")
                    self.gui.update_player_info(f"Player {self.player_id} (Playing)", True)
                    
                    # Start auto-claim if enabled
                    if self.gui.auto_claim_var.get():
                        self._start_auto_claim()
                    
                    # Start game timer
                    self._start_game_timer()
                
                elif header["msg_type"] == MSG_TYPE_GAME_OVER:
                    # Game over
                    self.game_active = False
                    self.gui.log_message("GAME OVER! 🏁", "info")
                    
                    # Parse winner information if available
                    if len(data) >= 23:
                        winner_id = struct.unpack("!B", data[22:23])[0]
                        if winner_id == 0:
                            self.gui.log_message("Game ended - no winner", "info")
                        elif winner_id == self.player_id:
                            self.gui.log_message("🎉 YOU WIN! 🎉", "success")
                        else:
                            self.gui.log_message(f"Player {winner_id} wins!", "info")
                    
                    # Disable auto-claim
                    self.gui.auto_claim_var.set(False)
                
                elif header["msg_type"] == MSG_TYPE_BOARD_SNAPSHOT and self.game_active:
                    snapshot_id = header.get("snapshot_id", 0)
                    server_ts_ms = header.get("timestamp", recv_time_ms)
                    
                    # Calculate latency
                    latency = recv_time_ms - server_ts_ms
                    self.stats['latency_sum'] += latency
                    self.stats['latency_count'] += 1
                    
                    # Unpack grid
                    payload = data[22:]
                    if payload:
                        try:
                            # Server sends actual player IDs (1, 2, 3, 4)
                            grid = unpack_grid_snapshot(payload)
                            
                            # Update the GUI with the grid data
                            self.gui.update_grid(grid)
                            
                            # Infer active players from grid
                            new_active_players = set()
                            for r in range(20):
                                for c in range(20):
                                    player_id = grid[r][c]
                                    if 1 <= player_id <= 4:
                                        new_active_players.add(player_id)
                            
                            # Update active players if changed
                            if new_active_players != self.active_players:
                                self.active_players = new_active_players
                                self.gui.update_players(self.active_players)
                            
                        except Exception as e:
                            self.gui.log_message(f"Grid unpack error: {e}", "error")
                    
                    # Update GUI with stats
                    self.gui.update_stats(self.stats)
                    self.gui.update_snapshot(snapshot_id)
                    
                    # Log snapshot (once per 5 seconds)
                    current_time = time.time()
                    if current_time - self.last_log_time >= 5.0:
                        self.last_log_time = current_time
                        remaining = self.game_duration - (current_time - self.game_start_time)
                        if remaining > 0:
                            self.gui.log_message(f"Game time remaining: {int(remaining)}s", "info")
                
                # Update GUI
                self.gui.update_stats(self.stats)
                
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.gui.log_message(f"Receive error: {e}", "error")
                    time.sleep(0.1)
    
    def _start_game_timer(self):
        """Start the game timer display"""
        if not self.game_active or not self.game_start_time:
            return
        
        current_time = time.time()
        elapsed = current_time - self.game_start_time
        remaining = max(0, self.game_duration - elapsed)
        
        # Update timer in GUI title
        minutes = int(remaining) // 60
        seconds = int(remaining) % 60
        self.gui.root.title(f"Grid Game Client - Time: {minutes:02d}:{seconds:02d}")
        
        # Check if game should end
        if remaining <= 0:
            self.game_active = False
            self.gui.log_message("Time's up! Game ended.", "info")
            self.gui.root.title("Grid Game Client - Game Over")
            return
        
        # Schedule next update
        self.game_timer_id = self.gui.root.after(1000, self._start_game_timer)
    
    def _on_auto_claim_toggle(self):
        """Handle auto-claim toggle"""
        if self.gui.auto_claim_var.get():
            if not self.game_active:
                self.gui.log_message("Game hasn't started yet", "warning")
                self.gui.auto_claim_var.set(False)
                return
            
            self.gui.log_message("Auto-claim enabled", "info")
            if self.running and self.player_id and self.game_active:
                self._start_auto_claim()
        else:
            self.gui.log_message("Auto-claim disabled", "info")
    
    def start(self):
        """Start the client GUI"""
        self.gui.run()


# Original main function
def original_main():
    """Original client code without GUI"""
    SERVER_IP = "127.0.0.1"
    SERVER_PORT = 5005

    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.settimeout(0.5)

    seq_num = 0
    player_id = None

    # Join Phase
    join_req = create_header(MSG_TYPE_JOIN_REQ, seq_num, 0)
    client_socket.sendto(join_req, (SERVER_IP, SERVER_PORT))
    print("[JOIN] Sent JOIN_REQUEST")
    seq_num += 1

    while True:
        try:
            data, addr = client_socket.recvfrom(1024)
            header = parse_header(data)
            if header["msg_type"] == MSG_TYPE_JOIN_RESP:
                player_id = struct.unpack("!B", data[22:])[0]
                print(f"[JOIN] Assigned PlayerID={player_id}")
                break
        except socket.timeout:
            continue

    # Main Loop
    start = time.time()
    claimed = set()

    while time.time() - start < 30:
        row, col = random.randint(0, 19), random.randint(0, 19)
        if (row, col) in claimed:
            continue
        claimed.add((row, col))

        payload = struct.pack("!BB", row, col)
        claim_req = create_header(MSG_TYPE_CLAIM_REQ, seq_num, len(payload)) + payload
        client_socket.sendto(claim_req, (SERVER_IP, SERVER_PORT))
        print(f"[CLAIM] Sent CLAIM_REQUEST for ({row},{col})")
        seq_num += 1

        try:
            while True:
                data, addr = client_socket.recvfrom(2048)
                recv_time_ms = int(time.time() * 1000)
                header = parse_header(data)

                if header["msg_type"] == MSG_TYPE_BOARD_SNAPSHOT:
                    snapshot_id = header.get("seq_num", 0)
                    server_ts_ms = recv_time_ms

                    print(f"{player_id or 0} {snapshot_id} {seq_num} {server_ts_ms} {recv_time_ms} 0.0 0.0 0.0")
                    print(f"[SNAPSHOT] Player {player_id} received SnapshotID={snapshot_id}")
                    break

        except socket.timeout:
            continue

    # Leave Phase
    leave_msg = create_header(MSG_TYPE_LEAVE, seq_num, 0)
    client_socket.sendto(leave_msg, (SERVER_IP, SERVER_PORT))
    print("[INFO] Sent LEAVE message.")
    client_socket.close()
    print("[INFO] Client closed.")


# Run with GUI by default
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--no-gui":
        original_main()
    else:
        client = GameClient()
        client.start()