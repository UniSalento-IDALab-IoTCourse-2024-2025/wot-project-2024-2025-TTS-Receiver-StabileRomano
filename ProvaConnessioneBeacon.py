import asyncio
from bleak import BleakScanner
import socket
import signal
import sys
import uuid
import platform

BEACONS = {
    "C1:4F:64:D9:F2:80": "014522",
    "C0:7E:31:1C:E3:A9": "014573",
    "D7:DA:5D:26:87:08": "014583",
    "E2:CB:C3:5C:C1:9A": "014594"
}

UDP_PORT = 5005
SCAN_INTERVAL = 15
BROADCAST_INTERVAL = 5

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

    async def scan_beacons(self):
        while self.running:
            try:
                devices = await BleakScanner.discover(timeout=1.5, return_adv=True)
                found = []

                for d, adv in devices.values():
                    if d.address in BEACONS or (d.name and d.name.startswith("BlueUp-")):
                        beacon_id = BEACONS.get(d.address, "Sconosciuto")
                        found.append((beacon_id, adv.rssi))

                if found:
                    found.sort(key=lambda x: x[1], reverse=True)
                    closest = found[0][0]
                    async with self.lock:
                        if closest != self.current_beacon:
                            self.current_beacon = closest
                else:
                    async with self.lock:
                        self.current_beacon = None

                await asyncio.sleep(SCAN_INTERVAL)
            except asyncio.CancelledError:
                break
            except:
                await asyncio.sleep(SCAN_INTERVAL)

    async def broadcast_message(self):
        while self.running:
            async with self.lock:
                if self.current_beacon:
                    msg = f"{self.current_beacon}|{self.sender_id}|{MESSAGGIO_PERSONALIZZATO}"
                    try:
                        self.sock_send.sendto(msg.encode(), (BROADCAST_IP, UDP_PORT))
                    except:
                        pass
            await asyncio.sleep(BROADCAST_INTERVAL)
