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

HEADER_FORMAT = "!4s B B H H I Q"  # protocol_id, version, msg_type, length, snapshot_ID, seq_num, timestamp ,
HEADER_SIZE = 22

def create_header(msg_type, seq_num, payload_len, snapshot_id=0):
    length = HEADER_SIZE + payload_len
    timestamp = int(time.time() * 1000)  # milliseconds since epoch
    return struct.pack(HEADER_FORMAT, PROTOCOL_ID, VERSION, msg_type, length, snapshot_id, seq_num, timestamp)

def parse_header(data):
    protocol_id, version, msg_type, length, snapshot_id, seq_num, timestamp = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    return {
        'protocol_id': protocol_id.decode(),
        'version': version,
        'msg_type': msg_type,
        'length': length,
        'snapshot_id': snapshot_id,
        'seq_num': seq_num,
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
