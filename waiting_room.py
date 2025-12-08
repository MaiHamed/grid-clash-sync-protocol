# waiting_room.py
import tkinter as tk
from tkinter import ttk, messagebox
import socket
import struct
import threading
import time

# You'll need to import from your protocol module
# For now, let me define the minimal protocol functions needed
def create_header(msg_type, seq_num, payload_len, snapshot_id=0):
    import struct
    import time
    PROTOCOL_ID = b'GSSP'
    VERSION = 1
    HEADER_FORMAT = "!4s B B H H I Q"
    timestamp = int(time.time() * 1000)
    return struct.pack(HEADER_FORMAT, PROTOCOL_ID, VERSION, msg_type, 
                      22 + payload_len, snapshot_id, seq_num, timestamp)

def parse_header(data):
    import struct
    HEADER_FORMAT = "!4s B B H H I Q"
    HEADER_SIZE = 22
    protocol_id, version, msg_type, length, snapshot_id, seq_num, timestamp = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    return {
        'protocol_id': protocol_id.decode(),
        'version': version,
        'msg_type': msg_type,
        'length': length,
        'snapshot_id': snapshot_id,
        'seq_num': seq_num,
        'timestamp': timestamp
    }

# Message types
MSG_TYPE_JOIN_REQ = 0
MSG_TYPE_JOIN_RESP = 1
MSG_TYPE_CLAIM_REQ = 2
MSG_TYPE_BOARD_SNAPSHOT = 3
MSG_TYPE_GAME_OVER = 4
MSG_TYPE_LEAVE = 5
MSG_TYPE_GAME_START = 6
MSG_TYPE_WAITING_ROOM = 8

class WaitingRoom:
    def __init__(self, server_ip="127.0.0.1", server_port=5005):
        self.server_ip = server_ip
        self.server_port = server_port
        self.root = tk.Tk()
        self.root.title("Grid Game - Waiting Room")
        self.root.geometry("500x450")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Connection
        self.client_socket = None
        self.player_id = None
        self.running = False
        self.receive_thread = None
        
        # Waiting room state
        self.players = {}  # player_id: status
        self.waiting_timer = 60
        self.timer_running = False
        self.min_players = 2
        self.game_started = False
        
        # UI setup
        self.setup_ui()
        
        # Connect to server
        self.connect()
        
        # Start UI updates
        self.update_ui_loop()
    
    def setup_ui(self):
        # Configure grid
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        # Main frame
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title = ttk.Label(main_frame, text="🎮 Grid Game Waiting Room", 
                         font=("Arial", 18, "bold"))
        title.grid(row=0, column=0, pady=(0, 20))
        
        # Status
        self.status_label = ttk.Label(main_frame, text="Connecting...", 
                                     font=("Arial", 11))
        self.status_label.grid(row=1, column=0, sticky=tk.W, pady=(0, 10))
        
        # Player ID
        self.player_id_label = ttk.Label(main_frame, text="Player ID: --", 
                                        font=("Arial", 11, "bold"))
        self.player_id_label.grid(row=2, column=0, sticky=tk.W, pady=(0, 20))
        
        # Players list
        players_frame = ttk.LabelFrame(main_frame, text="Players in Room", padding="10")
        players_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 20))
        
        self.players_text = tk.Text(players_frame, height=6, width=50, 
                                   font=("Consolas", 10), bg='#f8f9fa')
        self.players_text.grid(row=0, column=0)
        self.players_text.insert(tk.END, "No players yet...\n")
        self.players_text.config(state='disabled')
        
        # Timer
        timer_frame = ttk.LabelFrame(main_frame, text="Game Start", padding="10")
        timer_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 20))
        
        self.timer_label = ttk.Label(timer_frame, text="Waiting for players...", 
                                    font=("Arial", 12))
        self.timer_label.grid(row=0, column=0, sticky=tk.W)
        
        self.progress = ttk.Progressbar(timer_frame, length=300, mode='determinate', maximum=60)
        self.progress.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(10, 0))
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, pady=(0, 10))
        
        self.start_button = ttk.Button(button_frame, text="Start Game Now", 
                                      command=self.start_game, state='disabled', width=15)
        self.start_button.grid(row=0, column=0, padx=(0, 10))
        
        ttk.Button(button_frame, text="Leave", command=self.leave, width=15).grid(row=0, column=1)
        
        # Instructions
        ttk.Label(main_frame, text="Need at least 2 players to start", 
                 foreground="gray", font=("Arial", 9)).grid(row=6, column=0, pady=(10, 0))
    
    def connect(self):
        """Connect to server"""
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.client_socket.settimeout(1.0)
            
            # Send join request
            join_req = create_header(MSG_TYPE_JOIN_REQ, 0, 0)
            self.client_socket.sendto(join_req, (self.server_ip, self.server_port))
            
            # Start receive thread
            self.running = True
            self.receive_thread = threading.Thread(target=self.receive_loop)
            self.receive_thread.daemon = True
            self.receive_thread.start()
            
            self.status_label.config(text=f"Connected to {self.server_ip}:{self.server_port}")
            
        except Exception as e:
            self.status_label.config(text=f"Connection error: {e}")
    
    def receive_loop(self):
        """Receive messages from server"""
        while self.running and self.client_socket:
            try:
                data, addr = self.client_socket.recvfrom(1024)
                
                if len(data) < 22:
                    continue
                    
                header = parse_header(data)
                
                if header["msg_type"] == MSG_TYPE_JOIN_RESP and self.player_id is None:
                    if len(data) >= 23:
                        self.player_id = struct.unpack("!B", data[22:23])[0]
                        self.players[self.player_id] = "Ready"
                        self.update_players_display()
                        
                        # Update UI in main thread
                        self.root.after(0, lambda: self.player_id_label.config(
                            text=f"Player ID: {self.player_id}"
                        ))
                
                elif header["msg_type"] == MSG_TYPE_GAME_START:
                    # Game is starting!
                    self.game_started = True
                    self.root.after(0, self.launch_game)
                    break
                
                # Here you would handle player list updates from server
                # For simplicity, we'll simulate it
                
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"Receive error: {e}")
    
    def update_players_display(self):
        """Update players list"""
        if not self.player_id:
            return
            
        # Simulate other players joining (remove in final version)
        if len(self.players) < 4:
            # Add a simulated player
            for pid in range(1, 5):
                if pid not in self.players:
                    self.players[pid] = "Ready"
                    break
        
        # Update text widget
        self.players_text.config(state='normal')
        self.players_text.delete(1.0, tk.END)
        
        for pid in sorted(self.players.keys()):
            status = self.players[pid]
            self.players_text.insert(tk.END, f"Player {pid}: {status}\n")
        
        self.players_text.config(state='disabled')
        
        # Update timer
        player_count = len(self.players)
        if player_count >= self.min_players and not self.timer_running:
            self.start_countdown()
    
    def start_countdown(self):
        """Start countdown timer"""
        if not self.timer_running:
            self.timer_running = True
            self.start_button.config(state='normal')
            self.update_timer()
    
    def update_timer(self):
        """Update timer display"""
        if not self.timer_running or self.game_started:
            return
        
        player_count = len(self.players)
        
        if player_count < self.min_players:
            self.timer_label.config(text=f"Need {self.min_players - player_count} more player(s)")
            self.progress['value'] = 0
        else:
            minutes = self.waiting_timer // 60
            seconds = self.waiting_timer % 60
            self.timer_label.config(text=f"Game starts in: {minutes:02d}:{seconds:02d}")
            self.progress['value'] = 60 - self.waiting_timer
            
            if self.waiting_timer <= 0:
                self.start_game()
                return
            
            if player_count >= self.min_players:
                self.waiting_timer -= 1
        
        # Schedule next update
        self.root.after(1000, self.update_timer)
    
    def start_game(self):
        """Start the game"""
        if len(self.players) < self.min_players:
            self.timer_label.config(text=f"Need {self.min_players - len(self.players)} more player(s)")
            return
        
        self.game_started = True
        self.timer_label.config(text="Starting game...")
        self.start_button.config(state='disabled')
        
        # Launch game client
        self.root.after(2000, self.launch_game)
    
    def launch_game(self):
        """Launch the game client"""
        self.running = False
        self.root.destroy()
        
        # Import and start game client
        try:
            import client
            game_client = client.GameClient(self.server_ip, self.server_port)
            
            # Pass our socket and player ID to the client
            game_client.client_socket = self.client_socket
            game_client.player_id = self.player_id
            game_client.running = True
            
            # The client will handle the rest
            game_client.start()
        except Exception as e:
            print(f"Failed to launch game: {e}")
            messagebox.showerror("Error", f"Failed to start game: {e}")
    
    def leave(self):
        """Leave waiting room"""
        self.running = False
        
        if self.client_socket:
            # Send leave message
            leave_msg = create_header(MSG_TYPE_LEAVE, 0, 0)
            try:
                self.client_socket.sendto(leave_msg, (self.server_ip, self.server_port))
            except:
                pass
            self.client_socket.close()
        
        self.root.quit()
    
    def on_closing(self):
        """Handle window close"""
        self.leave()
        self.root.destroy()
    
    def update_ui_loop(self):
        """Periodic UI updates"""
        # Update players display periodically
        self.update_players_display()
        
        # Schedule next update
        self.root.after(2000, self.update_ui_loop)
    
    def run(self):
        """Start the waiting room"""
        self.root.mainloop()


if __name__ == "__main__":
    waiting_room = WaitingRoom()
    waiting_room.run()