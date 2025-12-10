import tkinter as tk
from tkinter import ttk

class LeaderboardGUI:
    def __init__(self, parent, player_scores, play_again_callback=None):
        self.window = tk.Toplevel(parent)
        self.window.title("Leaderboard")
        self.window.geometry("400x350")
        self.window.resizable(False, False)
        
        self.player_scores = sorted(player_scores, key=lambda x: x[1], reverse=True)
        self.play_again_callback = play_again_callback
        
        self.setup_ui()
    
    def setup_ui(self):
        # Title label
        title_label = ttk.Label(
            self.window,
            text="🏆 Leaderboard 🏆",
            font=("Arial", 16, "bold"),
            foreground="#1e3d59"
        )
        title_label.pack(pady=10)
        
        # Treeview for leaderboard
        columns = ("Rank", "Player", "Score")
        self.tree = ttk.Treeview(self.window, columns=columns, show="headings", height=8)
        self.tree.heading("Rank", text="Rank")
        self.tree.heading("Player", text="Player")
        self.tree.heading("Score", text="Score")
        self.tree.column("Rank", anchor=tk.CENTER, width=50)
        self.tree.column("Player", anchor=tk.CENTER, width=150)
        self.tree.column("Score", anchor=tk.CENTER, width=100)
        self.tree.pack(pady=10)
        
        # Insert player scores with color coding
        for idx, (pid, score) in enumerate(self.player_scores, start=1):
            self.tree.insert("", "end", values=(idx, f"Player {pid}", score))
        
        # Style top 3 players
        self.style_top_players()
        
        # Play Again button
        if self.play_again_callback:
            play_again_btn = ttk.Button(self.window, text="Play Again", command=self.on_play_again)
            play_again_btn.pack(pady=10)
        
        # Close button
        close_btn = ttk.Button(self.window, text="Close", command=self.window.destroy)
        close_btn.pack(pady=(0, 10))
    
    def style_top_players(self):
        colors = ["#FFD700", "#C0C0C0", "#CD7F32"]  # Gold, Silver, Bronze
        for idx, color in enumerate(colors):
            if idx < len(self.player_scores):
                item_id = self.tree.get_children()[idx]
                self.tree.item(item_id, tags=(f"top{idx+1}",))
                self.tree.tag_configure(f"top{idx+1}", background=color)
    
    def on_play_again(self):
        self.window.destroy()
        if self.play_again_callback:
            self.play_again_callback()

def play_again():
    print("Play again clicked!")

def main():
    # Create main window
    root = tk.Tk()
    root.title("Test Window")
    root.geometry("300x200")
    
    # Sample scores for testing
    test_scores = [
        (1, 42),
        (2, 35),
        (3, 28),
        (4, 15),
    ]
    
    # Button to show leaderboard
    def show_leaderboard():
        LeaderboardGUI(root, test_scores, play_again_callback=play_again)
    
    btn = ttk.Button(root, text="Show Leaderboard", command=show_leaderboard)
    btn.pack(expand=True)
    
    root.mainloop()

if __name__ == "__main__":
    main()