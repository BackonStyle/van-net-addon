#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -e

CONFIG_PATH=/data/config.yaml

bashio::log.info "Van-Netzwerk-Agent startet..."

# --------------------------------------------------------------- MQTT-Zugang
# Kommt automatisch vom Mosquitto-Add-on -- du musst nichts eintragen.
if bashio::services.available "mqtt"; then
    MQTT_HOST=$(bashio::services mqtt "host")
    MQTT_PORT=$(bashio::services mqtt "port")
    MQTT_USER=$(bashio::services mqtt "username")
    MQTT_PASS=$(bashio::services mqtt "password")
    bashio::log.info "MQTT-Broker gefunden: ${MQTT_HOST}:${MQTT_PORT}"
else
    bashio::log.fatal "Kein MQTT-Broker gefunden."
    bashio::log.fatal "Bitte zuerst das Add-on 'Mosquitto broker' installieren und starten."
    exit 1
fi

# -------------------------------------------------------------- Verzeichnisse
QR_DIR=/homeassistant/www/van-net
SHOT_DIR=/share/van-net/screenshots
mkdir -p "${QR_DIR}" "${SHOT_DIR}"

# ----------------------------------------------------------------- Browser
if bashio::config.true 'portal_browser_enabled'; then
    export PORTAL_BROWSER_DISABLED=0
    bashio::log.info "Portal-Automatik: aktiv (Chromium)"
else
    export PORTAL_BROWSER_DISABLED=1
    bashio::log.info "Portal-Automatik: abgeschaltet -- nur QR-Fallback"
fi

export LOG_LEVEL
LOG_LEVEL=$(bashio::string.upper "$(bashio::config 'log_level' 'info')")

# ----------------------------------------------------- Konfiguration schreiben
{
    echo "router:"
    echo "  host: \"$(bashio::config 'router_host')\""
    echo "  username: \"$(bashio::config 'router_username')\""
    if bashio::config.has_value 'router_ssh_key'; then
        echo "  ssh_key: \"$(bashio::config 'router_ssh_key')\""
    else
        echo "  password: \"$(bashio::config 'router_password')\""
    fi
    echo "  port: 22"
    echo ""
    echo "wifi:"
    echo "  client_device: \"$(bashio::config 'wifi_client_device')\""
    echo "  wan_interface: \"$(bashio::config 'wifi_wan_interface')\""
    echo "  auto_connect: $(bashio::config 'auto_connect')"
    echo "  auto_connect_open: $(bashio::config 'auto_connect_open')"
    echo "  min_signal_dbm: $(bashio::config 'min_signal_dbm')"
    echo "  scan_cooldown_seconds: $(bashio::config 'scan_cooldown_seconds')"

    echo "  known_networks:"
    if bashio::config.has_value 'known_networks'; then
        for idx in $(bashio::config 'known_networks|keys'); do
            ssid=$(bashio::config "known_networks[${idx}].ssid")
            pw=$(bashio::config "known_networks[${idx}].password" "")
            echo "    - ssid: \"${ssid}\""
            if [ -n "${pw}" ] && [ "${pw}" != "null" ]; then
                echo "      password: \"${pw}\""
            fi
        done
    else
        echo "    []"
    fi

    echo "  blocked_ssids:"
    if bashio::config.has_value 'blocked_ssids'; then
        for idx in $(bashio::config 'blocked_ssids|keys'); do
            echo "    - \"$(bashio::config "blocked_ssids[${idx}]")\""
        done
    else
        echo "    []"
    fi

    echo ""
    echo "mobile:"
    echo "  wan_interface: \"$(bashio::config 'mobile_wan_interface')\""
    echo ""
    echo "movement:"
    echo "  stationary_below_kmh: $(bashio::config 'stationary_below_kmh')"
    echo "  stationary_after_seconds: $(bashio::config 'stationary_after_seconds')"
    echo ""
    echo "portal:"
    echo "  max_rounds: $(bashio::config 'portal_max_rounds')"
    echo "  screenshot_dir: \"${SHOT_DIR}\""
    echo "  qr_path: \"${QR_DIR}/portal_qr.png\""
    echo "  qr_public_path: \"/local/van-net/portal_qr.png\""
    echo "  speedtest_url: \"https://speed.cloudflare.com/__down?bytes=25000000\""
    echo ""
    echo "mqtt:"
    echo "  host: \"${MQTT_HOST}\""
    echo "  port: ${MQTT_PORT}"
    echo "  username: \"${MQTT_USER}\""
    echo "  password: \"${MQTT_PASS}\""
    echo ""
    echo "poll_interval_seconds: $(bashio::config 'poll_interval_seconds')"
} > "${CONFIG_PATH}"

bashio::log.info "Konfiguration geschrieben nach ${CONFIG_PATH}"

# Rechte am SSH-Key korrigieren, falls einer hinterlegt ist
if bashio::config.has_value 'router_ssh_key'; then
    KEY=$(bashio::config 'router_ssh_key')
    if [ -f "${KEY}" ]; then
        chmod 600 "${KEY}" || true
        bashio::log.info "SSH-Key: ${KEY}"
    else
        bashio::log.warning "SSH-Key nicht gefunden: ${KEY}"
    fi
fi

cd /app
exec python3 agent.py
