import asyncio
import socket
import signal
import sys
import uuid
import platform

#  Configurazione beacon
BEACONS = {
    "C1:4F:64:D9:F2:80": "014522",
    "C0:7E:31:1C:E3:A9": "014573",
    "D7:DA:5D:26:87:08": "014583",
    "E2:CB:C3:5C:C1:9A": "014594"
}

UDP_PORT = 5005
SCAN_INTERVAL = 15
BROADCAST_INTERVAL = 5

#  Rileva il sistema operativo
if platform.system() == "Windows":
    MESSAGGIO_PERSONALIZZATO = "Sono il Windows"
    BROADCAST_IP = "192.168.1.255"
else:
    MESSAGGIO_PERSONALIZZATO = "Sono il Raspberry"
    BROADCAST_IP = "<broadcast>"

class BeaconCommander:
    def __init__(self):
        self.running = True
        self.current_beacon = None
        self.lock = asyncio.Lock()
        self.sender_id = str(uuid.uuid4())[:8]

        self.sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self.sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock_recv.bind(('0.0.0.0', UDP_PORT))
        self.sock_recv.settimeout(0.1)

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, sig, frame):
        self.running = False

    def stop(self):
        try:
            self.sock_recv.close()
        except:
            pass
        try:
            self.sock_send.close()
        except:
            pass
