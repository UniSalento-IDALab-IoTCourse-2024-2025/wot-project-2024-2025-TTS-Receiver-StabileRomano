import asyncio
from bleak import BleakScanner
import socket
import signal
import sys
import pyttsx3
import netifaces
import threading
import queue
from datetime import datetime

BEACONS = {
    "C1:4F:64:D9:F2:80": "014522",
    "C0:7E:31:1C:E3:A9": "014573",
    "D7:DA:5D:26:87:08": "014583",
    "E2:CB:C3:5C:C1:9A": "014594"
}

UDP_PORT = 5005
SCAN_INTERVAL = 5  # Secondi tra le scansioni BLE
LOG_FILE = "beacon_status.log"

# Variabili globali per il TTS
tts_engine = None
tts_queue = queue.Queue()
tts_thread_running = True


def tts_worker():
    global tts_engine
    while tts_thread_running:
        try:
            testo = tts_queue.get(timeout=0.5)
            if testo is None:
                continue

            try:
                if tts_engine:
                    tts_engine.stop()
                    tts_engine = None

                tts_engine = pyttsx3.init('espeak')
                tts_engine.setProperty('rate', 130)
                tts_engine.setProperty('volume', 1.0)

                # Configura voce italiana se disponibile
                voices = tts_engine.getProperty('voices')
                for voice in voices:
                    if 'italian' in voice.id.lower() or 'italian' in voice.name.lower():
                        tts_engine.setProperty('voice', voice.id)
                        break

                tts_engine.say(testo)
                tts_engine.runAndWait()
            except Exception as e:
                print(f"Errore TTS: {e}")
                try:
                    if tts_engine:
                        tts_engine.stop()
                except:
                    pass
                tts_engine = None
        except queue.Empty:
            continue
        except Exception as e:
            print(f"Errore nel worker TTS: {e}")


def tts_da_stringa(testo):
    if not testo:
        return
    try:
        tts_queue.put(testo)
    except Exception as e:
        print(f"Errore durante l'invio alla coda TTS: {e}")


# Avvia il worker TTS
tts_thread = threading.Thread(target=tts_worker, daemon=True)
tts_thread.start()


class BeaconListener:
    def __init__(self):
        self.running = True
        self.current_beacon = None
        self.lock = asyncio.Lock()
        self.local_ips = self._get_local_ips()

        # Configurazione socket UDP
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', UDP_PORT))
        self.sock.settimeout(0.1)

        # Gestione segnali
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def _get_local_ips(self):
        ips = []
        try:
            interfaces = netifaces.interfaces()
            for interface in interfaces:
                if interface == 'lo':
                    continue
                addrs = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addrs:
                    for addr_info in addrs[netifaces.AF_INET]:
                        ips.append(addr_info['addr'])
                if netifaces.AF_INET6 in addrs:
                    for addr_info in addrs[netifaces.AF_INET6]:
                        ip = addr_info['addr'].split('%')[0]
                        ips.append(ip)
            ips.extend(['127.0.0.1', '::1'])
        except Exception as e:
            print(f"Errore ottenimento IP locali: {e}")
            ips = ['127.0.0.1', '::1']
        return ips

    def signal_handler(self, sig, frame):
        print("\nArresto in corso...")
        global tts_thread_running
        tts_thread_running = False
        self.running = False

        try:
            if tts_engine:
                tts_engine.stop()
        except:
            pass

        self.sock.close()

    def update_beacon_log(self, beacon_id, rssi):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_line = f"{timestamp} - Beacon attivo: {beacon_id} (RSSI: {rssi} dBm)\n"
        try:
            with open(LOG_FILE, 'w') as f:
                f.write(status_line)
        except Exception as e:
            print(f"Errore salvataggio log: {e}")

    def clear_beacon_log(self):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_line = f"{timestamp} - Nessun beacon rilevato\n"
        try:
            with open(LOG_FILE, 'w') as f:
                f.write(status_line)
        except Exception as e:
            print(f"Errore salvataggio log: {e}")

    async def listen_for_broadcasts(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                if data:
                    if addr[0] in self.local_ips:
                        continue

                    async with self.lock:
                        current_beacon = self.current_beacon

                    if current_beacon:
                        parts = data.decode().split('|')
                        if len(parts) == 2:
                            beacon_id, messaggio = parts
                            if beacon_id == current_beacon:
                                print(f"\n[BEACON {beacon_id}] Messaggio: '{messaggio}'")
                                tts_da_stringa(messaggio)
            except socket.timeout:
                await asyncio.sleep(0.1)
            except Exception as e:
                if self.running:
                    print(f"Errore ricezione: {e}")

    async def scan_beacons(self):
        while self.running:
            try:
                print("Avvio scansione...")
                try:
                    # Utilizza return_adv per ottenere i dati di advertising
                    devices = await BleakScanner.discover(timeout=1.5, return_adv=True)
                except Exception as e:
                    error_msg = str(e)
                    if "Operation already in progress" in error_msg:
                        print("Scansione già in corso, attendo...")
                        await asyncio.sleep(SCAN_INTERVAL)
                        continue
                    elif "No power bluetooth adapter found" in error_msg:
                        print("Adapter Bluetooth non disponibile, riprovo...")
                        await asyncio.sleep(SCAN_INTERVAL * 2)
                        continue
                    raise

                found_beacons = []
                # Itera su tutti i dispositivi con i loro dati di advertising
                for d, adv in devices.values():
                    # Supporta sia indirizzi MAC che nomi BlueUp
                    if d.address in BEACONS or (d.name and d.name.startswith("BlueUp-")):
                        beacon_id = BEACONS.get(d.address, "Sconosciuto")
                        rssi = adv.rssi  # Ottieni RSSI dai dati di advertising
                        found_beacons.append((beacon_id, rssi))

                async with self.lock:
                    if found_beacons:
                        found_beacons.sort(key=lambda x: x[1], reverse=True)
                        closest_beacon = found_beacons[0][0]
                        closest_rssi = found_beacons[0][1]

                        if closest_beacon != self.current_beacon:
                            print(f"\nBeacon vicino: {closest_beacon} (RSSI: {closest_rssi} dBm)")
                            self.current_beacon = closest_beacon
                            self.update_beacon_log(closest_beacon, closest_rssi)
                    else:
                        if self.current_beacon is not None:
                            print("\nNessun beacon rilevato")
                            self.current_beacon = None
                            self.clear_beacon_log()
                        else:
                            self.clear_beacon_log()

                await asyncio.sleep(SCAN_INTERVAL)
            except Exception as e:
                if self.running:
                    print(f"Errore scansione: {e}")
                await asyncio.sleep(SCAN_INTERVAL)


async def main():
    listener = BeaconListener()
    await asyncio.gather(
        listener.scan_beacons(),
        listener.listen_for_broadcasts()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterruzione da tastiera")
    except Exception as e:
        print(f"Errore: {e}")
    finally:
        # Segnala al thread TTS di terminare
        tts_thread_running = False
        if tts_thread.is_alive():
            tts_thread.join(timeout=1)
        print("Uscita...")