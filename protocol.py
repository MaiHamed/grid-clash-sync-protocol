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
MSG_TYPE_GAME_SETTINGS = 8  # Add this with other message types
MSG_TYPE_ACK=9

HEADER_FORMAT = "!4s B B H H I I Q"  #protocol_id(4), version(1), msg_type(1), length(2), snapshot_ID(2), seq_num(4), ack_num(4), timestamp(8)
HEADER_SIZE = 26

def create_header(msg_type, seq_num, payload_len, snapshot_id=0, ack_num=0):
    length = HEADER_SIZE + payload_len
    timestamp = int(time.time() * 1000)
    return struct.pack(
        HEADER_FORMAT, 
        PROTOCOL_ID, 
        VERSION, 
        msg_type, 
        length, 
        snapshot_id, 
        seq_num, 
        ack_num,  
        timestamp
    )

def parse_header(data):
    # Add ack_num to unpack
    protocol_id, version, msg_type, length, snapshot_id, seq_num, ack_num, timestamp = struct.unpack(
        HEADER_FORMAT, data[:HEADER_SIZE]
    )
    return {
        'protocol_id': protocol_id.decode(),
        'version': version,
        'msg_type': msg_type,
        'length': length,
        'snapshot_id': snapshot_id,
        'seq_num': seq_num,
        'ack_num': ack_num,  
        'timestamp': timestamp
    }

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

    return bytes(packed)  # total 200 bytes for 20x20 grid


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

def create_ack_packet(ack_num, seq_num=0):
    return create_header(MSG_TYPE_ACK, seq_num=seq_num, payload_len=0, snapshot_id=0, ack_num=ack_num)