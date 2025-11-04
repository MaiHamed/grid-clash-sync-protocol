import socket
import struct
import time
import random
from protocol import (
    create_header, parse_header,
    MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP,
    MSG_TYPE_CLAIM_REQ, MSG_TYPE_BOARD_SNAPSHOT, MSG_TYPE_LEAVE,
    unpack_grid_snapshot
)

# server info
SERVER_IP = "127.0.0.1"
SERVER_PORT = 5005

client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
client_socket.settimeout(0.5)

seq_num = 0  # sequence number for messages

# send join request
join_request = create_header(MSG_TYPE_JOIN_REQ, seq_num, 0)
client_socket.sendto(join_request, (SERVER_IP, SERVER_PORT))
print("[JOIN] Sent JOIN_REQUEST")
seq_num += 1

# small random delay before listening to avoid packet storm
time.sleep(random.uniform(0.1, 0.4))

# wait for join response
while True:
    try:
        data, addr = client_socket.recvfrom(1024)
    except socket.timeout:
        continue

    header = parse_header(data)
    payload = data[22:]  

    if header['msg_type'] == MSG_TYPE_JOIN_RESP:
        player_id = struct.unpack("!B", payload)[0]
        print(f"[JOIN] Received JOIN_RESPONSE, assigned PlayerID: {player_id}")
        break
    else:
        print(f"[JOIN] Unexpected message type: {header['msg_type']}")

# main loop: send multiple claims for different cells
start_time = time.time()
claimed_cells = set()

while time.time() - start_time < 30:  # run for 30 seconds
    # pick a new cell that hasn't been claimed yet
    while True:
        row = random.randint(0, 19)
        col = random.randint(0, 19)
        if (row, col) not in claimed_cells:
            claimed_cells.add((row, col))
            break

    payload = struct.pack("!BB", row, col)
    claim_request = create_header(MSG_TYPE_CLAIM_REQ, seq_num, len(payload)) + payload
    client_socket.sendto(claim_request, (SERVER_IP, SERVER_PORT))
    print(f"[CLAIM] Sent CLAIM_REQUEST for cell ({row},{col})")
    seq_num += 1

    # small random delay before next claim
    time.sleep(random.uniform(0.5, 1.5))

    # check for snapshots
    try:
        while True:
            data, addr = client_socket.recvfrom(1024)
            header = parse_header(data)
            payload = data[22:] 

            if header['msg_type'] == MSG_TYPE_BOARD_SNAPSHOT:
                payload_len = header['length'] - 22  
                payload = data[22:22 + payload_len]   

                if len(payload) != 200:
                    print(f"[ERROR] BOARD_SNAPSHOT payload size incorrect: {len(payload)} bytes")
                    continue

                grid = unpack_grid_snapshot(payload)
                print("[SNAPSHOT] Received BOARD_SNAPSHOT:")
                for r in grid:
                    print(r)
                print("...")
            else:
                print(f"[INFO] Received message type: {header['msg_type']}")
    except socket.timeout:
        continue

# send LEAVE message
leave_msg = create_header(MSG_TYPE_LEAVE, seq_num, 0)
client_socket.sendto(leave_msg, (SERVER_IP, SERVER_PORT))
print("[INFO] Sent LEAVE message to server")

client_socket.close()
print("[INFO] Client closed connection.")