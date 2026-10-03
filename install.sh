#!/usr/bin/env bash
# =============================================================================
# Van-Netzwerk -- Installation auf einem frischen Home Assistant OS
#
# Aufruf im Terminal-Add-on von Home Assistant:
#
#   curl -sSL https://raw.githubusercontent.com/BackonStyle/van-net-addon/main/install.sh -o i.sh && bash i.sh
#
# Voraussetzung: Das Add-on "Terminal & SSH" oder "Advanced SSH & Web Terminal"
# ist installiert -- sonst gibt es keine Kommandozeile. Alles andere macht
# dieses Skript.
#
# Mehrfaches Ausfuehren ist unschaedlich; vorhandene Dateien werden gesichert.
# =============================================================================

set -u

REPO="BackonStyle/van-net-addon"
BRANCH="main"
ADDON_DIR="/addons/van_net"
PKG_DIR="/config/packages"
WWW_DIR="/config/www/van-net"
BACKUP_DIR="/share/van-net/backups"
DASH_DIR="/config/dashboards"
SLUG="local_van_net"
TMP="/tmp/van-net-install.$$"
CFG="/config/configuration.yaml"

# --------------------------------------------------------------- Darstellung

if [ -t 1 ]; then
    B=$(printf '\033[1m'); R=$(printf '\033[0m')
    GN=$(printf '\033[32m'); YL=$(printf '\033[33m'); RD=$(printf '\033[31m')
else
    B=""; R=""; GN=""; YL=""; RD=""
fi

step()  { printf "\n%s==> %s%s\n" "$B" "$1" "$R"; }
ok()    { printf "  %s*%s %s\n" "$GN" "$R" "$1"; }
warn()  { printf "  %s!%s %s\n" "$YL" "$R" "$1"; }
fail()  { printf "\n  %sFEHLER:%s %s\n\n" "$RD" "$R" "$1"; exit 1; }

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# Lesen von der Tastatur, auch wenn das Skript ueber eine Pipe kam
if ! exec 3</dev/tty 2>/dev/null; then exec 3<&0; fi

ask() {
    # ask <Frage> <Vorgabe> -> Antwort auf stdout
    local q="$1" def="$2" ans=""
    if [ -n "$def" ]; then
        printf "  %s [%s]: " "$q" "$def" >&2
    else
        printf "  %s: " "$q" >&2
    fi
    IFS= read -r ans <&3 || ans=""
    [ -z "$ans" ] && ans="$def"
    printf '%s' "$ans"
}

ask_secret() {
    local q="$1" ans=""
    printf "  %s (Eingabe bleibt unsichtbar): " "$q" >&2
    stty -echo 2>/dev/null
    IFS= read -r ans <&3 || ans=""
    stty echo 2>/dev/null
    printf "\n" >&2
    printf '%s' "$ans"
}

yesno() {
    local q="$1" def="${2:-j}" ans=""
    printf "  %s (j/n) [%s]: " "$q" "$def" >&2
    IFS= read -r ans <&3 || ans=""
    [ -z "$ans" ] && ans="$def"
    case "$ans" in [jJyY]*) return 0 ;; *) return 1 ;; esac
}

json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

# --------------------------------------------------------------- Vorbedingungen

cat <<'KOPF'

  ===========================================================
   Van-Netzwerk  --  Installation
   Teltonika RUTC50 eSIM + Home Assistant
  ===========================================================

KOPF

step "Umgebung pruefen"

command -v ha >/dev/null 2>&1 || fail \
"Das Kommando 'ha' fehlt. Dieses Skript muss im Terminal-Add-on von
     Home Assistant laufen, nicht in einer normalen Linux-Shell."

command -v curl >/dev/null 2>&1 || fail "curl fehlt."
ok "Home-Assistant-CLI gefunden"

if [ ! -d /addons ]; then
    mkdir -p /addons 2>/dev/null || fail "/addons nicht anlegbar."
fi
ok "Verzeichnisse erreichbar"

HA_VER=$(ha core info --raw-json 2>/dev/null | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' | head -1)
[ -n "$HA_VER" ] && ok "Home Assistant Core $HA_VER"

# Je nach Version heisst der Befehl 'apps' oder 'addons'
if ha apps >/dev/null 2>&1; then APPS="apps"; else APPS="addons"; fi
ok "CLI-Befehl: ha $APPS"

# --------------------------------------------------------------- MQTT

step "MQTT-Broker (Mosquitto)"

if ha "$APPS" info core_mosquitto >/dev/null 2>&1; then
    ok "bereits installiert"
else
    printf "  installiere ... "
    if ha "$APPS" install core_mosquitto >/dev/null 2>&1; then
        printf "fertig\n"
    else
        printf "\n"; warn "Installation fehlgeschlagen -- bitte 'Mosquitto broker' manuell installieren"
    fi
fi

MQ_STATE=$(ha "$APPS" info core_mosquitto 2>/dev/null | sed -n 's/^state: *//p' | head -1)
if [ "$MQ_STATE" != "started" ]; then
    printf "  starte ... "
    ha "$APPS" start core_mosquitto >/dev/null 2>&1 && printf "fertig\n" || printf "\n"
fi
ok "Mosquitto laeuft"

# --------------------------------------------------------------- Dateien holen

step "App-Dateien herunterladen"

mkdir -p "$TMP" || fail "Kein Schreibzugriff auf /tmp"

# Zwei Quellen probieren -- manche Netze sperren codeload.github.com
GOT=0
for URL in \
    "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz" \
    "https://codeload.github.com/${REPO}/tar.gz/refs/heads/${BRANCH}"
do
    if curl -sSL --fail --connect-timeout 15 "$URL" 2>/dev/null \
            | tar -xz -C "$TMP" 2>/dev/null; then
        GOT=1
        break
    fi
    warn "Quelle nicht erreichbar, versuche naechste ..."
done

[ "$GOT" = "1" ] || fail \
"Download von $REPO fehlgeschlagen.
     Internetverbindung pruefen, oder die Dateien per Samba nach
     $ADDON_DIR kopieren und dieses Skript erneut starten."

SRC=$(find "$TMP" -maxdepth 2 -type d -name van_net | head -1)
[ -n "$SRC" ] || fail "Ordner 'van_net' im Archiv nicht gefunden."
ok "heruntergeladen"

if [ -d "$ADDON_DIR" ]; then
    BACK="${ADDON_DIR}.bak.$(date +%Y%m%d%H%M%S)"
    mv "$ADDON_DIR" "$BACK"
    warn "alte Version gesichert: $BACK"
fi

mkdir -p "$ADDON_DIR"
cp "$SRC"/* "$ADDON_DIR"/ || fail "Kopieren nach $ADDON_DIR fehlgeschlagen."
chmod +x "$ADDON_DIR/run.sh" 2>/dev/null
ok "App liegt in $ADDON_DIR"

# --------------------------------------------------------------- Verzeichnisse

step "Home-Assistant-Verzeichnisse"

mkdir -p "$PKG_DIR" "$WWW_DIR" "$BACKUP_DIR"
ok "$PKG_DIR"
ok "$WWW_DIR  (fuer den QR-Code)"
ok "$BACKUP_DIR  (fuer die Router-Sicherungen)"

HA_PKG=$(find "$TMP" -maxdepth 3 -type f -name van_net.yaml | head -1)
if [ -n "$HA_PKG" ]; then
    if [ -f "$PKG_DIR/van_net.yaml" ]; then
        cp "$PKG_DIR/van_net.yaml" "$PKG_DIR/van_net.yaml.bak.$(date +%Y%m%d%H%M%S)"
        warn "altes Package gesichert"
    fi
    cp "$HA_PKG" "$PKG_DIR/van_net.yaml"
    ok "Package kopiert"
else
    warn "van_net.yaml nicht im Archiv -- spaeter manuell kopieren"
fi

# secrets.yaml vorbereiten
#
# van_net.yaml verweist mit !secret auf drei Eintraege. Fehlt auch nur einer,
# startet Home Assistant NICHT, sondern faellt in den abgesicherten Modus --
# mit einer Fehlermeldung, die auf die Package-Datei zeigt statt auf die
# fehlende Zeile. Deshalb legen wir Platzhalter an, bevor das Package greift.
SECRETS="/config/secrets.yaml"
touch "$SECRETS" 2>/dev/null
for eintrag in \
    'tablet_sleep_url|"http://192.168.1.230:2323/?cmd=forceSleep&type=json&password=PLATZHALTER"' \
    'tablet_screenon_url|"http://192.168.1.230:2323/?cmd=screenOn&type=json&password=PLATZHALTER"' \
    'van_shutdown_pin|"0000"'
do
    name="${eintrag%%|*}"
    wert="${eintrag#*|}"
    if grep -q "^${name}:" "$SECRETS" 2>/dev/null; then
        ok "secrets: ${name} vorhanden"
    else
        printf '%s: %s\n' "$name" "$wert" >> "$SECRETS"
        ok "secrets: ${name} als Platzhalter angelegt"
    fi
done
warn "PIN zum Herunterfahren steht auf 0000 -- in /config/secrets.yaml aendern"

# packages in configuration.yaml aktivieren
if [ -f "$CFG" ]; then
    if grep -q "include_dir_named packages" "$CFG"; then
        ok "packages in configuration.yaml bereits aktiv"
    else
        cp "$CFG" "${CFG}.bak.$(date +%Y%m%d%H%M%S)"
        if grep -q "^homeassistant:" "$CFG"; then
            warn "Block 'homeassistant:' existiert -- bitte diese Zeile selbst ergaenzen:"
            printf "\n      packages: !include_dir_named packages\n\n"
        else
            printf 'homeassistant:\n  packages: !include_dir_named packages\n\n' > "${CFG}.neu"
            cat "$CFG" >> "${CFG}.neu"
            mv "${CFG}.neu" "$CFG"
            ok "packages in configuration.yaml aktiviert"
        fi
    fi
fi

# --------------------------------------------------------------- Dashboard

step "Dashboard \"Internet\""

DASH_SRC=$(find "$TMP" -maxdepth 3 -type f -name van-internet.yaml | head -1)

if [ -z "$DASH_SRC" ]; then
    warn "van-internet.yaml nicht im Archiv -- Dashboard spaeter manuell anlegen"
elif ! yesno "Dashboard-Seite jetzt anlegen?" "j"; then
    warn "uebersprungen -- Anleitung steht im Handbuch, Kapitel 7"
else
    mkdir -p "$DASH_DIR"
    if [ -f "$DASH_DIR/van-internet.yaml" ]; then
        cp "$DASH_DIR/van-internet.yaml" \
           "$DASH_DIR/van-internet.yaml.bak.$(date +%Y%m%d%H%M%S)"
        warn "altes Dashboard gesichert"
    fi
    cp "$DASH_SRC" "$DASH_DIR/van-internet.yaml"
    ok "$DASH_DIR/van-internet.yaml"

    # Tablet-Dashboard mitnehmen, falls vorhanden
    TAB_SRC=$(find "$TMP" -maxdepth 3 -type f -name van-tablet.yaml | head -1)
    if [ -n "$TAB_SRC" ]; then
        cp "$TAB_SRC" "$DASH_DIR/van-tablet.yaml"
        ok "$DASH_DIR/van-tablet.yaml  (fuer ein Tablet im Fahrzeug)"
    fi

    # Eintrag in configuration.yaml -- nur wenn noch kein lovelace-Block da ist
    if [ ! -f "$CFG" ]; then
        warn "configuration.yaml nicht gefunden"
    elif grep -q "van-internet" "$CFG"; then
        ok "bereits in configuration.yaml eingetragen"
    elif grep -q "^lovelace:" "$CFG"; then
        warn "Es gibt schon einen 'lovelace:'-Block in configuration.yaml."
        warn "Die Datei wurde NICHT geaendert. Bitte dort ergaenzen --"
        warn "genau so eingerueckt, wie es zwischen den Linien steht:"
        printf '\n  ----------------------------------------------\n'
        cat <<'LOVELACE'
  dashboards:
    van-internet:
      mode: yaml
      filename: dashboards/van-internet.yaml
      title: Internet
      icon: mdi:web
      show_in_sidebar: true
    van-tablet:
      mode: yaml
      filename: dashboards/van-tablet.yaml
      title: Tablet
      icon: mdi:tablet-dashboard
      show_in_sidebar: false
LOVELACE
        printf '  ----------------------------------------------\n'
        warn "Steht dort bereits 'dashboards:', nur den Teil ab"
        warn "'van-internet:' darunter einfuegen (vier Leerzeichen)."
        printf '\n'
    else
        cp "$CFG" "${CFG}.bak.$(date +%Y%m%d%H%M%S)"
        cat >> "$CFG" <<'LOVELACE'

# Dashboard-Seite "Internet" -- angelegt vom Van-Netzwerk-Installer.
# mode: storage laesst das Standard-Dashboard weiter ueber die Oberflaeche
# bearbeitbar; nur diese eine Seite kommt aus einer Datei.
lovelace:
  mode: storage
  dashboards:
    van-internet:
      mode: yaml
      filename: dashboards/van-internet.yaml
      title: Internet
      icon: mdi:web
      show_in_sidebar: true
    van-tablet:
      mode: yaml
      filename: dashboards/van-tablet.yaml
      title: Tablet
      icon: mdi:tablet-dashboard
      show_in_sidebar: false
LOVELACE
        ok "in configuration.yaml eingetragen"
        ok "erscheint nach dem Neustart in der Seitenleiste"
    fi
fi

# --------------------------------------------------------------- Konfiguration

step "Konfiguration"

cat <<'HINWEIS'
  Jetzt werden die Werte abgefragt. Mit Enter uebernimmst du jeweils die
  Vorgabe in eckigen Klammern. Die Werte stehen danach in der App-
  Konfiguration und sind dort jederzeit aenderbar.

HINWEIS

ROUTER_HOST=$(ask "IP des Routers" "192.168.1.1")

printf "\n  Pruefe Erreichbarkeit ... "
if ping -c 1 -W 3 "$ROUTER_HOST" >/dev/null 2>&1; then
    printf "%serreichbar%s\n" "$GN" "$R"
else
    printf "%skeine Antwort%s\n" "$YL" "$R"
    warn "Router antwortet nicht. Installation laeuft weiter, die App"
    warn "verbindet sich spaeter von selbst, sobald er da ist."
fi

ROUTER_USER=$(ask "Benutzername fuer SSH am Router" "root")
ROUTER_PASS=$(ask_secret "Router-Passwort")

printf "\n"
cat <<'IFHINWEIS'
  Die Namen der WAN-Schnittstellen stehen am Router unter:
      ssh root@<router> "mwan3 status"
  Ueblich: wan1 fuer den WLAN-Uplink, mob1s3a1e1 fuer eine eSIM.

IFHINWEIS

WIFI_WAN=$(ask "WLAN-Uplink in mwan3" "wan1")
MOB_WAN=$(ask "Mobilfunk in mwan3" "mob1s3a1e1")
CLIENT_DEV=$(ask "Radio fuer den WLAN-Client (2,4 GHz)" "wlan0")

printf "\n"
if yesno "Captive-Portal-Login per Browser versuchen? (braucht ~500 MB RAM)" "j"; then
    PORTAL="true"
else
    PORTAL="false"
    warn "Nur QR-Fallback -- Portale bestaetigst du dann am Handy"
fi

GPS_IV=$(ask "Standort wie oft melden, in Sekunden" "1800")

# --------------------------------------------------------------- Optionen setzen

step "Optionen in die App schreiben"

OPTS=$(cat <<JSON
{"router_host":"$(json_escape "$ROUTER_HOST")","router_username":"$(json_escape "$ROUTER_USER")","router_password":"$(json_escape "$ROUTER_PASS")","router_ssh_key":"","wifi_client_device":"$(json_escape "$CLIENT_DEV")","wifi_wan_interface":"$(json_escape "$WIFI_WAN")","mobile_wan_interface":"$(json_escape "$MOB_WAN")","auto_connect":true,"auto_connect_open":true,"min_signal_dbm":-78,"scan_cooldown_seconds":300,"stationary_below_kmh":3.0,"stationary_after_seconds":180,"poll_interval_seconds":20,"portal_browser_enabled":${PORTAL},"portal_max_rounds":3,"gps_publish_interval_seconds":${GPS_IV},"known_networks":[],"blocked_ssids":[],"log_level":"info"}
JSON
)

# Store neu einlesen, damit die App bekannt ist
ha store reload >/dev/null 2>&1 || true
sleep 3

if ! ha "$APPS" info "$SLUG" >/dev/null 2>&1; then
    printf "  App noch nicht bekannt, installiere ... "
    ha "$APPS" install "$SLUG" >/dev/null 2>&1 && printf "fertig\n" || printf "\n"
fi

OPTS_FILE="$TMP/options.json"
printf '%s' "$OPTS" > "$OPTS_FILE"

if ha "$APPS" options "$SLUG" --options "$(cat "$OPTS_FILE")" >/dev/null 2>&1; then
    ok "Optionen gesetzt"
    OPTS_SET=1
else
    OPTS_SET=0
    warn "Optionen konnten nicht automatisch gesetzt werden."
    warn "Bitte in der App unter 'Konfiguration' eintragen:"
    printf "\n"
    printf "      router_host: %s\n" "$ROUTER_HOST"
    printf "      router_username: %s\n" "$ROUTER_USER"
    printf "      router_password: <dein Passwort>\n"
    printf "      wifi_client_device: %s\n" "$CLIENT_DEV"
    printf "      wifi_wan_interface: %s\n" "$WIFI_WAN"
    printf "      mobile_wan_interface: %s\n" "$MOB_WAN"
    printf "      portal_browser_enabled: %s\n" "$PORTAL"
    printf "      gps_publish_interval_seconds: %s\n\n" "$GPS_IV"
fi
unset ROUTER_PASS OPTS
rm -f "$OPTS_FILE"

# --------------------------------------------------------------- Bauen

step "App bauen und starten"

cat <<'BAUHINWEIS'
  Das dauert beim ersten Mal 15 bis 25 Minuten -- der Container wird auf
  dem Geraet selbst gebaut und laedt dabei Chromium herunter. Die Zeile
  bleibt waehrenddessen stehen, das ist normal. Nicht abbrechen.

BAUHINWEIS

if ha "$APPS" rebuild "$SLUG" >/dev/null 2>&1; then
    ok "gebaut"
elif ha "$APPS" install "$SLUG" >/dev/null 2>&1; then
    ok "installiert"
else
    warn "Bauen fehlgeschlagen -- Protokoll pruefen:  ha supervisor logs"
fi

ha "$APPS" start "$SLUG" >/dev/null 2>&1 && ok "gestartet" || warn "Start fehlgeschlagen"

# --------------------------------------------------------------- Abschluss

NOTIFY=$(find "$TMP" -maxdepth 3 -type f -name van_net.yaml -exec grep -ho 'notify\.mobile_app_[a-z0-9_]*' {} \; 2>/dev/null | head -1)

cat <<ENDE

  ===========================================================
   Installation abgeschlossen
  ===========================================================

  Noch von Hand zu erledigen:

  1. Benachrichtigungen
     In ${PKG_DIR}/van_net.yaml steht als Empfaenger:
         ${NOTIFY:-notify.mobile_app_...}
     Den eigenen Namen findest du unter
         Entwicklerwerkzeuge -> Aktionen -> Suchfeld "notify.mobile"
     und ersetzt ihn an allen Stellen in der Datei.

  2. Konfiguration pruefen und neu starten
         Entwicklerwerkzeuge -> YAML -> Konfiguration pruefen
         Entwicklerwerkzeuge -> YAML -> Home Assistant neu starten

  3. Dashboard
     Erscheint nach dem Neustart als Eintrag "Internet" in der
     Seitenleiste. Aenderungen gehen ueber
     ${DASH_DIR}/van-internet.yaml, danach Browser neu laden.

  4. Tablet im Fahrzeug (optional)
     Anleitung im Handbuch, Kapitel 8. Dashboard liegt bereit unter
     ${DASH_DIR}/van-tablet.yaml, erreichbar ueber /van-tablet/start

  Pruefen, ob die App laeuft:
         ha ${APPS} logs ${SLUG}

  Erwartete Zeilen:
         MQTT verbunden (rc=0)
         MQTT-Discovery veroeffentlicht
         Agent gestartet

ENDE

[ "$OPTS_SET" = "1" ] || printf "  %sNicht vergessen:%s Optionen in der App eintragen (siehe oben).\n\n" "$YL" "$R"

exit 0
