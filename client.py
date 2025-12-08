import socket
import struct
import time
import threading
from protocol import (
    create_ack_packet, create_header, parse_header, HEADER_SIZE,
    MSG_TYPE_JOIN_REQ, MSG_TYPE_JOIN_RESP,
    MSG_TYPE_CLAIM_REQ, MSG_TYPE_BOARD_SNAPSHOT, MSG_TYPE_LEAVE,
    MSG_TYPE_GAME_START, MSG_TYPE_GAME_OVER,
    unpack_grid_snapshot, MSG_TYPE_ACK
)

def current_time_ms():
    return int(time.time() * 1000)

class GameClient:
    def __init__(self, server_ip="127.0.0.1", server_port=5005):
        self.server_ip = server_ip
        self.server_port = server_port
        self.client_socket = None
        self.running = False

        # SR ARQ - Sender side
        self.N = 6  # Window size
        self.base = 0
        self.nextSeqNum = 0
        self.window = {}  # Unacknowledged packets
        self.timers = {}  # Timer start times
        self.send_timestamp = {}  # When packets were sent
        
        # SR ARQ - Receiver side
        self.receive_buffer = {}  # Out-of-order packets
        self.expected_seq = 0     # Next expected sequence number
        
        # RTT estimation
        self.estimatedRTT = 100
        self.devRTT = 50
        self.alpha = 0.125
        self.beta = 0.25
        self.RTO = self.estimatedRTT + 4*self.devRTT

        # Game state
        self.player_id = None
        self.game_active = False
        self.local_grid = [[0]*20 for _ in range(20)]  # Local copy of grid
        
        # Statistics
        self.stats = {'sent':0, 'received':0, 'dropped':0, 'retransmissions':0}
        
        # Callback for UI updates
        self.on_grid_update = None
        self.on_game_start = None
        self.on_game_over = None

    # ==================== SR ARQ Sender ====================
    def _sr_send(self, msg_type, payload=b''):
        """Send a packet with SR ARQ reliability"""
        if self.nextSeqNum < self.base + self.N:
            seq = self.nextSeqNum
            packet = create_header(msg_type, seq, len(payload)) + payload
            self.client_socket.sendto(packet, (self.server_ip, self.server_port))
            self.window[seq] = packet
            self.timers[seq] = current_time_ms()
            self.send_timestamp[seq] = current_time_ms()
            self.nextSeqNum += 1
            self.stats['sent'] += 1
            print(f"[SEND] seq={seq}, type={msg_type}, window={list(self.window.keys())}")
            return True
        else:
            self.stats['dropped'] += 1
            print(f"[DROPPED] seq={self.nextSeqNum}, window full")
            return False

    def _retransmit(self, seq):
        """Retransmit a specific packet"""
        packet = self.window.get(seq)
        if packet:
            self.client_socket.sendto(packet, (self.server_ip, self.server_port))
            self.timers[seq] = current_time_ms()
            self.stats['sent'] += 1
            self.stats['retransmissions'] += 1
            print(f"[RETRANSMIT] seq={seq}")

    def _timer_loop(self):
        """Check for expired timers and retransmit"""
        while self.running:
            now = current_time_ms()
            for seq in list(self.timers.keys()):
                if now - self.timers[seq] >= self.RTO:
                    self._retransmit(seq)
            time.sleep(0.01)

    # ==================== Network Connection ====================
    def connect(self):
        """Connect to the game server"""
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client_socket.settimeout(1.0)
        self.running = True
        
        # Start background threads
        threading.Thread(target=self._timer_loop, daemon=True).start()
        threading.Thread(target=self._receive_loop, daemon=True).start()
        
        # Send join request
        self._sr_send(MSG_TYPE_JOIN_REQ)
        print(f"[CONNECTING] to {self.server_ip}:{self.server_port}")

    def disconnect(self):
        """Cleanly disconnect from server"""
        if self.running and self.player_id is not None:
            # Send leave message
            self._sr_send(MSG_TYPE_LEAVE)
            time.sleep(0.1)  # Brief wait for potential ACK
            
        self.running = False
        if self.client_socket:
            self.client_socket.close()
        print("[DISCONNECTED]")

    # ==================== Receive Loop ====================
    def _receive_loop(self):
        """Main receive loop for handling incoming packets"""
        while self.running:
            try:
                data, addr = self.client_socket.recvfrom(2048)
                recv_ms = current_time_ms()
                
                if len(data) < HEADER_SIZE:
                    continue
                    
                header = parse_header(data)
                self.stats['received'] += 1
                
                seq = header["seq_num"]
                msg_type = header["msg_type"]
                payload = data[HEADER_SIZE:]

                # Handle ACK packets
                if msg_type == MSG_TYPE_ACK:
                    self._handle_ack(seq, recv_ms)
                    continue

                # Send ACK for any data packet
                ack_packet = create_ack_packet(ack_num=seq)  # `seq` is the sequence being acknowledged
                self.client_socket.sendto(ack_packet, addr)


                # Handle data packet with SR ARQ ordering
                self._handle_data_packet(seq, msg_type, payload, header)

            except socket.timeout:
                continue
            except Exception as e:
                print(f"[ERROR] in receive loop: {e}")

    def _handle_ack(self, seq, recv_ms):
        """Handle ACK packets"""
        if seq in self.window:
            # Calculate RTT sample
            sent_time = self.send_timestamp.get(seq, recv_ms)
            sampleRTT = recv_ms - sent_time
            
            # Update RTT estimates
            self.estimatedRTT = (1 - self.alpha) * self.estimatedRTT + self.alpha * sampleRTT
            self.devRTT = (1 - self.beta) * self.devRTT + self.beta * abs(sampleRTT - self.estimatedRTT)
            self.RTO = self.estimatedRTT + 4 * self.devRTT
            
            # Remove acknowledged packet
            del self.window[seq]
            del self.timers[seq]
            del self.send_timestamp[seq]
            
            # Slide window if base was acknowledged
            while self.base not in self.window and self.base < self.nextSeqNum:
                self.base += 1
                
            print(f"[ACK] seq={seq}, RTO={self.RTO:.1f}ms, window base={self.base}")
        else:
            print(f"[DUP ACK] seq={seq} already acknowledged")

    def _handle_data_packet(self, seq, msg_type, payload, header):
        """Handle data packets with SR ARQ ordering"""
        # Check if packet is in-order
        if seq == self.expected_seq:
            # Process immediately
            self._process_packet(msg_type, payload, header)
            self.expected_seq += 1
            
            # Deliver any buffered packets
            while self.expected_seq in self.receive_buffer:
                buffered = self.receive_buffer.pop(self.expected_seq)
                self._process_packet(buffered[0], buffered[1], buffered[2])
                self.expected_seq += 1
                
        elif seq > self.expected_seq:
            # Buffer out-of-order packet
            self.receive_buffer[seq] = (msg_type, payload, header)
            print(f"[BUFFER] Out-of-order seq={seq}, expected={self.expected_seq}")
        else:
            # Duplicate packet
            print(f"[DUPLICATE] Old packet seq={seq}")

    # ==================== Packet Processing ====================
    def _process_packet(self, msg_type, payload, header):
        """Process different message types"""
        try:
            if msg_type == MSG_TYPE_JOIN_RESP:
                self.player_id = struct.unpack("!B", payload)[0]
                print(f"[JOINED] Player ID: {self.player_id}")
                
            elif msg_type == MSG_TYPE_BOARD_SNAPSHOT:
                snapshot_id = struct.unpack("!I", payload[:4])[0]
                grid_data = payload[4:]
                self.local_grid = unpack_grid_snapshot(grid_data)
                
                # Notify UI if callback is set
                if self.on_grid_update:
                    self.on_grid_update(self.local_grid, snapshot_id)
                    
                print(f"[SNAPSHOT] ID: {snapshot_id}")
                
            elif msg_type == MSG_TYPE_GAME_START:
                self.game_active = True
                if self.on_game_start:
                    self.on_game_start()
                print("[GAME START]")
                
            elif msg_type == MSG_TYPE_GAME_OVER:
                self.game_active = False
                if self.on_game_over:
                    self.on_game_over()
                print("[GAME OVER]")
                
            elif msg_type == MSG_TYPE_LEAVE:
                print("[LEAVE ACK]")
                
            else:
                print(f"[UNKNOWN] Message type: {msg_type}")
                
        except Exception as e:
            print(f"[ERROR] Processing packet: {e}")

    # ==================== Game Actions ====================
    def send_claim(self, row, col):
        """Send a claim request for a cell"""
        if not self.game_active or self.player_id is None:
            print("[ERROR] Cannot claim - not in game")
            return False
            
        # Validate coordinates
        if not (0 <= row < 20 and 0 <= col < 20):
            print(f"[ERROR] Invalid coordinates ({row},{col})")
            return False
            
        # Pack coordinates
        payload = struct.pack("!BB", row, col)
        
        # Send with SR ARQ
        success = self._sr_send(MSG_TYPE_CLAIM_REQ, payload)
        if success:
            print(f"[CLAIM SENT] Cell ({row},{col})")
        return success

    # ==================== Statistics ====================
    def get_stats(self):
        """Get current statistics"""
        return self.stats.copy()