import socket
import struct
import time
from protocol import create_header, parse_header, MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP, MSG_TYPE_CLAIM_REQ

# server info
SERVER_IP = "127.0.0.1"
SERVER_PORT = 5005

client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

seq_num = 0  # sequence no for messages

# send join request
join_request = create_header(MSG_TYPE_JOIN_REQ, seq_num, 0) 
client_socket.sendto(join_request, (SERVER_IP, SERVER_PORT))
print("[JOIN] Sent JOIN_REQUEST")
seq_num += 1

# wait for join response
data, addr = client_socket.recvfrom(1024)
header = parse_header(data)
payload = data[20:] 

if header['msg_type'] == MSG_TYPE_JOIN_RESP:
    player_id = struct.unpack("!B", payload)[0]  
    print(f"[JOIN] Received JOIN_RESPONSE, assigned PlayerID: {player_id}")
else:
    print(f"[JOIN] Unexpected message type: {header['msg_type']}")

# simulate a claim request
row, col = 5, 7  # example cell
payload = struct.pack("!BB", row, col)
claim_request = create_header(MSG_TYPE_CLAIM_REQ, seq_num, len(payload)) + payload
client_socket.sendto(claim_request, (SERVER_IP, SERVER_PORT))
print(f"[CLAIM] Sent CLAIM_REQUEST for cell ({row},{col})")
seq_num += 1

#wait for server response
time.sleep(1)
client_socket.close()
