import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import sys
import threading
import socket

MAX_PLAYERS = 4
MIN_PLAYERS = 2
WAITING_ROOM_PORT = 5006 

_waiting_room_instance = None

class WaitingRoom:
    def __init__(self):
        global _waiting_room_instance
        
        if _waiting_room_instance is not None:
            try:
                _waiting_room_instance.root.lift()
                _waiting_room_instance.root.focus_force()
                print("[WAITING ROOM] Existing waiting room brought to front")
                
                # Send request to add player to existing waiting room
                self._request_add_to_existing()
                return
            except:
                _waiting_room_instance = None
        
        self.root = tk.Tk()
        self.root.title("🎮 Grid Game Waiting Room")
        self.root.geometry("500x450")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        _waiting_room_instance = self

        self.players = {}
        self.next_player_id = 1
        self.game_started = False
        self.waiting_timer = 60
        self.timer_running = False

        self.setup_ui()
        self.add_player()
        
        # Start listener for external player requests
        self._start_listener()
        
        self.update_ui_loop()

    def _start_listener(self):
        """Start a simple UDP server to listen for player join requests"""
        def listener_thread():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", WAITING_ROOM_PORT))
            sock.settimeout(1.0)
            
            while hasattr(self, 'root') and self.root:
                try:
                    data, addr = sock.recvfrom(1024)
                    if data == b"ADD_PLAYER":
                        # Add a player from external request
                        self.root.after(0, self.add_external_player)
                        sock.sendto(b"OK", addr)
                        print(f"[WAITING ROOM] Added player from external request")
                except socket.timeout:
                    continue
                except:
                    break
            
            sock.close()
        
        thread = threading.Thread(target=listener_thread, daemon=True)
        thread.start()

    def _request_add_to_existing(self):
        """Send request to add player to existing waiting room"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            sock.sendto(b"ADD_PLAYER", ("127.0.0.1", WAITING_ROOM_PORT))
            
            try:
                response, _ = sock.recvfrom(1024)
                if response == b"OK":
                    print("[WAITING ROOM] Successfully added to existing waiting room")
            except socket.timeout:
                print("[WAITING ROOM] Timeout adding to existing room")
            
            sock.close()
        except Exception as e:
            print(f"[WAITING ROOM] Error adding to existing: {e}")

    def add_external_player(self):
        """Add a player when another client clicks 'Play Again'"""
        if len(self.players) >= MAX_PLAYERS:
            messagebox.showinfo("Max Players", f"Maximum {MAX_PLAYERS} players reached.")
            return False
        
        pid = self.next_player_id
        self.players[pid] = "Ready"
        self.next_player_id += 1
        
        self.update_players_display()
        return True

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(expand=True, fill=tk.BOTH)

        ttk.Label(main_frame, text="🎮 Grid Game Waiting Room", font=("Arial", 18, "bold")).pack(pady=10)

        players_frame = ttk.LabelFrame(main_frame, text="Players in Room", padding=10)
        players_frame.pack(fill=tk.X, pady=10)
        self.players_text = tk.Text(players_frame, height=6, font=("Consolas", 10), bg="#f8f9fa")
        self.players_text.pack(fill=tk.X)
        self.players_text.config(state="disabled")

        timer_frame = ttk.LabelFrame(main_frame, text="Game Start Timer", padding=10)
        timer_frame.pack(fill=tk.X, pady=10)
        self.timer_label = ttk.Label(timer_frame, text="Waiting for players...", font=("Arial", 12))
        self.timer_label.pack()
        self.progress = ttk.Progressbar(timer_frame, length=300, mode='determinate', maximum=60)
        self.progress.pack(pady=5)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=10)
        self.start_button = ttk.Button(btn_frame, text="Start Game Now", command=self.start_game, state="disabled")
        self.start_button.grid(row=0, column=0, padx=5)
        self.more_players_btn = ttk.Button(btn_frame, text="Add Player", command=self.add_player)
        self.more_players_btn.grid(row=0, column=1, padx=5)

        self.player_count_label = ttk.Label(main_frame, text=f"Players: {len(self.players)}/{MAX_PLAYERS}")
        self.player_count_label.pack(pady=5)

    def add_player(self):
        """Add a new player internally (no new window)"""
        if len(self.players) >= MAX_PLAYERS:
            messagebox.showinfo("Max Players", f"Maximum {MAX_PLAYERS} players reached.")
            return

        pid = self.next_player_id
        self.players[pid] = "Ready"
        self.next_player_id += 1

        self.update_players_display()

    def update_players_display(self):
        self.players_text.config(state="normal")
        self.players_text.delete(1.0, tk.END)
        for pid, status in sorted(self.players.items()):
            self.players_text.insert(tk.END, f"Player {pid}: {status}\n")
        self.players_text.config(state="disabled")

        self.player_count_label.config(text=f"Players: {len(self.players)}/{MAX_PLAYERS}")

        if len(self.players) >= MIN_PLAYERS and not self.game_started:
            self.start_button.config(state="normal")
            if not self.timer_running:
                self.start_countdown()
        else:
            self.start_button.config(state="disabled")

    def start_countdown(self):
        self.timer_running = True
        self.update_timer()

    def update_timer(self):
        if not self.timer_running or self.game_started:
            return
        if len(self.players) < MIN_PLAYERS:
            self.timer_label.config(text=f"Need {MIN_PLAYERS - len(self.players)} more player(s)")
            self.progress['value'] = 0
            self.timer_running = False
            self.start_button.config(state="disabled")
            return

        self.timer_label.config(text=f"Game starts in {self.waiting_timer}s")
        self.progress['value'] = 60 - self.waiting_timer
        if self.waiting_timer <= 0:
            self.start_game()
            return
        self.waiting_timer -= 1
        self.root.after(1000, self.update_timer)

    def start_game(self):
        if len(self.players) < MIN_PLAYERS:
            self.timer_label.config(text=f"Need {MIN_PLAYERS - len(self.players)} more player(s)")
            return

        self.game_started = True
        self.timer_label.config(text="Starting game...")
        self.start_button.config(state="disabled")
        self.more_players_btn.config(state="disabled")

        for pid in self.players:
            threading.Thread(target=self.launch_client, args=(pid,), daemon=True).start()

        self.root.after(1000, self.root.destroy)  

    def launch_client(self, pid):
        try:
            subprocess.Popen([sys.executable, "client.py"])
        except Exception as e:
            print(f"Failed to launch client {pid}: {e}")

    def update_ui_loop(self):
        self.update_players_display()
        if not self.game_started:
            self.root.after(2000, self.update_ui_loop)

    def on_closing(self):
        global _waiting_room_instance
        
        if _waiting_room_instance == self:
            _waiting_room_instance = None
        
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    wr = WaitingRoom()
    wr.run()