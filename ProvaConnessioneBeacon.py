import asyncio
from bleak import BleakScanner
import socket
import signal
import sys
import pyttsx3

BEACONS = {
    "C1:4F:64:D9:F2:80": "014522",
    "C0:7E:31:1C:E3:A9": "014573",
    "D7:DA:5D:26:87:08": "014583",
    "E2:CB:C3:5C:C1:9A": "014594"
}

UDP_PORT = 5005
SCAN_INTERVAL = 5  # Secondi tra le scansioni BLE

# Inizializzazione motore TTS
try:
    tts_engine = pyttsx3.init('espeak')
    tts_engine.setProperty('rate', 130)
    tts_engine.setProperty('volume', 1.0)
    print("Motore TTS inizializzato")
except Exception as e:
    print(f"Errore inizializzazione TTS: {e}")
    tts_engine = None


def tts_da_stringa(testo):
    if not tts_engine:
        return
    try:
        tts_engine.say(testo)
        tts_engine.runAndWait()
    except Exception as e:
        print(f"Errore sintesi vocale: {e}")


class BeaconListener:
    def __init__(self):
        self.running = True
        self.current_beacon = None

        # Configurazione socket UDP
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', UDP_PORT))

        # Gestione segnali
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, sig, frame):
        print("\nArresto in corso...")
        self.running = False
        self.sock.close()
        if tts_engine:
            tts_engine.stop()

    async def listen_for_broadcasts(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                if data and self.current_beacon:
                    parts = data.decode().split('|')
                    if len(parts) == 2:
                        beacon_id, messaggio = parts
                        if beacon_id == self.current_beacon:
                            print(f"\n[BEACON {beacon_id}] Messaggio: '{messaggio}'")
                            tts_da_stringa(messaggio)
            except socket.timeout:
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Errore ricezione: {e}")

    async def scan_beacons(self):
        while self.running:
            try:
                devices = await BleakScanner.discover(timeout=1.5)
                found_beacons = []

                for d in devices:
                    if d.address in BEACONS:
                        beacon_id = BEACONS[d.address]
                        found_beacons.append((beacon_id, d.rssi))

                if found_beacons:
                    found_beacons.sort(key=lambda x: x[1], reverse=True)
                    closest_beacon = found_beacons[0][0]

                    if closest_beacon != self.current_beacon:
                        print(f"\nBeacon vicino: {closest_beacon}")
                        self.current_beacon = closest_beacon
                else:
                    if self.current_beacon is not None:
                        print("\nNessun beacon rilevato")
                        self.current_beacon = None

                await asyncio.sleep(SCAN_INTERVAL)
            except Exception as e:
                print(f"Errore scansione: {e}")
                await asyncio.sleep(SCAN_INTERVAL)


async def main():
    listener = BeaconListener()
    await asyncio.gather(
        listener.scan_beacons(),
        listener.listen_for_broadcasts()
    )


if __name__ == "__main__":
    asyncio.run(main())