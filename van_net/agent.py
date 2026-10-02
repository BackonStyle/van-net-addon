"""
Van-Net-Agent -- verbindet RUTC50 eSIM mit Home Assistant ueber MQTT.

Aufgaben:
  - Router-Status pollen und als MQTT-Discovery-Entities veroeffentlichen
  - Standzeit erkennen (GPS-Geschwindigkeit), nur dann WLAN scannen
  - Passende WLANs automatisch verbinden
  - Captive Portals automatisch bedienen, sonst QR-Fallback
  - WLAN-Geschwindigkeit messen
  - Manuellen WAN-Umschalter aus HA entgegennehmen

Das automatische Failover WLAN -> SIM macht der Router selbst (mwan3).
Der Agent mischt sich da nicht ein; er zeigt nur an, was aktiv ist, und
erlaubt das manuelle Erzwingen. So bleibt die Internetverbindung auch dann
bestehen, wenn dieser Agent oder Home Assistant gerade neu startet.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time

import paho.mqtt.client as mqtt
import yaml

from portal import PortalAutomation, check_internet, make_qr
from router import Router, RouterError

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)-8s %(message)s",
)
log = logging.getLogger("agent")

DISCOVERY_PREFIX = "homeassistant"
NODE = "van_net"
DEVICE = {
    "identifiers": [NODE],
    "name": "Van Netzwerk",
    "manufacturer": "Teltonika",
    "model": "RUTC50 eSIM",
}

WAN_MODES = ["Auto", "WLAN erzwingen", "SIM erzwingen"]

# Kartenschaechte und eSIM-Profile des RUTC50.
# position = physischer Schacht, esim = Profilnummer auf der eSIM,
# iface = Name in mwan3. Siehe 'mwan3 status' am Router.
SIM_SLOTS = [
    {"label": "SIM 1 (Schacht)",   "position": 1, "esim": None, "iface": "mob1s1a1"},
    {"label": "SIM 2 (Schacht)",   "position": 2, "esim": None, "iface": "mob1s2a1"},
    {"label": "eSIM Profil 1",     "position": 3, "esim": 1,    "iface": "mob1s3a1e1"},
    {"label": "eSIM Profil 2",     "position": 3, "esim": 2,    "iface": "mob1s3a1e2"},
]
MODE_TO_INTERNAL = {
    "Auto": "auto",
    "WLAN erzwingen": "wifi",
    "SIM erzwingen": "mobile",
}


class Agent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        r = cfg["router"]
        self.router = Router(
            host=r["host"],
            username=r.get("username", "root"),
            key_file=r.get("ssh_key"),
            password=r.get("password"),
            port=r.get("port", 22),
        )

        w = cfg["wifi"]
        self.client_device = w["client_device"]        # z.B. wlan0 (2.4 GHz)
        self.wifi_iface = w["wan_interface"]           # mwan3-Name, z.B. wwan
        self.mobile_iface = cfg["mobile"]["wan_interface"]  # z.B. mob1s1a1
        self.known = {n["ssid"]: n.get("password") for n in w.get("known_networks", [])}
        self.blocklist = set(w.get("blocked_ssids", []))
        self.min_signal = w.get("min_signal_dbm", -78)
        self.allow_open = w.get("auto_connect_open", True)

        m = cfg["movement"]
        self.stationary_kmh = m.get("stationary_below_kmh", 3.0)
        self.stationary_after = m.get("stationary_after_seconds", 180)

        p = cfg["portal"]
        self.portal = PortalAutomation(
            screenshot_dir=p.get("screenshot_dir", "/share/van-net/screenshots"),
            max_rounds=p.get("max_rounds", 3),
        )
        self.qr_path = p.get("qr_path", "/share/van-net/www/portal_qr.png")
        self.qr_public = p.get("qr_public_path", "/local/van-net/portal_qr.png")

        self.poll_interval = cfg.get("poll_interval_seconds", 20)
        self.scan_cooldown = cfg["wifi"].get("scan_cooldown_seconds", 300)

        # Laufzeitzustand
        self.state = {
            "wan_mode": "Auto",
            "active_wan": "unknown",
            "uplink_ssid": "",
            "wifi_signal": None,
            "wifi_speed_mbps": None,
            "internet_ok": False,
            "portal_state": "idle",   # idle|detected|solving|manual|ok|failed
            "portal_url": "",
            "speed_kmh": None,
            "stationary": False,
            "rssi": None,
            "rsrp": None,
            "rsrq": None,
            "sinr": None,
            "net_mode": "",
            "last_scan": "",
            "last_error": "",
            "selected_ssid": "",
            "connect_status": "bereit",
            "gps_fix": False,
            "gps_sats": None,
            "position_age": "",
            "sim_slot": "",
            "ap_locked": "",
            "ap_count": None,
            "ap_score": None,
            "modem_temp": None,
            "thermal_zone": "",
            "throttling": False,
            "last_backup": "",
        }
        self._moving_since = time.time()
        self._last_scan_ts = 0.0
        self._failed_ssids = {}       # ssid -> timestamp
        self._stop = threading.Event()
        self._busy = threading.Lock()

        # Manuelle WLAN-Auswahl aus Home Assistant
        self._found = []              # letzte Scanergebnisse fuer das Dropdown
        self._pending_password = ""   # bewusst NICHT im State -- siehe _on_message
        self._learned_path = "/data/learned_networks.json"
        self._learned = self._load_learned()
        self._learned_ap_path = "/data/learned_aps.json"
        self._learned_aps = self._load_json(self._learned_ap_path, "Basisstationen")

        # Standortmeldung: bewusst sparsam.
        # GPS wird weiter im Poll-Takt gelesen (fuer die Standzeit-Erkennung),
        # die Position aber nur alle 30 Minuten nach HA geschickt. Das haelt
        # die Datenbank klein und erzeugt keine Bewegungsspur im Minutentakt.
        g = cfg.get("gps", {}) or {}
        self.position_interval = g.get("publish_interval_seconds", 1800)
        self._last_position_ts = 0.0
        self._last_position = None

        self.mqtt = self._make_mqtt(cfg["mqtt"])

    # ------------------------------------------- Gelernte Netze (persistent)

    def _load_json(self, path: str, was: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                log.info("%d gelernte %s geladen", len(data), was)
                return data
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning("%s nicht lesbar: %s", was, exc)
        return {}

    def _load_learned(self) -> dict:
        """
        Netze, deren Passwort du einmal in HA eingetippt hast.

        Liegt unter /data und ueberlebt Neustarts und App-Updates. Damit
        verbindet sich der Van beim naechsten Besuch desselben Campingplatzes
        von selbst, ohne dass du das Passwort erneut suchen musst.
        """
        try:
            with open(self._learned_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                log.info("%d gelernte Netze geladen", len(data))
                return data
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning("Gelernte Netze nicht lesbar: %s", exc)
        return {}

    def _remember(self, ssid: str, password) -> None:
        self._learned[ssid] = password or None
        try:
            with open(self._learned_path, "w", encoding="utf-8") as fh:
                json.dump(self._learned, fh)
            os.chmod(self._learned_path, 0o600)
            log.info("'%s' gemerkt fuer kuenftige Besuche", ssid)
        except Exception as exc:
            log.warning("Netz konnte nicht gemerkt werden: %s", exc)

    def _password_for(self, ssid: str):
        """Passwort aus App-Konfiguration oder gelernten Netzen."""
        if ssid in self.known:
            return self.known[ssid]
        return self._learned.get(ssid)

    def _all_known_ssids(self) -> set:
        return set(self.known) | set(self._learned)

    # ------------------------------------------------------------------- MQTT

    def _make_mqtt(self, mcfg):
        client = mqtt.Client(client_id=f"{NODE}-agent")
        if mcfg.get("username"):
            client.username_pw_set(mcfg["username"], mcfg.get("password", ""))
        client.will_set(f"{NODE}/availability", "offline", retain=True)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.connect(mcfg["host"], mcfg.get("port", 1883), keepalive=60)
        client.loop_start()
        return client

    def _on_connect(self, client, _ud, _flags, rc):
        log.info("MQTT verbunden (rc=%s)", rc)
        client.publish(f"{NODE}/availability", "online", retain=True)
        client.subscribe(f"{NODE}/cmd/#")
        self._publish_discovery()
        self._publish_state()

    def _on_message(self, _client, _ud, msg):
        topic = msg.topic.rsplit("/", 1)[-1]
        payload = msg.payload.decode("utf-8", "replace").strip()
        log.info("Befehl: %s = %s", topic, payload)
        try:
            if topic == "wan_mode":
                self._set_wan_mode(payload)
            elif topic == "scan_now":
                threading.Thread(target=self.scan_and_connect,
                                 kwargs={"forced": True}, daemon=True).start()
            elif topic == "portal_retry":
                threading.Thread(target=self.handle_portal, daemon=True).start()
            elif topic == "speedtest_now":
                threading.Thread(target=self.run_speedtest, daemon=True).start()
            elif topic == "selected_ssid":
                ssid = self._display_to_ssid(payload)
                self.state["selected_ssid"] = ssid
                self.mqtt.publish(f"{NODE}/selected_display", payload, retain=True)
                if not ssid:
                    self.state["connect_status"] = "nichts ausgewaehlt"
                elif self._password_for(ssid):
                    self.state["connect_status"] = "Passwort bekannt"
                elif self._is_open(ssid):
                    self.state["connect_status"] = "offenes Netz"
                else:
                    self.state["connect_status"] = "Passwort noetig"
                self._publish_state()
            elif topic == "wifi_password":
                # Das Passwort wird NICHT in den State uebernommen -- der State
                # ist ein retained MQTT-Topic und landet im HA-Verlauf.
                # Es bleibt nur im Arbeitsspeicher bis zum Verbinden.
                self._pending_password = payload
                self._clear_password_field()
                self.state["connect_status"] = "Passwort eingegeben"
                self._publish_state()
            elif topic == "connect_selected":
                threading.Thread(target=self.connect_selected, daemon=True).start()
            elif topic == "router_reboot":
                threading.Thread(target=self.reboot_router, daemon=True).start()
            elif topic == "probe_aps":
                threading.Thread(target=self.probe_access_points,
                                 daemon=True).start()
            elif topic == "sim_slot":
                threading.Thread(target=self.switch_sim, args=(payload,),
                                 daemon=True).start()
            elif topic == "backup_now":
                threading.Thread(target=self.backup_router, daemon=True).start()
            elif topic == "position_now":
                threading.Thread(target=self.publish_position,
                                 kwargs={"forced": True}, daemon=True).start()
        except Exception as exc:
            log.exception("Befehl fehlgeschlagen")
            self.state["last_error"] = str(exc)[:200]
            self._publish_state()

    def _disc(self, component, object_id, payload):
        payload.setdefault("state_topic", f"{NODE}/state")
        payload.update({
            "availability_topic": f"{NODE}/availability",
            "device": DEVICE,
            "unique_id": f"{NODE}_{object_id}",
        })
        self.mqtt.publish(
            f"{DISCOVERY_PREFIX}/{component}/{NODE}/{object_id}/config",
            json.dumps(payload), retain=True)

    def _display_to_ssid(self, display: str) -> str:
        """
        Anzeigetext aus dem Dropdown zurueck in die echte SSID uebersetzen.

        Das Dropdown zeigt '*#Netzname (-62 dBm)'. Statt zu zerlegen,
        vergleichen wir mit den Scanergebnissen -- so bleiben SSIDs mit
        Klammern oder Sonderzeichen intakt.
        """
        for ap in self._found:
            if self._display_for(ap) == display:
                return ap["ssid"]
        return ""

    def _display_for(self, ap: dict) -> str:
        mark = "*" if ap["ssid"] in self._all_known_ssids() else ""
        lock = "" if ap["open"] else "#"
        return f"{mark}{lock}{ap['ssid']} ({ap['signal']} dBm)"

    def _is_open(self, ssid: str) -> bool:
        for ap in self._found:
            if ap["ssid"] == ssid:
                return bool(ap["open"])
        return False

    def _clear_password_field(self):
        """Eingabefeld leeren, damit kein Passwort in der Oberflaeche steht."""
        self.mqtt.publish(f"{NODE}/password_state", "", retain=True)

    def _publish_network_list(self):
        """
        Dropdown mit den gefundenen Netzen neu veroeffentlichen.

        MQTT-Discovery kennt keine dynamischen Optionen, deshalb schicken wir
        die Konfiguration nach jedem Scan erneut -- mit der aktuellen Liste.
        """
        options = [self._display_for(ap) for ap in self._found]
        if not options:
            options = ["(noch nicht gesucht)"]

        self._disc("select", "selected_ssid", {
            "name": "Gefundenes WLAN",
            "icon": "mdi:wifi-settings",
            "options": options[:40],
            "command_topic": f"{NODE}/cmd/selected_ssid",
            "state_topic": f"{NODE}/selected_display",
            "command_template": "{{ value }}",
        })
        self.mqtt.publish(f"{NODE}/selected_display",
                          options[0] if self._found else "(noch nicht gesucht)",
                          retain=True)

    def _publish_discovery(self):
        # Der manuelle Umschalter
        self._disc("select", "wan_mode", {
            "name": "WAN-Modus",
            "icon": "mdi:swap-horizontal",
            "options": WAN_MODES,
            "command_topic": f"{NODE}/cmd/wan_mode",
            "value_template": "{{ value_json.wan_mode }}",
        })

        sensors = [
            ("active_wan", "Aktiver Uplink", "mdi:transit-connection-variant", None, None),
            ("uplink_ssid", "Verbundenes WLAN", "mdi:wifi", None, None),
            ("wifi_signal", "WLAN-Signal", "mdi:wifi-strength-3", "dBm", "signal_strength"),
            ("wifi_speed_mbps", "WLAN-Geschwindigkeit", "mdi:speedometer", "Mbit/s", None),
            ("speed_kmh", "Fahrzeuggeschwindigkeit", "mdi:car-speed-limiter", "km/h", None),
            ("rsrp", "Mobilfunk RSRP", "mdi:signal-cellular-outline", "dBm", "signal_strength"),
            ("rsrq", "Mobilfunk RSRQ", "mdi:signal-cellular-outline", "dB", None),
            ("sinr", "Mobilfunk SINR", "mdi:signal-variant", "dB", None),
            ("rssi", "Mobilfunk RSSI", "mdi:antenna", "dBm", "signal_strength"),
            ("net_mode", "Mobilfunk Netzmodus", "mdi:network-outline", None, None),
            ("portal_state", "Portal-Status", "mdi:shield-account", None, None),
            ("portal_url", "Portal-Adresse", "mdi:link-variant", None, None),
            ("last_scan", "Letzter Scan", "mdi:radar", None, None),
            ("last_error", "Letzter Fehler", "mdi:alert-circle-outline", None, None),
            ("selected_ssid", "Ausgewaehltes WLAN", "mdi:wifi-cog", None, None),
            ("connect_status", "Verbindungsstatus", "mdi:progress-wrench", None, None),
            ("modem_temp", "Modemtemperatur", "mdi:thermometer", "\u00b0C", "temperature"),
            ("thermal_zone", "Thermikzone", "mdi:thermometer-alert", None, None),
            ("last_backup", "Letzte Router-Sicherung", "mdi:content-save-check", None, None),
            ("ap_locked", "Gebundene Basisstation", "mdi:access-point", None, None),
            ("ap_count", "Basisstationen im Netz", "mdi:access-point-network", None, None),
        ]
        for oid, name, icon, unit, devclass in sensors:
            payload = {
                "name": name,
                "icon": icon,
                "value_template": "{{ value_json.%s }}" % oid,
            }
            if unit:
                payload["unit_of_measurement"] = unit
                payload["state_class"] = "measurement"
            if devclass:
                payload["device_class"] = devclass
            self._disc("sensor", oid, payload)

        for oid, name, icon, devclass in [
            ("internet_ok", "Internet verfuegbar", "mdi:web-check", "connectivity"),
            ("stationary", "Fahrzeug steht", "mdi:parking", None),
            ("throttling", "Modem drosselt", "mdi:speedometer-slow", "problem"),
        ]:
            payload = {
                "name": name,
                "icon": icon,
                "value_template": "{{ 'ON' if value_json.%s else 'OFF' }}" % oid,
                "payload_on": "ON",
                "payload_off": "OFF",
            }
            if devclass:
                payload["device_class"] = devclass
            self._disc("binary_sensor", oid, payload)

        # Manuelle WLAN-Auswahl: Dropdown, Passwortfeld, Verbinden
        self._publish_network_list()

        self._disc("text", "wifi_password", {
            "name": "WLAN-Passwort",
            "icon": "mdi:form-textbox-password",
            "mode": "password",
            "min": 0,
            "max": 64,
            "command_topic": f"{NODE}/cmd/wifi_password",
            "state_topic": f"{NODE}/password_state",
        })
        self._clear_password_field()

        # SIM-Auswahl: physische Schaechte und eSIM-Profile
        self._disc("select", "sim_slot", {
            "name": "SIM-Karte",
            "icon": "mdi:sim",
            "options": [s["label"] for s in SIM_SLOTS],
            "command_topic": f"{NODE}/cmd/sim_slot",
            "value_template": "{{ value_json.sim_slot }}",
        })

        # Standort -- Zustand bleibt generisch, die Koordinaten stehen in den
        # Attributen. So landet keine Positionsangabe im Zustandsverlauf.
        self._disc("device_tracker", "position", {
            "name": "Van Standort",
            "icon": "mdi:van-passenger",
            "state_topic": f"{NODE}/availability",
            "payload_home": "online",
            "payload_not_home": "offline",
            "source_type": "gps",
            "json_attributes_topic": f"{NODE}/position",
        })

        for oid, name, icon in [
            ("connect_selected", "Mit ausgewaehltem WLAN verbinden", "mdi:wifi-plus"),
            ("probe_aps", "Beste Basisstation suchen", "mdi:access-point-network"),
            ("position_now", "Standort jetzt abfragen", "mdi:crosshairs-gps"),
            ("backup_now", "Router jetzt sichern", "mdi:content-save-cog"),
            ("router_reboot", "Router neu starten", "mdi:restart-alert"),
            ("scan_now", "Jetzt WLAN suchen", "mdi:wifi-refresh"),
            ("portal_retry", "Portal-Login wiederholen", "mdi:login-variant"),
            ("speedtest_now", "Speedtest starten", "mdi:speedometer"),
        ]:
            self._disc("button", oid, {
                "name": name,
                "icon": icon,
                "command_topic": f"{NODE}/cmd/{oid}",
            })

        log.info("MQTT-Discovery veroeffentlicht")

    def _publish_state(self):
        self.mqtt.publish(f"{NODE}/state", json.dumps(self.state), retain=True)

    # -------------------------------------------------------------- WAN-Modus

    def _set_wan_mode(self, label: str):
        if label not in MODE_TO_INTERNAL:
            log.warning("Unbekannter WAN-Modus: %s", label)
            return
        internal = MODE_TO_INTERNAL[label]
        self.router.set_wan_preference(internal, self.wifi_iface, self.mobile_iface)
        self.state["wan_mode"] = label
        self.state["last_error"] = ""
        self._publish_state()

    # ----------------------------------------------------------------- Polling

    def poll(self):
        try:
            # GPS wird hier im Poll-Takt gelesen, aber nur fuer die
            # Geschwindigkeit. Die Position geht separat und viel seltener
            # raus -- siehe publish_position().
            gps = self.router.gps()
            if gps:
                self.state["speed_kmh"] = gps.get("speed_kmh")
                self.state["gps_fix"] = bool(gps.get("fix"))
                self._update_stationary(gps.get("speed_kmh", 0.0))
            else:
                self.state["gps_fix"] = False

            link = self.router.wifi_link(self.client_device)
            self.state["uplink_ssid"] = link.get("ssid") or ""
            self.state["wifi_signal"] = link.get("signal")

            # Thermik -- nur jeden fuenften Durchlauf, aendert sich langsam
            self._therm_tick = getattr(self, "_therm_tick", 0) + 1
            if self._therm_tick % 5 == 1:
                th = self.router.thermal()
                if th:
                    self.state["modem_temp"] = th["temp_c"]
                    self.state["thermal_zone"] = th["zone"]
                    was = self.state["throttling"]
                    self.state["throttling"] = th["throttling"]
                    if th["throttling"] and not was:
                        log.warning("Modem drosselt: %.1f C, Grenze %.1f C",
                                    th["temp_c"], th["limit_c"])

            # Mobilfunk-Signalwerte -- Grundlage der Durchsatzschaetzung in HA
            sig = self.router.signal()
            for key in ("rssi", "rsrp", "rsrq", "sinr"):
                if key in sig:
                    self.state[key] = sig[key]
            if "net_mode" in sig:
                self.state["net_mode"] = sig["net_mode"]

            self.state["active_wan"] = self.router.active_wan(
                self.wifi_iface, self.mobile_iface)

            open_net, portal_url = check_internet()
            self.state["internet_ok"] = open_net
            if open_net and self.state["portal_state"] in ("detected", "solving"):
                self.state["portal_state"] = "ok"
            elif portal_url and not open_net:
                self.state["portal_url"] = portal_url
                if self.state["portal_state"] == "idle":
                    self.state["portal_state"] = "detected"

            self.state["last_error"] = ""
        except RouterError as exc:
            log.warning("Router nicht erreichbar: %s", exc)
            self.state["last_error"] = str(exc)[:200]
        finally:
            self._publish_state()

    def _update_stationary(self, speed_kmh: float):
        now = time.time()
        if speed_kmh is None:
            return
        war = self.state["stationary"]
        if speed_kmh > self.stationary_kmh:
            self._moving_since = now
            self.state["stationary"] = False
        else:
            self.state["stationary"] = (now - self._moving_since) >= self.stationary_after

        # Beim Wechsel fahrend -> stehend die Position sofort melden, statt bis
        # zu 30 Minuten zu warten. Davon haengen die Zonen-Automationen ab:
        # ohne frische Position merkt Home Assistant die Ankunft zu spaet.
        if self.state["stationary"] and not war:
            log.info("Fahrzeug steht -- melde Position ausserplanmaessig")
            threading.Thread(target=self.publish_position,
                             kwargs={"forced": True}, daemon=True).start()

    # --------------------------------------------------- Scannen und Verbinden

    def _candidate_networks(self, scan_results):
        """Scanergebnisse filtern und priorisieren."""
        now = time.time()
        candidates = []
        for ap in scan_results:
            ssid = ap["ssid"]
            if ssid in self.blocklist:
                continue
            if ap["signal"] < self.min_signal:
                continue
            # Netze, die vor kurzem gescheitert sind, 1 h ueberspringen
            if now - self._failed_ssids.get(ssid, 0) < 3600:
                continue
            if ssid in self._all_known_ssids():
                candidates.append((0, -ap["signal"], ap))   # bekannt = Prio 0
            elif ap["open"] and self.allow_open:
                candidates.append((1, -ap["signal"], ap))   # offen = Prio 1
        candidates.sort(key=lambda c: (c[0], c[1]))
        return [c[2] for c in candidates]

    def scan_and_connect(self, forced: bool = False) -> bool:
        if not self._busy.acquire(blocking=False):
            log.info("Scan laeuft bereits")
            return False
        try:
            if not forced:
                if not self.state["stationary"]:
                    log.debug("Fahrzeug faehrt -- kein Scan")
                    return False
                if time.time() - self._last_scan_ts < self.scan_cooldown:
                    return False

            log.info("Starte WLAN-Scan auf %s", self.client_device)
            self._last_scan_ts = time.time()
            self.state["last_scan"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._publish_state()

            results = self.router.scan(self.client_device)
            log.info("%d Netze gefunden", len(results))

            # Dropdown in Home Assistant mit den Fundstellen fuellen
            self._found = results
            self._publish_network_list()

            for ap in self._candidate_networks(results):
                ssid = ap["ssid"]
                log.info("Versuche '%s' (%d dBm, %s)", ssid, ap["signal"],
                         "offen" if ap["open"] else "verschluesselt")
                try:
                    self.router.connect_wifi(
                        ssid, key=self._password_for(ssid),
                        bssid=self._learned_aps.get(ssid))
                except RouterError as exc:
                    log.warning("Verbindung zu '%s' fehlgeschlagen: %s", ssid, exc)
                    self._failed_ssids[ssid] = time.time()
                    continue

                if not self._wait_for_association(ssid):
                    self._failed_ssids[ssid] = time.time()
                    continue

                self.state["uplink_ssid"] = ssid
                self._publish_state()

                open_net, portal_url = check_internet()
                if not open_net and portal_url:
                    self.state["portal_url"] = portal_url
                    self.state["portal_state"] = "detected"
                    self._publish_state()
                    if not self.handle_portal():
                        self._failed_ssids[ssid] = time.time()
                        continue
                elif not open_net:
                    log.info("'%s' assoziiert, aber kein Internet", ssid)
                    self._failed_ssids[ssid] = time.time()
                    continue

                log.info("'%s' erfolgreich verbunden", ssid)
                self.state["internet_ok"] = True
                self._publish_state()
                self.run_speedtest()
                return True

            log.info("Kein brauchbares WLAN -- Router bleibt per Failover auf SIM")
            return False
        except RouterError as exc:
            log.warning("Scan fehlgeschlagen: %s", exc)
            self.state["last_error"] = str(exc)[:200]
            self._publish_state()
            return False
        finally:
            self._busy.release()

    def _wait_for_association(self, ssid: str, timeout: int = 45) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(3)
            try:
                link = self.router.wifi_link(self.client_device)
            except RouterError:
                continue
            if link.get("connected") and link.get("ssid") == ssid:
                time.sleep(4)   # DHCP abwarten
                return True
        log.warning("'%s' nicht assoziiert nach %ds", ssid, timeout)
        return False

    # ------------------------------------------- Beste Basisstation finden

    @staticmethod
    def _score(q: dict, mbps) -> float:
        """
        Eine Zahl aus Durchsatz, Latenz und Paketverlust.

            Punkte = min(Mbit/s, 100) x 100/(100+Latenz_ms) x (1 - Verlust)

        Der Durchsatz treibt das Ergebnis, wird aber bei 100 Mbit/s gedeckelt
        -- schneller merkt im Van niemand. Die Latenz halbiert die Punktzahl
        bei 100 ms, viertelt sie bei 300 ms. Verlust ueber 30 Prozent macht
        eine Strecke unbrauchbar, egal wie schnell sie ist.
        """
        loss = q.get("loss", 1.0)
        if loss is None or loss > 0.30:
            return 0.0
        lat = q.get("latency_ms")
        if lat is None:
            return 0.0
        thr = min(float(mbps or 0.0), 100.0)
        return round(thr * (100.0 / (100.0 + lat)) * (1.0 - loss), 2)

    def probe_access_points(self, max_aps: int = 4) -> bool:
        """
        Bei mehreren Basisstationen unter derselben SSID die mit dem besten
        Internet auswaehlen -- nicht die mit dem staerksten Funk.

        Genau der Fall auf Campingplaetzen mit einer Unifi-Anlage: Der
        naechstgelegene Accesspoint hat den besten Empfang, haengt aber
        vielleicht an einer ueberlasteten Zuleitung. Ohne Bindung nimmt der
        Client immer den naechsten, weil er das Netz dahinter nicht kennt.

        Ablauf: an jede Basisstation einzeln binden, dahinter Latenz,
        Verlust und Durchsatz messen, die beste festnageln.
        """
        ssid = self.state.get("uplink_ssid") or self.state.get("selected_ssid")
        if not ssid:
            self.state["connect_status"] = "kein WLAN verbunden"
            self._publish_state()
            return False

        if not self._busy.acquire(blocking=False):
            self.state["connect_status"] = "anderer Vorgang laeuft"
            self._publish_state()
            return False

        try:
            self.state["connect_status"] = "suche Basisstationen"
            self._publish_state()

            try:
                found = self.router.scan(self.client_device)
            except RouterError as exc:
                self.state["last_error"] = str(exc)[:200]
                self._publish_state()
                return False

            peers = [ap for ap in found if ap["ssid"] == ssid and ap["bssid"]]
            # Gleiche Basisstation kann auf 2,4 und 5 GHz doppelt auftauchen
            seen, unique = set(), []
            for ap in peers:
                if ap["bssid"].upper() not in seen:
                    seen.add(ap["bssid"].upper())
                    unique.append(ap)
            unique.sort(key=lambda a: a["signal"], reverse=True)
            unique = unique[:max_aps]

            self.state["ap_count"] = len(unique)
            self._publish_state()

            if len(unique) < 2:
                self.state["connect_status"] = "nur eine Basisstation -- nichts zu waehlen"
                log.info("Nur %d Basisstation(en) fuer '%s'", len(unique), ssid)
                self._publish_state()
                return False

            log.info("%d Basisstationen fuer '%s' -- messe durch", len(unique), ssid)
            password = self._password_for(ssid)
            results = []

            for idx, ap in enumerate(unique, 1):
                bssid = ap["bssid"]
                self.state["connect_status"] = (
                    f"teste {idx}/{len(unique)}: {bssid[-5:]} ({ap['signal']} dBm)")
                self._publish_state()

                try:
                    self.router.connect_wifi(ssid, key=password, bssid=bssid)
                except RouterError as exc:
                    log.warning("%s nicht konfigurierbar: %s", bssid, exc)
                    continue

                if not self._wait_for_association(ssid, timeout=40):
                    log.info("%s keine Assoziation", bssid)
                    results.append({"bssid": bssid, "signal": ap["signal"],
                                    "score": 0.0, "note": "keine Verbindung"})
                    continue

                open_net, _ = check_internet()
                if not open_net:
                    log.info("%s assoziiert, aber kein Internet", bssid)
                    results.append({"bssid": bssid, "signal": ap["signal"],
                                    "score": 0.0, "note": "kein Internet"})
                    continue

                quality = self.router.link_quality()
                mbps = self._measure_download(budget_mb=3, seconds=8)
                score = self._score(quality, mbps)

                results.append({
                    "bssid": bssid,
                    "signal": ap["signal"],
                    "latency_ms": quality.get("latency_ms"),
                    "jitter_ms": quality.get("jitter_ms"),
                    "loss": quality.get("loss"),
                    "mbps": round(mbps, 1) if mbps else 0.0,
                    "score": score,
                    "note": "",
                })
                log.info("%s: %s dBm, %s ms, %.0f%% Verlust, %.1f Mbit/s -> %.2f Punkte",
                         bssid, ap["signal"], quality.get("latency_ms"),
                         (quality.get("loss") or 0) * 100, mbps or 0, score)

            usable = [r for r in results if r["score"] > 0]
            if not usable:
                # Bindung loesen, damit der Client wieder frei waehlen kann
                self.router.connect_wifi(ssid, key=password, bssid=None)
                self.state["connect_status"] = "keine Basisstation brauchbar"
                self.state["ap_locked"] = ""
                self._publish_state()
                return False

            best = max(usable, key=lambda r: r["score"])
            strongest = max(results, key=lambda r: r["signal"])

            self.router.connect_wifi(ssid, key=password, bssid=best["bssid"])
            self._wait_for_association(ssid, timeout=40)

            self.state["ap_locked"] = best["bssid"]
            self.state["ap_score"] = best["score"]
            self.state["wifi_speed_mbps"] = best["mbps"]
            self.state["connect_status"] = (
                f"gebunden an {best['bssid'][-5:]} "
                f"({best['mbps']} Mbit/s, {best['latency_ms']} ms)")

            if best["bssid"] != strongest["bssid"]:
                log.info("Nicht die staerkste Station gewaehlt: %s (%.2f) statt %s (%.2f)",
                         best["bssid"], best["score"],
                         strongest["bssid"], strongest.get("score", 0))

            # Gewinner merken -- beim naechsten Besuch direkt dorthin
            self._remember_ap(ssid, best["bssid"])
            self._publish_state()

            self.mqtt.publish(f"{NODE}/event/ap_probe", json.dumps({
                "ssid": ssid,
                "gewaehlt": best["bssid"],
                "staerkste": strongest["bssid"],
                "ergebnisse": sorted(results, key=lambda r: -r["score"]),
            }))
            return True
        finally:
            self._busy.release()

    def _remember_ap(self, ssid: str, bssid: str) -> None:
        """Die gewaehlte Basisstation zum Netz dazuspeichern."""
        self._learned_aps[ssid] = bssid
        try:
            with open(self._learned_ap_path, "w", encoding="utf-8") as fh:
                json.dump(self._learned_aps, fh)
            os.chmod(self._learned_ap_path, 0o600)
        except OSError as exc:
            log.warning("Basisstation nicht merkbar: %s", exc)

    # ---------------------------------------------------------------- SIM

    def switch_sim(self, label: str) -> bool:
        """
        Auf einen anderen Kartenschacht oder ein eSIM-Profil umschalten.

        Dauert rund 30 bis 60 Sekunden: Das Modem meldet sich im alten Netz
        ab und im neuen wieder an. Waehrenddessen traegt -- falls vorhanden --
        das WLAN, sonst ist kurz kein Internet da.
        """
        slot = next((s for s in SIM_SLOTS if s["label"] == label), None)
        if slot is None:
            log.warning("Unbekannte SIM-Auswahl: %s", label)
            return False

        self.state["connect_status"] = f"wechsle auf {label}"
        self.state["last_error"] = ""
        self._publish_state()

        try:
            self.router.switch_sim(slot["position"], esim_profile=slot["esim"])
        except RouterError as exc:
            self.state["connect_status"] = "SIM-Wechsel fehlgeschlagen"
            self.state["last_error"] = str(exc)[:200]
            self._publish_state()
            return False

        self.state["sim_slot"] = label
        self._publish_state()

        # Auf die Einbuchung warten, statt blind weiterzumachen
        deadline = time.time() + 120
        while time.time() < deadline and not self._stop.is_set():
            self._stop.wait(8)
            sig = self.router.signal()
            if sig.get("rsrp") is not None:
                self.state["connect_status"] = f"{label} eingebucht"
                log.info("SIM-Wechsel auf %s abgeschlossen", label)
                self._publish_state()
                return True

        self.state["connect_status"] = f"{label} meldet kein Signal"
        self.state["last_error"] = "Nach 2 Minuten keine Einbuchung -- Karte vorhanden?"
        self._publish_state()
        return False

    # ------------------------------------------------------------ Sicherung

    def backup_router(self) -> bool:
        """Router-Konfiguration auf den Pi holen, mit Aufbewahrungsgrenze."""
        stamp = time.strftime("%Y-%m-%d")
        path = f"/share/van-net/backups/router-{stamp}.tar.gz"
        self.state["connect_status"] = "sichere Router"
        self._publish_state()
        try:
            self.router.backup(path)
        except (RouterError, OSError) as exc:
            self.state["connect_status"] = "Sicherung fehlgeschlagen"
            self.state["last_error"] = str(exc)[:200]
            self._publish_state()
            return False

        # Nur die letzten zwoelf behalten -- eine pro Monat, also ein Jahr
        try:
            folder = os.path.dirname(path)
            files = sorted(f for f in os.listdir(folder)
                           if f.startswith("router-") and f.endswith(".tar.gz"))
            for old in files[:-12]:
                os.remove(os.path.join(folder, old))
                log.info("Alte Sicherung entfernt: %s", old)
        except OSError:
            pass

        self.state["last_backup"] = stamp
        self.state["connect_status"] = "Sicherung abgelegt"
        self._publish_state()
        return True

    # ---------------------------------------------------------- Standort

    def publish_position(self, forced: bool = False) -> bool:
        """
        Position nach Home Assistant melden.

        Laeuft im Hintergrund nur alle 30 Minuten (einstellbar). Der Knopf
        'Standort jetzt abfragen' umgeht das Intervall.

        Die Koordinaten gehen als Attribute an einen device_tracker -- damit
        erscheint der Van auf der Karte, ohne dass die Position als Zustand
        in jeder Verlaufsansicht auftaucht.
        """
        now = time.time()
        if not forced and now - self._last_position_ts < self.position_interval:
            return False

        try:
            gps = self.router.gps()
        except RouterError as exc:
            log.debug("GPS nicht lesbar: %s", exc)
            return False

        if not gps or not gps.get("fix"):
            self.state["gps_fix"] = False
            if forced:
                self.state["last_error"] = "Kein GPS-Fix -- freie Sicht noetig"
                self._publish_state()
            return False

        self._last_position_ts = now
        self._last_position = gps
        self.state["gps_fix"] = True
        self.state["gps_sats"] = gps.get("sats")
        self.state["position_age"] = time.strftime("%Y-%m-%d %H:%M:%S")

        self.mqtt.publish(f"{NODE}/position", json.dumps({
            "latitude": gps["lat"],
            "longitude": gps["lon"],
            "gps_accuracy": 15,
            "source_type": "gps",
            "satelliten": gps.get("sats"),
            "zuletzt": self.state["position_age"],
        }), retain=True)

        log.info("Position gemeldet (%d Satelliten)%s",
                 gps.get("sats") or 0, " -- manuell" if forced else "")
        self._publish_state()
        return True

    # ------------------------------------------------ Manuelles Verbinden

    def connect_selected(self) -> bool:
        """
        Mit dem im Dropdown gewaehlten Netz verbinden.

        Passwort-Herkunft in dieser Reihenfolge:
          1. gerade in HA eingetippt
          2. in der App-Konfiguration hinterlegt (known_networks)
          3. bei einem frueheren Besuch gelernt
          4. keins -- dann muss das Netz offen sein
        """
        ssid = self.state.get("selected_ssid")
        if not ssid:
            self.state["connect_status"] = "kein Netz ausgewaehlt"
            self._publish_state()
            return False

        if not self._busy.acquire(blocking=False):
            self.state["connect_status"] = "Scan laeuft noch"
            self._publish_state()
            return False

        try:
            password = self._pending_password or self._password_for(ssid)
            if not password and not self._is_open(ssid):
                self.state["connect_status"] = "Passwort fehlt"
                self._publish_state()
                return False

            self.state["connect_status"] = f"verbinde mit {ssid}"
            self._publish_state()
            log.info("Manuelles Verbinden mit '%s'", ssid)

            # Netz war vielleicht schon einmal als gescheitert markiert
            self._failed_ssids.pop(ssid, None)

            try:
                self.router.connect_wifi(ssid, key=password,
                                         bssid=self._learned_aps.get(ssid))
            except RouterError as exc:
                self.state["connect_status"] = "Fehler beim Umstellen"
                self.state["last_error"] = str(exc)[:200]
                self._publish_state()
                return False

            if not self._wait_for_association(ssid):
                self.state["connect_status"] = "keine Verbindung -- Passwort falsch?"
                self._publish_state()
                return False

            self.state["uplink_ssid"] = ssid
            self.state["connect_status"] = "verbunden, pruefe Internet"
            self._publish_state()

            open_net, portal_url = check_internet()
            if not open_net and portal_url:
                self.state["portal_url"] = portal_url
                self.state["portal_state"] = "detected"
                self._publish_state()
                open_net = self.handle_portal()

            if open_net:
                # Erst jetzt merken -- ein falsches Passwort lernen waere unsinnig
                if password:
                    self._remember(ssid, password)
                self.state["connect_status"] = "verbunden"
                self.state["internet_ok"] = True
                self._pending_password = ""
                self._publish_state()
                self.run_speedtest()
                return True

            self.state["connect_status"] = "verbunden, aber kein Internet"
            self._publish_state()
            return False
        finally:
            self._busy.release()
            self._clear_password_field()

    # -------------------------------------------------------------- Router

    def reboot_router(self) -> None:
        """
        Router neu starten.

        Danach ist fuer etwa zwei Minuten kein Internet verfuegbar -- auch
        Home Assistant selbst haengt am Router. Deshalb liegt im Dashboard
        eine Rueckfrage auf dem Knopf.
        """
        log.warning("Router-Neustart ausgeloest")
        self.state["connect_status"] = "Router startet neu"
        self.state["last_error"] = ""
        self._publish_state()
        try:
            # Antwort kommt nicht mehr -- der Router geht mitten im Befehl aus
            self.router.run("reboot", timeout=8)
        except RouterError as exc:
            log.info("Reboot-Befehl ohne Rueckmeldung (erwartet): %s", exc)
        self.router.close()

        # Warten, bis er wieder antwortet, statt blind weiterzupollen
        deadline = time.time() + 240
        while time.time() < deadline and not self._stop.is_set():
            self._stop.wait(10)
            if self.router.alive():
                log.info("Router ist wieder erreichbar")
                self.state["connect_status"] = "Router wieder online"
                self._device_cache_reset()
                self._publish_state()
                return
        self.state["connect_status"] = "Router antwortet nicht mehr"
        self.state["last_error"] = "Nach Neustart 4 Minuten keine Antwort"
        self._publish_state()

    def _device_cache_reset(self):
        """Nach einem Neustart koennen die Interface-Suffixe anders sein."""
        try:
            self.router._device_cache = None
        except Exception:
            pass

    # -------------------------------------------------------------- Portal

    def handle_portal(self) -> bool:
        """True, wenn am Ende echtes Internet steht."""
        url = self.state.get("portal_url")
        if not url:
            _, url = check_internet()
            if not url:
                return False
            self.state["portal_url"] = url

        ssid = self.state.get("uplink_ssid", "")
        self.state["portal_state"] = "solving"
        self._publish_state()

        result = self.portal.try_login(url, ssid=ssid)
        log.info("Portal-Ergebnis: %s", result)

        if result["success"]:
            self.state["portal_state"] = "ok"
            self.state["internet_ok"] = True
            self._publish_state()
            return True

        # Fallback: QR-Code fuer manuelle Bestaetigung am Handy
        final_url = result.get("final_url") or url
        make_qr(final_url, self.qr_path,
                label=f"Portal: {ssid}" if ssid else "Captive Portal")
        self.state["portal_state"] = "manual"
        self.state["portal_url"] = final_url
        self.state["last_error"] = result.get("note", "")[:200]
        self._publish_state()

        # Eigenes Event -- darauf haengt die HA-Notification mit QR-Code
        self.mqtt.publish(f"{NODE}/event/portal_manual", json.dumps({
            "ssid": ssid,
            "url": final_url,
            "qr": self.qr_public,
            "note": result.get("note", ""),
            "screenshot": result.get("screenshot") or "",
        }))
        return False

    # ----------------------------------------------------------- Speedtest

    def run_speedtest(self):
        """
        Misst die WLAN-Geschwindigkeit.

        Laeuft bewusst nur ueber WLAN. Ein Speedtest ueber die SIM wuerde
        Datenvolumen verbrennen -- die Mobilfunk-Schaetzung passiert
        stattdessen in Home Assistant aus den Signalwerten.
        """
        if self.state.get("active_wan") != "wifi":
            log.info("Speedtest uebersprungen -- aktiver Uplink ist nicht WLAN")
            return
        mbps = self._measure_download()
        if mbps is not None:
            self.state["wifi_speed_mbps"] = round(mbps, 1)
            log.info("WLAN-Durchsatz: %.1f Mbit/s", mbps)
            self._publish_state()

    def _measure_download(self, budget_mb: int = 25, seconds: int = 20):
        # Bevorzugt speedtest-cli, sonst einfacher HTTP-Download
        # Beim Durchtesten vieler Basisstationen zaehlt Tempo, nicht Praezision
        if budget_mb >= 25:
            try:
                import speedtest
                st = speedtest.Speedtest(secure=True)
                st.get_best_server()
                return st.download(threads=2) / 1_000_000
            except Exception as exc:
                log.info("speedtest-cli nicht nutzbar (%s), nutze HTTP-Messung", exc)

        import requests
        url = (f"https://speed.cloudflare.com/__down?bytes={int(budget_mb) * 1_000_000}"
               if budget_mb < 25 else self.cfg["portal"].get(
                   "speedtest_url",
                   "https://speed.cloudflare.com/__down?bytes=25000000"))
        try:
            start = time.time()
            total = 0
            with requests.get(url, stream=True, timeout=seconds + 25) as resp:
                for chunk in resp.iter_content(262144):
                    total += len(chunk)
                    if time.time() - start > seconds:
                        break
            elapsed = max(time.time() - start, 0.1)
            return (total * 8) / elapsed / 1_000_000
        except Exception as exc:
            log.warning("Speedtest fehlgeschlagen: %s", exc)
            return None

    # ------------------------------------------------------------------ Loop

    def run(self):
        log.info("Agent gestartet")
        if not self.router.alive():
            log.error("Router %s per SSH nicht erreichbar -- bitte README Schritt 5 pruefen",
                      self.cfg["router"]["host"])

        # Aktiven Kartenschacht einmalig aus mwan3 ableiten
        try:
            status = self.router.mwan_status()
            for slot in SIM_SLOTS:
                if status.get(slot["iface"]) == "online":
                    self.state["sim_slot"] = slot["label"]
                    break
            else:
                cur = next((s for s in SIM_SLOTS
                            if s["iface"] == self.mobile_iface), None)
                if cur:
                    self.state["sim_slot"] = cur["label"]
        except Exception:
            pass

        last_autoscan = 0.0
        while not self._stop.is_set():
            try:
                self.poll()

                # Standort -- prueft selbst, ob das Intervall um ist
                self.publish_position()

                autoscan = self.cfg["wifi"].get("auto_connect", True)
                needs_wifi = self.state["active_wan"] != "wifi" or not self.state["internet_ok"]
                if (autoscan and needs_wifi and self.state["stationary"]
                        and self.state["wan_mode"] != "SIM erzwingen"
                        and time.time() - last_autoscan > self.scan_cooldown):
                    last_autoscan = time.time()
                    self.scan_and_connect()

                # Portal von selbst aufgetaucht (z.B. Session abgelaufen)
                if (self.state["portal_state"] == "detected"
                        and self.state["active_wan"] == "wifi"):
                    self.handle_portal()

            except Exception:
                log.exception("Fehler im Hauptloop")

            self._stop.wait(self.poll_interval)

        log.info("Agent beendet")
        self.mqtt.publish(f"{NODE}/availability", "offline", retain=True)
        self.mqtt.loop_stop()
        self.router.close()

    def stop(self, *_):
        self._stop.set()


def main():
    cfg_path = os.environ.get("CONFIG", "/config/config.yaml")
    if not os.path.exists(cfg_path):
        log.error("Konfiguration nicht gefunden: %s", cfg_path)
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    agent = Agent(cfg)
    signal.signal(signal.SIGTERM, agent.stop)
    signal.signal(signal.SIGINT, agent.stop)
    agent.run()


if __name__ == "__main__":
    main()
