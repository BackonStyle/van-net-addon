# Van Netzwerk — Home-Assistant-Add-on

Automatische WLAN-Suche im Stand, Captive-Portal-Login, Geschwindigkeitsmessung
und manueller Uplink-Umschalter für einen Teltonika RUTC50 eSIM im Fahrzeug.

## Installation

1. In Home Assistant: **Einstellungen → Add-ons → Add-on-Store**
2. **⋮ oben rechts → Repositories**
3. Die URL dieses Repositories eintragen, **Hinzufügen**
4. Seite neu laden — das Add-on **Van Netzwerk Agent** erscheint
5. **Installieren** (dauert 10–20 Minuten, der Container wird lokal gebaut)

## Voraussetzungen

- **Mosquitto broker** Add-on installiert und gestartet
- Ordner `/config/www/van-net/` angelegt (für den QR-Code)
- Am Router: SSH erreichbar, WLAN-Client im Modus `sta` vorhanden
- Access Point und WLAN-Client auf **verschiedenen Bändern** — der RUTC50 hat
  nur einen WiFi-Chip

## Konfiguration

| Option | Bedeutung |
|---|---|
| `router_host` | IP des Routers, meist `192.168.1.1` |
| `router_password` | Router-Passwort (alternativ `router_ssh_key`) |
| `wifi_client_device` | Radio des Clients, z. B. `wlan0` — nur ein Hinweis, das Add-on sucht die Schnittstelle selbst |
| `wifi_wan_interface` | Name in mwan3, z. B. `wan1` |
| `mobile_wan_interface` | Name in mwan3, z. B. `mob1s3a1e1` |
| `portal_browser_enabled` | `false` spart ~500 MB RAM, dann nur QR-Fallback |
| `known_networks` | Liste bekannter WLANs mit Passwort |
| `blocked_ssids` | Netze, die nie verwendet werden |

Es stehen **keine Zugangsdaten in diesem Repository** — Passwörter werden
ausschließlich in der Add-on-Konfiguration in Home Assistant eingetragen und
bleiben dort.

## Was das Add-on in Home Assistant anlegt

Per MQTT-Discovery erscheint ein Gerät **Van Netzwerk** mit rund 15 Entitäten:
WAN-Modus (Auswahl), aktiver Uplink, verbundenes WLAN, Signalstärke, gemessene
WLAN-Geschwindigkeit, Portal-Status, Fahrzeuggeschwindigkeit, sowie Schaltflächen
für Scan, Portal-Login und Speedtest.

## Grenzen

- Captive-Portal-Automatik schafft etwa 80 % der Portale. Voucher-Codes,
  SMS-Bestätigung, Social-Login und CAPTCHAs sind nicht lösbar — dafür der
  QR-Fallback.
- Die Mobilfunk-Geschwindigkeit wird aus Signalwerten **geschätzt**, nicht
  gemessen. Echtes Messen würde Datenvolumen kosten.
- Das automatische Failover WLAN → SIM läuft auf dem Router (mwan3), nicht in
  diesem Add-on. Es funktioniert also auch dann, wenn Home Assistant neu startet.
