"""
SSH-Anbindung an den Teltonika RUTC50 (eSIM), RutOS 7.x.

Bewusste Entscheidung: Steuerung laeuft ueber SSH mit uci/ubus, nicht ueber die
REST-API. Gruende:
  - Die REST-Endpunkte haben sich zwischen RutOS-Versionen mehrfach geaendert.
  - Der API-Token laeuft schnell ab und muss staendig erneuert werden.
  - uci/ubus ist stabil und wird von Teltonika selbst fuer WiFi-Client-Steuerung
    empfohlen.

Die reinen Mess-Sensoren (RSRP/RSRQ/SINR/Temperatur) holt NICHT dieses Modul,
sondern die offizielle Teltonika-Integration in Home Assistant.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import threading
import time

import paramiko

log = logging.getLogger("router")


class RouterError(RuntimeError):
    pass


class Router:
    """Duenne, thread-sichere SSH-Huelle um den Router."""

    def __init__(self, host, username="root", key_file=None, password=None,
                 port=22, timeout=15):
        self.host = host
        self.username = username
        self.key_file = key_file
        self.password = password
        self.port = port
        self.timeout = timeout
        self._client = None
        self._device_cache = None
        self._thermal_cfg = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- Verbindung

    def _connect(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
            "banner_timeout": self.timeout,
            "auth_timeout": self.timeout,
            "look_for_keys": False,
            "allow_agent": False,
        }
        if self.key_file:
            kwargs["key_filename"] = self.key_file
        else:
            kwargs["password"] = self.password
        client.connect(**kwargs)
        return client

    def _ensure(self):
        if self._client is not None:
            tr = self._client.get_transport()
            if tr is not None and tr.is_active():
                return self._client
            self.close()
        self._client = self._connect()
        return self._client

    def close(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def run(self, cmd: str, timeout: int | None = None) -> str:
        """Kommando ausfuehren, stdout zurueckgeben. Ein Reconnect-Versuch."""
        with self._lock:
            for attempt in (1, 2):
                try:
                    client = self._ensure()
                    _, stdout, stderr = client.exec_command(
                        cmd, timeout=timeout or self.timeout)
                    out = stdout.read().decode("utf-8", "replace")
                    rc = stdout.channel.recv_exit_status()
                    if rc != 0:
                        err = stderr.read().decode("utf-8", "replace").strip()
                        raise RouterError(
                            f"rc={rc} bei '{cmd}': {err or out.strip()}")
                    return out
                except RouterError:
                    raise
                except Exception as exc:
                    self.close()
                    if attempt == 2:
                        raise RouterError(f"SSH fehlgeschlagen: {exc}") from exc
                    time.sleep(1)
        raise RouterError("unerreichbar")

    def run_json(self, cmd: str, timeout: int | None = None) -> dict:
        raw = self.run(cmd, timeout=timeout).strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RouterError(
                f"Keine gueltige JSON-Antwort von '{cmd}': {raw[:200]}") from exc

    def alive(self) -> bool:
        try:
            self.run("true", timeout=8)
            return True
        except Exception:
            return False

    # ---------------------------------------------------------------- UCI

    def uci_get(self, path: str):
        try:
            return self.run(f"uci -q get {shlex.quote(path)}").strip()
        except RouterError:
            return None

    def uci_set(self, assignments: dict, package: str):
        """Mehrere uci-Werte setzen und das Paket committen."""
        parts = [f"uci set {shlex.quote(f'{k}={v}')}"
                 for k, v in assignments.items()]
        parts.append(f"uci commit {shlex.quote(package)}")
        self.run(" && ".join(parts))

    # ---------------------------------------------------------------- GPS

    def gps(self) -> dict:
        """
        Liefert {'lat','lon','speed_kmh','sats','fix'} oder {} wenn kein Fix.

        RutOS liefert GPS je nach Firmware unterschiedlich, deshalb mehrere
        Versuche in absteigender Zuverlaessigkeit.
        """
        for call in ("gpsd info", "gps info"):
            try:
                data = self.run_json(f"ubus call {call} '{{}}'", timeout=10)
                if data:
                    norm = self._normalise_gps(data)
                    if norm:
                        return norm
            except RouterError:
                continue

        # Fallback: klassisches Teltonika-CLI
        try:
            raw = self.run("gpsctl -i -x -s -u", timeout=10)
            nums = re.findall(r"-?\d+\.?\d*", raw)
            if len(nums) >= 3:
                return {
                    "lat": float(nums[0]),
                    "lon": float(nums[1]),
                    "speed_kmh": max(0.0, float(nums[2])),
                    "sats": int(float(nums[3])) if len(nums) > 3 else 0,
                    "fix": True,
                }
        except (RouterError, ValueError):
            pass

        return {}

    @staticmethod
    def _normalise_gps(data: dict) -> dict:
        lat = data.get("latitude", data.get("lat"))
        lon = data.get("longitude", data.get("lon"))
        if lat is None or lon is None:
            return {}
        if float(lat) == 0.0 and float(lon) == 0.0:
            return {}
        speed = float(data.get("speed", 0) or 0)
        # ubus liefert je nach Firmware m/s oder km/h.
        # Siehe README "GPS kalibrieren" -- einmal pruefen und ggf. anpassen.
        if data.get("speed_unit", "ms") == "ms":
            speed *= 3.6
        return {
            "lat": float(lat),
            "lon": float(lon),
            "speed_kmh": max(0.0, round(speed, 1)),
            "sats": int(data.get("satellites", data.get("sats", 0)) or 0),
            "fix": bool(data.get("fix", True)),
        }

    # ---------------------------------------------------------------- WLAN-Scan

    def resolve_device(self, hint: str) -> str:
        """
        Den echten iwinfo-Namen des Client-Radios finden.

        RutOS haengt an jede Schnittstelle einen Suffix: aus 'wlan0' wird
        'wlan0-3'. Der Suffix aendert sich, wenn Schnittstellen neu angelegt
        werden -- ein fest eingetragener Name waere also eine Zeitbombe.
        Reihenfolge: Cache, exakter Treffer, STA-Modus, Praefix.
        """
        if self._device_cache:
            return self._device_cache

        try:
            devices = self.run_json("ubus call iwinfo devices '{}'").get("devices", [])
        except RouterError:
            return hint
        if not devices:
            return hint

        if hint in devices:
            self._device_cache = hint
            return hint

        for dev in devices:
            try:
                info = self.run_json(
                    "ubus call iwinfo info " + shlex.quote(json.dumps({"device": dev})))
            except RouterError:
                continue
            if str(info.get("mode", "")).lower() in ("client", "managed", "sta"):
                log.info("Client-Radio erkannt: %s (Hinweis war '%s')", dev, hint)
                self._device_cache = dev
                return dev

        for dev in devices:
            if dev.startswith(hint):
                log.info("Client-Radio ueber Praefix erkannt: %s", dev)
                self._device_cache = dev
                return dev

        return hint

    def scan(self, device: str) -> list:
        """
        Umgebungsscan via iwinfo.

        WICHTIG: Der Scan laeuft auf dem Client-Radio (2.4 GHz). Der AP auf
        5 GHz bleibt oben, weil es ein anderes Radio ist. Laegen AP und Client
        auf demselben Band, braeche der AP weg -- der RUTC50 hat nur einen
        WiFi-Chip.
        """
        data = self.run_json(
            "ubus call iwinfo scan " + shlex.quote(
                json.dumps({"device": self.resolve_device(device)})),
            timeout=45)
        results = []
        for ap in data.get("results", []):
            ssid = (ap.get("ssid") or "").strip()
            if not ssid:
                continue  # versteckte Netze ignorieren
            enc = ap.get("encryption", {}) or {}
            quality = ap.get("quality", 0) or 0
            quality_max = ap.get("quality_max", 70) or 70
            results.append({
                "ssid": ssid,
                "bssid": ap.get("bssid", ""),
                "channel": ap.get("channel", 0),
                "signal": ap.get("signal", -100),
                "quality_pct": round(100 * quality / quality_max),
                "open": not enc.get("enabled", False),
                "auth": ",".join(enc.get("authentication", []) or []),
            })
        results.sort(key=lambda r: r["signal"], reverse=True)
        return results

    # ---------------------------------------------------------------- WLAN-Client

    def find_client_iface(self) -> str:
        """Den uci-Abschnitt der WiFi-Client-Schnittstelle (mode=sta) finden."""
        raw = self.run("uci show wireless")
        for line in raw.splitlines():
            m = re.match(r"wireless\.([\w@\[\]-]+)\.mode='sta'", line.strip())
            if m:
                return m.group(1)
        raise RouterError(
            "Keine WiFi-Client-Schnittstelle (mode='sta') gefunden. "
            "Einmalig in der WebUI anlegen -- siehe README, Schritt 3.")

    def current_uplink_ssid(self):
        section = self.find_client_iface()
        if self.uci_get(f"wireless.{section}.disabled") == "1":
            return None
        return self.uci_get(f"wireless.{section}.ssid") or None

    def wifi_link(self, device: str) -> dict:
        """Verbindungsstatus des Client-Radios."""
        try:
            data = self.run_json(
                "ubus call iwinfo info " + shlex.quote(
                    json.dumps({"device": self.resolve_device(device)})),
                timeout=10)
        except RouterError:
            self._device_cache = None   # Name koennte sich geaendert haben
            return {"connected": False}
        ssid = data.get("ssid")
        return {
            "connected": bool(ssid),
            "ssid": ssid,
            "signal": data.get("signal"),
            "bitrate": data.get("bitrate"),
        }

    def connect_wifi(self, ssid: str, key=None, encryption=None,
                     bssid=None) -> None:
        """
        Client-Schnittstelle auf ein neues Netz umkonfigurieren.

        bssid bindet an genau eine Basisstation. Das ist bei Anlagen mit
        mehreren Accesspoints unter derselben SSID gewollt -- ohne Bindung
        nimmt der Client den mit dem staerksten Signal, und der hat nicht
        zwangslaeufig das beste Internet. Ohne bssid wird eine bestehende
        Bindung entfernt, sonst scheitert jeder Wechsel in ein anderes Netz.
        """
        section = self.find_client_iface()
        enc = encryption or ("psk2" if key else "none")

        for stale in ("bssid", "_bgscan_enabled"):
            try:
                self.run(f"uci -q delete wireless.{section}.{stale}")
            except RouterError:
                pass

        # ROHWERTE, nicht quotieren! uci_set() setzt den gesamten Ausdruck
        # "schluessel=wert" bereits in Anfuehrungszeichen. Eine zweite
        # Quotierung hier wuerde von der ersten geschuetzt und landete damit
        # als echtes Zeichen im Wert: der Router suchte dann ein Netz namens
        # 'FRITZ!Box 7590 MP' -- mit Apostrophen -- und fand nie eines.
        assignments = {
            f"wireless.{section}.ssid": ssid,
            f"wireless.{section}.encryption": enc,
            f"wireless.{section}.disabled": "0",
        }
        if bssid:
            assignments[f"wireless.{section}.bssid"] = bssid
        if key:
            assignments[f"wireless.{section}.key"] = key
        else:
            # Alten Schluessel entfernen, sonst scheitert die Assoziation
            try:
                self.run(f"uci -q delete wireless.{section}.key")
            except RouterError:
                pass
        self.uci_set(assignments, "wireless")
        self.run("wifi reload", timeout=40)
        # Nach einem Reload kann die Schnittstelle einen neuen Suffix haben
        self._device_cache = None
        log.info("WLAN-Client auf '%s' umgestellt (encryption=%s%s)", ssid, enc,
                 f", BSSID {bssid}" if bssid else "")

    def disconnect_wifi(self) -> None:
        section = self.find_client_iface()
        self.uci_set({f"wireless.{section}.disabled": "1"}, "wireless")
        self.run("wifi reload", timeout=40)
        log.info("WLAN-Client deaktiviert")

    # ---------------------------------------------------------------- Mobilfunk

    def signal(self) -> dict:
        """
        Signalwerte des Modems.

        Ersetzt die offizielle Teltonika-Integration, die auf RutOS 7.24
        an einem fehlenden Feld (release.target) scheitert. Der Weg ueber
        ubus ist ohnehin direkter und braucht keinen API-Token.

        Liefert {'rssi','rsrp','rsrq','sinr','net_mode'} oder {}.
        """
        try:
            data = self.run_json("ubus call gsm.modem0 get_signal_query '{}'",
                                 timeout=10)
        except RouterError:
            return {}

        out = {}
        for key in ("rssi", "rsrp", "rsrq", "sinr"):
            value = data.get(key)
            if isinstance(value, (int, float)):
                out[key] = value
        mode = data.get("net_mode")
        if mode:
            out["net_mode"] = str(mode)
        return out

    def link_quality(self, host: str = "1.1.1.1", count: int = 12) -> dict:
        """
        Latenz, Jitter und Paketverlust des aktuellen Uplinks.

        Gemessen auf dem Router, nicht auf dem Pi -- so liegt kein eigenes
        LAN-Segment dazwischen und das Ergebnis beschreibt wirklich die
        Strecke vom Router ins Netz.

        Rueckgabe: {'latency_ms', 'jitter_ms', 'loss'} oder {}.
        """
        try:
            raw = self.run(
                f"ping -q -c {int(count)} -W 2 {shlex.quote(host)} 2>&1 || true",
                timeout=count * 3 + 20)
        except RouterError:
            return {}

        loss = 1.0
        m = re.search(r"(\d+(?:\.\d+)?)% packet loss", raw)
        if m:
            loss = min(1.0, float(m.group(1)) / 100.0)

        out = {"loss": round(loss, 3)}

        # BusyBox: 'round-trip min/avg/max = 8.9/13.8/18.8 ms'
        m = re.search(r"min/avg/max(?:/mdev)?\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)", raw)
        if m:
            lo, avg, hi = (float(x) for x in m.groups())
            out["latency_ms"] = round(avg, 1)
            out["jitter_ms"] = round(hi - lo, 1)
        elif loss >= 1.0:
            out["latency_ms"] = None
            out["jitter_ms"] = None
        return out

    # ---------------------------------------------------------------- Thermik

    def thermal(self) -> dict:
        """
        Modemtemperatur und ob gedrosselt wird.

        Der RUTC50 kennt drei Zonen (get_thermal_cfg): operate_normal,
        operate_up und extreme_up. Verlaesst die Temperatur die
        Normalzone, senkt das Modem Sendeleistung und Datenrate.
        Genau dieser Zustand laesst sich aus den beiden Abfragen ableiten.

        Rueckgabe: {'temp_c', 'zone', 'throttling', 'limit_c'} oder {}.
        """
        try:
            raw = self.run_json("ubus call gsm.modem0 get_temperature '{}'",
                                timeout=10)
        except RouterError:
            return {}

        temp = None
        for key in ("temperature", "temp", "value"):
            if isinstance(raw.get(key), (int, float)):
                temp = float(raw[key])
                break
        if temp is None:
            return {}

        # Manche Firmware liefert Zehntelgrad als Ganzzahl
        if temp > 200:
            temp /= 10.0

        if self._thermal_cfg is None:
            try:
                self._thermal_cfg = self.run_json(
                    "ubus call gsm.modem0 get_thermal_cfg '{}'", timeout=10)
            except RouterError:
                self._thermal_cfg = {}

        cfg = self._thermal_cfg or {}
        normal_max = cfg.get("operate_normal_zone_max")
        extreme_min = cfg.get("extreme_up_zone_min")

        # Ohne Zonenangaben ein konservativer Richtwert fuer 5G-Module
        if not isinstance(normal_max, (int, float)):
            normal_max = 70

        zone = "normal"
        if isinstance(extreme_min, (int, float)) and temp >= extreme_min:
            zone = "extrem"
        elif temp >= normal_max:
            zone = "erhoeht"

        return {
            "temp_c": round(temp, 1),
            "zone": zone,
            "throttling": zone != "normal",
            "limit_c": round(float(normal_max), 1),
        }

    # ---------------------------------------------------------------- Sicherung

    def backup(self, local_path: str) -> str:
        """
        Router-Konfiguration sichern und per SFTP herholen.

        Die Sicherung muss vom Router weg: Ein defektes Geraet nimmt seine
        eigene Sicherung mit. Deshalb landet sie auf dem Pi.
        """
        remote = "/tmp/van-backup.tar.gz"
        self.run(f"rm -f {remote}", timeout=15)
        self.run(f"sysupgrade -b {remote}", timeout=90)

        size = self.run(f"wc -c < {remote}", timeout=15).strip()
        if not size.isdigit() or int(size) < 1024:
            raise RouterError(f"Sicherung unplausibel klein ({size} Bytes)")

        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with self._lock:
            client = self._ensure()
            sftp = client.open_sftp()
            try:
                sftp.get(remote, local_path)
            finally:
                sftp.close()
        self.run(f"rm -f {remote}", timeout=15)

        log.info("Router-Sicherung geholt: %s (%s Bytes)", local_path, size)
        return local_path

    # ---------------------------------------------------------------- SIM

    def sim_status(self) -> dict:
        """Welcher Kartenschacht bzw. eSIM-Profil ist aktiv?"""
        out = {}
        try:
            data = self.run_json("ubus call gsm.modem0 get_mod_status '{}'",
                                 timeout=10)
            if isinstance(data, dict):
                out.update({k: v for k, v in data.items()
                            if isinstance(v, (str, int, float))})
        except RouterError:
            pass
        try:
            iccid = self.run("gsmctl -J 2>/dev/null || true", timeout=10).strip()
            if iccid and iccid.isdigit():
                out["iccid"] = iccid
        except RouterError:
            pass
        return out

    def switch_sim(self, position: int, esim_profile=None) -> None:
        """
        Auf einen anderen Kartenschacht oder ein eSIM-Profil umschalten.

        Mehrere Wege, weil sich der Befehl zwischen RutOS-Versionen
        unterscheidet. Der erste, der ohne Fehler durchlaeuft, gewinnt.
        """
        attempts = [
            f"ubus call gsm.modem0 set_sim "
            f"{shlex.quote(json.dumps({'sim': int(position)}))}",
            f"ubus call sim_switch switch "
            f"{shlex.quote(json.dumps({'modem_id': '2-1.1', 'sim': int(position)}))}",
            f"gsmctl -A 'AT+QUIMSLOT={int(position)}'",
        ]
        if esim_profile is not None:
            attempts.insert(0,
                f"ubus call esim.modem0 enable_profile "
                f"{shlex.quote(json.dumps({'profile': int(esim_profile)}))}")

        last = None
        for cmd in attempts:
            try:
                self.run(cmd, timeout=30)
                log.info("SIM-Wechsel erfolgreich: %s", cmd.split()[2])
                return
            except RouterError as exc:
                last = exc
                continue
        raise RouterError(
            f"Kein SIM-Wechsel-Befehl hat funktioniert. Letzter Fehler: {last}")

    # ---------------------------------------------------------------- WAN / Failover

    def mwan_status(self) -> dict:
        """Interface-Status aus mwan3: {ifname: 'online'|'offline'|...}"""
        try:
            raw = self.run("mwan3 status", timeout=20)
        except RouterError:
            return {}
        status = {}
        for line in raw.splitlines():
            m = re.search(r"interface (\S+) is (\w+)", line)
            if m:
                status[m.group(1)] = m.group(2)
        return status

    def active_wan(self, wifi_iface: str, mobile_iface: str) -> str:
        """'wifi', 'mobile' oder 'none' -- welcher Uplink traegt gerade."""
        status = self.mwan_status()
        if status.get(wifi_iface) == "online":
            return "wifi"
        if status.get(mobile_iface) == "online":
            return "mobile"
        return "none"

    def set_wan_preference(self, mode: str, wifi_iface: str, mobile_iface: str):
        """
        mode: 'auto' | 'wifi' | 'mobile'

        auto   -- beide Interfaces aktiv, mwan3 entscheidet nach Metrik
        wifi   -- Mobilfunk deaktiviert, erzwingt WLAN
        mobile -- WLAN-Uplink deaktiviert, erzwingt SIM
        """
        if mode not in ("auto", "wifi", "mobile"):
            raise ValueError(f"Unbekannter Modus: {mode}")

        wifi_q = shlex.quote(wifi_iface)
        mob_q = shlex.quote(mobile_iface)

        if mode == "auto":
            self.run(f"mwan3 interface {wifi_q} enable || true")
            self.run(f"mwan3 interface {mob_q} enable || true")
        elif mode == "wifi":
            self.run(f"mwan3 interface {wifi_q} enable || true")
            self.run(f"mwan3 interface {mob_q} disable || true")
        else:
            self.run(f"mwan3 interface {mob_q} enable || true")
            self.run(f"mwan3 interface {wifi_q} disable || true")
        log.info("WAN-Praeferenz auf '%s' gesetzt", mode)
