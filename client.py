import socket
import struct
import time
import random
from protocol import create_header, parse_header, MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP, MSG_TYPE_CLAIM_REQ, MSG_TYPE_BOARD_SNAPSHOT, unpack_grid_snapshot

# server info
SERVER_IP = "127.0.0.1"
SERVER_PORT = 5005

client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
client_socket.settimeout(0.5)  # non-blocking receive with timeout

seq_num = 0  # sequence no for messages

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
    payload = data[20:] 

    if header['msg_type'] == MSG_TYPE_JOIN_RESP:
        player_id = struct.unpack("!B", payload)[0]  
        print(f"[JOIN] Received JOIN_RESPONSE, assigned PlayerID: {player_id}")
        break
    else:
        print(f"[JOIN] Unexpected message type: {header['msg_type']}")

# small delay before sending claim (avoid sending too fast)
time.sleep(0.3)

# simulate a claim request
row = random.randint(0, 19)
col = random.randint(0, 19)
payload = struct.pack("!BB", row, col)
claim_request = create_header(MSG_TYPE_CLAIM_REQ, seq_num, len(payload)) + payload
client_socket.sendto(claim_request, (SERVER_IP, SERVER_PORT))
print(f"[CLAIM] Sent CLAIM_REQUEST for cell ({row},{col})")
seq_num += 1

# listen for board snapshot messages
start_time = time.time()
while time.time() - start_time < 30:
    try:
        data, addr = client_socket.recvfrom(1024)
    except socket.timeout:
        time.sleep(0.1)
        continue

    header = parse_header(data)
    payload = data[20:]

    if header['msg_type'] == MSG_TYPE_BOARD_SNAPSHOT:
        grid = unpack_grid_snapshot(payload)
        print("[SNAPSHOT] Received BOARD_SNAPSHOT:")
        for row in grid: 
            print(row)
        print("...")
        time.sleep(0.2)  
    else:
        print(f"[INFO] Received message type: {header['msg_type']}")

client_socket.close()