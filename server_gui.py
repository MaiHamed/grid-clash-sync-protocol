# server_gui.py - Server GUI that displays the grid and controls
import tkinter as tk
from tkinter import ttk, scrolledtext
import queue
import time
import threading
from server import GameServer  # Import your existing server class

class ServerGUI:
    def __init__(self, server_ip="127.0.0.1", server_port=5005):
        self.root = tk.Tk()
        self.root.title("Grid Game Server")
        self.root.geometry("1200x800")
        
        # Server instance
        self.server = GameServer(server_ip, server_port)
        self.server_running = False
        
        # Grid data
        self.grid_state = [[0]*20 for _ in range(20)]
        self.rows = 20
        self.cols = 20
        self.cell_size = 20
        
        # Message queue for thread-safe updates
        self.message_queue = queue.Queue()
        
        # Setup UI
        self.setup_ui()
        
        # Start queue processing
        self.root.after(100, self.process_queue)
        
        # Start periodic update of server data
        self.root.after(1000, self.update_from_server)
    
    def setup_ui(self):
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=3)  # Game board
        main_frame.columnconfigure(1, weight=1)  # Controls/stats
        main_frame.rowconfigure(0, weight=1)
        
        # Game board frame
        self.create_game_board(main_frame)
        
        # Right panel
        right_panel = ttk.Frame(main_frame)
        right_panel.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(10, 0))
        right_panel.columnconfigure(0, weight=1)
        
        # Control panel
        self.create_control_panel(right_panel)
        
        # Player list panel
        self.create_player_panel(right_panel)
        
        # Statistics panel
        self.create_stats_panel(right_panel)
        
        # Log panel
        self.create_log_panel(right_panel)
    
    def create_game_board(self, parent):
        board_frame = ttk.LabelFrame(parent, text="Server View - Game Grid", padding="10")
        board_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Canvas for grid
        canvas_width = self.cols * self.cell_size + 40
        canvas_height = self.rows * self.cell_size + 40
        
        self.canvas = tk.Canvas(
            board_frame,
            width=canvas_width,
            height=canvas_height,
            bg='white',
            highlightthickness=1,
            highlightbackground="#333333"
        )
        self.canvas.grid(row=0, column=0)
        
        # Draw initial grid
        self.draw_grid()
    
    def create_control_panel(self, parent):
        control_frame = ttk.LabelFrame(parent, text="Server Controls", padding="10")
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N), pady=(0, 10))
        
        # Server status
        ttk.Label(control_frame, text="Status:", width=10).grid(row=0, column=0, sticky=tk.W)
        self.server_status_var = tk.StringVar(value="Stopped")
        self.server_status_label = ttk.Label(
            control_frame,
            textvariable=self.server_status_var,
            font=("Arial", 10, "bold"),
            foreground="red"
        )
        self.server_status_label.grid(row=0, column=1, sticky=tk.W)
        
        # Connection info
        ttk.Label(control_frame, text="Address:").grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        ttk.Label(control_frame, text=f"{self.server.ip}:{self.server.port}").grid(
            row=1, column=1, sticky=tk.W, pady=(5, 0))
        
        # Control buttons
        button_frame = ttk.Frame(control_frame)
        button_frame.grid(row=2, column=0, columnspan=2, pady=(10, 0))
        
        self.start_button = ttk.Button(
            button_frame,
            text="Start Server",
            command=self.start_server,
            width=15
        )
        self.start_button.grid(row=0, column=0, padx=(0, 5))
        
        self.stop_button = ttk.Button(
            button_frame,
            text="Stop Server",
            command=self.stop_server,
            state=tk.DISABLED,
            width=15
        )
        self.stop_button.grid(row=0, column=1, padx=(5, 0))
        
        # Game controls
        game_frame = ttk.Frame(control_frame)
        game_frame.grid(row=3, column=0, columnspan=2, pady=(15, 0))
        
        self.start_game_button = ttk.Button(
            game_frame,
            text="Force Start Game",
            command=self.force_start_game,
            state=tk.DISABLED,
            width=15
        )
        self.start_game_button.grid(row=0, column=0, padx=(0, 5))
        
        self.end_game_button = ttk.Button(
            game_frame,
            text="End Game",
            command=self.end_current_game,
            state=tk.DISABLED,
            width=15
        )
        self.end_game_button.grid(row=0, column=1, padx=(5, 0))
    
    def create_player_panel(self, parent):
        player_frame = ttk.LabelFrame(parent, text="Connected Players", padding="10")
        player_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N), pady=(0, 10))
        
        # Create a Treeview for players
        columns = ('ID', 'Status', 'Address')
        self.player_tree = ttk.Treeview(player_frame, columns=columns, show='headings', height=6)
        
        # Define headings
        for col in columns:
            self.player_tree.heading(col, text=col)
            self.player_tree.column(col, width=60 if col == 'ID' else 100)
        
        # Add scrollbar
        scrollbar = ttk.Scrollbar(player_frame, orient=tk.VERTICAL, command=self.player_tree.yview)
        self.player_tree.configure(yscrollcommand=scrollbar.set)
        
        self.player_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        player_frame.columnconfigure(0, weight=1)
        player_frame.rowconfigure(0, weight=1)
    
    def create_stats_panel(self, parent):
        stats_frame = ttk.LabelFrame(parent, text="Server Statistics", padding="10")
        stats_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N), pady=(0, 10))
        
        # Statistics variables
        self.clients_var = tk.StringVar(value="0")
        self.snapshots_var = tk.StringVar(value="0")
        self.packets_sent_var = tk.StringVar(value="0")
        self.packets_received_var = tk.StringVar(value="0")
        self.game_active_var = tk.StringVar(value="No")
        
        # Layout stats
        ttk.Label(stats_frame, text="Connected Clients:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Label(stats_frame, textvariable=self.clients_var, font=("Arial", 10, "bold")).grid(
            row=0, column=1, sticky=tk.W, pady=2, padx=(10, 0))
        
        ttk.Label(stats_frame, text="Snapshots Sent:").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Label(stats_frame, textvariable=self.snapshots_var, font=("Arial", 10, "bold")).grid(
            row=1, column=1, sticky=tk.W, pady=2, padx=(10, 0))
        
        ttk.Label(stats_frame, text="Packets Sent:").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Label(stats_frame, textvariable=self.packets_sent_var, font=("Arial", 10, "bold")).grid(
            row=2, column=1, sticky=tk.W, pady=2, padx=(10, 0))
        
        ttk.Label(stats_frame, text="Packets Received:").grid(row=3, column=0, sticky=tk.W, pady=2)
        ttk.Label(stats_frame, textvariable=self.packets_received_var, font=("Arial", 10, "bold")).grid(
            row=3, column=1, sticky=tk.W, pady=2, padx=(10, 0))
        
        ttk.Label(stats_frame, text="Game Active:").grid(row=4, column=0, sticky=tk.W, pady=2)
        ttk.Label(stats_frame, textvariable=self.game_active_var, font=("Arial", 10, "bold")).grid(
            row=4, column=1, sticky=tk.W, pady=2, padx=(10, 0))
        
        # Board coverage progress bar
        ttk.Label(stats_frame, text="Board Coverage:").grid(row=5, column=0, sticky=tk.W, pady=(10, 5))
        self.coverage_progress = ttk.Progressbar(stats_frame, length=180, mode='determinate')
        self.coverage_progress.grid(row=6, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5))
        
        self.coverage_var = tk.StringVar(value="0/400 (0%)")
        ttk.Label(stats_frame, textvariable=self.coverage_var).grid(
            row=7, column=0, columnspan=2, sticky=tk.W)
    
    def create_log_panel(self, parent):
        log_frame = ttk.LabelFrame(parent, text="Server Log", padding="10")
        log_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        parent.rowconfigure(3, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            width=40,
            height=15,
            font=("Consolas", 9),
            bg='#f8f9fa'
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure text tags
        self.log_text.tag_config("timestamp", foreground="#6c757d", font=("Consolas", 8))
        self.log_text.tag_config("error", foreground="#dc3545")
        self.log_text.tag_config("success", foreground="#28a745")
        self.log_text.tag_config("info", foreground="#007bff")
        self.log_text.tag_config("warning", foreground="#ffc107")
    
    def draw_grid(self):
        """Draw the game grid"""
        self.canvas.delete("all")
        
        # Player colors (same as client)
        player_colors = {
            1: {'color': '#2196F3', 'dark': '#0D47A1'},
            2: {'color': '#4CAF50', 'dark': '#1B5E20'},
            3: {'color': '#FF9800', 'dark': '#E65100'},
            4: {'color': '#9C27B0', 'dark': '#4A148C'},
            5: {'color': '#E91E63', 'dark': '#880E4F'},
            6: {'color': '#00BCD4', 'dark': '#006064'},
            7: {'color': '#8BC34A', 'dark': '#33691E'}
        }
        
        # Draw cells
        for r in range(self.rows):
            for c in range(self.cols):
                x1 = c * self.cell_size + 20
                y1 = r * self.cell_size + 20
                x2 = x1 + self.cell_size
                y2 = y1 + self.cell_size
                
                cell_value = self.grid_state[r][c]
                
                if cell_value == 0:  # Unclaimed
                    fill_color = 'white'
                    outline_color = '#e0e0e0'
                elif 1 <= cell_value <= 7:
                    player_info = player_colors.get(cell_value, {'color': '#757575', 'dark': '#424242'})
                    fill_color = player_info['color']
                    outline_color = player_info['dark']
                else:
                    fill_color = '#757575'
                    outline_color = '#424242'
                
                # Draw cell with shadow for claimed cells
                if cell_value > 0:
                    self.canvas.create_rectangle(
                        x1 + 1, y1 + 1, x2 + 1, y2 + 1,
                        fill='#333333',
                        outline='',
                        width=0
                    )
                
                # Draw main cell
                self.canvas.create_rectangle(
                    x1, y1, x2, y2,
                    fill=fill_color,
                    outline=outline_color,
                    width=2 if cell_value > 0 else 1
                )
        
        # Draw grid lines
        for i in range(self.rows + 1):
            y = i * self.cell_size + 20
            self.canvas.create_line(20, y, self.cols * self.cell_size + 20, y, 
                                  fill='#e0e0e0', width=1)
        
        for i in range(self.cols + 1):
            x = i * self.cell_size + 20
            self.canvas.create_line(x, 20, x, self.rows * self.cell_size + 20, 
                                  fill='#e0e0e0', width=1)
        
        # Update coverage
        self.update_coverage()
    
    def update_coverage(self):
        """Update board coverage statistics"""
        claimed_count = sum(1 for row in self.grid_state for cell in row if cell > 0)
        total_cells = self.rows * self.cols
        percentage = (claimed_count / total_cells * 100) if total_cells > 0 else 0
        
        self.coverage_progress['value'] = percentage
        self.coverage_var.set(f"{claimed_count}/{total_cells} ({percentage:.1f}%)")
    
    def start_server(self):
        """Start the game server"""
        if not self.server_running:
            try:
                # Start server in background thread
                self.server.start()
                self.server_running = True
                
                self.server_status_var.set("Running")
                self.server_status_label.config(foreground="#28a745")
                self.start_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.NORMAL)
                self.start_game_button.config(state=tk.NORMAL)
                
                self.log_message("Server started successfully", "success")
                
            except Exception as e:
                self.log_message(f"Failed to start server: {e}", "error")
    
    def stop_server(self):
        """Stop the game server"""
        if self.server_running:
            try:
                self.server.stop()
                self.server_running = False
                
                self.server_status_var.set("Stopped")
                self.server_status_label.config(foreground="#dc3545")
                self.start_button.config(state=tk.NORMAL)
                self.stop_button.config(state=tk.DISABLED)
                self.start_game_button.config(state=tk.DISABLED)
                self.end_game_button.config(state=tk.DISABLED)
                
                self.log_message("Server stopped", "info")
                
            except Exception as e:
                self.log_message(f"Error stopping server: {e}", "error")
    
    def force_start_game(self):
        """Force start the game even without minimum players"""
        if self.server_running:
            if len(self.server.waiting_room_players) >= 1:  # At least 1 player
                # Move all waiting players to game
                for pid, addr in self.server.waiting_room_players.items():
                    self.server.clients[pid] = (addr, time.time())
                self.server.waiting_room_players.clear()
                self.server.game_active = True
                
                # Send game start to all clients
                for pid in self.server.clients.keys():
                    self.server._sr_send(pid, self.server.MSG_TYPE_GAME_START)
                
                self.start_game_button.config(state=tk.DISABLED)
                self.end_game_button.config(state=tk.NORMAL)
                self.game_active_var.set("Yes")
                
                self.log_message("Game started manually", "success")
            else:
                self.log_message("Need at least 1 player to start game", "warning")
    
    def end_current_game(self):
        """End the current game"""
        if self.server_running and self.server.game_active:
            self.server.end_game()
            self.end_game_button.config(state=tk.DISABLED)
            self.start_game_button.config(state=tk.NORMAL)
            self.game_active_var.set("No")
            self.log_message("Game ended", "info")
    
    def log_message(self, message, level="info"):
        """Add message to log with timestamp"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] ", "timestamp")
        self.log_text.insert(tk.END, f"{message}\n", level)
        self.log_text.see(tk.END)
    
    def update_from_server(self):
        """Periodically update GUI from server data"""
        if self.server_running:
            try:
                # Update grid
                self.grid_state = self.server.grid_state
                
                # Update statistics
                stats = self.server.stats
                self.clients_var.set(str(stats.get('client_count', 0)))
                self.snapshots_var.set(str(self.server.snapshot_id))
                self.packets_sent_var.set(str(stats.get('sent', 0)))
                self.packets_received_var.set(str(stats.get('received', 0)))
                
                # Update game status
                self.game_active_var.set("Yes" if self.server.game_active else "No")
                
                # Update player list
                self.update_player_list()
                
                # Redraw grid
                self.draw_grid()
                
            except Exception as e:
                self.log_message(f"Error updating from server: {e}", "error")
        
        # Schedule next update
        self.root.after(1000, self.update_from_server)
    
    def update_player_list(self):
        """Update the player treeview"""
        # Clear existing items
        for item in self.player_tree.get_children():
            self.player_tree.delete(item)
        
        # Add active game players
        for pid, (addr, last_seen) in self.server.clients.items():
            status = "In Game" if self.server.game_active else "Active"
            self.player_tree.insert('', 'end', values=(pid, status, f"{addr[0]}:{addr[1]}"))
        
        # Add waiting room players
        for pid, addr in self.server.waiting_room_players.items():
            self.player_tree.insert('', 'end', values=(pid, "Waiting", f"{addr[0]}:{addr[1]}"))
    
    def process_queue(self):
        """Process messages from queue"""
        # Currently not using queue heavily, but keeping for consistency
        try:
            while True:
                self.message_queue.get_nowait()
        except queue.Empty:
            pass
        
        self.root.after(100, self.process_queue)
    
    def run(self):
        """Start the GUI"""
        self.root.mainloop()
    
    def close(self):
        """Clean shutdown"""
        if self.server_running:
            self.stop_server()
        if self.root:
            self.root.quit()
            self.root.destroy()


if __name__ == "__main__":
    gui = ServerGUI()
    gui.run()