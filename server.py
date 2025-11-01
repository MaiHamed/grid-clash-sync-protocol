
import socket
import struct
import time
import threading

from protocol import create_header, parse_header, MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP, MSG_TYPE_CLAIM_REQ

# server config
UDP_IP = "127.0.0.1"
UDP_PORT = 5005

server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server_socket.bind((UDP_IP, UDP_PORT))

# game state info
clients = {} 
seq_num = 0
GRID_ROWS = 20
GRID_COLS = 20
grid_state = [[0 for _ in range(GRID_COLS)] for _ in range(GRID_ROWS)] 

#incoming messages
def handle_client():
    global seq_num
    while True:
        data, addr = server_socket.recvfrom(1024)
        if len(data) < 20: 
            print(f"[ERROR] Received packet too short from {addr}")
            continue

        header = parse_header(data)

        if header['msg_type'] == MSG_TYPE_JOIN_REQ:
            player_id = len(clients) + 1
            clients[player_id] = addr
            print(f"[JOIN] New player {player_id} from {addr}")

            # create join response
            payload = struct.pack("!B", player_id) 
            response = create_header(MSG_TYPE_JOIN_RESP, seq_num, len(payload)) + payload
            server_socket.sendto(response, addr)
            seq_num += 1

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

# run listener in separate thread
threading.Thread(target=handle_client, daemon=True).start()

print(f"Server running on {UDP_IP}:{UDP_PORT}")

while True:
    time.sleep(1)
