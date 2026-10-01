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

    def connect_wifi(self, ssid: str, key=None, encryption=None) -> None:
        """Client-Schnittstelle auf ein neues Netz umkonfigurieren."""
        section = self.find_client_iface()
        enc = encryption or ("psk2" if key else "none")

        # Feste BSSID-Bindung entfernen. Bleibt sie stehen, verbindet sich der
        # Client nur mit genau diesem einen Access Point und scheitert an
        # jedem anderen Netz.
        for stale in ("bssid", "_bgscan_enabled"):
            try:
                self.run(f"uci -q delete wireless.{section}.{stale}")
            except RouterError:
                pass

        assignments = {
            f"wireless.{section}.ssid": shlex.quote(ssid),
            f"wireless.{section}.encryption": enc,
            f"wireless.{section}.disabled": "0",
        }
        if key:
            assignments[f"wireless.{section}.key"] = shlex.quote(key)
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
        log.info("WLAN-Client auf '%s' umgestellt (encryption=%s)", ssid, enc)

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
