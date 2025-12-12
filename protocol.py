import struct
import time

PROTOCOL_ID = b'GSSP'
VERSION = 1

# message types
MSG_TYPE_JOIN_REQ = 0
MSG_TYPE_JOIN_RESP = 1
MSG_TYPE_CLAIM_REQ = 2
MSG_TYPE_BOARD_SNAPSHOT = 3 
MSG_TYPE_GAME_OVER = 4
MSG_TYPE_LEAVE = 5
MSG_TYPE_GAME_START = 6
MSG_TYPE_WAITING_ROOM = 7
MSG_TYPE_ACK=8
MSG_TYPE_LEADERBOARD = 9

HEADER_FORMAT = "!4s B B H H I I Q H"  # Added Checksum(2) at end
HEADER_SIZE = 28

def compute_checksum(data):
    """
    Compute 16-bit Internet Checksum (RFC 1071).
    Sum of 16-bit words (1's complement).
    """
    if len(data) % 2 == 1:
        data += b'\x00'
    
    s = sum(struct.unpack('!%dH' % (len(data) // 2), data))
    
    # Fold carry bits
    s = (s >> 16) + (s & 0xffff)
    s += s >> 16
    
    return ~s & 0xffff

def create_packet(msg_type, seq_num, payload, snapshot_id=0, ack_num=0):
    """Creates a full packet with 16-bit Internet Checksum."""
    length = len(payload)
    timestamp = int(time.time() * 1000)
    
    # 1. Pack with 0 checksum
    header_no_checksum = struct.pack(
        HEADER_FORMAT, 
        PROTOCOL_ID, 
        VERSION, 
        msg_type, 
        length, 
        snapshot_id, 
        seq_num, 
        ack_num,  
        timestamp,
        0 # Checksum placeholder
    )
    
    # 2. Calculate checksum of (Header + Payload)
    full_data = header_no_checksum + payload
    checksum = compute_checksum(full_data)
    
    # 3. Repack header with correct checksum
    header_final = struct.pack(
        HEADER_FORMAT, 
        PROTOCOL_ID, 
        VERSION, 
        msg_type, 
        length, 
        snapshot_id, 
        seq_num, 
        ack_num,  
        timestamp,
        checksum
    )
    
    return header_final + payload

def parse_packet(data):
    """
    Parses a packet, validates 16-bit checksum.
    Returns: (header_dict, payload, valid_checksum)
    """
    if len(data) < HEADER_SIZE:
        return None, None, False

    # 1. Unpack header
    protocol_id, version, msg_type, length, snapshot_id, seq_num, ack_num, timestamp, received_checksum = struct.unpack(
        HEADER_FORMAT, data[:HEADER_SIZE]
    )
    
    # 2. Validate Checksum
    # Summing the entire packet with correct checksum should result in 0 (in 1's complement logic with inverse)
    # OR: Recompute checksum with 0 field and match.
    # We will recompute for clarity.
    
    header_no_checksum = struct.pack(
        HEADER_FORMAT, 
        protocol_id, 
        version, 
        msg_type, 
        length, 
        snapshot_id, 
        seq_num, 
        ack_num, 
        timestamp, 
        0
    )
    
    payload = data[HEADER_SIZE:]
    calculated_checksum = compute_checksum(header_no_checksum + payload)
    
    valid = (received_checksum == calculated_checksum)
    
    header = {
        'protocol_id': protocol_id.decode(),
        'version': version,
        'msg_type': msg_type,
        'length': length,
        'snapshot_id': snapshot_id,
        'seq_num': seq_num,
        'ack_num': ack_num,  
        'timestamp': timestamp,
        'received_checksum': received_checksum
    }
    
    return header, payload, valid

def pack_grid_snapshot(grid):
    packed = bytearray()
    rows = len(grid)
    cols = len(grid[0])

    for r in range(rows):
        for c in range(0, cols, 2):  
            cell1 = grid[r][c] & 0x0F  
            cell2 = grid[r][c+1] & 0x0F 
            packed_byte = (cell1 << 4) | cell2
            packed.append(packed_byte)

    return bytes(packed) 


def unpack_grid_snapshot(payload, rows=20, cols=20):
    grid = [[0 for _ in range(cols)] for _ in range(rows)]
    i = 0  # index in payload

    for r in range(rows):
        for c in range(0, cols, 2):
            byte = payload[i]
            grid[r][c] = (byte >> 4) & 0x0F  
            grid[r][c+1] = byte & 0x0F       
            i += 1

    return grid

def create_ack_packet(ack_num, seq_num=0, snapshot_id=0):
    return create_packet(MSG_TYPE_ACK, seq_num, b'', snapshot_id, ack_num)

def pack_leaderboard_data(leaderboard):

    # Format: count (1 byte) + for each entry: player_id (1 byte), score (2 bytes), rank (1 byte)
    count = len(leaderboard)
    data = struct.pack("!B", count)
    for pid, score, rank in leaderboard:
        data += struct.pack("!BHB", pid, score, rank)
    return data

def unpack_leaderboard_data(payload):
    if len(payload) < 1:
        return []
    
    count = struct.unpack("!B", payload[0:1])[0]
    offset = 1
    leaderboard = []
    
    for _ in range(count):
        if len(payload) >= offset + 4:  # 1 + 2 + 1 = 4 bytes per entry
            pid, score, rank = struct.unpack("!BHB", payload[offset:offset+4])
            leaderboard.append((pid, score, rank))
            offset += 4
    
    return leaderboard