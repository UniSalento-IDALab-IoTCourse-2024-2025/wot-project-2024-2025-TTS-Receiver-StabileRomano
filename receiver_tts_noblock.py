import asyncio
from bleak import BleakScanner
import socket
import signal
import sys
import pyttsx3
import netifaces
from datetime import datetime
import threading
import queue
import time

#DICHIARATO IL DIZIONARIO DEI BEACON DA CONSIDERARE
BEACONS = {
    "C1:4F:64:D9:F2:80": "014522",
    "C0:7E:31:1C:E3:A9": "014573",
    "D7:DA:5D:26:87:08": "014583",
    "E2:CB:C3:5C:C1:9A": "014594"
}

UDP_PORT = 5005
SCAN_INTERVAL = 5  # Secondi tra le scansioni BLE
LOG_FILE = "beacon_status.log" #QUI VENGONO SALVATI I BEACON RILEVATI
RECEIVED_FILE = "messagges.log" #QUI VENGONO SALVATI I MESSAGGI RICEVUTI

# Variabili globali per il TTS (Istanza motore tts, cosa thread-safe, flag per far
# girare o fermare il thread)
tts_engine = None
tts_queue = queue.Queue()
tts_thread_running = True


def tts_worker():
    #Worker thread per gestire le richieste TTS, preleva i messaggi dalla coda tts
    global tts_engine
    while tts_thread_running:
        try:
            testo = tts_queue.get(timeout=0.5)
            if testo is None:
                continue

            try:
                # Riavvia sempre il motore TTS prima di ogni messaggio per evitare blocchi
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
                #aggiunte delle virgole per non far mangiare parole al riproduttore vocale
                testo = ",,,," + testo
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
    #Aggiunge il testo alla coda TTS
    if not testo:
        return
    try:
        tts_queue.put(testo)
    except Exception as e:
        print(f"Errore durante l'invio alla coda TTS: {e}")


# Avvia il worker TTS all'avvio del modulo
tts_thread = threading.Thread(target=tts_worker, daemon=True)
tts_thread.start()

#Classe per scannerizzare i beacon
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

        # Gestione segnale di interruzione
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, sig, frame):
        #Gestisce la chiusura pulita del programma
        print("\nRicevuto segnale di interruzione, arresto in corso...")
        global tts_thread_running
        tts_thread_running = False
        self.running = False

        try:
            if tts_engine:
                tts_engine.stop()
        except:
            pass

        self.sock.close()
        if hasattr(self, 'tts_thread') and self.tts_thread.is_alive():
            self.tts_thread.join(timeout=1)

        sys.exit(0)

    #ascolta messaggi UDP in arrivo
    async def listen_for_broadcasts(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                if data:
                    # Se l'indirizzo del mittente è locale, ignora il messaggio
                    if addr[0] in self.local_ips:
                        continue

                    async with self.lock:
                        current_beacon = self.current_beacon

                    parts = data.decode().split('|')
                    if len(parts) == 2 and current_beacon:
                        beacon_id, messaggio = parts
                        if beacon_id == current_beacon:
                            print(f"\n[BEACON {beacon_id}] Ricevuto da {addr[0]}:")
                            print(f"Messaggio: '{messaggio}'")
                            tts_da_stringa(messaggio)
                            try:
                                with open(RECEIVED_FILE, 'w') as f:
                                    f.write(messaggio)
                            except Exception as e:
                                print(f"Errore durante il salvataggio del log: {e}")
            except socket.timeout:
                await asyncio.sleep(0.1)
            except Exception as e:
                if self.running:  # Evita messaggi di errore durante la chiusura
                    print(f"Errore ricezione: {e}")

    def _get_local_ips(self):
        #Restituisce una lista di tutti gli indirizzi IP locali (IPv4 e IPv6)
        #Serve a ignorare i messaggi inviati da sè stesso
        ips = []
        try:
            # Ottieni tutte le interfacce di rete
            interfaces = netifaces.interfaces()

            for interface in interfaces:
                # Ignora l'interfaccia di loopback
                if interface == 'lo':
                    continue

                # Ottieni tutti gli indirizzi per questa interfaccia
                addrs = netifaces.ifaddresses(interface)

                # IPv4
                if netifaces.AF_INET in addrs:
                    for addr_info in addrs[netifaces.AF_INET]:
                        ips.append(addr_info['addr'])

                # IPv6 (opzionale)
                if netifaces.AF_INET6 in addrs:
                    for addr_info in addrs[netifaces.AF_INET6]:
                        # Rimuove lo scope ID (es. %eth0)
                        ip = addr_info['addr'].split('%')[0]
                        ips.append(ip)

            # Aggiungi gli indirizzi di loopback standard
            ips.extend(['127.0.0.1', '::1'])

        except Exception as e:
            print(f"Errore ottenimento IP locali: {e}")
            # Fallback agli indirizzi base
            ips.extend(['127.0.0.1', '::1'])

        return ips

    def update_beacon_log(self, beacon_id, rssi):
        #Scrive lo stato corrente del beacon nel file di log
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_line = f"{timestamp} - Beacon attivo: {beacon_id} (RSSI: {rssi} dBm)\n"

        try:
            with open(LOG_FILE, 'w') as f:
                f.write(status_line)
        except Exception as e:
            print(f"Errore durante il salvataggio del log: {e}")

    def clear_beacon_log(self):
        #Pulisce il file di log quando nessun beacon è rilevato
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_line = f"{timestamp} - Nessun beacon rilevato\n"

        try:
            with open(LOG_FILE, 'w') as f:
                f.write(status_line)
        except Exception as e:
            print(f"Errore durante il salvataggio del log: {e}")

    async def scan_beacons(self):
        while self.running:
            try:
                print("Avvio scansione...")
                # Scansione BLE con gestione degli errori specifici
                try:
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
                for d, adv in devices.values():
                    if d.address in BEACONS or (d.name and d.name.startswith("BlueUp-")):
                        beacon_id = BEACONS.get(d.address, "Sconosciuto")
                        found_beacons.append((beacon_id, adv.rssi))

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
                            print("\nNessun beacon rilevato (perso segnale)")
                            self.current_beacon = None
                            self.clear_beacon_log()
                        else:
                            print("\nStato: Nessun beacon rilevato")
                            self.clear_beacon_log()

                await asyncio.sleep(SCAN_INTERVAL)

            except Exception as e:
                if self.running:
                    print(f"Errore durante la scansione: {e}")
                await asyncio.sleep(SCAN_INTERVAL)


async def main():
    listener = BeaconListener()

    try:
        # Avvia tutti i task in parallelo
        await asyncio.gather(
            listener.scan_beacons(),
            listener.listen_for_broadcasts(),
            return_exceptions=True
        )
    except asyncio.CancelledError:
        pass
    finally:
        listener.sock.close()
        print("\nProgramma terminato correttamente")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterruzione da tastiera")
    except Exception as e:
        print(f"Errore: {e}")
    finally:
        # Non serve dichiarare global qui, stiamo solo leggendo il valore
        if 'tts_thread_running' in globals():
            globals()['tts_thread_running'] = False
        if 'tts_thread' in globals() and tts_thread.is_alive():
            tts_thread.join(timeout=1)
        print("Uscita...")