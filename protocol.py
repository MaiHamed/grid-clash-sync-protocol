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

HEADER_FORMAT = "!4s B B H I Q"  # protocol_id, version, msg_type, length, seq_num, timestamp
HEADER_SIZE = 20

def create_header(msg_type, seq_num, payload_len):
    length = HEADER_SIZE + payload_len
    timestamp = int(time.time() * 1000)  # milliseconds since epoch
    return struct.pack(HEADER_FORMAT, PROTOCOL_ID, VERSION, msg_type, length, seq_num, timestamp)

def parse_header(data):
    protocol_id, version, msg_type, length, seq_num, timestamp = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    return {
        'protocol_id': protocol_id.decode(),
        'version': version,
        'msg_type': msg_type,
        'length': length,
        'seq_num': seq_num,
        'timestamp': timestamp
    }


def pack_grid_snapshot(grid):
    return b"".join(bytes(row) for row in grid)

def unpack_grid_snapshot(payload, rows=20, cols=20):
    grid = []
    for i in range(rows):
        row_start = i * cols
        row_end = row_start + cols
        grid.append(list(payload[row_start:row_end]))
    return grid
