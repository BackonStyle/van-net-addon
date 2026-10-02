# Home-Assistant-Dateien

Diese Dateien gehören nicht in die App, sondern in die
Home-Assistant-Konfiguration. Das Installationsskript legt beide selbst ab —
hier stehen sie für den Fall, dass du es von Hand machst.

## van_net.yaml

Kopieren nach `config/packages/van_net.yaml`.

Aktivieren, indem in `configuration.yaml` steht:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Enthält den geschätzten Mobilfunk-Durchsatz aus SINR und RSRP, die
Benachrichtigung mit QR-Code bei gescheiterter Portal-Anmeldung, den
Wechselvorschlag mit Bestätigungsknopf, die Warnung bei Drosselung wegen
Hitze, die monatliche Router-Sicherung und die Erinnerung an einen erzwungenen
Uplink.

**Auf einem neuen Gerät anzupassen:** nur der Notify-Dienst, drei Vorkommen
hinter `- action:`. Den eigenen Namen findest du unter
*Entwicklerwerkzeuge → Aktionen*, Suchfeld `notify.mobile`.

## van-internet.yaml

Kopieren nach `config/dashboards/van-internet.yaml`, dann in
`configuration.yaml`:

```yaml
lovelace:
  mode: storage
  dashboards:
    van-internet:
      mode: yaml
      filename: dashboards/van-internet.yaml
      title: Internet
      icon: mdi:web
      show_in_sidebar: true
```

Die Seite erscheint danach als eigener Eintrag in der Seitenleiste und lässt
dein vorhandenes Dashboard unberührt. Sie ist dafür nicht über die Oberfläche
bearbeitbar — Änderungen gehen über die Datei, danach Browser neu laden.

**Lieber als Seite im eigenen Dashboard?** Den Block unterhalb von `views:`
kopieren und über *Dashboard → Bearbeiten → ⋮ → Rohkonfigurations-Editor*
einhängen.

## Voraussetzungen

- App **Van Netzwerk Agent** installiert und gestartet
- **Mosquitto broker** läuft, MQTT-Integration eingerichtet
- Ordner `config/www/van-net/` vorhanden — dort landet der QR-Code
- Companion-App auf dem Handy für die Benachrichtigungen
