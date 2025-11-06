import socket
import struct
import time
import select
from protocol import (
    create_header, pack_grid_snapshot, parse_header,
    MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP,
    MSG_TYPE_CLAIM_REQ, MSG_TYPE_LEAVE, MSG_TYPE_BOARD_SNAPSHOT
)

# -------------------------------
# Server Configuration
# -------------------------------
UDP_IP = "127.0.0.1"
UDP_PORT = 5005

server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
server_socket.bind((UDP_IP, UDP_PORT))

clients = {}
seq_num = 0
GRID_ROWS, GRID_COLS = 20, 20
grid_state = [[0 for _ in range(GRID_COLS)] for _ in range(GRID_ROWS)]

# Snapshot timing
SNAPSHOT_INTERVAL = 0.033  # 30Hz
last_snapshot_time = 0
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
                print(f"[ERROR] Short packet from {addr}")
                continue

            header = parse_header(data)
            msg_type = header["msg_type"]

            if msg_type == MSG_TYPE_JOIN_REQ:
                player_id = len(clients) + 1
                clients[player_id] = addr
                print(f"[JOIN] Player {player_id} from {addr}")

                payload = struct.pack("!B", player_id)
                resp = create_header(MSG_TYPE_JOIN_RESP, seq_num, len(payload)) + payload
                server_socket.sendto(resp, addr)
                print(f"[JOIN] Sent JOIN_RESPONSE to {addr}")
                seq_num += 1

            elif msg_type == MSG_TYPE_CLAIM_REQ:
                payload = data[22:]
                if len(payload) < 2:
                    print(f"[ERROR] Invalid CLAIM_REQUEST from {addr}")
                    continue
                row, col = payload[0], payload[1]
                if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
                    grid_state[row][col] = 1
                    print(f"[CLAIM] Player at {addr} claimed ({row},{col})")

            elif msg_type == MSG_TYPE_LEAVE:
                leaving = [pid for pid, c in clients.items() if c == addr]
                if leaving:
                    pid = leaving[0]
                    del clients[pid]
                    print(f"[LEAVE] Player {pid} left. {len(clients)} active.")

        except Exception as e:
            print(f"[ERROR] Handling client: {e}")

    # Send periodic board snapshots
    current_time = time.time()
    if clients and current_time - last_snapshot_time >= SNAPSHOT_INTERVAL:
        snapshot_bytes = pack_grid_snapshot(grid_state)
        payload_len = len(snapshot_bytes)
        server_timestamp_ms = int(current_time * 1000)

        # Send to all clients
        for pid, addr in list(clients.items()):
            try:
                msg = create_header(MSG_TYPE_BOARD_SNAPSHOT, seq_num, payload_len) + snapshot_bytes
                server_socket.sendto(msg, addr)

                # Log clean line for postprocessing
                print(f"{pid} {snapshot_id} {seq_num} {server_timestamp_ms} {server_timestamp_ms} 0.0 0.0 0.0")

                print(f"[SNAPSHOT] Sent SnapshotID={snapshot_id} Seq={seq_num} to Player {pid}")
            except Exception as e:
                print(f"[ERROR] Snapshot send failed for {pid}: {e}")
                clients.pop(pid, None)

        seq_num += 1
        snapshot_id += 1
        last_snapshot_time = current_time
