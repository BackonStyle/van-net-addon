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
            "last_scan": "",
            "last_error": "",
        }
        self._moving_since = time.time()
        self._last_scan_ts = 0.0
        self._failed_ssids = {}       # ssid -> timestamp
        self._stop = threading.Event()
        self._busy = threading.Lock()

        self.mqtt = self._make_mqtt(cfg["mqtt"])

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
        except Exception as exc:
            log.exception("Befehl fehlgeschlagen")
            self.state["last_error"] = str(exc)[:200]
            self._publish_state()

    def _disc(self, component, object_id, payload):
        payload.update({
            "availability_topic": f"{NODE}/availability",
            "state_topic": f"{NODE}/state",
            "device": DEVICE,
            "unique_id": f"{NODE}_{object_id}",
        })
        self.mqtt.publish(
            f"{DISCOVERY_PREFIX}/{component}/{NODE}/{object_id}/config",
            json.dumps(payload), retain=True)

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
            ("portal_state", "Portal-Status", "mdi:shield-account", None, None),
            ("portal_url", "Portal-Adresse", "mdi:link-variant", None, None),
            ("last_scan", "Letzter Scan", "mdi:radar", None, None),
            ("last_error", "Letzter Fehler", "mdi:alert-circle-outline", None, None),
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

        for oid, name, icon in [
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
            gps = self.router.gps()
            if gps:
                self.state["speed_kmh"] = gps.get("speed_kmh")
                self._update_stationary(gps.get("speed_kmh", 0.0))

            link = self.router.wifi_link(self.client_device)
            self.state["uplink_ssid"] = link.get("ssid") or ""
            self.state["wifi_signal"] = link.get("signal")

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
        if speed_kmh > self.stationary_kmh:
            self._moving_since = now
            self.state["stationary"] = False
        else:
            self.state["stationary"] = (now - self._moving_since) >= self.stationary_after

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
            if ssid in self.known:
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

            for ap in self._candidate_networks(results):
                ssid = ap["ssid"]
                log.info("Versuche '%s' (%d dBm, %s)", ssid, ap["signal"],
                         "offen" if ap["open"] else "verschluesselt")
                try:
                    self.router.connect_wifi(ssid, key=self.known.get(ssid))
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

    def _measure_download(self):
        # Bevorzugt speedtest-cli, sonst einfacher HTTP-Download
        try:
            import speedtest
            st = speedtest.Speedtest(secure=True)
            st.get_best_server()
            return st.download(threads=2) / 1_000_000
        except Exception as exc:
            log.info("speedtest-cli nicht nutzbar (%s), nutze HTTP-Messung", exc)

        import requests
        url = self.cfg["portal"].get(
            "speedtest_url", "https://speed.cloudflare.com/__down?bytes=25000000")
        try:
            start = time.time()
            total = 0
            with requests.get(url, stream=True, timeout=45) as resp:
                for chunk in resp.iter_content(262144):
                    total += len(chunk)
                    if time.time() - start > 20:
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

        last_autoscan = 0.0
        while not self._stop.is_set():
            try:
                self.poll()

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
