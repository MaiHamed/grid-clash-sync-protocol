# server.py - Add player status updates
import socket
import struct
import time
import select
import threading
import tkinter as tk
from protocol import (
    create_header, pack_grid_snapshot, parse_header,
    MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP,
    MSG_TYPE_CLAIM_REQ, MSG_TYPE_LEAVE, MSG_TYPE_BOARD_SNAPSHOT
)

class GameServer:
    def __init__(self, ip="127.0.0.1", port=5005):
        self.ip = ip
        self.port = port
        
        self.server_socket = None
        self.clients = {}  # {player_id: (addr, last_seen)}
        self.seq_num = 0
        self.snapshot_id = 0
        
        # Grid state: 0=unclaimed, player_id=claimed
        self.grid_state = [[0 for _ in range(20)] for _ in range(20)]
        self.running = False
        self.server_thread = None
        
        # Snapshot timing
        self.SNAPSHOT_INTERVAL = 0.033  # ~30Hz
        self.last_snapshot_time = time.time()
        
        # Statistics
        self.stats = {
            'sent': 0,
            'received': 0,
            'dropped': 0,
            'client_count': 0
        }
        
        # Import GUI
        from gui import GameGUI
        self.gui = GameGUI(title="Grid Game Server")
        self._setup_gui_callbacks()
    
    def _setup_gui_callbacks(self):
        """Setup GUI button callbacks for server"""
        self.gui.connect_button.config(text="Start Server", command=self.start)
        self.gui.disconnect_button.config(text="Stop Server", command=self.stop)
        
        # Override the GUI's callback methods
        self.gui.on_connect_click = self.start
        self.gui.on_disconnect_click = self.stop
    
    def start(self):
        """Start the server"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            self.server_socket.setblocking(0)
            self.server_socket.bind((self.ip, self.port))
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_loop)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.gui.log_message(f"Server started on {self.ip}:{self.port}", "success")
            self.gui.update_player_info("Server", True)
            
            return True
            
        except Exception as e:
            self.gui.log_message(f"Server start error: {e}", "error")
            return False
    
    def stop(self):
        """Stop the server"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
            self.server_socket = None
        
        # Clear clients
        self.clients.clear()
        
        self.gui.log_message("Server stopped", "info")
        self.gui.update_player_info("Server", False)
        self.gui.update_players(self.clients)
        self.stats['client_count'] = 0
        self.gui.update_stats(self.stats)
    
    def _server_loop(self):
        """Main server loop"""
        while self.running:
            try:
                ready = select.select([self.server_socket], [], [], 0.1)
                
                if ready[0]:
                    try:
                        data, addr = self.server_socket.recvfrom(1024)
                        if len(data) < 22:
                            continue
                        
                        self._handle_message(data, addr)
                        
                    except BlockingIOError:
                        pass
                    except Exception as e:
                        self.gui.log_message(f"Receive error: {e}", "error")
                
                # Send periodic snapshots
                current_time = time.time()
                if self.clients and current_time - self.last_snapshot_time >= self.SNAPSHOT_INTERVAL:
                    self._send_snapshot()
                    self.last_snapshot_time = current_time
                    
            except Exception as e:
                if self.running:
                    self.gui.log_message(f"Server loop error: {e}", "error")
                time.sleep(0.1)
    
    def _handle_message(self, data, addr):
        """Handle incoming message"""
        try:
            header = parse_header(data)
            msg_type = header["msg_type"]
            seq_num = header.get("seq_num", 0)
            
            self.stats['received'] += 1
            
            if msg_type == MSG_TYPE_JOIN_REQ:
                # Assign new player ID
                new_player_id = 1
                while new_player_id in self.clients:
                    new_player_id += 1
                
                self.clients[new_player_id] = (addr, time.time())
                self.stats['client_count'] = len(self.clients)
                
                self.gui.log_message(f"Player {new_player_id} joined from {addr}", "success")
                
                # Send join response with player list
                active_players = list(self.clients.keys())
                payload = struct.pack("!B", new_player_id)
                resp = create_header(MSG_TYPE_JOIN_RESP, self.seq_num, len(payload)) + payload
                self.server_socket.sendto(resp, addr)
                self.seq_num += 1
                self.stats['sent'] += 1
                
                # Update GUI
                self.gui.update_players(self.clients)
                self.gui.update_stats(self.stats)
            
            elif msg_type == MSG_TYPE_CLAIM_REQ:
                # Find player ID
                player_id = None
                for pid, (client_addr, _) in self.clients.items():
                    if client_addr == addr:
                        player_id = pid
                        break
                
                if player_id:
                    payload = data[22:]
                    if len(payload) >= 2:
                        row, col = struct.unpack("!BB", payload[:2])
                        if 0 <= row < 20 and 0 <= col < 20 and self.grid_state[row][col] == 0:
                            self.grid_state[row][col] = player_id
                            self.gui.log_message(f"Cell ({row},{col}) claimed by Player {player_id}", "info")
                            self.gui.update_grid(self.grid_state)
                
                if player_id in self.clients:
                    self.clients[player_id] = (addr, time.time())
            
            elif msg_type == MSG_TYPE_LEAVE:
                # Remove client
                to_remove = []
                for pid, (client_addr, _) in self.clients.items():
                    if client_addr == addr:
                        to_remove.append(pid)
                
                for pid in to_remove:
                    del self.clients[pid]
                    self.gui.log_message(f"Player {pid} left", "info")
                
                self.stats['client_count'] = len(self.clients)
                self.gui.update_players(self.clients)
                self.gui.update_stats(self.stats)
            
            # Update stats in GUI
            self.gui.update_stats(self.stats)
            
        except Exception as e:
            self.gui.log_message(f"Message handling error: {e}", "error")
    
    def _send_snapshot(self):
        """Send snapshot to all clients"""
        try:
            # Send ACTUAL player IDs
            compatible_grid = [[0 for _ in range(20)] for _ in range(20)]
            for r in range(20):
                for c in range(20):
                    compatible_grid[r][c] = self.grid_state[r][c]
            
            snapshot_bytes = pack_grid_snapshot(compatible_grid)
            payload_len = len(snapshot_bytes)
            
            # Send to all active clients
            sent_count = 0
            for pid, (addr, last_seen) in list(self.clients.items()):
                try:
                    msg = create_header(MSG_TYPE_BOARD_SNAPSHOT, self.seq_num, payload_len, self.snapshot_id) + snapshot_bytes
                    self.server_socket.sendto(msg, addr)
                    sent_count += 1
                    
                    # Update last seen time
                    self.clients[pid] = (addr, time.time())
                    
                    # Log for testing
                    server_ts_ms = int(time.time() * 1000)
                    print(f"LOG {pid} {self.snapshot_id} {self.seq_num} {server_ts_ms} {server_ts_ms} 0.0 0.0 0.0")
                    
                except Exception as e:
                    self.gui.log_message(f"Failed to send to player {pid}: {e}", "error")
            
            if sent_count > 0:
                self.stats['sent'] += sent_count
                self.snapshot_id += 1
                self.seq_num += 1
                
                # Update GUI
                self.gui.update_snapshot(self.snapshot_id)
                self.gui.update_stats(self.stats)
                
                if self.snapshot_id % 10 == 0:
                    self.gui.log_message(f"Snapshot {self.snapshot_id} sent to {sent_count} client(s)", "info")
        
        except Exception as e:
            self.gui.log_message(f"Snapshot error: {e}", "error")
    
    def start_gui(self):
        """Start the GUI"""
        self.gui.run()


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