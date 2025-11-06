import socket
import struct
import time
import select
from protocol import create_header, pack_grid_snapshot, parse_header, MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP, MSG_TYPE_CLAIM_REQ, MSG_TYPE_LEAVE,MSG_TYPE_BOARD_SNAPSHOT

# server config
UDP_IP = "127.0.0.1"
UDP_PORT = 5005

server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
server_socket.bind((UDP_IP, UDP_PORT))

# game state info
clients = {}
seq_num = 0
GRID_ROWS = 20
GRID_COLS = 20
grid_state = [[0 for _ in range(GRID_COLS)] for _ in range(GRID_ROWS)]

# Timing for snapshot broadcasts
last_snapshot_time = 0
SNAPSHOT_INTERVAL = 0.033 
snapshot_id = 0 

print(f"Server running on {UDP_IP}:{UDP_PORT}")

while True:
    current_time = time.time()
    next_snapshot_time = last_snapshot_time + SNAPSHOT_INTERVAL
    timeout = max(0, next_snapshot_time - current_time) if clients else 0.1
    
    readable, _, _ = select.select([server_socket], [], [], timeout)
    
    if server_socket in readable:
        try:
            data, addr = server_socket.recvfrom(1024)
            if len(data) < 22:
                print(f"[ERROR] Received packet too short from {addr}")
                continue

            header = parse_header(data)
            if header['msg_type'] == MSG_TYPE_JOIN_REQ:
                player_id = len(clients) + 1
                clients[player_id] = addr
                print(f"[JOIN] New player {player_id} from {addr}. Total clients: {len(clients)}")

                payload = struct.pack("!B", player_id)
                response = create_header(MSG_TYPE_JOIN_RESP, seq_num, len(payload)) + payload
                server_socket.sendto(response, addr)
                seq_num += 1
                print(f"[JOIN] Sent JOIN_RESPONSE to player {player_id}")

            elif header['msg_type'] == MSG_TYPE_CLAIM_REQ:
                payload = data[22:]
                if len(payload) < 2:
                    print(f"[ERROR] Invalid CLAIM_REQUEST from {addr}")
                    continue

                row, col = payload[0], payload[1]

                if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
                    grid_state[row][col] = 1
                    print(f"[CLAIM] Player at {addr} claimed cell ({row}, {col})")
                else:
                    print(f"[CLAIM] Invalid cell ({row},{col}) from {addr}")

            elif header['msg_type'] == MSG_TYPE_LEAVE:
                leaving_player = None
                for pid, c_addr in list(clients.items()):
                    if c_addr == addr:
                        leaving_player = pid
                        break

                if leaving_player:
                    print(f"[LEAVE] Player {leaving_player} at {addr} disconnected.")
                    del clients[leaving_player]
                    print(f"[INFO] Active clients: {len(clients)}")
                else:
                    print(f"[LEAVE] Received from unknown address {addr}")

            else:
                print(f"[UNKNOWN] Received unknown message type {header['msg_type']} from {addr}")

        except Exception as e:
            print(f"[ERROR] Exception handling client: {e}")
 

        current_time = time.time()
        if clients and current_time - last_snapshot_time >= SNAPSHOT_INTERVAL:
            snapshot_bytes = pack_grid_snapshot(grid_state)
            payload_len = len(snapshot_bytes)
            
            # include snapshot_id in header
            msg = create_header(MSG_TYPE_BOARD_SNAPSHOT, seq_num, payload_len, snapshot_id) + snapshot_bytes

            sent_count = 0
            print(f"[DEBUG] Preparing to send to {len(clients)} clients: {list(clients.items())}")
            
            disconnected_players = []

            for player_id, addr in list(clients.items()):
                try:
                    server_socket.sendto(msg, addr)
                    sent_count += 1
                    print(f"[SNAPSHOT] Sent SnapshotID {snapshot_id} to player {player_id} at {addr}")
                except (ConnectionRefusedError, OSError) as e:
                    print(f"[DISCONNECT] Player {player_id} at {addr} seems offline: {e}")
                    disconnected_players.append(player_id)
                except Exception as e:
                    print(f"[ERROR] Failed to send snapshot to player {player_id}: {e}")

            for pid in disconnected_players:
                clients.pop(pid, None)

            if sent_count > 0:
                print(f"[SNAPSHOT] Broadcasted grid to {sent_count} clients (Seq={seq_num}, SnapshotID={snapshot_id})")
                seq_num += 1
                snapshot_id += 1  # increment for next snapshot
            else:
                print(f"[SNAPSHOT] No clients to send to!")
            
            last_snapshot_time = current_time
