# Van-Netzwerk

**Fahrzeug-Internet mit Teltonika-Router und Home Assistant.** Sucht
selbstständig WLAN im Stand, meldet sich an Captive-Portalen an, wählt bei
mehreren Accesspoints den mit dem besten Internet — und entscheidet nie
selbst, wann auf Mobilfunk gewechselt wird.

Gebaut für ein Wohnmobil mit **Teltonika RUTC50 eSIM** und einem
**Raspberry Pi 4B** mit Home Assistant OS. Läuft genauso auf RUTX50 und
RUTM50.

---

## Installation in einem Befehl

Voraussetzung: Die App **Terminal & SSH** ist in Home Assistant installiert.
Dann dort:

```sh
curl -sSL https://raw.githubusercontent.com/BackonStyle/van-net-addon/main/install.sh -o i.sh && bash i.sh
```

Das Skript installiert Mosquitto, legt die App an, richtet beide Dashboards
ein, trägt alles in die `configuration.yaml` ein (mit Sicherung) und führt
durch ein Frage-Menü. Mehrfaches Ausführen ist unschädlich.

**Vollständige Anleitung: [HANDBUCH.md](HANDBUCH.md)** — 25 Seiten, von der
Router-Einrichtung bis zum Bedienpanel. Wer das Handbuch liest, braucht
nichts weiter.

---

## Was es kann

**Immer Internet.** Der Router bevorzugt WLAN und schaltet bei Ausfall in
etwa neun Sekunden auf Mobilfunk. Das läuft in `mwan3` auf dem Router
selbst — also auch dann, wenn der Pi neu startet, abstürzt oder fehlt. Eine
Hausautomation ist kein Fundament für die Internetverbindung eines Fahrzeugs.

**WLAN suchen, nur im Stand.** Nach drei Minuten unter 3 km/h gilt das
Fahrzeug als stehend. Während der Fahrt wird nicht gescannt, weil jeder Scan
das Funkmodul belegt.

**Die richtige Basisstation, nicht die stärkste.** Große Anlagen auf
Campingplätzen bestehen aus mehreren Accesspoints mit derselben SSID. Ein
normaler Client nimmt den mit dem stärksten Signal — und der hängt nicht
selten an einer überlasteten Zuleitung. Dieses System misst hinter jeder
Basisstation das echte Internet:

```
Punkte = min(Mbit/s, 100) × 100/(100 + Latenz_ms) × (1 − Verlust)
```

| Basisstation | Funk | Latenz | Verlust | Durchsatz | Punkte |
|---|---|---|---|---|---|
| nah, überlastete Zuleitung | −41 dBm | 95 ms | 2 % | 1,2 Mbit/s | 0,60 |
| mittlere Entfernung | −68 dBm | 22 ms | 0 % | 48 Mbit/s | 39,34 |
| weit, Glasfaser dahinter | −72 dBm | 14 ms | 0 % | 240 Mbit/s | **87,72** |

Ein normaler Client hätte Zeile eins gewählt. Mehr als 30 Prozent
Paketverlust disqualifiziert eine Strecke, egal wie schnell sie ist.

**Anmeldeseiten automatisch bestätigen.** Ein Headless-Browser klickt
Cookie-Banner weg, hakt Zustimmungsfelder an und sucht den Absenden-Knopf
über eine mehrsprachige Wortliste. Trefferquote rund 80 Prozent; scheitert
es, kommt ein QR-Code aufs Handy.

**Bedienung in Home Assistant.** Uplink-Umschalter, SIM-Auswahl (zwei
Kartenschächte, zwei eSIM-Profile), WLAN-Dropdown mit Passwortfeld,
Speedtest, Router-Neustart mit Rückfrage, monatliche Konfigurationssicherung.

**Mobilfunk-Durchsatz geschätzt**, nicht gemessen — Messen würde
Datenvolumen kosten. Aus SINR und RSRP nach Shannon mit 256QAM-Deckel,
Genauigkeit etwa ±30 Prozent. Reicht für die Frage „lohnt sich der Wechsel".

**Optional ein Bedienpanel** im Fahrzeug: Android-Tablet mit Fully Kiosk,
eigenes reduziertes Dashboard, Ladefenster gegen Akkuquellung, Tiefschlaf an
der Heimatadresse.

---

## Zwei Dinge, die ihr an eurem Router prüfen solltet

Beides wurde beim Bauen gefunden, beides hat nichts mit diesem Projekt zu
tun — aber beides hätte unterwegs für Ärger gesorgt.

**SIM-Umschaltung auf einen leeren Kartenschacht:**

```sh
cat /etc/config/sim_switch
```

Steht dort bei einem leeren Schacht `enabled '1'`, oder bei der aktiven Karte
ein `switch_back`, schaltet der Router von selbst weg. Im getesteten Fall
alle 15 Minuten auf einen Schacht ohne Karte — die Verbindung war also
viertelstündlich weg, unabhängig vom Empfang. Unterwegs erlebt man das als
„die Verbindung ist manchmal komisch" und sucht an der falschen Stelle.

**Failover-Metriken und Tracking:**

```sh
mwan3 status
uci show network | grep metric
```

Im getesteten Fall hatte der WLAN-Uplink die **schlechteste** Metrik, und für
keine Schnittstelle war die Überwachung aktiv. Das Failover hätte nie
ausgelöst.

---

## Mindestanforderungen

| | |
|---|---|
| Router | Teltonika RUTC50, RUTX50 oder RUTM50 · RutOS 7.x |
| **Pflicht** | **zwei WLAN-Bänder**, SSH aktiv, `mwan3` vorhanden |
| Raspberry Pi | 4B, 2 GB (4 GB empfohlen), **aktiv gekühlt**, am LAN-Kabel |
| Home Assistant | OS 14+, Core 2024.6+ |
| Mobilfunk | SIM oder eSIM mit Datentarif |

> **K.-o.-Kriterium:** Geräte mit nur einem Funkchip — darunter der RUTC50 —
> betreiben Accesspoint und Client ausschließlich auf verschiedenen Bändern.
> 2,4 GHz wird Suchradio, 5 GHz das eigene Netz. Geräte, die nur 2,4 GHz
> können, lassen sich danach nicht mehr anschließen.

Andere OpenWRT-Router sind nicht getestet. Vorausgesetzt werden `uci`, `ubus`
und `mwan3`.

---

## Was noch fehlt — hier ist Hilfe willkommen

Das Projekt läuft, aber es ist nicht fertig. Diese Punkte stehen offen, und
bei den ersten drei komme ich ohne fremde Geräte nicht weiter:

**Datenverbrauch überwachen.** RutOS hat `quota_limit` und `mdcollectd`, aber
ich habe den richtigen Weg noch nicht gefunden, den Zählerstand auszulesen.
Wer weiß, welcher `ubus`-Aufruf oder welche Datei den Verbrauch pro
SIM liefert, hilft hier am meisten — ohne das ist ein Volumenlimit nicht
überwachbar.

**Roaming-Schalter.** Soll ein An/Aus-Schalter mit Kostenwarnung werden.
Gesucht: wie die Roaming-Sperre in RutOS 7.x intern heißt und ob sie per
`uci` oder `ubus` umschaltbar ist.

**SIM-Wechsel per Befehl.** `router.py` probiert drei Wege durch
(`set_sim`, `sim_switch switch`, `AT+QUIMSLOT`). Welcher auf welcher
Firmware funktioniert, ist unklar — Rückmeldungen von anderen Modellen sind
wertvoll.

**Captive-Portal-Muster.** Die Wortliste `ACCEPT_PATTERNS` in `portal.py`
deckt Deutsch, Englisch, Französisch, Italienisch und Spanisch ab. Jedes
Portal, das nicht durchläuft, legt ein Bildschirmfoto unter
`/share/van-net/screenshots/` ab. Wer Muster ergänzt, hebt die Trefferquote
für alle.

**Andere Router.** Ob das auf RUT240, RUT955 oder nicht-Teltonika-OpenWRT
läuft, weiß niemand. Berichte willkommen, auch negative.

**Mehr Testfälle für die AP-Bewertung.** Die Punkteformel ist plausibel, aber
nur gegen gerechnete Szenarien geprüft, nicht gegen viele echte Anlagen.

Pull Requests und Issues gern. Wer nur berichten will, was auf seinem Gerät
anders ist, hilft genauso.

---

## Aufbau

```
van-net-addon/
├── install.sh                      Ein-Befehl-Installation
├── HANDBUCH.md                     vollständige Anleitung, 25 Seiten
├── van_net/                        die Home-Assistant-App
│   ├── agent.py                    Hauptprogramm, MQTT-Discovery
│   ├── router.py                   SSH/uci/ubus-Anbindung
│   ├── portal.py                   Captive-Portal-Automatik
│   ├── config.yaml                 App-Manifest
│   └── run.sh                      Start, liest die Optionen
└── homeassistant/
    ├── van_net.yaml                Sensoren und Automationen
    ├── van-internet.yaml           Dashboard-Seite
    └── van-tablet.yaml             Dashboard für ein Bedienpanel
```

**Steuerung per SSH, nicht REST.** Die REST-Endpunkte haben sich zwischen
RutOS-Versionen mehrfach geändert, und der API-Token läuft nach Minuten ab.
`uci` und `ubus` sind stabil und werden von Teltonika selbst für die
WLAN-Client-Steuerung empfohlen.

**Die offizielle Teltonika-Integration wird nicht benötigt** — sie scheitert
auf RutOS 7.24 an einem fehlenden Feld in der API-Antwort
(`data.static.release.target`). Die App liest die Signalwerte selbst:

```sh
ubus call gsm.modem0 get_signal_query '{}'
→ {"net_mode":"LTE","rssi":-57,"rsrp":-105,"sinr":-13,"rsrq":-20}
```

---

## Ehrliche Grenzen

- **Anmeldeseiten: etwa 80 Prozent.** Gutscheincodes, Standplatznummern,
  SMS-Bestätigung, Social-Login und CAPTCHAs sind nicht lösbar.
- **Mobilfunk-Durchsatz: ±30 Prozent.** Eine Schätzung, keine Messung.
- **Kein 2,4-GHz-Netz** für eigene Geräte, Folge des einzelnen Funkchips.
- **Ohne GPS-Fix keine Automatik** — in einer Tiefgarage gilt das Fahrzeug
  nicht als stehend. Der Knopf „Netze suchen" umgeht das.
- **Dauerhafter Pflegeaufwand.** Portale ändern sich.
- **Rechtliches:** Die Automatik akzeptiert Nutzungsbedingungen, die niemand
  gelesen hat. Manche Betreiber untersagen automatisierten Zugriff
  ausdrücklich. Das ist eine Entscheidung, die jeder selbst trifft.

---

## Lizenz

[MIT](LICENSE) — nutzen, ändern, weitergeben. Ohne Gewähr.
