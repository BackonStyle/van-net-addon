"""
Captive-Portal-Erkennung und automatischer Login.

Strategie:
  1. Erkennen, ob ueberhaupt ein Portal dazwischenhaengt (mehrere
     Erkennungs-URLs, damit ein einzelner Ausfall nicht alles blockiert).
  2. Portal mit echtem Browser (Playwright/Chromium) oeffnen und per Heuristik
     bedienen: Cookie-Banner weg, alle Checkboxen setzen, Absenden-Button nach
     mehrsprachiger Wortliste finden und klicken.
  3. Nach jedem Versuch pruefen, ob das Internet wirklich offen ist.
  4. Scheitert alles: Screenshot fuer die Fehlersuche + QR-Code mit der
     Portal-URL fuer den manuellen Fallback.

WICHTIG zum QR-Fallback:
Captive Portals autorisieren nach MAC-Adresse. Scannst du den QR-Code und
oeffnest das Portal ueber die Mobilfunkverbindung deines Handys, wird DAS
HANDY freigeschaltet, nicht der Router. Damit der Fallback wirkt, muss dein
Handy auf dem 5-GHz-AP des Routers bleiben und am Router muss
"Redirect captive portal" aktiv sein. Dann laeuft dein Tap durch den Router,
das Portal sieht dessen MAC, und die Bestaetigung gilt fuer den ganzen Van.
"""

from __future__ import annotations

import logging
import os
import re
import time

import requests

log = logging.getLogger("portal")

# Erkennungs-URLs: liefern im Normalfall exakt definierten Inhalt.
# Weicht die Antwort ab oder wird umgeleitet, haengt ein Portal dazwischen.
DETECT_TARGETS = [
    ("http://detectportal.firefox.com/success.txt", "success"),
    ("http://connectivitycheck.gstatic.com/generate_204", ""),
    ("http://captive.apple.com/hotspot-detect.html", "Success"),
]

# Mehrsprachige Wortliste fuer den Absenden-Button.
# Reihenfolge = Priorisierung: eindeutige Zustimmung vor vagem "weiter".
ACCEPT_PATTERNS = [
    r"\b(ich stimme zu|einverstanden|akzeptieren|zustimmen)\b",
    r"\b(accept|i agree|agree and connect|accept and connect)\b",
    r"\b(verbinden|jetzt verbinden|online gehen|kostenlos surfen)\b",
    r"\b(connect|get online|start browsing|free wifi|free internet)\b",
    r"\b(accepter|j'accepte|se connecter|connexion)\b",
    r"\b(accetta|accetto|connetti|navigazione gratuita)\b",
    r"\b(aceptar|acepto|conectar|conectarse)\b",
    r"\b(login|anmelden|einloggen|sign in)\b",
    r"\b(weiter|continue|continuar|continuer|fortfahren|ok)\b",
]

# Cookie-Banner zuerst wegklicken, sonst verdecken sie den echten Button.
COOKIE_PATTERNS = [
    r"\b(alle akzeptieren|alle cookies|accept all|allow all|tout accepter)\b",
    r"\b(nur notwendige|only necessary|essential only|reject all|ablehnen)\b",
]


def check_internet(timeout: float = 6.0) -> tuple:
    """
    Prueft die Internetverbindung.

    Rueckgabe: (offen: bool, portal_url: str | None)
      (True,  None)        -- freier Internetzugang
      (False, "http://..") -- Portal erkannt, URL bekannt
      (False, None)        -- gar keine Verbindung
    """
    reachable_any = False
    for url, expect in DETECT_TARGETS:
        try:
            resp = requests.get(url, timeout=timeout, allow_redirects=True)
        except requests.RequestException:
            continue

        reachable_any = True

        # Umleitung auf eine fremde Adresse = Portal
        if resp.url.rstrip("/") != url.rstrip("/"):
            return False, resp.url

        if expect == "":
            if resp.status_code == 204:
                return True, None
            return False, resp.url

        if expect.lower() in resp.text.lower():
            return True, None

        # Antwort kam, Inhalt stimmt nicht -- typisch fuer transparente Portale
        return False, resp.url

    if not reachable_any:
        return False, None
    return False, None


class PortalAutomation:
    """Playwright-gestuetzter Portal-Login."""

    def __init__(self, screenshot_dir: str, headless: bool = True,
                 nav_timeout: int = 25000, max_rounds: int = 3):
        self.screenshot_dir = screenshot_dir
        self.headless = headless
        self.nav_timeout = nav_timeout
        self.max_rounds = max_rounds
        os.makedirs(screenshot_dir, exist_ok=True)

    # ------------------------------------------------------------------ public

    def try_login(self, portal_url: str, ssid: str = "") -> dict:
        """
        Versucht den Portal-Login.

        Rueckgabe: {'success': bool, 'rounds': int, 'screenshot': str|None,
                    'final_url': str, 'note': str}
        """
        if os.environ.get("PORTAL_BROWSER_DISABLED") == "1":
            return {"success": False, "rounds": 0, "screenshot": None,
                    "final_url": portal_url,
                    "note": "Browser-Automatik abgeschaltet -- QR-Fallback"}

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"success": False, "rounds": 0, "screenshot": None,
                    "final_url": portal_url,
                    "note": "Playwright nicht installiert"}

        result = {"success": False, "rounds": 0, "screenshot": None,
                  "final_url": portal_url, "note": ""}

        try:
            with sync_playwright() as pw:
                launch_args = {
                    "headless": self.headless,
                    "args": ["--no-sandbox", "--disable-dev-shm-usage",
                             "--ignore-certificate-errors",
                             "--disable-gpu", "--single-process"],
                }
                # Auf dem Raspberry Pi nutzen wir das Chromium des Systems
                # (ARM64-Paket aus Debian) statt des Playwright-Downloads.
                chromium_path = os.environ.get("CHROMIUM_PATH")
                if chromium_path and os.path.exists(chromium_path):
                    launch_args["executable_path"] = chromium_path
                browser = pw.chromium.launch(**launch_args)
                context = browser.new_context(
                    ignore_https_errors=True,
                    locale="de-DE",
                    viewport={"width": 420, "height": 860},
                    # Mobile UA: viele Portale liefern mobil eine schlankere,
                    # besser automatisierbare Seite aus.
                    user_agent=("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/120 Mobile Safari/537.36"),
                )
                page = context.new_page()
                page.set_default_timeout(self.nav_timeout)

                try:
                    page.goto(portal_url, wait_until="domcontentloaded")
                except Exception as exc:
                    log.warning("Portal nicht ladbar: %s", exc)

                for round_no in range(1, self.max_rounds + 1):
                    result["rounds"] = round_no
                    log.info("Portal-Versuch %d/%d", round_no, self.max_rounds)

                    self._dismiss_cookies(page)
                    self._tick_checkboxes(page)
                    clicked = self._click_accept(page)

                    page.wait_for_timeout(3500)
                    result["final_url"] = page.url

                    open_net, _ = check_internet()
                    if open_net:
                        result["success"] = True
                        result["note"] = f"Erfolg nach {round_no} Runde(n)"
                        break

                    if not clicked:
                        # Nichts mehr zum Klicken -- weitere Runden bringen nichts
                        result["note"] = "Kein passender Button gefunden"
                        break

                    self._enter_frames(page)

                if not result["success"]:
                    result["screenshot"] = self._screenshot(page, ssid)
                    if not result["note"]:
                        result["note"] = "Login fehlgeschlagen"

                context.close()
                browser.close()

        except Exception as exc:
            log.exception("Portal-Automatik abgestuerzt")
            result["note"] = f"Fehler: {exc}"

        return result

    # ----------------------------------------------------------------- interna

    def _candidates(self, page):
        """Alle klickbaren Elemente einsammeln, inkl. iframes."""
        sel = ("button, input[type=submit], input[type=button], a, "
               "[role=button], div[onclick], span[onclick]")
        try:
            return page.query_selector_all(sel)
        except Exception:
            return []

    def _click_by_patterns(self, page, patterns) -> bool:
        for pattern in patterns:
            rx = re.compile(pattern, re.IGNORECASE)
            for el in self._candidates(page):
                try:
                    if not el.is_visible() or not el.is_enabled():
                        continue
                    text = " ".join(filter(None, [
                        el.inner_text() or "",
                        el.get_attribute("value") or "",
                        el.get_attribute("aria-label") or "",
                        el.get_attribute("title") or "",
                    ])).strip()
                    if not text or len(text) > 80:
                        continue
                    if rx.search(text):
                        el.click(timeout=5000)
                        log.info("Geklickt: %r", text[:60])
                        page.wait_for_timeout(1200)
                        return True
                except Exception:
                    continue
        return False

    def _dismiss_cookies(self, page) -> bool:
        return self._click_by_patterns(page, COOKIE_PATTERNS)

    def _click_accept(self, page) -> bool:
        return self._click_by_patterns(page, ACCEPT_PATTERNS)

    def _tick_checkboxes(self, page) -> int:
        """Alle sichtbaren, nicht gesetzten Checkboxen anhaken (AGB-Zustimmung)."""
        count = 0
        try:
            boxes = page.query_selector_all("input[type=checkbox]")
        except Exception:
            return 0
        for box in boxes:
            try:
                if box.is_visible() and not box.is_checked():
                    box.check(timeout=4000)
                    count += 1
            except Exception:
                # Manche Portale verstecken die echte Box hinter einem Label
                try:
                    box.click(force=True, timeout=3000)
                    count += 1
                except Exception:
                    continue
        if count:
            log.info("%d Checkbox(en) gesetzt", count)
        return count

    def _enter_frames(self, page) -> bool:
        """Zweiter Anlauf innerhalb von iframes (haeufig bei Hotspot-Systemen)."""
        acted = False
        for frame in page.frames[1:]:
            try:
                for pattern in ACCEPT_PATTERNS:
                    rx = re.compile(pattern, re.IGNORECASE)
                    for el in frame.query_selector_all(
                            "button, input[type=submit], a, [role=button]"):
                        if not el.is_visible():
                            continue
                        text = (el.inner_text() or
                                el.get_attribute("value") or "").strip()
                        if text and len(text) <= 80 and rx.search(text):
                            el.click(timeout=4000)
                            log.info("iframe-Klick: %r", text[:60])
                            acted = True
                            break
                    if acted:
                        break
            except Exception:
                continue
            if acted:
                break
        return acted

    def _screenshot(self, page, ssid: str):
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", ssid or "portal")[:40]
        path = os.path.join(
            self.screenshot_dir, f"portal_{safe}_{int(time.time())}.png")
        try:
            page.screenshot(path=path, full_page=True)
            log.info("Screenshot: %s", path)
            return path
        except Exception as exc:
            log.warning("Screenshot fehlgeschlagen: %s", exc)
            return None


def make_qr(url: str, out_path: str, label: str = "") -> str | None:
    """
    QR-Code mit der Portal-URL erzeugen.

    Landet im www-Verzeichnis von Home Assistant und wird von der
    Notification als Bild angehaengt.
    """
    try:
        import qrcode
        from PIL import Image, ImageDraw
    except ImportError:
        log.error("qrcode/Pillow fehlen -- QR-Fallback nicht verfuegbar")
        return None

    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=3,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

        if label:
            w, h = img.size
            canvas = Image.new("RGB", (w, h + 46), "white")
            canvas.paste(img, (0, 0))
            draw = ImageDraw.Draw(canvas)
            text = label[:48]
            # Standardfont: reicht, haelt den Container schlank
            draw.text((14, h + 14), text, fill="black")
            img = canvas

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        img.save(out_path)
        log.info("QR-Code: %s", out_path)
        return out_path
    except Exception as exc:
        log.exception("QR-Erzeugung fehlgeschlagen: %s", exc)
        return None
