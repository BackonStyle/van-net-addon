# Van-Netzwerk

**Handbuch**

Fahrzeug-Internet mit Teltonika RUTC50 und Home Assistant: automatische
WLAN-Suche im Stand, Captive-Portal-Anmeldung, Auswahl der Basisstation nach
echter Internetqualität und ein Uplink-Umschalter, der nie von selbst
entscheidet.

Stand: 2. Oktober 2026 · Version 1.4

---

## Inhalt

**Teil I — Überblick**
1. [Was das System kann](#1-was-das-system-kann)
2. [Mindestanforderungen](#2-mindestanforderungen)
3. [Wie es aufgebaut ist](#3-wie-es-aufgebaut-ist)

**Teil II — Einrichtung**
4. [Router vorbereiten](#4-router-vorbereiten)
5. [Installation in einem Befehl](#5-installation-in-einem-befehl)
6. [Was der Konfigurator fragt](#6-was-der-konfigurator-fragt)
7. [Dashboard und Fernzugriff](#7-dashboard-und-fernzugriff)
8. [Tablet im Fahrzeug](#8-tablet-im-fahrzeug)
9. [Abnahmetests](#9-abnahmetests)

**Teil III — Betrieb**
10. [Der Alltag](#10-der-alltag)
11. [Was das System nicht kann](#11-was-das-system-nicht-kann)
12. [Fehlersuche](#12-fehlersuche)
13. [Wartung und Updates](#13-wartung-und-updates)

**Teil IV — Hintergrund**
14. [Wie es entstanden ist](#14-wie-es-entstanden-ist)
15. [Gefundene Fehler](#15-gefundene-fehler)
16. [Entscheidungen und ihre Gründe](#16-entscheidungen-und-ihre-gründe)
17. [Befehls-Spickzettel](#17-befehls-spickzettel)

---
---

# Teil I — Überblick

## 1. Was das System kann

### Immer Internet

Der Router bevorzugt WLAN und schaltet bei Ausfall innerhalb von etwa neun
Sekunden auf Mobilfunk. Das läuft auf dem Router selbst, nicht in Home
Assistant — es funktioniert also auch dann, wenn der Raspberry Pi neu startet,
abstürzt oder ganz fehlt. Dein eigenes WLAN im Fahrzeug bleibt dabei
unverändert bestehen.

### WLAN suchen, nur im Stand

Nach drei Minuten unter 3 km/h gilt das Fahrzeug als stehend. Erst dann sucht
das System nach Netzen: bekannte zuerst, dann offene nach Signalstärke.
Während der Fahrt wird nicht gescannt, weil jeder Scan das Funkmodul belegt.

### Die richtige Basisstation, nicht die stärkste

Große Anlagen auf Campingplätzen bestehen aus mehreren Accesspoints mit
derselben SSID. Ein normaler Client nimmt den mit dem stärksten Signal — und
der hängt nicht selten an einer überlasteten Zuleitung.

Das System misst stattdessen hinter jeder Basisstation das echte Internet:
Latenz, Jitter, Paketverlust und Durchsatz. Daraus entsteht eine Punktzahl:

```
Punkte = min(Mbit/s, 100) × 100/(100 + Latenz_ms) × (1 − Verlust)
```

Der Durchsatz treibt das Ergebnis, gedeckelt bei 100 Mbit/s. Die Latenz
halbiert die Punktzahl bei 100 ms und viertelt sie bei 300 ms. Mehr als
30 Prozent Paketverlust disqualifiziert eine Strecke, egal wie schnell sie
ist — damit ist nichts Interaktives mehr möglich.

Ein Beispiel aus der Messreihe:

| Basisstation | Funk | Latenz | Verlust | Durchsatz | Punkte |
|---|---|---|---|---|---|
| nah, überlastete Zuleitung | −41 dBm | 95 ms | 2 % | 1,2 Mbit/s | 0,60 |
| mittlere Entfernung | −68 dBm | 22 ms | 0 % | 48 Mbit/s | 39,34 |
| weit, Glasfaser dahinter | −72 dBm | 14 ms | 0 % | 240 Mbit/s | **87,72** |

Ein normaler Client hätte die erste Zeile gewählt. Das System nimmt die dritte
und bindet sich fest an deren Adresse. Beim nächsten Besuch desselben Platzes
geht es direkt dorthin.

### Anmeldeseiten automatisch bestätigen

Findet das System eine Captive-Portal-Seite, öffnet es sie in einem echten
Browser, klickt Cookie-Banner weg, hakt Zustimmungsfelder an und sucht den
Absenden-Knopf über eine mehrsprachige Wortliste (Deutsch, Englisch,
Französisch, Italienisch, Spanisch). Bis zu drei Durchläufe, auch innerhalb
von iframes. Nach jedem Versuch wird echte Konnektivität geprüft.

Scheitert es, bekommst du eine Benachrichtigung mit QR-Code aufs Handy.
Scannen, bestätigen, fertig.

### Geschwindigkeit messen und einordnen

Nach erfolgreicher Verbindung wird der WLAN-Durchsatz gemessen. Die
Mobilfunk-Geschwindigkeit wird aus den Signalwerten **geschätzt** — echtes
Messen würde Datenvolumen kosten. Liegt der geschätzte Mobilfunk deutlich über
dem gemessenen WLAN, bekommst du einen Vorschlag mit Knopf. **Geschaltet wird
nur auf deinen Klick.**

### Bedienung in Home Assistant

| Bedienelement | Funktion |
|---|---|
| Uplink-Modus | Auto · WLAN erzwingen · SIM erzwingen |
| SIM-Karte | zwei Kartenschächte, zwei eSIM-Profile |
| Netze suchen | Scan auslösen |
| Netz wählen | Dropdown mit den gefundenen Netzen |
| Passwort | maskiertes Eingabefeld |
| Verbinden | mit dem gewählten Netz |
| Beste Basisstation messen | nur bei mehreren Accesspoints |
| Speedtest | nur über WLAN |
| Standort abfragen | außerhalb des 30-Minuten-Takts |
| Anschrift zur Position | Straße und Hausnummer, über OpenStreetMap |
| Router sichern | eine Kachel: zeigt das Datum, löst aus |
| Router neu starten | mit PIN |
| Pi herunterfahren | mit PIN |
| GPS-Empfang | Hinweis, wenn kein Fix vorliegt |

### Tablet als festes Bedienpanel

Ein Android-Tablet im Fahrzeug zeigt eine eigene, reduzierte Seite: große
Flächen, nur die Bedienelemente, die man unterwegs antippt. Es startet nach dem
Einschalten von selbst ins Dashboard, ohne Anmeldung, ohne sichtbare
Navigation. Home Assistant kann dabei Bildschirm und Helligkeit steuern und den
Akku überwachen — inklusive Ladeschonbereich, damit die Zelle die Hitze im
Fahrzeug übersteht. Der Bildschirm geht beim Abstellen an der Heimatadresse
von selbst aus und auf Reisen wieder an. Siehe Kapitel 8.

### Was im Hintergrund passiert

- Position alle 30 Minuten, sparsam und ohne Bewegungsspur im Minutentakt
- Modemtemperatur; eine Warnung erscheint, wenn der Router wegen Hitze drosselt
- Router-Konfiguration am ersten Tag jedes Monats, zwölf Stände werden behalten
- Netze mit Passwort und gewählter Basisstation werden gelernt
- Erinnerung, wenn der Uplink länger als vier Stunden erzwungen bleibt

---


## 2. Mindestanforderungen

### Router

| | |
|---|---|
| **Modell** | Teltonika RUTC50, RUTX50 oder RUTM50 |
| **Firmware** | RutOS 7.x · getestet mit RUTC_R_00.07.24.5 |
| **Pflicht** | **zwei WLAN-Bänder** · SSH aktiv · `mwan3` vorhanden |
| **Antenne** | Außen- oder Dachantenne für Mobilfunk |
| **GPS** | aktiviert — ohne Fix keine automatische Suche |

Andere OpenWRT-Router sind nicht getestet. Vorausgesetzt werden `uci`, `ubus`
und `mwan3`.

> **K.-o.-Kriterium:** Bei nur einem Funkchip — so beim RUTC50 — laufen
> Accesspoint und Client nur auf **verschiedenen Bändern**. Deine Geräte hängen
> am 5-GHz-Netz, 2,4 GHz gehört der Suche. Ein Einband-Router ist unbrauchbar.

### Raspberry Pi

| | Minimum | Empfohlen |
|---|---|---|
| Modell | Pi 4B | Pi 4B oder Pi 5 |
| Arbeitsspeicher | 2 GB | 4 GB |
| Speicher | 32 GB Karte, ~2 GB belegt | SSD über USB |
| Kühlung | passiv | **aktiv (Lüfter)** |
| Anbindung | **LAN-Kabel zum Router** | LAN-Kabel |
| Netzteil | **5,1 V / 3 A** | 3 A, im Fahrzeug gepuffert |

- **Strom:** Ein 1-A-Netzteil reicht nicht. Der Pi zieht beim Start über 1,2 A; bricht die Spannung ein, kommt er nicht durch — der Router zeigt dann Link, aber kein Paket. Beim Anlassen des Motors entsteht dasselbe Bild.
- **Kühlung:** 60 °C im Fahrzeug plus Browser-Last — ohne Lüfter drosselt der Pi.
- **Anbindung:** Über WLAN verlierst du beim Bandwechsel die Steuerverbindung.
- **Bei 1–2 GB:** `portal_browser_enabled` auf `false` spart ~500 MB.

### Software, Mobilfunk, Tablet

| | |
|---|---|
| Home Assistant OS | 14+ · getestet mit 17.3 |
| Home Assistant Core | 2024.6+ · getestet mit 2026.9.3 |
| Terminal-App | **vor der Installation nötig** — sonst kein Skriptstart |
| Mosquitto broker | installiert der Konfigurator selbst |
| Companion-App | für Benachrichtigungen und QR-Code |
| SIM / eSIM | eine Karte mit Datentarif; zwei möglich, umschaltbar |
| Tablet *(optional)* | Android ab 10″, getestet Fire HD 10 (11. Gen.) · App **Fully Kiosk Plus**, ~7 € · **nie in direkter Sonne** montieren, siehe Kapitel 8 |



## 3. Wie es aufgebaut ist

```
                    ┌──────────────────────────┐
   Campingplatz ))) │ 2,4 GHz  (Client)        │
                    │                          │
         5G/LTE ))) │ Modem, SIM oder eSIM     │
                    │                          │
                    │    mwan3 Failover        │  automatisch,
                    │    WLAN bevorzugt,       │  auf dem Router
                    │    Mobilfunk als Reserve │
                    │                          │
    deine Geräte ))) │ 5 GHz  (Accesspoint)     │
                    │                          │
      Pi / HAOS ────│ LAN                      │
                    └──────────────────────────┘
                              │ SSH (uci / ubus)
                    ┌─────────▼────────────────┐
                    │   App "Van Netzwerk"     │
                    │   Scan · Portal · Messen │
                    └─────────┬────────────────┘
                              │ MQTT Discovery
                    ┌─────────▼────────────────┐
                    │     Home Assistant       │
                    └──────────────────────────┘
```

### Zwei Ebenen, bewusst getrennt

**Der Router sorgt für die Verbindung.** Das Failover zwischen WLAN und
Mobilfunk läuft in `mwan3` auf dem Gerät selbst. Es funktioniert unabhängig
davon, ob Home Assistant läuft.

**Die App sorgt für den Komfort.** Scannen, Portal-Anmeldung, Messen,
Umschalten auf Wunsch. Fällt sie aus, bleibt die Internetverbindung bestehen —
du verlierst nur die Automatik.

Diese Trennung ist der wichtigste Entwurfsentscheid des Projekts. Eine
Hausautomation ist kein Fundament für die Internetverbindung eines Fahrzeugs.

### Warum SSH und nicht die REST-Schnittstelle

Die Steuerung läuft über SSH mit `uci` und `ubus`:

- Die REST-Endpunkte haben sich zwischen RutOS-Versionen mehrfach geändert
- Der API-Token läuft nach Minuten ab und muss ständig erneuert werden
- `uci` und `ubus` sind stabil und werden von Teltonika selbst für die
  WLAN-Client-Steuerung empfohlen

### Woher die Daten kommen

Alle Werte liest die App selbst per SSH und veröffentlicht sie über
MQTT-Discovery. Die offizielle Teltonika-Integration wird **nicht** benötigt —
sie scheitert auf RutOS 7.24 an einem fehlenden Feld in der API-Antwort
(Kapitel 14).

---
---

# Teil II — Einrichtung

## 4. Router vorbereiten

Dieser Teil lässt sich nicht automatisieren: Der Router ist ein eigenes Gerät
mit eigener Oberfläche. Rechne mit 45 Minuten.

> **Vorher ein Backup ziehen.** In der Weboberfläche unter
> *System → Backup → Download*. Falls etwas schiefgeht, bist du damit in zwei
> Minuten zurück statt beim Werksreset.

### 4.1 Bänder trennen

Der kritischste Schritt. Teltonika bestätigt: Accesspoint und Client
funktionieren bei einem einzigen Funkchip nur auf verschiedenen Bändern.
Teilen sie sich ein Band, bricht dein Fahrzeug-WLAN weg, sobald der Client
scannt.

| Radio | Band | Rolle |
|---|---|---|
| radio0 | 2,4 GHz | **Client** — sucht Campingplatz-WLAN |
| radio1 | 5 GHz | **Accesspoint** — deine Geräte |

Campingplatz-WLANs senden fast ausschließlich auf 2,4 GHz. Die Aufteilung
passt also zum Zweck.

```sh
# Eigenes Netz auf 5 GHz benennen
uci set wireless.default_radio1.ssid='MeinVanNetz'
uci set wireless.default_radio1.key='<eigenes Passwort, min. 12 Zeichen>'

# 2,4 GHz wird reines Suchradio
uci set wireless.default_radio0.disabled='1'

uci commit wireless && wifi reload
```

> **Folge:** Es gibt kein 2,4-GHz-Netz mehr vom Router. Geräte, die
> ausschließlich 2,4 GHz können — manche Sensoren, ältere Kameras,
> ESP-Bastelgeräte — lassen sich nicht mehr verbinden.

Kontrolle: `iwinfo` darf nur noch eine SSID auf Kanal 36 oder höher zeigen.

### 4.2 WLAN-Client anlegen

Die App schreibt einen bestehenden Abschnitt mit `mode='sta'` um. Existiert
der nicht, findet sie nichts.

In der Weboberfläche unter *Netzwerk → Wireless → Scan* **einmal manuell** mit
einem beliebigen Netz verbinden, dessen Passwort du kennst. Als Netzwerkname
`wan1` eintragen, Zone `wan`.

Kontrolle:

```sh
uci show wireless | grep "mode='sta'"
```

Kommt keine Zeile, hat es nicht geklappt.

> **Falls dort eine `bssid` steht,** entfernen — sonst verbindet sich der
> Client nur mit genau dieser einen Basisstation und scheitert überall sonst.
> Die App verwaltet diese Bindung ab jetzt selbst.

### 4.3 Namen notieren

```sh
mwan3 status
```

Du brauchst zwei Namen: den WLAN-Uplink (meist `wan1`) und den Mobilfunk
(`mob1s1a1` für Kartenschacht 1, `mob1s3a1e1` für eSIM-Profil 1).

```sh
uci show simcard | grep -E "position|primary|iccid"
```

Das zeigt, welche Karte als primär markiert ist.

### 4.4 Failover einrichten

```sh
# WLAN bevorzugen
uci set network.wan1.metric='1'
uci set network.<mobilfunk>.metric='2'
uci commit network

# Überwachung einschalten
uci set mwan3.wan1_member_mwan.metric='1'
uci set mwan3.<mobilfunk>_member_mwan.metric='2'
uci set mwan3.wan1.enabled='1'
uci set mwan3.<mobilfunk>.enabled='1'
uci commit mwan3

/etc/init.d/mwan3 restart
ifup <mobilfunk>
```

Niedrigere Metrik gewinnt. Die Prüfparameter sind in RutOS brauchbar
vorbelegt: Ping auf 1.1.1.1 und 8.8.8.8, Intervall 3 s, drei Fehlversuche —
das ergibt rund neun Sekunden Umschaltzeit.

Die übrigen Schnittstellen bewusst auf `enabled '0'` lassen, damit der Router
nie über einen leeren Kartenschacht oder einen unbenutzten Port routet.

### 4.5 Automatisches Umschalten der SIM prüfen

```sh
cat /etc/config/sim_switch
```

Steht dort bei einem **leeren** Kartenschacht `enabled '1'`, oder bei deiner
aktiven Karte ein `switch_back`, schaltet der Router von selbst weg — unter
Umständen auf einen Schacht ohne Karte. Siehe Kapitel 14, das war der
gravierendste Fund des Projekts.

### 4.6 GPS einschalten

**Ab Werk ist GPS abgeschaltet.** Das wird leicht uebersehen, weil der Dienst
trotzdem laeuft — er hat nur keine Instanz. Erst pruefen:

```sh
uci get gps.gpsd.enabled
```

Steht dort `0`, einschalten. Die drei weiteren Satellitensysteme gleich mit:

```sh
uci set gps.gpsd.enabled='1'
uci set gps.gpsd.galileo_sup='1'
uci set gps.gpsd.glonass_sup='1'
uci set gps.gpsd.beidou_sup='1'
uci commit gps
/etc/init.d/gpsd restart
```

Galileo, GLONASS und BeiDou kosten nichts und verkuerzen den ersten Fix
deutlich — in Staedten und Taelern ist das der Unterschied zwischen sofort
und mehreren Minuten. Das Modul empfaengt sie ohnehin.

Dann im Freien pruefen:

```sh
ubus call gpsd info '{}'
```

Es müssen echte Koordinaten erscheinen, nicht Null. **Merke dir das Feld
`speed`** — es wird in Kapitel 8 kalibriert.

> **Woran man es erkennt, wenn GPS fehlt:** `gpsctl -i` meldet
> `Unable to retrieve valid gpsd response: Not found`, und
> `/etc/init.d/gpsd status` sagt `active with no instances`. Das ist **nicht**
> „kein Empfang" — bei fehlendem Fix antwortet der Dienst und liefert nur
> keine Koordinaten.

**Ohne GPS steht mehr still als die Karte.** Die automatische WLAN-Suche
setzt voraus, dass das Fahrzeug drei Minuten unter 3 km/h war. Ohne
Positionsdaten gilt es nie als stehend, und der automatische Scan loest nie
aus — der Knopf im Dashboard funktioniert, die Automatik nicht. Wer sich
wundert, warum unterwegs nie von selbst ein Netz gefunden wird, pruefe
zuerst hier.

---

## 5. Installation in einem Befehl

### Vorbedingung

Auf einem frischen Home Assistant OS zuerst die App **Terminal & SSH** oder
**Advanced SSH & Web Terminal** installieren. Ohne Kommandozeile gibt es
keinen Weg, ein Skript zu starten — das ist die einzige Handarbeit.

### Der Befehl

Im Terminal:

```sh
curl -sSL https://raw.githubusercontent.com/BackonStyle/van-net-addon/main/install.sh -o i.sh && bash i.sh
```

### Was dabei passiert

1. Umgebung prüfen — CLI vorhanden, Verzeichnisse beschreibbar
2. **Mosquitto** installieren und starten, falls nicht vorhanden
3. App-Dateien aus dem Repository laden, vorhandene Version sichern
4. `packages`, `www/van-net` und `backups` anlegen
5. `packages:` in die `configuration.yaml` eintragen, mit Sicherung
6. **Dashboard-Seite** anlegen und eintragen — auf Rückfrage
7. **Konfigurator** — siehe nächstes Kapitel
8. App bauen und starten

Schritt 8 dauert beim ersten Mal **15 bis 25 Minuten**: Der Container wird auf
dem Gerät selbst gebaut und lädt dabei den Browser herunter. Die Ausgabe steht
währenddessen still. Nicht abbrechen.

Mehrfaches Ausführen ist unschädlich. Vorhandene Dateien werden mit Zeitstempel
gesichert, nicht überschrieben.

> **Tipp:** Baue, solange der Router noch an einem Festnetzanschluss hängt.
> Der Download über Mobilfunk kostet sonst knapp ein Gigabyte.

---

### 5.3 secrets.yaml — ohne diese drei Zeilen startet nichts

Die Package-Datei verweist an drei Stellen mit `!secret` auf
`/config/secrets.yaml`. **Fehlt auch nur ein Eintrag, startet Home Assistant
nicht**, sondern faellt in den abgesicherten Modus — und die Fehlermeldung
zeigt auf `van_net.yaml` statt auf die fehlende Zeile. Das kostet
erfahrungsgemaess eine Viertelstunde Suche.

Der Installer legt die Eintraege mit Platzhaltern an. Wer von Hand
installiert, ergaenzt sie selbst:

```yaml
tablet_sleep_url: "http://192.168.1.230:2323/?cmd=forceSleep&type=json&password=DEINPASSWORT"
tablet_screenon_url: "http://192.168.1.230:2323/?cmd=screenOn&type=json&password=DEINPASSWORT"
van_shutdown_pin: "0000"
```

| Eintrag | wofuer | wann anpassen |
|---|---|---|
| `tablet_sleep_url` | Tiefschlaf des Bedienpanels | mit dem Fully-Passwort aus 8.3 |
| `tablet_screenon_url` | Bildschirm wieder an | dito |
| `van_shutdown_pin` | Abschalt-Knopf | **sofort** — Vorgabe ist 0000 |

> Das Fully-Passwort darf keine Zeichen enthalten, die in einer Internetadresse
> eine eigene Bedeutung haben: `&`, `=`, `?`, `#`, `+` und Leerzeichen zerlegen
> den Aufruf. Buchstaben und Ziffern sind unproblematisch.

### 5.4 Den Pi geordnet herunterfahren

Das Stromkabel zu ziehen beschaedigt frueher oder spaeter die Datenbank. Home
Assistant schreibt staendig, und eine SD-Karte verzeiht einen Stromverlust
mitten im Schreibvorgang nicht — man merkt es erst beim naechsten Start.

Im Terminal:

```sh
ha host shutdown
```

Oder ueber die Kachel **Pi herunterfahren** im Bereich *Werkzeuge*. Sie oeffnet
ein kompaktes Fenster mit **genau einem Zahlenfeld** fuer die PIN; auf einem
Tablet geht dabei die Zifferntastatur auf. Dieselbe PIN sichert den
Router-Neustart.

> **Keine PIN mit fuehrender Null.** Das Feld ist ein Zahlenfeld, und `0123`
> kommt dort als `123` an — die Pruefung schluege dann immer fehl.

Beide Knoepfe melden bei falscher Eingabe „PIN falsch" und tun nichts. Die PIN
steht in `secrets.yaml` unter `van_shutdown_pin`, nicht im Dashboard.

Warum ueberhaupt eine PIN: die Kachel sitzt auf einem Bedienpanel im Fahrzeug.
Ein versehentlicher Druck schaltet das gesamte System ab, und danach hilft nur
noch der Griff ans Geraet.

Nach etwa dreissig Sekunden ist er aus. Der Pi 4B zeigt das nicht an, aber die
gruene LED hoert auf zu blinken und bleibt dunkel. Dann darf der Strom weg.

---

## 6. Was der Konfigurator fragt

Mit Enter übernimmst du jeweils die Vorgabe in eckigen Klammern. Alle Werte
sind später in der App unter *Konfiguration* änderbar.

| Frage | Vorgabe | Woher du den Wert nimmst |
|---|---|---|
| IP des Routers | 192.168.1.1 | Weboberfläche des Routers |
| Benutzername für SSH | root | — |
| Router-Passwort | — | Eingabe bleibt unsichtbar |
| WLAN-Uplink in mwan3 | wan1 | `mwan3 status`, Kapitel 4.3 |
| Mobilfunk in mwan3 | mob1s3a1e1 | `mwan3 status`, Kapitel 4.3 |
| Radio für den Client | wlan0 | nur ein Hinweis, siehe unten |
| Portal-Login per Browser | ja | bei 1–2 GB RAM: nein |
| Standort wie oft melden | 1800 s | 30 Minuten |

Nach der IP-Abfrage wird der Router angepingt. Antwortet er nicht, läuft die
Installation weiter — die App verbindet sich später von selbst.

**Zum Radio:** RutOS hängt an jede Schnittstelle einen Suffix, aus `wlan0`
wird intern `wlan0-3`. Der Suffix ändert sich, wenn Schnittstellen neu
angelegt werden. Die App sucht deshalb selbst nach der Schnittstelle im
Client-Modus; der Wert hier ist nur ein Startpunkt. Trag das Radio ohne Suffix
ein.

### Danach von Hand

**Benachrichtigungen.** In `config/packages/van_net.yaml` steht ein
Platzhalter für den Empfänger. Den eigenen Namen findest du unter
*Entwicklerwerkzeuge → Aktionen*, Suchfeld `notify.mobile`. An allen Stellen
ersetzen.

**Neu starten.** *Entwicklerwerkzeuge → YAML → Konfiguration prüfen*, dann
*Home Assistant neu starten*.

---

## 7. Dashboard und Fernzugriff

### Dashboard

Das Installationsskript fragt, ob es die Seite anlegen soll, und erledigt dann
beides: es legt `/config/dashboards/van-internet.yaml` ab und trägt den
Verweis in die `configuration.yaml` ein. Nach dem Neustart erscheint
**Internet** als eigener Eintrag in der Seitenleiste.

Es entsteht eine Seite mit drei sichtbaren Abschnitten — Verbindung,
Mobilfunk und Fahrzeug — dazu die Anmeldeseite, die nur bei Bedarf erscheint,
und **zwei Unterseiten**: eine fuer den WLAN-Verbindungsablauf, eine fuer die
Werkzeuge. Verwendet werden ausschliesslich eingebaute Karten,
kein HACS. Am Telefon ordnet sich alles einspaltig.

**Verbindung** traegt alles Zusammengehoerige. Ganz oben steht der Netzname
ueber die volle Breite — die Angabe, die man unterwegs am haeufigsten sucht.
Darunter halbbreite Kacheln, zwei je Reihe: Uplink-Modus, Zustandsanzeige,
Signal, gemessenes Tempo, Empfehlung, der Einstieg in den Verbindungsablauf
und die Werkzeuge. Die vier WLAN-bezogenen
Kacheln erscheinen nur, solange das WLAN auch wirklich die Internetquelle ist
— auf Mobilfunk schrumpft der Bereich von selbst.

Die Zustandsanzeige ist bewusst **keine** Kachel, sondern eine Markdown-Karte:
nur dort lassen sich Schriftschnitt, Ausrichtung und Symbolfarbe frei setzen.

| Uplink | Anzeige |
|---|---|
| WLAN | gruenes `mdi:wifi`, fett **WLAN** |
| Mobilfunk | rotes `mdi:wifi-off` (durchgestrichen), fett **Mobilfunk** |
| keiner | rotes `mdi:network-off`, fett **Kein Internet** |

Die Farben kommen aus den Themenfarben (`--success-color`, `--error-color`)
und passen sich hellem wie dunklem Erscheinungsbild an.

**Zwei Abläufe liegen auf Unterseiten**, erreichbar ueber je eine Kachel
im Verbindungsbereich: das Verbinden mit einem Netz und die Werkzeuge
(Speedtest, Sicherung, Neustart, Herunterfahren). Der Pfeil oben links kommt
zurueck. `subview: true` haelt die Seite
aus der Navigation heraus, sie ist also nur ueber die Kachel erreichbar. Ein
frei schwebendes Fenster kann Home Assistant aus einer Kachel heraus nicht
oeffnen -- eine Unterseite kommt dem am naechsten und braucht kein HACS.

Unter der Karte sitzt **eine** Kachel fuer Standort und Anschrift: sie zeigt
die Adresse und loest beim Antippen eine neue Abfrage aus. Der Zeitpunkt des
letzten Drucks interessiert niemanden, die Adresse schon.

Vier Karten erscheinen nur bei Bedarf: der QR-Code bei offener Anmeldeseite,
die Drosselungswarnung bei Hitze, die Messung der Basisstationen bei mehreren
Funden, und der Hinweis **Kein GPS-Empfang** unter der Karte.

> **Zu den Zeiger-Anzeigen.** Fruehere Fassungen zeigten Signal, Tempo und
> SINR als runde Zeiger. Die sehen gut aus, brauchen aber die dreifache Hoehe
> einer Kachel — auf einem Bedienpanel im Fahrzeug bedeutet das Scrollen. Sie
> wurden durch Kacheln ersetzt; die Farbabstufung nach Qualitaet entfaellt
> dabei.

> **Die Feinjustierung steht nicht mehr im Dashboard.** Bandbreite,
> Realismusfaktor und Wechselschwelle wirken unveraendert, sind aber nur noch
> unter *Einstellungen → Geraete & Dienste → Hilfselemente* erreichbar. Wer
> sie nie anfasst, soll sie auch nicht sehen.

> **Zwei Dinge zum Mitnehmen.** Dein vorhandenes Dashboard wird dabei nicht
> angefasst — die Seite ist ein eigener Eintrag. Dafür lässt sie sich **nicht
> über die Oberfläche bearbeiten**: Änderungen gehen über die Datei, danach
> den Browser neu laden.

**Existiert schon ein `lovelace:`-Block** in deiner `configuration.yaml`,
lässt das Skript die Datei unberührt und gibt den Abschnitt zum Einfügen aus.
Das ist Absicht — an einer bestehenden Dashboard-Konfiguration soll kein
Skript herumschreiben.

**Lieber als Seite im eigenen Dashboard?** Dann den Block unterhalb von
`views:` aus der Datei kopieren und über *Dashboard → Bearbeiten → ⋮ →
Rohkonfigurations-Editor* dort einhängen. So bleibt die Seite über die
Oberfläche bearbeitbar, muss aber bei einer Neuinstallation von Hand
nachgezogen werden.

### Fernzugriff über Tailscale

Nötig, wenn du vom Sofa an das Fahrzeug willst. Keine Portweiterleitung am
Router — denn dessen WAN-Seite ist später das Campingplatz-WLAN, und was du
fürs Heimnetz öffnest, steht dort genauso offen.

App **Tailscale** installieren, dann:

```yaml
accept_routes: true
advertise_routes:
  - 192.168.1.0/24
userspace_networking: false     # zwingend, sonst kein Subnetz-Routing
snat_subnet_routes: true
```

Danach im Tailscale-Webinterface unter *Machines → ⋯ → Edit route settings*
die Route **genehmigen**. Ohne diesen Haken meldet der Pi sie an, aber
Tailscale verteilt sie nicht — der häufigste Stolperstein.

Danach erreichst du Home Assistant unter seiner Tailscale-Adresse und über die
Subnetz-Route auch den Router selbst per SSH.


### 7.4 Standort und Anschrift

Die Position geht als Attribut an einen `device_tracker`. Dadurch erscheint das
Fahrzeug auf der Karte, ohne dass die Koordinaten als Zustand in jeder
Verlaufsansicht auftauchen — eine bewusste Entscheidung gegen eine
minuetliche Bewegungsspur in der Datenbank.

Zusaetzlich loest der Agent die Koordinaten in eine Anschrift auf und zeigt sie
in der Kachel unter der Karte:

```
Pariser Platz 2, 10117 Berlin
Alpseestrasse, 87645 Schwangau        (ohne Hausnummer)
Piazza San Marco, 30124 Venezia (IT)  (Ausland mit Laenderkuerzel)
```

Dafuer wird der Adressdienst **Nominatim** von OpenStreetMap befragt:
kostenlos, ohne Anmeldung, aber mit Nutzungsregeln. Hat sich das Fahrzeug
weniger als 50 Meter bewegt, nimmt der Agent die gespeicherte Antwort — bei
einem stehenden Wohnmobil ist das der Normalfall, und die erlaubte Abfragerate
wird dadurch um Groessenordnungen unterschritten.

> **Das sollte man wissen:** Bei jeder Standortmeldung verlassen die
> Koordinaten das Fahrzeug und gehen an einen fremden Dienst. Wem das nicht
> recht ist, entfernt den Aufruf von `_adresse_zu()` in `publish_position()` —
> Pin und Karte funktionieren unveraendert weiter, nur die Kachel bleibt leer.

Ohne GPS-Fix wird gar nichts gemeldet, auch keine veraltete Position. Lieber
keine Angabe als eine falsche. Siehe Kapitel 4.6, wenn dauerhaft nichts kommt.

---

## 8. Tablet im Fahrzeug

Ein festverbautes Tablet als Anzeige und Bedienung. Beschrieben für ein
**Amazon Fire HD 10 (11. Generation)**; für andere Android-Tablets gilt alles
außer dem Fire-OS-Teil.

### 8.1 Zuerst das Unbequeme: Hitze und Dauerladung

Amazon gibt für das Fire HD 10 einen Betriebsbereich von **0 bis 35 °C** an.
Ein geparktes Fahrzeug erreicht im Sommer hinter Glas 60 °C und mehr. Dazu
kommt, dass ein Tablet an Dauerstrom permanent bei 100 % Ladung steht.

Hitze und volle Zelle zusammen sind das Schlimmste für Lithium-Akkus. Ein
aufgequollener Akku, der die Displayscheibe hochdrückt, ist bei fest
verbauten Tablets der häufigste Ausfall — teils schon im ersten Jahr.

**Drei Gegenmaßnahmen, in dieser Reihenfolge:**

**Montageort.** Nicht hinter die Windschutzscheibe, nicht in direkte Sonne.
Eine Position an der Seitenwand oder im Schatten des Armaturenbretts macht
bei gleicher Außentemperatur 15 bis 20 °C Unterschied.

**Ladung begrenzen.** Fire OS kann das nicht selbst. Mit einem von Home
Assistant schaltbaren 12-V-USB-Netzteil lässt sich der Akku zwischen 25 und
80 Prozent halten — das vervielfacht die Lebensdauer. Die beiden
Automationen dafür stehen im Package und brauchen nur den Namen deines
Schalters.

**Ohne schaltbaren Strom:** Tablet an Zündungsstrom hängen. Dann lädt es
während der Fahrt und läuft im Stand auf Akku, bis es sich abschaltet. Für
die Zelle besser als Dauerstrom, aber das Tablet ist nach einigen Stunden
Standzeit aus.

> Plane realistisch mit zwei bis drei Jahren Lebensdauer. Das Fire HD 10 ist
> für diesen Preis ein gutes Anzeigegerät, aber kein Industriepanel.

### 8.2 Fire OS vorbereiten

**Automatische Updates abschalten.** Der wichtigste Schritt: Ein
Fire-OS-Update kann den Autostart und die Kiosk-Einstellungen
zurücksetzen — und es kommt ohne Vorwarnung.

*Einstellungen → Geräteoptionen → Systemaktualisierungen* und dort
automatische Updates deaktivieren.

**Werbung auf dem Sperrbildschirm.** Bei Geräten mit „Spezialangeboten"
blendet Fire OS Anzeigen ein. Amazon entfernt das gegen eine Einmalzahlung
über *Mein Konto → Geräte*. Alternativ bleibt der Bildschirm durch Fully
Kiosk ohnehin dauerhaft an, dann greift der Sperrbildschirm nicht.

**Energiesparen aus.** *Einstellungen → Akku* und den Energiesparmodus
abschalten. Fire OS beendet sonst Hintergrund-Apps.

**Mit dem Fahrzeug-WLAN verbinden.** Das 5-GHz-Netz des Routers.

**Feste Adresse geben.** Am Router, analog zum Raspberry Pi:

```sh
uci add dhcp host
uci set dhcp.@host[-1].name='van-tablet'
uci set dhcp.@host[-1].mac='<MAC des Tablets>'
uci set dhcp.@host[-1].ip='192.168.1.230'
uci commit dhcp && /etc/init.d/dnsmasq restart
```

Die MAC-Adresse steht unter *Einstellungen → Geräteoptionen → Info*.

### 8.3 Fully Kiosk Browser installieren

**Warum diese App:** Home Assistant hat seit Version 2022.9 eine **eingebaute
Integration** dafür. Damit kann HA den Bildschirm ein- und ausschalten, die
Helligkeit regeln und den Akkustand lesen — genau das, was die Automationen
aus Abschnitt 8.1 brauchen. Freie Alternativen wie WallPanel können das nicht.

Die App kostet als **Fully Plus** rund sieben Euro einmalig. Die
Fernverwaltung, auf der die HA-Integration aufsetzt, ist nur in dieser Fassung
ohne Wasserzeichen nutzbar.

**Installation.** Die App ist nicht im Amazon Appstore. Das APK lädst du im
Silk-Browser des Tablets direkt von `fully-kiosk.com`. Vorher unter
*Einstellungen → Sicherheit und Privatsphäre* die Installation aus unbekannten
Quellen für Silk erlauben.

**Einstellungen in Fully Kiosk**, nach dem ersten Start:

| Bereich | Einstellung | Wert |
|---|---|---|
| Web Content | Start URL | `http://192.168.1.223:8123/van-tablet/start` |
| Web Content | Enable JavaScript Interface | an |
| Web Content | Enable Zoom | aus |
| Device Management | Keep Screen On | an |
| Device Management | Launch on Boot | **an** |
| Device Management | Prevent Sleep | an |
| Kiosk Mode | Enable Kiosk Mode | **an** |
| Kiosk Mode | Disable Status Bar | an |
| Kiosk Mode | Disable Home Button | an |
| Remote Admin | Enable Remote Administration | **an** |
| Remote Admin | Remote Admin Password | setzen und notieren |

> **Kiosk-Modus erst zuletzt einschalten.** Danach kommst du nur noch über
> ein Wischen in eine Bildschirmecke plus PIN aus der App heraus. Vergib
> vorher eine PIN, die du dir merkst.

**Zur Kopfzeile von Home Assistant.** In vielen Anleitungen steht, man koenne
sie per *Custom CSS* in Fully Kiosk ausblenden. **Das funktioniert nicht**, und
zwar aus einem grundsaetzlichen Grund: die Oberflaeche von Home Assistant
besteht aus Web-Komponenten, deren Innenleben in abgeschotteten Bereichen
(Shadow DOM) liegt. Von aussen eingespritztes CSS erreicht `app-header` oder
`ha-menu-button` dort nicht — die Regel wird uebernommen und bleibt wirkungslos.
In neueren Fully-Fassungen fehlt das Eingabefeld ohnehin.

Zwei brauchbare Wege:

**Kopfzeile stehen lassen.** Sie kostet rund 50 Pixel. Das Bedienpanel ist auf
grosse Flaechen ausgelegt und verliert dadurch nichts. Als Nebeneffekt bleibt
ein Menuesymbol, ueber das sich die vollstaendige Internet-Seite erreichen
laesst, ohne den Kiosk zu verlassen. Fuer die meisten Fahrzeuge reicht das.

**`kiosk-mode` ueber HACS nachruesten.** Diese Erweiterung laeuft innerhalb der
Oberflaeche und kommt deshalb an die Stellen heran, an denen CSS scheitert. Sie
blendet Kopfzeile und Seitenleiste wahlweise pro Dashboard oder pro Benutzer
aus. Dafuer sind HACS, eine Installation und ein Neustart noetig — ein eigener
Arbeitsschritt, kein Nebenbei.

### 8.4 Anmeldung ohne Passwort

Ein Tablet, das nach jedem Neustart eine Anmeldung verlangt, ist als Anzeige
unbrauchbar. Home Assistant kann Geräte aus bestimmten Adressen automatisch
anmelden.

In der `configuration.yaml`:

```yaml
homeassistant:
  auth_providers:
    - type: homeassistant
    - type: trusted_networks
      trusted_networks:
        - 192.168.1.230/32      # genau das Tablet, nichts sonst
      trusted_users:
        192.168.1.230: <Benutzer-ID des Tablet-Kontos>
      allow_bypass_login: true
```

> **Was das bedeutet:** Wer diese IP-Adresse benutzt, kommt ohne Passwort in
> Home Assistant. Deshalb exakt eine Adresse mit `/32`, nicht das ganze Netz.
> Lege im Voraus einen **eigenen Benutzer** für das Tablet an — ohne
> Administratorrechte. Dann kann von dort niemand Einstellungen ändern, auch
> wenn jemand das Tablet in die Hand nimmt.
>
> Die Benutzer-ID findest du unter *Einstellungen → Personen →* Benutzer
> anklicken; sie steht in der Adresszeile.
>
> Dieser Weg setzt voraus, dass du dem Fahrzeug-WLAN vertraust. Gibst du das
> WLAN-Passwort an Gäste weiter, vergib für die eine eigene SSID.

Nach der Änderung: *Entwicklerwerkzeuge → YAML → Konfiguration prüfen*, dann
Home Assistant neu starten.

### 8.5 Tablet in Home Assistant einbinden

*Einstellungen → Geräte & Dienste → Integration hinzufügen → Fully Kiosk
Browser*

| Feld | Wert |
|---|---|
| Host | `192.168.1.230` |
| Passwort | das Remote-Admin-Passwort aus 8.3 |

Danach existieren unter anderem `sensor.van_tablet_battery` und
`light.van_tablet_screen`. **Die Namen hängen davon ab, wie du das Gerät in
Home Assistant benennst** — prüfe sie unter *Entwicklerwerkzeuge → Zustände*
und passe sie im Package und im Dashboard an, falls sie abweichen.

### 8.6 Tablet-Dashboard

Eine eigene Seite, bewusst reduziert: große Flächen für Finger, nur was man im
Fahrzeug antippt. Feinjustierung und Diagnose bleiben auf dem Telefon.

Datei `homeassistant/van-tablet.yaml` nach `/config/dashboards/` kopieren,
dann in der `configuration.yaml` unter `lovelace.dashboards` ergänzen:

```yaml
    van-tablet:
      mode: yaml
      filename: dashboards/van-tablet.yaml
      title: Tablet
      icon: mdi:tablet-dashboard
      show_in_sidebar: false
```

`show_in_sidebar: false` hält die Seite aus deiner eigenen Navigation heraus —
erreichbar ist sie trotzdem über die Adresse, die das Tablet aufruft.

Die Seite zeigt: Verbindungsstatus groß, Uplink- und SIM-Umschalter, die vier
Schritte zum WLAN-Verbinden, Mobilfunk kompakt und die Bildschirmsteuerung des
Tablets. Der QR-Code für Anmeldeseiten erscheint bildschirmbreit mit
Erklärtext — auf dem Tablet ist er am nächsten dran, wenn man ihn braucht.

### 8.7 Automationen

Sieben Automationen für das Tablet stehen im Package:

| Automation | Zweck |
|---|---|
| Laden ein unter 25 % | Akku im Schonbereich halten |
| Laden aus über 80 % | Akku im Schonbereich halten |
| Bildschirm aus zu Hause | beim Abstellen an der Heimatadresse |
| Bildschirm an auf Reisen | beim Verlassen der Heimatzone |
| Zustand nach Neustart | stellt nach einem HA-Neustart das Richtige her |
| Helligkeit nach Tageszeit | nachts 15 %, tags 90 %, nur unterwegs |
| Nicht erreichbar | Meldung nach 15 Minuten Stille, nur unterwegs |

**Anzupassen:** `switch.tablet_ladung` ist der Schalter deiner 12-V-Versorgung.
Hast du keinen, lösche die beiden Akku-Automationen.

> **„Aus" heißt Bildschirm aus, nicht Strom weg.** Ein ausgeschaltetes
> Fire-Tablet lässt sich per Software nicht wieder einschalten — Strom
> anlegen lädt nur, bootet aber nicht. Mit dunklem Bildschirm bleibt das
> Gerät erreichbar und zieht etwa ein halbes Watt.

**Wie die Ankunft erkannt wird.** Der Agent meldet die Position
außerplanmäßig, sobald das Fahrzeug nach einer Fahrt zum Stehen kommt. Ohne
das würde die Zonen-Automation erst beim nächsten 30-Minuten-Takt auslösen —
du wärst längst im Haus, und der Bildschirm würde noch leuchten.

**Warum die Offline-Meldung nur unterwegs greift.** Zu Hause darf das Tablet
nach Wochen Standzeit leerlaufen. Eine Warnung dafür wäre eine Fehlmeldung,
und Fehlmeldungen trainieren das Wegklicken.

### 8.8 Was das für den Akku bedeutet

Eine verbreitete Annahme: „Bildschirm aus schont den Akku." Das stimmt nicht.
Lithiumzellen altern durch **hohen Ladestand × Wärme × Zeit**. Ob das Display
leuchtet, kostet nur Strom.

**Der Nutzen liegt woanders:** Die Kombination aus „nur unterwegs an" und dem
25-bis-80-Prozent-Fenster vermeidet genau das Szenario, das Tablets im
Fahrzeug tötet — tagelang bei voller Ladung in einem heißen, geparkten Auto
stehen. Unterwegs ist das Fahrzeug belebt und belüftet, und der Akku wird
benutzt statt nur gehalten.

Steht das Fahrzeug lange zu Hause, pendelt der Ladestand durch die beiden
Lade-Automationen langsam zwischen 25 und 80 Prozent. Das ist deutlich
schonender als dauerhaft 100 Prozent, auch wenn es Ladezyklen kostet.

### 8.9 Wäre ein Touchscreen besser?

Ein 12-V-betriebener Touchscreen hat kein Akkuproblem — die Schwachstelle
entfällt vollständig. Für ein Panel, das rund um die Uhr läuft, wäre das die
richtige Antwort.

**Der Haken:** Home Assistant OS hat keine Desktop-Oberfläche. Darauf lässt
sich kein Browser starten. Ein Touchscreen bräuchte also einen **zweiten
Rechner** — etwa einen Pi mit Raspberry Pi OS und Chromium im Kiosk-Modus —
nur zum Anzeigen.

| | Tablet | Touchscreen + zweiter Pi |
|---|---|---|
| Akku als Schwachstelle | ja | **nein** |
| Fire-OS-Updates | können den Kiosk zerstören | entfällt |
| Temperaturtoleranz | 0–35 °C | deutlich weiter |
| Geräte im Fahrzeug | 1 | 2 |
| Aufwand | App installieren | Gehäuse, Verkabelung, zweites System |
| Zusatzkosten | — | 80–150 € |

**Empfehlung:** Bei der Nutzung „nur unterwegs an" ist das Tablet die
richtige Wahl — die Automationen entschärfen dessen einzige echte Schwäche.
Der Touchscreen lohnt sich, wenn das Panel dauerhaft laufen soll oder das
Fahrzeug viel in der Sonne steht. Ein späterer Wechsel ist unproblematisch:
Die Dashboard-Dateien bleiben unverändert, nur das Anzeigegerät tauscht.

### 8.10 Prüfen

1. Tablet neu starten — Fully Kiosk muss von selbst starten und das
   Dashboard zeigen, ohne Anmeldung
2. Statusleiste und Seitenleiste von Home Assistant dürfen nicht sichtbar sein
3. Uplink-Modus auf dem Tablet umschalten, Wirkung am Telefon prüfen
4. In Home Assistant `light.van_tablet_screen` ausschalten — der Bildschirm
   des Tablets muss dunkel werden
5. `sensor.van_tablet_battery` muss einen Prozentwert zeigen

Klappt Schritt 1 nicht, liegt es fast immer an *Launch on Boot* oder am
Energiesparmodus von Fire OS.

## 9. Abnahmetests

Der Reihe nach, jeder baut auf dem vorigen auf.

### Test 1 — Grundfunktion

Auf dem Dashboard:

| Entität | Erwartung |
|---|---|
| Aktiver Uplink | `wifi` oder `mobile`, nicht `unknown` |
| Internet verfügbar | an |
| **Letzter Fehler** | **leer** |

Steht dort `SSH fehlgeschlagen`, fehlt das Router-Passwort.

### Test 2 — Manuelles Umschalten

Uplink-Modus auf **SIM erzwingen**, 30 Sekunden warten, aktiver Uplink muss
auf `mobile` wechseln. Dann zurück auf **Auto**.

### Test 3 — Automatisches Failover

Das Kernziel. Modus auf **Auto**, dann dem Router die WLAN-Quelle wegnehmen.
Nach etwa neun Sekunden muss der Mobilfunk tragen, ohne dass deine Geräte die
Verbindung verlieren. Quelle zurückgeben, Uplink geht wieder auf `wifi`.

### Test 4 — GPS kalibrieren

> Dieser Test wird am häufigsten übersprungen — und dann scannt das System
> entweder dauernd während der Fahrt oder nie.

Eine Runde mit konstant etwa 50 km/h fahren, dann die
Fahrzeuggeschwindigkeit ansehen:

| Anzeige | Bedeutung | Lösung |
|---|---|---|
| ~50 | korrekt | nichts tun |
| ~14 | Umrechnung fehlt | in `router.py` `* 3.6` ergänzen |
| ~180 | doppelt umgerechnet | `* 3.6` entfernen |

Die Stelle heißt `_normalise_gps`. Danach die App neu starten.

Anschließend anhalten und drei Minuten warten: **Fahrzeug steht** muss
umschalten.

### Test 5 — WLAN-Suche

Bei stehendem Fahrzeug den Knopf **Netze suchen** drücken. Im Protokoll muss
die Anzahl gefundener Netze auftauchen.

### Test 6 — Anmeldeseite

Nur auf einem echten Campingplatz prüfbar. Läuft die Automatik durch, merkst
du nichts. Scheitert sie, kommt der QR-Code aufs Handy.

> **Beim Scannen muss das Handy im Fahrzeug-WLAN bleiben.** Über Mobilfunk
> geöffnet, schaltest du nur das Handy frei, nicht den Router.

### Test 7 — Basisstationen

Auch nur in einer echten Mehrfach-Anlage prüfbar. Steht bei
**Basisstationen im Netz** eine Zahl über 1, erscheint der Messknopf.

---
---

# Teil III — Betrieb

## 10. Der Alltag

**Normalfall: nichts tun.** Modus steht auf `Auto`, deine Geräte hängen
dauerhaft am Fahrzeug-WLAN.

**Während der Fahrt** nutzt der Router die SIM. Es wird nicht gescannt.

**Bei Ankunft** sucht das System nach drei Minuten Stillstand. Bekannte Netze
zuerst, dann offene nach Signalstärke. Bei einem bekannten Netz mit gelernter
Basisstation geht es direkt dorthin.

**Bei einer Anmeldeseite** versucht es den Login selbst. Klappt das nicht,
kommt der QR-Code.

**Danach** wird gemessen. Liegt der geschätzte Mobilfunk deutlich darüber,
bekommst du einen Vorschlag mit Knopf.

**Bei mehreren Basisstationen** lohnt der Messknopf. Rund eine Minute pro
Station, dafür bleibt die Wahl gespeichert.

**Nach vier Stunden** im erzwungenen Modus erinnert dich Home Assistant, damit
du nicht unbemerkt Datenvolumen verbrauchst.

---

## 11. Was das System nicht kann

Ehrliche Grenzen, damit du nicht an der falschen Stelle suchst.

### Anmeldeseiten: etwa 80 Prozent

**Funktioniert:** Zustimmungsfelder mit Absenden-Knopf, Cookie-Banner, die
meisten Standard-Hotspot-Systeme, mehrsprachige Seiten.

**Funktioniert nicht:** Gutscheincodes, Zimmer- oder Standplatznummern,
SMS-Bestätigung, Anmeldung über soziale Netzwerke, CAPTCHAs. Dafür ist der
QR-Code da, und der kostet zehn Sekunden.

### Mobilfunk-Durchsatz: Schätzung mit ±30 Prozent

Die echte Geschwindigkeit ließe sich nur messen, indem man die SIM benutzt.
Das kostet Volumen und setzt ein Umschalten voraus — also genau das, was nicht
automatisch passieren soll.

Gerechnet wird aus SINR und RSRP nach Shannon, gedeckelt bei 256QAM, mit
MIMO-Faktor und einem einstellbaren Realismusfaktor für die geteilte Funkzelle.

| Lage | Schätzung |
|---|---|
| 5G stark (SINR 25, RSRP −80) | 300 Mbit/s |
| 5G gut (SINR 18, RSRP −90) | 243 Mbit/s |
| LTE brauchbar (SINR 10, RSRP −105) | 98 Mbit/s |
| LTE schwach (SINR 3, RSRP −115) | 26 Mbit/s |
| Funkloch (SINR −2, RSRP −125) | 4 Mbit/s |

Die Frage „lohnt sich der Wechsel überhaupt" beantwortet das zuverlässig.
„Wie viele Mbit/s genau" nicht.

Nach einigen Wochen lässt sich der Realismusfaktor nachjustieren: einen echten
Speedtest über die SIM mit dem geschätzten Wert vergleichen.

### Kein 2,4-GHz-Netz für deine Geräte

Folge des einzelnen Funkchips. Geräte, die nur 2,4 GHz können, lassen sich
nicht ans Fahrzeug-WLAN anschließen.

### Ohne GPS-Fix keine Automatik

In einer Tiefgarage oder bei Antennenproblemen gibt es keine Geschwindigkeit,
also gilt das Fahrzeug nicht als stehend, also wird nicht automatisch gesucht.
Der Knopf **Netze suchen** umgeht das jederzeit.

### Dauerhafter Pflegeaufwand

Anmeldeseiten ändern sich. Nach jedem Fehlschlag liegt ein Bildschirmfoto
unter `share/van-net/screenshots/`. Damit lässt sich meist in Minuten ein
passendes Schlagwort in `ACCEPT_PATTERNS` ergänzen.

### Rechtliches

Die Automatik akzeptiert Nutzungsbedingungen, die du nicht gelesen hast.
Manche Betreiber untersagen automatisierten Zugriff ausdrücklich. Das ist deine
Entscheidung.

---

## 12. Fehlersuche

### App startet nicht

| Meldung | Ursache | Lösung |
|---|---|---|
| `Kein MQTT-Broker gefunden` | Mosquitto läuft nicht | App installieren und starten |
| `SSH fehlgeschlagen: Authentication failed` | falsches Passwort | Konfiguration prüfen |
| `SSH fehlgeschlagen: timed out` | IP falsch oder SSH aus | Router prüfen |
| `Keine WiFi-Client-Schnittstelle gefunden` | Kapitel 4.2 übersprungen | nachholen |

### App taucht nicht im Store auf

Dateien müssen direkt in `/addons/van_net/` liegen, nicht eine Ebene tiefer.
Danach *App-Store → ⋮ → Nach Updates suchen* und Seite neu laden.

### Fahrzeug-WLAN bricht beim Scannen weg

Immer der Bänder-Fehler. Mit `iwinfo` prüfen, ob auf dem 2,4-GHz-Radio ein
Accesspoint läuft. Kapitel 4.1 wiederholen.

### Keine Entitäten in Home Assistant

MQTT-Integration eingerichtet? Steht im App-Protokoll
`MQTT-Discovery veroeffentlicht`? Dann App neu starten und 30 Sekunden warten.

### QR-Code wird nicht angezeigt

`config/www/van-net/` muss existieren. Fehlt der Ordner, anlegen und App neu
starten.

### Geschwindigkeit immer 0 km/h

GPS-Einheit falsch interpretiert. Test 4 in Kapitel 8.

### Nach dem Messen der Basisstationen kein Internet

Die Bindung an eine Basisstation kann hängen bleiben, wenn die Messung
abbricht. Einmal **Verbinden** drücken — das löst die Bindung und verbindet
frei.

### Protokolle

```sh
ha apps logs local_van_net        # App
ha supervisor logs                 # Supervisor
ls -lt /share/van-net/screenshots/ # Portal-Fehlschläge
```

---

## 13. Wartung und Updates

### App aktualisieren

Liegt die App als lokaler Ordner (`repository: local`), zählt **der Ordner**,
nicht das Repository. Dateien per Samba nach `addons/van_net/` kopieren, dann:

```sh
ha apps rebuild local_van_net
```

Die Versionsanzeige bleibt dabei auf dem alten Stand stehen — der Supervisor
aktualisiert die Metadaten lokaler Apps nicht. Ob der neue Code läuft, prüft
man an den Entitäten, nicht an der Versionsnummer.

### Router-Sicherung

Läuft automatisch am ersten Tag jedes Monats um 03:17 Uhr. Die Sicherung landet
unter `/share/van-net/backups/` auf dem Pi, nicht auf dem Router — ein defektes
Gerät nimmt seine eigene Sicherung mit. Zwölf Stände werden behalten, also ein
Jahr.

Der Knopf **Router jetzt sichern** löst es außerplanmäßig aus.

### Dashboard ändern

Die Seite kommt aus `/config/dashboards/van-internet.yaml`. Datei bearbeiten,
speichern, Browser neu laden — ein Neustart von Home Assistant ist nicht
nötig. Über die Oberfläche ist sie bewusst nicht bearbeitbar.

### Gelernte Daten

| Datei | Inhalt |
|---|---|
| `/data/learned_networks.json` | Netze mit Passwort |
| `/data/learned_aps.json` | gewählte Basisstation pro Netz |

Beide überstehen Neustarts und App-Updates, beide haben Dateirechte 600. Bei
einer Deinstallation gehen sie verloren.

### Firmware des Routers

Vor einem Firmware-Update eine Sicherung ziehen. Updates können `uci`-Pfade
ändern; danach Test 1 und 3 wiederholen.

---
---

# Teil IV — Hintergrund

## 14. Wie es entstanden ist

Das Projekt entstand in zwei Tagen, in sieben Schritten. Die Reihenfolge ist
kein Zufall — jeder Schritt deckte etwas auf, das den nächsten geprägt hat.

### Schritt 1 — Die Hardware-Grenze verstehen

Die ursprüngliche Anforderung lautete: WLAN scannen und gleichzeitig das
Fahrzeug-WLAN betreiben. Die Recherche ergab, dass Teltonika das für Geräte mit
einem Funkchip ausdrücklich ausschließt — Accesspoint und Client gehen nur auf
verschiedenen Bändern.

Das legte die gesamte Architektur fest: 2,4 GHz wird Suchradio, 5 GHz bleibt
das eigene Netz. Alles Weitere baute darauf auf.

### Schritt 2 — Den Router einrichten

Zuerst per Weboberfläche geplant, dann auf SSH umgestellt, weil der eingebaute
Browser keine lokalen Adressen erreicht. Das erwies sich als Glücksfall:
`uci`-Befehle sind eindeutig, ihre Ausgaben nachprüfbar, und jeder Schritt
ließ sich einzeln bestätigen.

Dabei kamen zwei Funde zutage, die nichts mit der Aufgabe zu tun hatten, aber
alles mit der Funktionsfähigkeit — siehe Kapitel 14.

### Schritt 3 — Failover und Beweis

Metriken gedreht, Überwachung eingeschaltet, in beide Richtungen getestet. Ab
hier stand das Kernziel: durchgehend Internet im Fahrzeug, unabhängig von Home
Assistant.

### Schritt 4 — Die App ins Laufen bringen

Der mühsamste Teil, und nicht wegen des Codes. Erst scheiterte die
Installation als lokale App, dann über ein Git-Repository, dann an einer
Oberfläche, die Add-ons inzwischen „Apps" nennt und lokale Ordner anders
behandelt als dokumentiert. Die Lösung lag am Ende in einer Kombination aus
beidem (Kapitel 14).

### Schritt 5 — Die Integration ersetzen

Die offizielle Teltonika-Integration brach an der aktuellen Firmware. Statt zu
warten, liest die App die Signalwerte jetzt selbst über `ubus` — ein Befehl,
kein Token, keine Versionsabhängigkeit. Das Ergebnis ist robuster als der
Umweg über die Integration.

### Schritt 6 — Bedienbar machen

Bis hierher musste jedes WLAN vorab in eine Konfigurationsdatei eingetragen
werden. Dropdown, Passwortfeld und Verbinden-Knopf machten daraus etwas, das
man auf einem Campingplatz tatsächlich benutzt. Dazu Standort, SIM-Auswahl,
Router-Neustart und Sicherung.

### Schritt 7 — Vom stärksten zum besten Signal

Der letzte Schritt kam aus der Praxis: eine Unifi-Anlage, bei der der nächste
Accesspoint guten Funk und schlechtes Internet hatte. Die Lösung steckte
ironischerweise in genau dem, was in Schritt 2 entfernt worden war — die
feste Bindung an eine Basisstation. Jetzt wird sie gemessen statt geraten.

### Schritt 8 — Der erste Tag im Echtbetrieb

Der Tag, an dem alles zusammenkam, und der die meisten Fehler zutage foerderte
— nicht trotz, sondern wegen des echten Betriebs.

Sechs Funde an einem Nachmittag: ein zu schwaches Netzteil, das den Pi gar
nicht erst starten liess; Add-on-Optionen, die beim Aktualisieren leer bleiben;
ein Vorlagensensor, der einen Text statt einer Zahl lieferte; ein 5-GHz-Kanal,
den europaeische Geraete nicht sehen duerfen; abgeschaltetes GPS; und die
doppelte Quotierung, die jeden Netznamen unbrauchbar machte.

Alle sechs stehen in Kapitel 15, mit Symptom, Ursache und Nachweis. Keiner
davon war ein Programmierfehler im engeren Sinn — es waren Annahmen, die im
Trockenen stimmten und in der Wirklichkeit nicht.

Gleichzeitig hat der Kern gehalten: als der WLAN-Uplink waehrend der Arbeit
wegbrach, uebernahm die eSIM und trug fast sechs Stunden lang den gesamten
Verkehr, ohne dass jemand eingreifen musste. Genau dafuer wurde das System
gebaut, und es hat sich bewaehrt, bevor die erste Reise begann.

Dazu kamen die Bequemlichkeiten, die erst im Gebrauch auffallen: Knoepfe, die
sofort ausloesen statt ein Fenster zu oeffnen; eine Anschrift unter der Karte
statt nackter Koordinaten; ein Abschalt-Knopf mit PIN, damit niemand das
System im Vorbeiwischen ausknipst.

### Schritt 9 — Die Oberflaeche wird benutzbar

Der Tag nach der Inbetriebnahme, und der erste, an dem nicht mehr die Technik
im Weg stand, sondern die Bedienung. Alle Aenderungen kamen aus dem Gebrauch,
keine aus einer Planung:

Knoepfe oeffneten beim Antippen ein Fenster, statt zu tun, was draufsteht —
`tap_action: perform-action` behebt das, und der Scan-Knopf, der angeblich
defekt war, funktionierte danach auf Anhieb: wer das Fenster schloss, ohne auf
*Druecken* zu tippen, hatte nie einen Befehl geschickt.

Zwei gefaehrliche Knoepfe bekamen eine PIN. Erst mit Bestaetigungshaken und
Textfeld, dann als Ziffernblock im Dashboard, schliesslich als kompaktes
Fenster mit einem einzigen Zahlenfeld. Drei Anlaeufe fuer eine Sache, die man
nicht vorher entscheiden kann — man muss sie am Geraet in der Hand halten.

Kacheln waren doppelt so hoch wie noetig (`vertical: true`), Zeiger-Anzeigen
brauchten die dreifache Hoehe einer Kachel, und Abschnitte richteten sich an
der hoechsten Spalte aus statt Luecken zu fuellen. Zusammen bedeutete das auf
einem 10-Zoll-Tablet im Querformat dauerndes Scrollen.

Und der Uplink stand als Wort da — `wifi` oder `mobile` —, wo ein Symbol
gereicht haette. Jetzt traegt die Farbe die Information, nicht der Text.

Der groesste Einzelgewinn war nichts davon, sondern eine Einsicht ueber
Reihenfolge: was man staendig ansieht, gehoert nach oben; was man nur auf
einem Campingplatz braucht, auf eine Unterseite. Danach passte alles ohne
Scrollen auf den Bildschirm.

---

## 15. Gefundene Fehler

### Die eSIM wurde alle 15 Minuten abgeschaltet

Der gravierendste Fund, und er hatte nichts mit der Aufgabe zu tun.

Aus `/etc/config/sim_switch`:

```
config sim                 # Schacht 1 — physisch leer
    option position '1'
    option enabled '1'
    option order '1'

config sim                 # Schacht 3 — die eSIM
    option position '3'
    option enable_back '1'
    option switch_back '15'
    option order '3'
```

Belegt durch das Protokoll:

```
19:42:52  Joined 5G-NSA network ... Connected to operator
19:42:55  Mobile data connected (IPv4)
19:58:45  Changing to SIM1 (After set timeout)
19:58:46  Mobile data disconnected
19:58:51  PIN State changed to: SIM not inserted (10)
```

Die eSIM verband sich, und nach 16 Minuten schaltete der Router auf den
**leeren** Kartenschacht. Das Fahrzeug wäre im Viertelstundentakt offline
gegangen — unabhängig vom Empfang, und äußerst schwer zu finden, wenn man es
unterwegs als „die Verbindung ist manchmal weg" erlebt.

Dass die eSIM in `/etc/config/simcard` als `primary` markiert war, half nicht:
`sim_switch` ist eine eigene Mechanik und überstimmt diese Markierung.

Behoben durch Abschalten der Umschaltung auf den leeren Schacht und Entfernen
von `switch_back`. Ein Neustart war nötig, weil das Modem hardwareseitig auf
dem leeren Schacht stand.

### Die Metriken standen verkehrt

Der WLAN-Uplink hatte Metrik 8, die Mobilfunk-Schnittstellen 3 bis 7.
Niedriger gewinnt — WLAN wäre also nie bevorzugt worden. Zusätzlich war für
**keine** Schnittstelle die Überwachung aktiv, das Failover hätte also
ohnehin nicht ausgelöst.

### Der Client war an eine Basisstation gefesselt

Der vorhandene WLAN-Client trug eine feste `bssid` der heimischen Fritz!Box.
Damit hätte er sich auf keinem Campingplatz verbinden können. Entfernt — und
in Schritt 7 als steuerbare Funktion wieder eingeführt.

### Die Teltonika-Integration ist inkompatibel

```
1 validation error for ApiResponse[DeviceStatusData]
data.static.release.target  Field required
```

Sie erwartet ein Feld, das RutOS 7.24 nicht mehr mitschickt. Die App liest die
Werte jetzt selbst:

```sh
ubus call gsm.modem0 get_signal_query '{}'
→ {"net_mode":"LTE","rssi":-57,"rsrp":-105,"sinr":-13,"rsrq":-20}
```

### Schnittstellennamen tragen einen Suffix

```
ubus call iwinfo scan '{"device":"wlan0"}'    → Not found
ubus call iwinfo scan '{"device":"wlan0-3"}'  → liefert Netze
```

Der Suffix kann sich ändern, wenn Schnittstellen neu angelegt werden. Die App
sucht deshalb selbst nach der Schnittstelle im Client-Modus und nutzt den
konfigurierten Wert nur als Startpunkt.

### Lokale Apps: Quelle ist der Ordner, nicht das Repository

Zunächst schien HA OS 17.3 das Verzeichnis `/addons` nicht mehr einzulesen:
Weder die App noch ein minimales Wegwerf-Beispiel tauchten auf, und im
Startprotokoll des Supervisors fehlte jede Zeile dazu. Nach dem Einbinden als
Git-Repository erschien sie.

**Aber:** Sie trägt `repository: local`. Die installierte App stammt also aus
dem Ordner, nicht aus dem Repository — das Hinzufügen der Git-Quelle hat nur
einen vollständigen Scan ausgelöst, bei dem der lokale Ordner mitgenommen
wurde.

Für Änderungen zählt deshalb der Ordner. Das Repository bleibt als Sicherung
und für die Installation auf weiteren Geräten sinnvoll.

### Link vorhanden, aber kein einziges Paket — ein 1-A-Netzteil

Nach dem Wiederaufbau zu Hause war der Pi nicht erreichbar. Die Suche lief
der Reihe nach: Mac im richtigen Netz (`192.168.1.194`, Router `.1`) ✓, Pi
nicht im DHCP-Lease, auch nicht im Hausnetz hinter der Fritz!Box, kein Dienst
auf Port 8123 oder 4357 bei keinem der 16 dort gefundenen Geräte.

Entschieden hat es der Blick auf die Bridge:

```
lan2@eth0  UP  <BROADCAST,MULTICAST,UP,LOWER_UP>   # Kabel hat Kontakt
6: lan2@eth0: ... state forwarding cost 5          # Port leitet weiter

=== MAC-Tabelle br-lan ===
aa:bb:cc:dd:ee:ff dev wlan1-2 ...                  # nur der Mac über WLAN
                                                   # kein Eintrag für lan2
```

`LOWER_UP` bei leerer MAC-Tabelle ist eine eindeutige Signatur: die Buchse ist
elektrisch belegt, aber das Gerät dahinter hat **kein einziges Paket**
gesendet. Ein laufendes Home Assistant ist nie still. Also lief es nicht.

Ursache war das Netzteil — 1 A. Der Pi 4B mit Lüfter zieht beim Start über
1,2 A, die Spannung bricht ein, der Startvorgang kommt nicht durch. Der
Ethernet-Baustein bekommt trotzdem Strom und verhandelt die Verbindung; von
außen sieht das aus wie ein Netzwerkproblem und führt eine halbe Stunde in
die falsche Richtung.

Zwei Lehren daraus, beide in Kapitel 2 aufgenommen: **5,1 V / 3 A sind
Pflicht**, und im Fahrzeug muss der Wandler die 3 A auch beim Anlassen des
Motors halten — ein Spannungseinbruch dort erzeugt dasselbe Bild, nur
unterwegs und ohne Terminal. Wer das Muster kennt, spart sich die Suche:
*Link ja, MAC-Tabelle leer* heißt Strom oder Startmedium, nie Netzwerk.

Beiläufig fiel dabei auf, dass der Pi seine Adresse über DHCP bezieht und
nach jedem Neustart eine andere bekommen kann. Eine feste Reservierung auf
seine MAC-Adresse im Router gehört zur Einrichtung — siehe Kapitel 5.

### Die SSID bekam Anfuehrungszeichen verpasst — doppelte Quotierung

Der folgenschwerste Fehler des Projekts, und er wurde nur durch Zufall sichtbar.
Nach einem Verbindungsversuch ueber das WLAN-Dropdown stand im Router:

```
wireless.1.ssid=<Netzname mit Apostrophen drumherum>   # der Client
wireless.default_radio1.ssid='Fahrzeug-WLAN'            # der Accesspoint
```

Die zweite Zeile ist sauber. In der ersten steckte der Netzname **mit
Apostrophen als echten Zeichen** im Wert: der Router suchte ein WLAN, dessen
Name mit einem Apostroph beginnt, und fand natuerlich keines. Nach aussen sah
das aus wie ein falsches Passwort — die Fehlersuche lief eine halbe Stunde in
die Irre.

Die Ursache waren zwei Ebenen, die sich gegenseitig schuetzten:

```python
# in connect_wifi
f"wireless.{section}.ssid": shlex.quote(ssid)     # quotiert den Wert

# in uci_set
f"uci set {shlex.quote(f'{k}={v}')}"              # quotiert das Ganze erneut
```

Die erste Quotierung schuetzt vor der Shell, die zweite schuetzt die erste —
und damit landen die Anfuehrungszeichen im Wert statt um ihn herum. **Regel
daraus: quotiert wird genau einmal, naemlich dort, wo der Befehl
zusammengesetzt wird.** Wer eine Ebene tiefer schon quotiert, verdirbt das
Ergebnis.

Behoben, indem `connect_wifi` Rohwerte uebergibt. Geprueft gegen fuenf Faelle,
darunter ein Netzname mit Apostroph und einer mit Anfuehrungszeichen — alle
kommen jetzt unveraendert an.

**Warum das so wichtig ist:** Zuhause gibt es eine Rueckfallebene. Auf einem
Campingplatz haette das WLAN-Dropdown schlicht nie funktioniert, ohne jede
Fehlermeldung, die auf die Ursache zeigt.

### Fully Kiosk benennt seine Entitaeten anders als erwartet

Die Integration leitet die Entitaetsnamen vom **Geraetenamen** ab, den man in
Fully Kiosk vergibt — nicht von einem Wunschnamen in der Konfiguration.

Gravierender ist der zweite Unterschied: **der Bildschirm ist ein `switch`,
kein `light`.** Ein `light.turn_on` auf eine Schalter-Entitaet schlaegt fehl.
Die Helligkeit sitzt in einer eigenen `number`-Entitaet mit Wertebereich
0 bis 255, nicht in Prozent.

| erwartet | tatsaechlich |
|---|---|
| `sensor.van_tablet_battery` | `sensor.fire_tablet_batterie` |
| `light.van_tablet_screen` | `switch.fire_tablet_bildschirm` |
| `brightness_pct: 15` | `number.fire_tablet_bildschirmhelligkeit: 38` |

Deshalb steht in Kapitel 8 ein eigener Schritt dafuer. Wer ihn ueberspringt,
hat Automationen, die ins Leere laufen — ohne Fehlermeldung.

### GPS war ab Werk abgeschaltet

```
gps.gpsd.enabled='0'
/etc/init.d/gpsd status  ->  active with no instances
gpsctl -i                ->  Unable to retrieve valid gpsd response: Not found
```

Das liest sich wie "kein Empfang", ist aber etwas anderes: der Dienst laeuft
ohne Instanz, weil er nie eingeschaltet wurde. Bei fehlendem Fix antwortet
gpsd und liefert nur keine Koordinaten.

Die Folge reicht weit ueber die Karte hinaus. **Ohne GPS gibt es keine
Standzeit-Erkennung**, und ohne die loest die automatische WLAN-Suche nie aus:
der Knopf im Dashboard funktioniert, die Automatik schweigt. Man sucht den
Fehler dann beim Scannen statt beim Standort. Siehe Kapitel 4.6.

### Knopf-Kacheln oeffneten ein Fenster statt auszuloesen

Eine `tile`-Karte mit einer `button`-Entitaet oeffnet beim Antippen die
Detailansicht; erst ein zweiter Druck loest aus. Auf einem Bedienpanel im
Fahrzeug ist das unbrauchbar. Abhilfe:

```yaml
tap_action:
  action: perform-action
  perform_action: button.press
  target:
    entity_id: button.van_netzwerk_standort_jetzt_abfragen
```

Das gilt fuer alle Knoepfe — mit einer bewussten Ausnahme: der Router-Neustart
behaelt seine Rueckfrage. Eine Kachel, die zwei Minuten lang jede Verbindung
kappt, darf man nicht im Vorbeiwischen treffen.

Nebenwirkung des alten Verhaltens: Wer das Fenster schloss, ohne auf
*Druecken* zu tippen, schickte nie einen Befehl — und im Protokoll des Agenten
stand folgerichtig nichts. Das sah aus wie ein defekter Knopf.

### Das eigene Netz war fuer das Tablet unsichtbar — Kanal 149

Beim Einrichten des Bedienpanels fand das Amazon-Tablet das Fahrzeug-WLAN
nicht, obwohl Mac und Telefon problemlos verbunden waren. Die Abfrage:

```
wireless.radio1.channel='auto'
wireless.radio1.channels='36-165'
wireless.radio1.country='DE'
Mode: Master  Channel: 149 (5.745 GHz)  HT Mode: HE80
```

Die automatische Kanalwahl hatte **149** gewaehlt. Dieser Kanal liegt im
Bereich UNII-3 (149–165), der in Europa fuer WLAN nicht freigegeben ist — die
Laendereinstellung `DE` hat das nicht verhindert, weil der Router den Bereich
nicht ausschliesst.

Entscheidend ist, dass sich Geraete unterschiedlich verhalten: die meisten
folgen dem, was der Accesspoint ankuendigt, und verbinden sich. Andere —
Amazon-Tablets, viele Android-Geraete mit strenger Zertifizierung — blenden
solche Netze **ohne Hinweis** aus. Man sucht dann am Geraet statt am Router.

Fest gesetzt auf Kanal 36 und die Auswahl begrenzt, damit "auto" nicht beim
naechsten Neustart wieder nach oben wandert:

```sh
uci set wireless.radio1.channel='36'
uci set wireless.radio1.channels='36-48'
uci commit wireless; wifi reload
```

Warum nicht 52 bis 140: diese Kanaele sind in Europa zwar erlaubt, verlangen
aber eine Radarerkennung. Der Accesspoint muss vor dem Senden eine Minute
beobachten und bei Radarverdacht sofort wechseln. In einem Fahrzeug, das
taeglich neu startet und staendig den Standort wechselt, heisst das eine
Minute Funkstille nach jedem Einschalten. Die Kanaele 36 bis 48 sind frei
davon und europaweit nutzbar.

**Pruefe das vor der ersten Reise**, auch wenn alle deine Geraete verbunden
sind — ein neues Geraet unterwegs faellt sonst aus, und die Ursache ist von
aussen nicht zu erkennen.

### Neue Add-on-Optionen sind in bestehenden Installationen leer

Beim Sprung von 1.1.0 auf 1.5.0 stuerzte der Hauptloop in Sekundentakt ab:

```
TypeError: '<' not supported between instances of 'float' and 'NoneType'
```

Die Ursache ist allgemein und betrifft jedes Add-on, das Optionen nachruestet.
`bashio::config 'schluessel'` liefert fuer einen Schluessel, der in den
**gespeicherten** Optionen fehlt, das Wort `null`. Beim Aktualisieren behaelt
Home Assistant die alten Optionen des Benutzers; die neu hinzugekommenen
Schluessel existieren dort nicht. In der erzeugten Konfiguration steht dann
YAML-Null, und in Python kommt `None` an.

Der Fallstrick liegt eine Ebene tiefer: `dict.get(key, default)` rettet davor
**nicht**. Der Vorgabewert greift nur, wenn der Schluessel fehlt — hier ist er
vorhanden und sein Wert ist None.

Zwei Auspraegungen, die sich stark unterscheiden:

| Typ | Verhalten | Auffindbarkeit |
|---|---|---|
| Zahl | Absturz beim ersten Vergleich | sofort, mit Traceback |
| Ja/Nein | `None` ist falsch — die Funktion schaltet sich ab | **gar nicht** |

Die zweite Zeile ist die gefaehrliche. `auto_connect` als Null haette die
automatische WLAN-Suche lautlos stillgelegt: kein Absturz, keine Meldung,
keine Spur im Protokoll. Aufgefallen waere das erst auf dem Campingplatz.

Behoben auf drei Ebenen: `run.sh` gibt jedem Options-Zugriff den Vorgabewert
mit, `agent.py` holt Zahlen ueber `_num()` und Ja/Nein-Werte ueber `_flag()`,
und beide behandeln `None` wie einen fehlenden Schluessel. Wer nur die
Oberflaeche nutzt, kommt mit einem Druck auf **Speichern** in der
Add-on-Konfiguration ans selbe Ziel — das schreibt alle Vorgaben hinein.

### Ein Zahlensensor darf nicht "unknown" sagen

Im Protokoll von Home Assistant, bei jedem Zyklus:

```
Received invalid sensor state: unknown for entity
sensor.mobilfunk_geschaetzter_durchsatz, expected a number
```

Die Vorlage gab bei fehlendem SINR den **Text** `unknown` zurueck. Das ist fuer
einen Sensor mit Einheit und `state_class: measurement` ungueltig. Richtig ist
ein `availability:`-Ausdruck: faellt er auf falsch, meldet sich die Entitaet als
nicht verfuegbar und die Kachel zeigt einen Strich, statt dass im Protokoll
eine Fehlerzeile pro Durchlauf auflaeuft.

```yaml
availability: >
  {% set sinr = states(states('input_text.van_teltonika_sinr_entity')) | float(-99) %}
  {{ -20 <= sinr <= 50 }}
```

Allgemein: ein Zustand, der keine Zahl ist, gehoert nicht in den Zustand,
sondern in die Verfuegbarkeit.

### Verworfene Verdachtsmomente

Zwei Hypothesen wurden geprüft und ausgeschlossen: negative Zahlenbereiche im
Schema (`int(-95,-40)`) und `stage: experimental`, das Apps ohne erweiterten
Modus ausblendet. Beide Änderungen wurden trotzdem beibehalten, weil sie
sinnvoll sind.

---

## 16. Entscheidungen und ihre Gründe

### Failover auf dem Router, nicht in Home Assistant

Eine Hausautomation ist kein Fundament für die Internetverbindung eines
Fahrzeugs. Startet der Pi neu, stürzt die App ab oder fehlt sie ganz — die
Verbindung bleibt.

### Mobilfunk schätzen statt messen

Messen kostet Datenvolumen und setzt ein Umschalten voraus. Für die
Entscheidung „lohnt sich der Wechsel" genügt eine Schätzung.

### Passwörter nicht in den Zustand

Der MQTT-Zustand ist ein `retained` Topic und landet im Verlauf von Home
Assistant. Eingegebene Passwörter bleiben deshalb im Arbeitsspeicher der App
bis zum Verbindungsaufbau, danach wird das Feld geleert. Zusätzlich ist die
Entität vom `recorder` ausgeschlossen.

### Standort sparsam melden

GPS wird alle 20 Sekunden gelesen, aber nur für die Geschwindigkeit — davon
hängt die Standzeit-Erkennung ab. Die Position geht nur alle 30 Minuten nach
Home Assistant, und die Koordinaten stehen in den **Attributen** des
`device_tracker`, nicht in seinem Zustand. So entsteht keine Bewegungsspur im
Minutentakt.

### Keine Portweiterleitung für den Fernzugriff

Die WAN-Seite des Routers ist später das Campingplatz-WLAN. Was für das
Heimnetz geöffnet wird, steht dort genauso offen. Tailscale baut die
Verbindung von innen nach außen auf.

### Rückfrage am Neustart-Knopf

Ein Fehltipper kostet zwei Minuten Internet — auch für Home Assistant selbst.

### Netz erst nach erfolgreicher Verbindung lernen

Ein falsches Passwort zu speichern wäre sinnlos. Gemerkt wird erst, wenn das
Internet tatsächlich erreichbar ist.

### Durchsatz bei 100 Mbit/s deckeln

Beim Vergleich von Basisstationen zählt, ob eine Strecke benutzbar ist. Ob
hinter einem Accesspoint 150 oder 400 Mbit/s liegen, merkt im Fahrzeug
niemand — Latenz und Paketverlust dagegen sofort.

---

## 17. Befehls-Spickzettel

### Router

```sh
iwinfo                                       # Radios und Bänder
ubus call iwinfo devices                     # echte Schnittstellennamen
uci show wireless | grep "mode='sta'"        # Client vorhanden?
mwan3 status                                 # Uplink-Zustand
ifstatus <mobilfunk> | jsonfilter -e '@.up'  # Mobilfunk online?
logread | grep -ci 'Changing to SIM'         # SIM-Wechsel gezählt
ubus call gpsd info '{}'                     # GPS-Fix
ubus call gsm.modem0 get_signal_query '{}'   # Signalwerte
ubus call gsm.modem0 get_temperature '{}'    # Modemtemperatur
cat /tmp/dhcp.leases                         # Geräte am Router
sysupgrade -b /tmp/backup.tar.gz             # Konfiguration sichern
```

### Home Assistant

```sh
ha apps logs local_van_net        # App-Protokoll
ha apps rebuild local_van_net     # nach Dateiänderung neu bauen
ha apps restart local_van_net     # nur neu starten
ha supervisor logs                 # Supervisor
```

### Oberfläche

| Aufgabe | Weg |
|---|---|
| App-Protokoll | Einstellungen → Apps → Van Netzwerk Agent → Protokoll |
| YAML prüfen | Entwicklerwerkzeuge → YAML → Konfiguration prüfen |
| Entity-ID finden | Entwicklerwerkzeuge → Zustände |
| Notify-Dienst finden | Entwicklerwerkzeuge → Aktionen → `notify.mobile` |
| Datei bearbeiten | Seitenleiste → File editor |

### Verzeichnisse

| Pfad | Inhalt |
|---|---|
| `/addons/van_net/` | die App — **hier wird geändert** |
| `/config/packages/van_net.yaml` | Sensoren und Automationen |
| `/config/dashboards/van-internet.yaml` | Dashboard-Seite „Internet" |
| `/config/dashboards/van-tablet.yaml` | Dashboard für das Tablet |
| `/config/www/van-net/` | QR-Code |
| `/share/van-net/screenshots/` | gescheiterte Anmeldeseiten |
| `/share/van-net/backups/` | Router-Sicherungen |
| `/data/learned_networks.json` | gelernte Netze |
| `/data/learned_aps.json` | gelernte Basisstationen |
