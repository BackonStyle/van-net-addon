# Home-Assistant-Dateien

Diese beiden Dateien gehören **nicht** in die App, sondern in die
Home-Assistant-Konfiguration. Sie werden nicht automatisch mitinstalliert.

## van_net.yaml

Kopieren nach `config/packages/van_net.yaml`.

Aktivieren, indem in `configuration.yaml` ganz oben steht:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Enthält:

- **Geschätzter Mobilfunk-Durchsatz** aus SINR und RSRP, mit einstellbarer
  Bandbreite und Realismusfaktor
- **Benachrichtigung mit QR-Code**, wenn der Captive-Portal-Login scheitert
- **Wechselvorschlag**, wenn Mobilfunk deutlich schneller wäre als das
  verbundene WLAN — mit Bestätigungsknopf, geschaltet wird nie von selbst
- **Erinnerung**, wenn der WAN-Modus länger als vier Stunden auf
  „SIM erzwingen" steht

**Auf einem neuen Gerät anzupassen:** nur `notify.mobile_app_daniphone15pro`,
drei Vorkommen. Der eigene Name steht unter *Entwicklerwerkzeuge → Aktionen*,
Suchfeld `notify.mobile`.

## dashboard-card.yaml

Inhalt kopieren und im Dashboard einfügen über
**Bearbeiten → ⋮ → Rohkonfigurations-Editor**.

Zeigt Uplink-Status, Signalwerte, die Steuerknöpfe und bei Bedarf den
QR-Code für das Captive Portal.

## Voraussetzungen

- App **Van Netzwerk Agent** installiert und gestartet
- **Mosquitto broker** läuft, MQTT-Integration eingerichtet
- Ordner `config/www/van-net/` angelegt — dort schreibt die App den QR-Code hin
- Companion-App auf dem Handy für die Benachrichtigungen
