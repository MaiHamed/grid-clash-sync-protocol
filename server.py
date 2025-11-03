import socket
import struct
import time
import select
from protocol import create_header, parse_header, MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP, MSG_TYPE_CLAIM_REQ, MSG_TYPE_BOARD_SNAPSHOT, MSG_TYPE_GAME_OVER

# server config
UDP_IP = "127.0.0.1"
UDP_PORT = 5005

server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
server_socket.bind((UDP_IP, UDP_PORT))

# game state info
clients = {}  # Format: {player_id: addr}
seq_num = 0
GRID_ROWS = 20
GRID_COLS = 20
grid_state = [[0 for _ in range(GRID_COLS)] for _ in range(GRID_ROWS)]

# Timing for snapshot broadcasts
last_snapshot_time = 0
SNAPSHOT_INTERVAL = 0.5  # Send snapshots every 0.5 seconds

print(f"Server running on {UDP_IP}:{UDP_PORT}")

while True:
    # Use select to check if there's data to read, with timeout
    current_time = time.time()
    next_snapshot_time = last_snapshot_time + SNAPSHOT_INTERVAL
    timeout = max(0, next_snapshot_time - current_time) if clients else 0.1
    
    readable, _, _ = select.select([server_socket], [], [], timeout)
    
    # Handle incoming messages first (priority)
    if server_socket in readable:
        try:
            data, addr = server_socket.recvfrom(1024)
            if len(data) < 20:
                print(f"[ERROR] Received packet too short from {addr}")
                continue

            header = parse_header(data)

            if header['msg_type'] == MSG_TYPE_JOIN_REQ:
                player_id = len(clients) + 1
                clients[player_id] = addr
                print(f"[JOIN] New player {player_id} from {addr}. Total clients: {len(clients)}")

                # create join response
                payload = struct.pack("!B", player_id)
                response = create_header(MSG_TYPE_JOIN_RESP, seq_num, len(payload)) + payload
                server_socket.sendto(response, addr)
                seq_num += 1
                print(f"[JOIN] Sent JOIN_RESPONSE to player {player_id}")

            elif header['msg_type'] == MSG_TYPE_CLAIM_REQ:
                payload = data[20:]
                if len(payload) < 2:
                    print(f"[ERROR] Invalid CLAIM_REQUEST from {addr}")
                    continue

                row, col = payload[0], payload[1]

                # bounds check
                if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
                    grid_state[row][col] = 1
                    print(f"[CLAIM] Player at {addr} claimed cell ({row}, {col})")
                else:
                    print(f"[CLAIM] Invalid cell ({row},{col}) from {addr}")

            else:
                print(f"[UNKNOWN] Received unknown message type {header['msg_type']} from {addr}")
                
        except Exception as e:
            print(f"[ERROR] Exception handling client: {e}")

    # Send snapshots if it's time (after handling all incoming messages)
    current_time = time.time()
    if clients and current_time - last_snapshot_time >= SNAPSHOT_INTERVAL:
        snapshot_bytes = b"".join(bytes(row) for row in grid_state)
        payload = snapshot_bytes
        msg = create_header(MSG_TYPE_BOARD_SNAPSHOT, seq_num, len(payload)) + payload

        sent_count = 0
        print(f"[DEBUG] Preparing to send to {len(clients)} clients: {list(clients.items())}")
        
        for player_id, addr in list(clients.items()):
            try:
                server_socket.sendto(msg, addr)
                sent_count += 1
                print(f"[SNAPSHOT] Sent to player {player_id} at {addr}")
            except Exception as e:
                print(f"[DISCONNECT] Removing player {player_id}: {e}")
                if player_id in clients:
                    del clients[player_id]

        if sent_count > 0:
            print(f"[SNAPSHOT] Broadcasted grid to {sent_count} clients (Seq={seq_num})")
            seq_num += 1
        else:
            print(f"[SNAPSHOT] No clients to send to!")
        
        last_snapshot_time = current_time
