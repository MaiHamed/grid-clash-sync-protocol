# gui.py - Fixed version with proper initialization order
import tkinter as tk
from tkinter import ttk, scrolledtext
import queue
import time

class GameGUI:
    def __init__(self, title="Grid Game", rows=20, cols=20, cell_size=25):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("1400x900")
        
        self.rows = rows
        self.cols = cols
        self.cell_size = cell_size
        
        # Data from network
        self.grid_state = [[0 for _ in range(cols)] for _ in range(rows)]
        self.players = {}
        self.snapshot_id = 0
        self.packet_stats = {
            'sent': 0,
            'received': 0,
            'dropped': 0,
            'latency_sum': 0,
            'latency_count': 0
        }
        
        # Message queue for thread-safe GUI updates
        self.message_queue = queue.Queue()
        
        # Click handler callback (set by client)
        self.cell_click_handler = None
        
        # Initialize UI widgets to None first
        self.progress = None
        self.coverage_var = None
        self.snapshot_var = None
        self.players_var = None
        self.sent_var = None
        self.received_var = None
        self.latency_var = None
        self.player_id_var = None
        self.status_var = None
        self.status_label = None
        self.connect_button = None
        self.disconnect_button = None
        self.claim_button = None
        self.auto_claim_var = None
        self.auto_check = None
        self.log_text = None
        
        # Player status labels
        self.player_1_status = None
        self.player_2_status = None
        self.player_3_status = None
        self.player_4_status = None
        
        # Setup UI
        self.setup_ui()
        
        # Start queue processing
        self.root.after(100, self.process_queue)
    
    def setup_ui(self):
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        # Create main frames
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure main frame grid
        main_frame.columnconfigure(0, weight=3)  # Game board
        main_frame.columnconfigure(1, weight=1)  # Controls
        main_frame.rowconfigure(0, weight=1)
        
        # Game Board Canvas
        self.create_game_board(main_frame)
        
        # Right panel with controls and info
        right_panel = ttk.Frame(main_frame)
        right_panel.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(10, 0))
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(0, weight=0)  # Control panel
        right_panel.rowconfigure(1, weight=0)  # Player info
        right_panel.rowconfigure(2, weight=1)  # Statistics
        right_panel.rowconfigure(3, weight=2)  # Log
        
        # Control Panel
        self.create_control_panel(right_panel)
        
        # Player Info Panel
        self.create_player_info_panel(right_panel)
        
        # Statistics Panel
        self.create_statistics_panel(right_panel)
        
        # Log Panel
        self.create_log_panel(right_panel)
    
    def create_game_board(self, parent):
        board_frame = ttk.LabelFrame(parent, text="Game Board - Click on cells to claim!", padding="10")
        board_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Calculate canvas size
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
        
        # Bind click event
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        
        # Draw initial grid
        self.draw_grid()
    
    def create_control_panel(self, parent):
        control_frame = ttk.LabelFrame(parent, text="Connection Controls", padding="10")
        control_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N), pady=(0, 10))
        
        # Connection status
        status_frame = ttk.Frame(control_frame)
        status_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        ttk.Label(status_frame, text="Status:", width=10).grid(row=0, column=0, sticky=tk.W)
        self.status_var = tk.StringVar(value="Disconnected")
        self.status_label = ttk.Label(
            status_frame, 
            textvariable=self.status_var,
            font=("Arial", 10, "bold"), 
            foreground="red"
        )
        self.status_label.grid(row=0, column=1, sticky=tk.W)
        
        # Player ID
        ttk.Label(status_frame, text="Player ID:", width=10).grid(row=1, column=0, sticky=tk.W, pady=(5, 0))
        self.player_id_var = tk.StringVar(value="Not Connected")
        self.player_id_label = ttk.Label(
            status_frame, 
            textvariable=self.player_id_var, 
            font=("Arial", 10, "bold")
        )
        self.player_id_label.grid(row=1, column=1, sticky=tk.W, pady=(5, 0))
        
        # Control buttons
        button_frame = ttk.Frame(control_frame)
        button_frame.grid(row=1, column=0, columnspan=2, pady=(10, 0))
        
        self.connect_button = ttk.Button(
            button_frame, 
            text="Connect",
            command=self.on_connect_click,
            width=15
        )
        self.connect_button.grid(row=0, column=0, padx=(0, 5))
        
        self.disconnect_button = ttk.Button(
            button_frame,
            text="Disconnect",
            command=self.on_disconnect_click,
            state=tk.DISABLED,
            width=15
        )
        self.disconnect_button.grid(row=0, column=1, padx=(5, 0))
        
        # Auto-claim toggle
        self.auto_claim_var = tk.BooleanVar(value=False)
        self.auto_check = ttk.Checkbutton(
            control_frame,
            text="Auto-claim random cells",
            variable=self.auto_claim_var,
            command=self.on_auto_claim_toggle
        )
        self.auto_check.grid(row=2, column=0, columnspan=2, pady=(10, 0), sticky=tk.W)
        
        # Instructions
        instructions = ttk.Label(
            control_frame,
            text="Tip: Click on the game board to claim cells!",
            foreground="gray",
            font=("Arial", 9)
        )
        instructions.grid(row=3, column=0, columnspan=2, pady=(10, 0), sticky=tk.W)
    
    def create_player_info_panel(self, parent):
        player_frame = ttk.LabelFrame(parent, text="Players", padding="10")
        player_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N), pady=(0, 10))
        
        # Player colors for up to 4 players
        self.player_colors = {
            1: {'name': 'Player 1', 'color': '#2196F3', 'dark': '#0D47A1'},
            2: {'name': 'Player 2', 'color': '#4CAF50', 'dark': '#1B5E20'},
            3: {'name': 'Player 3', 'color': '#FF9800', 'dark': '#E65100'},
            4: {'name': 'Player 4', 'color': '#9C27B0', 'dark': '#4A148C'},
        }
        
        # Create color indicators
        for i in range(1, 5):
            color_frame = ttk.Frame(player_frame)
            color_frame.grid(row=i-1, column=0, sticky=tk.W, pady=2)
            
            # Color box
            color_canvas = tk.Canvas(color_frame, width=20, height=20, highlightthickness=0)
            color_canvas.grid(row=0, column=0, padx=(0, 5))
            color_canvas.create_rectangle(2, 2, 18, 18, 
                                        fill=self.player_colors[i]['color'],
                                        outline=self.player_colors[i]['dark'],
                                        width=2)
            
            # Player label
            ttk.Label(color_frame, text=self.player_colors[i]['name']).grid(row=0, column=1, sticky=tk.W)
            
            # Status label
            status_label = ttk.Label(color_frame, text="Offline", foreground="gray")
            status_label.grid(row=0, column=2, padx=(10, 0), sticky=tk.W)
            
            # Store status label
            if i == 1:
                self.player_1_status = status_label
            elif i == 2:
                self.player_2_status = status_label
            elif i == 3:
                self.player_3_status = status_label
            elif i == 4:
                self.player_4_status = status_label
    
    def create_statistics_panel(self, parent):
        stats_frame = ttk.LabelFrame(parent, text="Statistics", padding="10")
        stats_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        parent.rowconfigure(2, weight=1)
        
        # Use a grid layout for better organization
        stats_grid = ttk.Frame(stats_frame)
        stats_grid.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Snapshot info
        ttk.Label(stats_grid, text="Snapshot ID:", font=("Arial", 9)).grid(
            row=0, column=0, sticky=tk.W, pady=3)
        self.snapshot_var = tk.StringVar(value="0")
        ttk.Label(stats_grid, textvariable=self.snapshot_var, 
                 font=("Arial", 9, "bold")).grid(row=0, column=1, sticky=tk.W, pady=3, padx=(10, 0))
        
        # Active players
        ttk.Label(stats_grid, text="Active Players:", font=("Arial", 9)).grid(
            row=1, column=0, sticky=tk.W, pady=3)
        self.players_var = tk.StringVar(value="0")
        ttk.Label(stats_grid, textvariable=self.players_var, 
                font=("Arial", 9, "bold")).grid(row=1, column=1, sticky=tk.W, pady=3, padx=(10, 0))
        
        # Separator
        ttk.Separator(stats_grid, orient='horizontal').grid(
            row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        
        # Packet statistics
        ttk.Label(stats_grid, text="Packets Sent:", font=("Arial", 9)).grid(
            row=3, column=0, sticky=tk.W, pady=3)
        self.sent_var = tk.StringVar(value="0")
        ttk.Label(stats_grid, textvariable=self.sent_var, font=("Arial", 9)).grid(
            row=3, column=1, sticky=tk.W, pady=3, padx=(10, 0))
        
        ttk.Label(stats_grid, text="Packets Received:", font=("Arial", 9)).grid(
            row=4, column=0, sticky=tk.W, pady=3)
        self.received_var = tk.StringVar(value="0")
        ttk.Label(stats_grid, textvariable=self.received_var, font=("Arial", 9)).grid(
            row=4, column=1, sticky=tk.W, pady=3, padx=(10, 0))
        
        ttk.Label(stats_grid, text="Avg Latency:", font=("Arial", 9)).grid(
            row=5, column=0, sticky=tk.W, pady=3)
        self.latency_var = tk.StringVar(value="0 ms")
        ttk.Label(stats_grid, textvariable=self.latency_var, font=("Arial", 9)).grid(
            row=5, column=1, sticky=tk.W, pady=3, padx=(10, 0))
        
        # Separator
        ttk.Separator(stats_grid, orient='horizontal').grid(
            row=6, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        
        # Board coverage
        ttk.Label(stats_grid, text="Board Coverage:", font=("Arial", 9)).grid(
            row=7, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
        
        self.progress = ttk.Progressbar(stats_grid, length=180, mode='determinate')
        self.progress.grid(row=8, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5))
        
        self.coverage_var = tk.StringVar(value="0/400 (0%)")
        ttk.Label(stats_grid, textvariable=self.coverage_var, 
                 font=("Arial", 9)).grid(row=9, column=0, columnspan=2, sticky=tk.W)
    
    def create_log_panel(self, parent):
        log_frame = ttk.LabelFrame(parent, text="Event Log", padding="10")
        log_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        parent.rowconfigure(3, weight=2)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        
        # Create scrolled text widget with better styling
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            width=45,
            height=12,
            font=("Consolas", 9),
            bg='#f8f9fa',
            relief='flat'
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure text tags with better colors
        self.log_text.tag_config("timestamp", foreground="#6c757d", font=("Consolas", 8))
        self.log_text.tag_config("error", foreground="#dc3545")
        self.log_text.tag_config("success", foreground="#28a745")
        self.log_text.tag_config("info", foreground="#007bff")
        self.log_text.tag_config("warning", foreground="#ffc107")
        self.log_text.tag_config("claim", foreground="#6610f2")
        self.log_text.tag_config("join", foreground="#20c997")
        self.log_text.tag_config("leave", foreground="#fd7e14")
    
    def on_canvas_click(self, event):
        """Handle click on game board"""
        if not self.cell_click_handler:
            return
            
        # Calculate which cell was clicked
        x = event.x - 20
        y = event.y - 20
        
        if x < 0 or y < 0:
            return
            
        col = x // self.cell_size
        row = y // self.cell_size
        
        if 0 <= row < self.rows and 0 <= col < self.cols:
            self.cell_click_handler(row, col)
    
    def draw_grid(self):
        """Draw the game grid with player colors"""
        # Clear existing grid
        self.canvas.delete("all")
        
        # Draw cells
        for r in range(self.rows):
            for c in range(self.cols):
                x1 = c * self.cell_size + 20
                y1 = r * self.cell_size + 20
                x2 = x1 + self.cell_size
                y2 = y1 + self.cell_size
                
                # Determine cell color based on player who claimed it
                cell_value = self.grid_state[r][c]
                
                if cell_value == 0:  # Unclaimed
                    fill_color = 'white'
                    outline_color = '#e0e0e0'
                elif 1 <= cell_value <= 4:
                    player_info = self.player_colors.get(cell_value, 
                                                       {'color': '#757575', 'dark': '#424242'})
                    fill_color = player_info['color']
                    outline_color = player_info['dark']
                elif cell_value == 255:  # Your pending claim
                    fill_color = '#FFEB3B'
                    outline_color = '#FBC02D'
                else:
                    fill_color = '#757575'
                    outline_color = '#424242'
                
                # Draw cell with shadow effect for claimed cells
                if cell_value > 0:
                    self.canvas.create_rectangle(
                        x1 + 1, y1 + 1, x2 + 1, y2 + 1,
                        fill='#333333',
                        outline='',
                        width=0
                    )
                
                # Draw main cell
                cell_id = self.canvas.create_rectangle(
                    x1, y1, x2, y2,
                    fill=fill_color,
                    outline=outline_color,
                    width=2 if cell_value > 0 else 1
                )
                
                # Store cell ID for hover effects
                self.canvas.tag_bind(cell_id, "<Enter>", 
                                   lambda e, r=r, c=c: self.on_cell_enter(r, c))
                self.canvas.tag_bind(cell_id, "<Leave>", 
                                   lambda e: self.on_cell_leave())
        
        # Draw grid lines
        for i in range(self.rows + 1):
            y = i * self.cell_size + 20
            self.canvas.create_line(20, y, self.cols * self.cell_size + 20, y, 
                                  fill='#e0e0e0', width=1)
        
        for i in range(self.cols + 1):
            x = i * self.cell_size + 20
            self.canvas.create_line(x, 20, x, self.rows * self.cell_size + 20, 
                                  fill='#e0e0e0', width=1)
        
        # Update coverage info only if progress bar exists
        if hasattr(self, 'progress') and self.progress:
            claimed_count = sum(1 for row in self.grid_state for cell in row if 1 <= cell <= 4)
            total_cells = self.rows * self.cols
            percentage = (claimed_count / total_cells * 100) if total_cells > 0 else 0
            
            self.progress['value'] = percentage
            if hasattr(self, 'coverage_var') and self.coverage_var:
                self.coverage_var.set(f"{claimed_count}/{total_cells} ({percentage:.1f}%)")
        
        # Add title
        self.canvas.create_text(
            20, 10,
            text="Grid Clash - Claim cells by clicking!",
            anchor=tk.W,
            font=("Arial", 11, "bold"),
            fill='#333333'
        )
    
    def on_cell_enter(self, row, col):
        """Handle mouse entering a cell"""
        cell_value = self.grid_state[row][col]
        if cell_value == 0:
            self.canvas.config(cursor="hand2")
        else:
            self.canvas.config(cursor="arrow")
    
    def on_cell_leave(self):
        """Handle mouse leaving a cell"""
        self.canvas.config(cursor="")
    
    def update_player_status(self, players):
        """Update player status indicators"""
        player_status_widgets = {
            1: self.player_1_status,
            2: self.player_2_status,
            3: self.player_3_status,
            4: self.player_4_status
        }
        
        for player_id, status_widget in player_status_widgets.items():
            if status_widget:
                if player_id in players:
                    status_widget.config(text="Online", foreground="#28a745")
                else:
                    status_widget.config(text="Offline", foreground="#6c757d")
    
    # Thread-safe update methods
    def log_message(self, message, level="info"):
        self.message_queue.put(("log", message, level))
    
    def update_grid(self, grid_data):
        self.message_queue.put(("grid", grid_data))
    
    def update_stats(self, stats):
        self.message_queue.put(("stats", stats))
    
    def update_players(self, players):
        self.message_queue.put(("players", players))
    
    def update_player_info(self, player_id, connected=True):
        self.message_queue.put(("player_info", player_id, connected))
    
    def update_snapshot(self, snapshot_id):
        self.message_queue.put(("snapshot", snapshot_id))
    
    def highlight_cell(self, row, col):
        self.message_queue.put(("highlight", row, col))
    
    def process_queue(self):
        """Process messages from queue in main thread"""
        try:
            while True:
                item = self.message_queue.get_nowait()
                msg_type = item[0]
                
                if msg_type == "log":
                    _, message, level = item
                    self._add_log_message(message, level)
                
                elif msg_type == "grid":
                    _, grid_data = item
                    self._update_grid_display(grid_data)
                
                elif msg_type == "stats":
                    _, stats = item
                    self._update_stats_display(stats)
                
                elif msg_type == "players":
                    _, players = item
                    self._update_players_display(players)
                
                elif msg_type == "player_info":
                    _, player_id, connected = item
                    self._update_player_info_display(player_id, connected)
                
                elif msg_type == "snapshot":
                    _, snapshot_id = item
                    self._update_snapshot_display(snapshot_id)
                
                elif msg_type == "highlight":
                    _, row, col = item
                    self._highlight_cell_display(row, col)
                
        except queue.Empty:
            pass
        
        self.root.after(100, self.process_queue)
    
    def _add_log_message(self, message, level):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] ", "timestamp")
        
        if "error" in message.lower():
            level = "error"
        elif "success" in message.lower():
            level = "success"
        elif "claim" in message.lower():
            level = "claim"
        elif "join" in message.lower():
            level = "join"
        elif "leave" in message.lower():
            level = "leave"
        elif "warning" in message.lower():
            level = "warning"
        
        self.log_text.insert(tk.END, f"{message}\n", level)
        self.log_text.see(tk.END)
    
    def _update_grid_display(self, grid_data):
        self.grid_state = grid_data
        self.draw_grid()
    
    def _update_stats_display(self, stats):
        self.packet_stats = stats
        if hasattr(self, 'sent_var') and self.sent_var:
            self.sent_var.set(str(stats.get('sent', 0)))
        if hasattr(self, 'received_var') and self.received_var:
            self.received_var.set(str(stats.get('received', 0)))
        
        latency_count = stats.get('latency_count', 0)
        if latency_count > 0 and hasattr(self, 'latency_var') and self.latency_var:
            avg_latency = stats.get('latency_sum', 0) / latency_count
            self.latency_var.set(f"{avg_latency:.1f} ms")
        elif hasattr(self, 'latency_var') and self.latency_var:
            self.latency_var.set("0 ms")
    
    def _update_players_display(self, players):
        self.players = players
        if hasattr(self, 'players_var') and self.players_var:
            self.players_var.set(str(len(players)))
        self.update_player_status(players)
    
    def _update_player_info_display(self, player_id, connected=True):
        if connected:
            if player_id == "Server":
                self.player_id_var.set("Server")
                self.status_var.set("Running")
                self.status_label.config(foreground="#28a745")
                self.connect_button.config(state=tk.DISABLED, text="Server Running")
                self.disconnect_button.config(state=tk.NORMAL, text="Stop Server")
            else:
                self.player_id_var.set(f"Player {player_id}")
                self.status_var.set("Connected")
                self.status_label.config(foreground="#28a745")
                self.connect_button.config(state=tk.DISABLED)
                self.disconnect_button.config(state=tk.NORMAL)
        else:
            if player_id == "Server":
                self.player_id_var.set("Server")
                self.status_var.set("Stopped")
                self.status_label.config(foreground="#dc3545")
                self.connect_button.config(state=tk.NORMAL, text="Start Server")
                self.disconnect_button.config(state=tk.DISABLED, text="Stop Server")
            else:
                self.player_id_var.set("Not Connected")
                self.status_var.set("Disconnected")
                self.status_label.config(foreground="#dc3545")
                self.connect_button.config(state=tk.NORMAL)
                self.disconnect_button.config(state=tk.DISABLED)
    
    def _update_snapshot_display(self, snapshot_id):
        self.snapshot_id = snapshot_id
        if hasattr(self, 'snapshot_var') and self.snapshot_var:
            self.snapshot_var.set(str(snapshot_id))
    
    def _highlight_cell_display(self, row, col):
        if 0 <= row < self.rows and 0 <= col < self.cols:
            original = self.grid_state[row][col]
            self.grid_state[row][col] = 255
            self.draw_grid()
            self.root.after(300, lambda: self._restore_cell(row, col, original))
    
    def _restore_cell(self, row, col, original_value):
        if 0 <= row < self.rows and 0 <= col < self.cols:
            self.grid_state[row][col] = original_value
            self.draw_grid()
    
    def set_cell_click_handler(self, handler):
        self.cell_click_handler = handler
    
    def on_connect_click(self):
        self.log_message("Connect button clicked", "info")
    
    def on_disconnect_click(self):
        self.log_message("Disconnect button clicked", "info")
    
    def on_claim_click(self):
        self.log_message("Claim button clicked", "info")
    
    def on_auto_claim_toggle(self):
        if self.auto_claim_var.get():
            self.log_message("Auto-claim enabled", "info")
        else:
            self.log_message("Auto-claim disabled", "info")
    
    def run(self):
        self.root.mainloop()
    
    def close(self):
        if self.root:
            self.root.quit()
            self.root.destroy()

if __name__ == "__main__":
    app = GameGUI()
    app.run()