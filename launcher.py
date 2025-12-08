# launcher.py - Updated to use waiting room
import tkinter as tk
from tkinter import ttk
import subprocess
import sys
import threading

class Launcher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Grid Game Launcher")
        self.root.geometry("500x400")
        
        self.server_process = None
        self.setup_ui()
    
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title = ttk.Label(main_frame, text="🎮 Grid Game Network", font=("Arial", 18, "bold"))
        title.grid(row=0, column=0, pady=(0, 20))
        
        # Description
        desc = ttk.Label(main_frame, text="Multiplayer grid claiming game for Computer Networks project", 
                        wraplength=400, justify="center")
        desc.grid(row=1, column=0, pady=(0, 30))
        
        # Server section
        server_frame = ttk.LabelFrame(main_frame, text="Server", padding="10")
        server_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 20))
        
        server_btn = ttk.Button(
            server_frame,
            text="Start Game Server",
            command=self.start_server,
            width=20
        )
        server_btn.grid(row=0, column=0, padx=(0, 10))
        
        self.server_status = ttk.Label(server_frame, text="Not running", foreground="red")
        self.server_status.grid(row=0, column=1)
        
        # Client section
        client_frame = ttk.LabelFrame(main_frame, text="Client", padding="10")
        client_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 20))
        
        # Waiting room button
        waiting_btn = ttk.Button(
            client_frame,
            text="Join Waiting Room",
            command=self.join_waiting_room,
            width=20
        )
        waiting_btn.grid(row=0, column=0, padx=(0, 10))
        
        # Direct game client button (for testing/debugging)
        direct_btn = ttk.Button(
            client_frame,
            text="Direct Game Client",
            command=self.start_direct_client,
            width=20
        )
        direct_btn.grid(row=0, column=1)
        
        # Quick start section
        quick_frame = ttk.LabelFrame(main_frame, text="Quick Start", padding="10")
        quick_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 20))
        
        quick_btn = ttk.Button(
            quick_frame,
            text="Start Server + Join Waiting Room",
            command=self.quick_start,
            width=30
        )
        quick_btn.grid(row=0, column=0)
        
        # Instructions
        instructions = ttk.Label(
            quick_frame,
            text="Tip: You need at least 2 players to start the game",
            foreground="gray",
            font=("Arial", 9)
        )
        instructions.grid(row=1, column=0, pady=(10, 0))
        
        # Quit button
        quit_btn = ttk.Button(
            main_frame,
            text="Quit",
            command=self.root.quit,
            width=20
        )
        quit_btn.grid(row=5, column=0, pady=(20, 0))
    
    def start_server(self):
        """Start the game server"""
        if self.server_process is None:
            self.server_process = subprocess.Popen([sys.executable, "server.py"])
            self.server_status.config(text="Running", foreground="green")
    
    def start_direct_client(self):
        """Start game client directly (for testing without waiting room)"""
        subprocess.Popen([sys.executable, "client.py"])
    
    def join_waiting_room(self):
        """Start waiting room"""
        try:
            # Check if waiting_room.py exists
            subprocess.Popen([sys.executable, "waiting_room.py"])
        except FileNotFoundError:
            # If waiting_room.py doesn't exist, show message and open regular client
            self.show_waiting_room_message()
            subprocess.Popen([sys.executable, "client.py"])
    
    def show_waiting_room_message(self):
        """Show message about waiting room"""
        message_window = tk.Toplevel(self.root)
        message_window.title("Info")
        message_window.geometry("400x200")
        
        ttk.Label(message_window, text="Waiting Room Not Available", 
                 font=("Arial", 14, "bold")).pack(pady=20)
        
        ttk.Label(message_window, text="The waiting room feature is not implemented yet.", 
                 wraplength=350).pack(pady=10)
        
        ttk.Label(message_window, text="Opening regular game client instead.", 
                 wraplength=350).pack(pady=10)
        
        ttk.Button(message_window, text="OK", 
                  command=message_window.destroy).pack(pady=20)
    
    def quick_start(self):
        """Quick start: server + waiting room"""
        self.start_server()
        
        # Wait a bit for server to start
        threading.Timer(1.0, self.join_waiting_room).start()
    
    def run(self):
        """Start the launcher"""
        self.root.mainloop()

    # In launcher.py, update the start_client function:
    def start_client(self):
        """Start waiting room (not direct client)"""
        try:
            subprocess.Popen([sys.executable, "waiting_room.py"])
        except:
            # Fallback to regular client if waiting_room.py doesn't exist
            subprocess.Popen([sys.executable, "client.py"])

    def start_both(self):
        """Start server and waiting room"""
        self.start_server()
        
        # Wait 2 seconds for server to start, then open waiting room
        import threading
        threading.Timer(2.0, self.start_client).start()

    


if __name__ == "__main__":
    launcher = Launcher()
    launcher.run()