import os
import sys
import time
import logging
import warnings
import random
import io
import requests
import ddddocr
from PIL import Image, ImageEnhance, ImageFilter
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
PHONE = os.environ.get("TM_PHONE", "71751555")
PASSWORD = os.environ.get("TM_PASSWORD", "shazada")

USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Edge/122.0.2365.92"
]

PROXY_SERVER = os.environ.get("TM_PROXY_SERVER", None)

HOME_URL = "https://turkmenistanairlines.tm"
LOGIN_URL = "https://turkmenistanairlines.tm/tm/auth/login"

ORIGIN_CITY = "Ashgabat"
ORIGIN_CODE = "ASB"
DEST_CITY = "Stambul"
DEST_CODE = "IST"
DEPARTURE_DAY = 1
DEPARTURE_MONTH = 8
DEPARTURE_YEAR = 2026

def preprocess_captcha_image(img_bytes):
    try:
        image = Image.open(io.BytesIO(img_bytes))
        if image.mode != 'RGB':
            image = image.convert('RGB')
        w, h = image.size
        image = image.resize((w * 3, h * 3), Image.Resampling.LANCZOS)
        image = image.convert('L')
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.5)
        sharpness = ImageEnhance.Sharpness(image)
        image = sharpness.enhance(2.0)
        buf = io.BytesIO()
        image.save(buf, format='PNG')
        return buf.getvalue()
    except Exception as e:
        logging.warning(f"Captcha görsel ön işleme hatası: {e}")
        return img_bytes

def send_telegram(message, photo_path=None):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=30
        )
    except Exception as e:
        logging.error(f"Telegram metin gönderilemedi: {e}")
    if photo_path and os.path.exists(photo_path):
        try:
            with open(photo_path, 'rb') as f:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                    data={'chat_id': CHAT_ID, 'caption': message, 'parse_mode': 'HTML'},
                    files={'photo': f},
                    timeout=40
                )
        except Exception as e:
            logging.error(f"Telegram görsel gönderilemedi: {e}")

def send_telegram_document(file_path, caption=""):
    if not TELEGRAM_TOKEN or not CHAT_ID or not os.path.exists(file_path):
        return
    try:
        with open(file_path, 'rb') as f:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
                data={'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'},
                files={'document': f},
                timeout=40
            )
    except Exception as e:
        logging.error(f"Telegram dosya gönderilemedi: {e}")

def extract_form_errors(page):
    try:
        errors = page.evaluate(
            """
            () => {
                const nodes = document.querySelectorAll(
                    '[class*="long-from__error"], [class*="long-form__error"]'
                );
                const results = [];
                nodes.forEach(n => {
                    const cls = n.className || '';
                    if (cls.includes('inactive')) return;
                    const text = (n.textContent || '').trim();
                    if (!text) return;
                    const id = n.id || '(id yok)';
                    results.push(id + ': ' + text);
                });
                return results;
            }
            """
        )
        return errors or []
    except Exception:
        return []

def capture_debug(page, tag):
    shot_path = f"debug_{tag}.png"
    html_path = f"debug_{tag}.html"
    try:
        page.screenshot(path=shot_path, full_page=True)
    except Exception:
        pass
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception:
        pass
    errors = extract_form_errors(page)
    if errors:
        error_block = "\n\n⚠️ <b>Form Hataları Tespit Edildi:</b>\n" + "\n".join(
            f"• {e}" for e in errors
        )
        logging.warning(f"[{tag}] Form hataları: {errors}")
    else:
        error_block = ""
    send_telegram(f"🔎 <b>Debug:</b> {tag}\nURL: {page.url}{error_block}", photo_path=shot_path)
    if os.path.exists(html_path):
        send_telegram_document(html_path, caption=f"HTML dump: {tag}{error_block}")

def close_unwanted_popups(page):
    try:
        page.evaluate("""() => {
            const modals = document.querySelectorAll('.modal, .popup, div[role="dialog"], #contact-modal, .modal-backdrop');
            modals.forEach(m => m.remove());
            document.body.classList.remove('modal-open');
        }""")
    except Exception:
        pass

def robust_click(ctx, locator, timeout=10000):
    try:
        locator.first.wait_for(state="visible", timeout=timeout)
        locator.first.scroll_into_view_if_needed()
        locator.first.click(timeout=6000)
        return True
    except Exception:
        pass
    try:
        locator.first.click(timeout=6000, force=True)
        return True
    except Exception:
        pass
    try:
        locator.first.evaluate("el => el.click()")
        return True
    except Exception:
        return False

def _first_visible(locator):
    try:
        count = locator.count()
    except Exception:
        return None
    for i in range(count):
        item = locator.nth(i)
        try:
            if item.is_visible():
                return item
        except Exception:
            continue
    return None

def find_and_click_across_frames(page, text, exact=False, timeout=20000):
    locator = page.get_by_text(text, exact=exact)
    visible_item = _first_visible(locator)
    if visible_item is not None and robust_click(page, visible_item, timeout):
        return True
    for frame in page.frames:
        try:
            flocator = frame.get_by_text(text, exact=exact)
            fvisible_item = _first_visible(flocator)
            if fvisible_item is not None and robust_click(frame, fvisible_item, timeout):
                return True
        except Exception:
            continue
    return False

def login(page):
    logging.info("Login sayfasına gidiliyor...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    close_unwanted_popups(page)
    logging.info(f"Telefon dolduruluyor: {PHONE}")
    page.locator("#telephone").click()
    page.locator("#telephone").fill(PHONE)
    page.wait_for_timeout(500)
    logging.info("Şifre dolduruluyor...")
    page.locator("#password").click()
    page.locator("#password").fill(PASSWORD)
    page.wait_for_timeout(500)
    logging.info("Giriş butonuna basılıyor...")
    page.locator("#auth-login-submit").click()
    page.wait_for_timeout(4000)
    login_confirmed = False
    if "customer/account" in page.url:
        login_confirmed = True
    else:
        try:
            logout_link = page.locator("a[href*='logout'], [class*='logout']").first
            if logout_link.count() > 0 and logout_link.is_visible():
                login_confirmed = True
        except Exception:
            pass
    if login_confirmed:
        logging.info("✅ Giriş başarılı.")
        return True
    capture_debug(page, "login_failed")
    raise Exception("Giriş başarısız oldu (login_failed debug'ına bak)")

def click_international_tab(page, timeout=12000):
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1000)
    for text in ["DAŞARKY GATNAWLAR", "Daşarky Gatnawlar", "Daşarky", "Dış Hatlar", "International"]:
        if find_and_click_across_frames(page, text, exact=False, timeout=6000):
            logging.info(f"Dış Hatlar sekmesi seçildi (eşleşme: {text}).")
            page.wait_for_timeout(2000)
            return
    capture_debug(page, "international_tab_not_found")
    raise Exception("Dış Hatlar sekmesi bulunamadı/tıklanamadı")

def select_city(page, field_id: str, city_name: str, iata_code: str, timeout=12000):
    ctx = page
    field = None
    for frame in [page] + list(page.frames):
        try:
            loc = frame.locator(f"#{field_id}")
            if loc.count() > 0 and loc.is_visible():
                ctx = frame
                field = loc
                break
        except Exception:
            continue
    if not field:
        capture_debug(page, f"city_field_not_found_{field_id}")
        raise Exception(f"{field_id} alanı bulunamadı")
    field.scroll_into_view_if_needed()
    field.click(force=True)
    try:
        ctx.wait_for_selector(
            f"#{field_id} + ul li:not(.autocomplete__no-results)",
            timeout=timeout
        )
    except PlaywrightTimeoutError:
        capture_debug(page, f"city_list_not_loaded_{field_id}")
        raise Exception(f"{field_id}: tıklama sonrası şehir listesi hiç yüklenmedi")
    capture_debug(page, f"dropdown_open_{field_id}")
    dropdown_selectors = [
        f"#{field_id} + ul li:has-text('({iata_code})')",
        f"#{field_id} + ul.autocomplete__list li:has-text('({iata_code})')",
        f"#{field_id} + ul li[data-value='{iata_code}']",
        f"#{field_id} + ul li:has-text('{city_name}')",
        f"li:visible:has-text('({iata_code})')",
        f"li:visible:has-text('{city_name}')",
    ]
    clicked = False
    for sel in dropdown_selectors:
        item = ctx.locator(sel).first
        try:
            item.wait_for(state="visible", timeout=4000)
            if robust_click(ctx, item, 4000):
                clicked = True
                break
        except PlaywrightTimeoutError:
            continue
    if not clicked:
        capture_debug(page, f"city_not_matched_{field_id}")
        raise Exception(
            f"{field_id}: '{city_name}' ({iata_code}) dropdown'da bulunamadı/seçilemedi"
        )
    try:
        actual_value = ctx.locator(f"#{field_id}").input_value()
    except Exception:
        actual_value = None
    logging.info(f"✅ {field_id} -> {city_name} ({iata_code}) seçildi. Input değeri: '{actual_value}'")
    if not actual_value or iata_code not in actual_value:
        logging.warning(
            f"⚠️ {field_id} seçildi görünüyor ama input değeri beklenenle eşleşmiyor "
            f"(beklenen kod: {iata_code}, gerçek değer: '{actual_value}'). "
            f"Form submit sırasında bu alan boş/yanlış gidebilir."
        )

def select_departure_date(page, day: int, month: int, year: int, field_id: str = "external-depart-date", timeout=12000):
    ctx = page
    field = ctx.locator(f"#{field_id}")
    if field.count() == 0 or not field.is_visible():
        capture_debug(page, f"date_field_not_found_{field_id}")
        raise Exception(f"{field_id} alanı bulunamadı/görünmüyor")
    if not robust_click(ctx, field, timeout):
        capture_debug(page, f"date_field_not_clickable_{field_id}")
        raise Exception(f"{field_id} tıklanamadı")
    page.wait_for_timeout(1500)
    date_key = f"{month}/{day}/{year}"
    cell = ctx.locator(f"li[data-date-input='{date_key}']").first
    max_month_clicks = 12
    clicks_done = 0
    next_button_selectors = [
        "[class*='calendar'] [class*='next']",
        "[class*='datepicker'] [class*='next']",
        "a.next", "button.next", "[data-action='next-month']",
    ]
    while cell.count() == 0 and clicks_done < max_month_clicks:
        advanced = False
        for sel in next_button_selectors:
            nxt = ctx.locator(sel).first
            try:
                if nxt.count() > 0 and nxt.is_visible():
                    robust_click(ctx, nxt, 3000)
                    advanced = True
                    break
            except Exception:
                continue
        if not advanced:
            break
        clicks_done += 1
        page.wait_for_timeout(600)
        cell = ctx.locator(f"li[data-date-input='{date_key}']").first
    if cell.count() == 0:
        capture_debug(page, "day_cell_not_found")
        raise Exception(f"{date_key} tarihi takvimde bulunamadı (gösterilen aylar arasında olmayabilir)")
    cls = cell.get_attribute("class") or ""
    if "disabled" in cls:
        capture_debug(page, "day_cell_disabled")
        raise Exception(f"{date_key} tarihi devre dışı (geçmiş tarih olabilir)")
    if not robust_click(ctx, cell, timeout):
        capture_debug(page, "day_cell_not_clickable")
        raise Exception(f"{date_key} tıklanamadı")
    logging.info(f"✅ Gidiş tarihi -> {date_key} seçildi.")
    page.wait_for_timeout(500)
    try:
        calendar_still_open = ctx.locator(f"li[data-date-input='{date_key}']").first.is_visible()
    except Exception:
        calendar_still_open = False
    if calendar_still_open:
        try:
            field.click(force=True)
            page.wait_for_timeout(500)
        except Exception:
            pass
    try:
        actual_value = field.input_value()
    except Exception:
        actual_value = None
    logging.info(f"Tarih alanı input değeri: '{actual_value}'")
    if not actual_value:
        logging.warning(
            "⚠️ Tarih seçildi görünüyor ama input alanı boş. "
            "Submit sırasında tarih formda gitmeyebilir."
        )

def debug_form_state(page):
    try:
        state = page.evaluate(
            """
            () => {
                const depart = document.querySelector('#external-depart-port');
                const arrival = document.querySelector('#external-arrival-port');
                const date = document.querySelector('#external-depart-date');
                return {
                    depart_value: depart ? depart.value : null,
                    arrival_value: arrival ? arrival.value : null,
                    date_value: date ? date.value : null,
                    url: window.location.href,
                };
            }
            """
        )
    except Exception as e:
        state = {"error": str(e)}
    logging.info(f"📋 Submit öncesi form durumu: {state}")
    msg = (
        "📋 <b>Submit öncesi form durumu</b>\n"
        f"Nereden: <code>{state.get('depart_value')}</code>\n"
        f"Nereye: <code>{state.get('arrival_value')}</code>\n"
        f"Tarih: <code>{state.get('date_value')}</code>"
    )
    send_telegram(msg)
    return state

def click_search_button(page, timeout=12000):
    logging.info("Arama butonuna basılıyor...")
    btn = page.locator("#external-ticket-submit")
    if btn.count() == 0:
        capture_debug(page, "search_button_not_found")
        raise Exception("external-ticket-submit butonu bulunamadı")
    captured_responses = []
    failed_requests = []
    def _on_response(response):
        try:
            status = response.status
            url = response.url
            if 300 <= status < 400:
                try:
                    location = response.headers.get("location", "(location header yok)")
                except Exception:
                    location = "(okunamadı)"
                captured_responses.append((status, url, location))
            elif status >= 400 or any(k in url.lower() for k in ["search", "flight", "ticket", "external", "captcha", "recaptcha"]):
                captured_responses.append((status, url, None))
        except Exception:
            pass
    def _on_request_failed(request):
        try:
            failed_requests.append((request.url, request.failure))
        except Exception:
            pass
    page.on("response", _on_response)
    page.on("requestfailed", _on_request_failed)
    form_state = debug_form_state(page)
    url_before = page.url
    if not robust_click(page, btn, timeout):
        page.remove_listener("response", _on_response)
        page.remove_listener("requestfailed", _on_request_failed)
        capture_debug(page, "search_button_not_clickable")
        raise Exception("external-ticket-submit tıklanamadı")
    logging.info("✅ Arama butonuna tıklandı.")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except PlaywrightTimeoutError:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(3000)
    page.remove_listener("response", _on_response)
    page.remove_listener("requestfailed", _on_request_failed)
    url_after = page.url
    logging.info(f"URL değişimi: '{url_before}' -> '{url_after}'")
    for status, url, location in captured_responses:
        if location:
            logging.info(f"📡 Redirect yakalandı: {status} - {url} -> Location: {location}")
        else:
            logging.info(f"📡 Yakalanan network isteği: {status} - {url}")
    for url, failure in failed_requests:
        logging.warning(f"❌ Başarısız istek: {url} - Sebep: {failure}")
    landed_on_home = (
        url_after.rstrip("/") == HOME_URL.rstrip("/")
        or (url_after.rstrip("/") == url_before.rstrip("/") and "search" not in url_after.lower())
    )
    if landed_on_home:
        captcha_popup, captcha_sel = None, None
        for _ in range(5):
            captcha_popup, captcha_sel = find_captcha_popup(page)
            if captcha_popup is not None:
                break
            page.wait_for_timeout(1000)
        if captcha_popup is not None:
            logging.info(f"🧩 'Ana sayfaya düştük' zannedilen durum aslında captcha popup'ı (selector: {captcha_sel}). Hata fırlatılmıyor.")
            landed_on_home = False
        else:
            logging.info("Captcha popup polling ile de bulunamadı, gerçekten ana sayfaya düşülmüş görünüyor.")
    if landed_on_home:
        redirect_lines = []
        for status, url, location in captured_responses:
            if location:
                redirect_lines.append(f"• {status} — {url}\n   ↳ Location: {location}")
            else:
                redirect_lines.append(f"• {status} — {url}")
        redirect_info = "\n".join(redirect_lines) or "Yok (network isteği yakalanamadı)"
        failed_info = "\n".join(f"• {url} — {failure}" for url, failure in failed_requests) or "Yok"
        form_info = (
            f"Nereden: {form_state.get('depart_value')}\n"
            f"Nereye: {form_state.get('arrival_value')}\n"
            f"Tarih: {form_state.get('date_value')}"
        )
        capture_debug(page, "redirected_to_home")
        send_telegram(
            "🚨 <b>Arama sonrası ana sayfaya geri atıldı!</b>\n\n"
            f"URL (önce): <code>{url_before}</code>\n"
            f"URL (sonra): <code>{url_after}</code>\n\n"
            f"<b>Submit anındaki form değerleri:</b>\n{form_info}\n\n"
            f"<b>Yakalanan network yanıtları (redirect'ler dahil):</b>\n{redirect_info}\n\n"
            f"<b>Başarısız istekler:</b>\n{failed_info}"
        )
        raise Exception(
            f"Arama sonrası ana sayfaya yönlendirildi (önce: {url_before}, sonra: {url_after}). "
            f"Form değerleri: {form_state}"
        )

def get_last_update_id():
    try:
        resp = requests.get(f"{TELEGRAM_API}/getUpdates", params={"limit": 1, "offset": -1}, timeout=15)
        results = resp.json().get("result", [])
        if results:
            return results[-1]["update_id"]
    except Exception as e:
        logging.warning(f"getUpdates (offset init) hata: {e}")
    return None

def get_telegram_reply(after_update_id=None, timeout=300, poll_interval=5):
    start = time.time()
    offset = (after_update_id + 1) if after_update_id else None
    while time.time() - start < timeout:
        try:
            resp = requests.get(
                f"{TELEGRAM_API}/getUpdates",
                params={"timeout": poll_interval, "offset": offset},
                timeout=poll_interval + 15
            )
            data = resp.json()
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                if str(msg.get("chat", {}).get("id")) == str(CHAT_ID) and "text" in msg:
                    return msg["text"].strip(), upd["update_id"]
        except Exception as e:
            logging.warning(f"Telegram getUpdates hata: {e}")
            time.sleep(2)
    return None, offset
    def find_captcha_popup(page):
    selectors = [
        "#captchaPopup",
        "[id*='captcha' i]",
        "[class*='captcha' i]",
        "iframe[src*='captcha' i]",
        "iframe[title*='captcha' i]",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            if loc.is_visible():
                return loc, sel
            try:
                loc.evaluate(
                    """el => {
                        el.style.setProperty('display', 'flex', 'important');
                        el.style.setProperty('visibility', 'visible', 'important');
                        el.style.setProperty('opacity', '1', 'important');
                        el.style.setProperty('z-index', '99999', 'important');
                        let p = el.parentElement;
                        while (p) {
                            const cs = window.getComputedStyle(p);
                            if (cs.display === 'none') p.style.setProperty('display', 'block', 'important');
                            if (cs.visibility === 'hidden') p.style.setProperty('visibility', 'visible', 'important');
                            p = p.parentElement;
                        }
                    }"""
                )
            except Exception:
                pass
            if loc.is_visible():
                logging.info(f"🧩 Captcha popup DOM'da vardı ama gizliydi, zorla görünür kılındı (selector: {sel}).")
                return loc, sel
        except Exception:
            continue
    return None, None

def trigger_captcha_refresh(page, popup):
    try:
        refresh_resp = page.request.post("https://turkmenistanairlines.tm/refresh-captcha")
        if refresh_resp.ok:
            captcha_html = refresh_resp.text()
            page.evaluate(
                """html => {
                    const el = document.getElementById('refreshRecaptcha');
                    if (el) el.innerHTML = html;
                }""",
                captcha_html
            )
            logging.info("✅ Captcha görseli POST isteği ile yenilendi.")
            return True
    except Exception as e:
        logging.warning(f"⚠️ Captcha POST yenileme başarısız: {e}")
    try:
        refresh_el = popup.locator("#refreshRecaptcha, .refreshRecaptcha").first
        if refresh_el.count() == 0:
            refresh_el = page.locator("#refreshRecaptcha, .refreshRecaptcha").first
        if refresh_el.count() > 0:
            robust_click(page, refresh_el, timeout=5000)
            logging.info("🔄 Captcha butona tıklanarak yenilendi.")
            return True
    except Exception as e:
        logging.warning(f"⚠️ Captcha buton tıklama ile yenilenemedi: {e}")
    return False

def handle_captcha_if_present(page, wait_after_click=3000, answer_timeout=300, submit_url_builder=None):
    page.wait_for_timeout(wait_after_click)
    popup, matched_sel = find_captcha_popup(page)
    if popup is None:
        logging.info("Captcha popup görünmüyor, devam ediliyor.")
        return False
    logging.info(f"🧩 Captcha popup tespit edildi (selector: {matched_sel}).")
    diag_network_hits = []
    diag_console_msgs = []
    diag_page_errors = []
    def _on_diag_response(response):
        try:
            u = response.url.lower()
            if "captcha" in u or "recaptcha" in u:
                diag_network_hits.append((response.status, response.url))
        except Exception:
            pass
    def _on_diag_console(msg):
        try:
            if msg.type in ("error", "warning"):
                diag_console_msgs.append(f"[{msg.type}] {msg.text}")
        except Exception:
            pass
    def _on_diag_pageerror(exc):
        try:
            diag_page_errors.append(str(exc))
        except Exception:
            pass
    page.on("response", _on_diag_response)
    page.on("console", _on_diag_console)
    page.on("pageerror", _on_diag_pageerror)
    trigger_captcha_refresh(page, popup)
    try:
        refresh_el = popup.locator("#refreshRecaptcha, .refreshRecaptcha").first
        if refresh_el.count() == 0:
            refresh_el = page.locator("#refreshRecaptcha, .refreshRecaptcha").first
        if refresh_el.count() > 0:
            refresh_el.evaluate(
                """el => {
                    el.style.setProperty('min-width', '200px', 'important');
                    el.style.setProperty('min-height', '60px', 'important');
                    el.style.setProperty('display', 'inline-block', 'important');
                    el.style.setProperty('background-size', 'contain', 'important');
                    el.style.setProperty('background-repeat', 'no-repeat', 'important');
                }"""
            )
    except Exception:
        pass
    page.wait_for_timeout(1500)
    page.remove_listener("response", _on_diag_response)
    page.remove_listener("console", _on_diag_console)
    page.remove_listener("pageerror", _on_diag_pageerror)
    shot_path = "captcha_popup.png"
    answer = None
    ocr = ddddocr.DdddOcr(show_ad=False)
    max_refreshes = 3
    for refresh_attempt in range(max_refreshes + 1):
        if refresh_attempt > 0:
            logging.info(f"🔄 Captcha 6 haneli okunamadı. Görsel yenileniyor ({refresh_attempt}/{max_refreshes})...")
            trigger_captcha_refresh(page, popup)
            page.wait_for_timeout(2000)
        captcha_img_bytes = None
        try:
            refresh_el = popup.locator("#refreshRecaptcha, .refreshRecaptcha").first
            if refresh_el.count() == 0:
                refresh_el = page.locator("#refreshRecaptcha, .refreshRecaptcha").first
            if refresh_el.count() > 0 and refresh_el.is_visible():
                captcha_img_bytes = refresh_el.screenshot()
        except Exception as e:
            logging.warning(f"Captcha elemanının ekran görüntüsü alınamadı: {e}")
        if not captcha_img_bytes:
            try:
                popup.screenshot(path=shot_path)
                if os.path.exists(shot_path):
                    with open(shot_path, "rb") as f:
                        captcha_img_bytes = f.read()
            except Exception:
                pass
        if captcha_img_bytes:
            processed_bytes = preprocess_captcha_image(captcha_img_bytes)
            try:
                parsed_text = ocr.classification(processed_bytes)
                clean_text = "".join(c for c in str(parsed_text or "").strip() if c.isalnum())
                if len(clean_text) != 6:
                    raw_parsed = ocr.classification(captcha_img_bytes)
                    raw_clean = "".join(c for c in str(raw_parsed or "").strip() if c.isalnum())
                    if len(raw_clean) == 6:
                        clean_text = raw_clean
                logging.info(f"🤖 ddddocr denemesi [{refresh_attempt}/{max_refreshes}] okunan: '{clean_text}' (Uzunluk: {len(clean_text)})")
                if len(clean_text) == 6:
                    answer = clean_text
                    try:
                        popup.screenshot(path=shot_path)
                    except Exception:
                        pass
                    logging.info(f"✅ 6 Haneli Captcha Tam Başarıyla Okundu: {answer}")
                    break
            except Exception as e:
                logging.error(f"ddddocr okuma sırasında hata: {e}")
    if not answer:
        try:
            popup.screenshot(path=shot_path)
        except Exception:
            pass
        logging.warning("⚠️ ddddocr ile 6 haneli captcha okunamadı. Telegram üzerinden manuel yanıt bekleniyor...")
        last_update_id = get_last_update_id()
        send_telegram(
            "🧩 <b>Captcha 6 haneli okunamadı (3 Yenileme Tamamlandı)!</b>\n\n"
            "Lütfen görseldeki 6 haneli kodu bu sohbete yazın.",
            photo_path=shot_path
        )
        answer, _ = get_telegram_reply(after_update_id=last_update_id, timeout=answer_timeout)
    if not answer:
        send_telegram("⏱️ Captcha cevabı alınamadı, işlem durduruluyor.")
        raise Exception("Captcha cevabı alınamadı (timeout / OCR başarısız)")
    logging.info(f"✅ Kullanılacak captcha cevabı: {answer}")
    send_telegram(
        f"🤖 <b>Captcha Otomatik Geçiliyor:</b> <code>{answer}</code>",
        photo_path=shot_path if os.path.exists(shot_path) else None
    )
    input_selectors = [
        "#captchaInput",
        "input[name='captcha']",
        "input[name*='captcha' i]",
        "input[id*='captcha' i]",
        "input[type='text']",
    ]
    filled = False
    for isel in input_selectors:
        try:
            inp = popup.locator(isel).first
            if inp.count() == 0:
                inp = page.locator(isel).first
            if inp.count() > 0 and inp.is_visible():
                inp.click()
                inp.fill(answer)
                filled = True
                break
        except Exception:
            continue
    if not filled:
        capture_debug(page, "captcha_input_not_found")
        raise Exception("Captcha input alanı bulunamadı, cevap yazılamadı")
    confirmed = False
    if submit_url_builder is not None:
        try:
            target_url = submit_url_builder(answer)
        except Exception as e:
            target_url = None
            logging.warning(f"⚠️ submit_url_builder çalıştırılamadı: {e}")
        if target_url:
            logging.info(f"➡️ Captcha submit URL'i (özel builder) oluşturuldu, gidiliyor: {target_url}")
            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                confirmed = True
            except Exception as e:
                logging.warning(f"⚠️ Captcha submit URL'ine gidilemedi: {e}")
    else:
        try:
            csrf_token = page.evaluate(
                """() => {
                    const tokenInput = document.querySelector(
                        'form[name="external_ticket_search"] input[name="_token"]'
                    );
                    if (tokenInput && tokenInput.value) return tokenInput.value;
                    const meta = document.querySelector('meta[name="csrf-token"]');
                    return meta ? meta.getAttribute('content') : null;
                }"""
            )
        except Exception as e:
            csrf_token = None
            logging.warning(f"⚠️ CSRF token okunamadı: {e}")
        if csrf_token:
            params = {
                "_token": csrf_token,
                "search_type": "external",
                "is_cship": "1",
                "departPort": ORIGIN_CODE,
                "arrivalPort": DEST_CODE,
                "tripType": "ow",
                "departDate": f"{DEPARTURE_MONTH}/{DEPARTURE_DAY}/{DEPARTURE_YEAR}",
                "arrivalDate": "",
                "adult": "1",
                "child": "0",
                "infant": "0",
                "captcha": answer,
            }
            target_url = "https://turkmenistanairlines.tm/tm/flights/search?" + urlencode(params)
            logging.info(f"➡️ Captcha submit URL'i (bilinen parametrelerle) oluşturuldu, gidiliyor: {target_url}")
            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                confirmed = True
            except Exception as e:
                logging.warning(f"⚠️ Captcha submit URL'ine gidilemedi: {e}")
        else:
            logging.warning("⚠️ CSRF token bulunamadı, eski (form'a bağımlı) yönteme düşülüyor.")
            try:
                target_url = page.evaluate(
                    """captchaValue => {
                        const form = document.forms['external_ticket_search'] || document.forms['internal_ticket_search'];
                        if (!form) return null;
                        const formData = new URLSearchParams(new FormData(form));
                        formData.append('captcha', captchaValue);
                        return form.action + '?' + formData.toString();
                    }""",
                    answer
                )
                if target_url:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                    confirmed = True
            except Exception as e:
                logging.warning(f"⚠️ Yedek yöntem de başarısız: {e}")
    if not confirmed:
        try:
            submit_btn = popup.locator("#submitCaptcha").first
            if submit_btn.count() == 0:
                submit_btn = page.locator("#submitCaptcha").first
            if submit_btn.count() > 0 and submit_btn.is_visible():
                confirmed = robust_click(page, submit_btn)
        except Exception:
            pass
    if not confirmed:
        confirm_texts = ["Отправить", "Onayla", "Gönder", "Devam", "Submit", "Confirm", "OK", "Tamam"]
        for t in confirm_texts:
            if find_and_click_across_frames(page, t, exact=False, timeout=3000):
                confirmed = True
                break
    if not confirmed:
        try:
            btn = popup.locator("button[type='submit'], button").first
            if btn.count() > 0:
                robust_click(page, btn)
                confirmed = True
        except Exception:
            pass
    page.wait_for_timeout(3000)
    send_telegram("✅ Captcha cevabı gönderildi, sonuç kontrol ediliyor...")
    return True

def run_with_retries(step_name, func, *args, retries=2, **kwargs):
    last_err = None
    for attempt in range(1, retries + 2):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            logging.warning(f"[{step_name}] deneme {attempt} başarısız: {e}")
            if attempt <= retries:
                time.sleep(3)
    raise last_err

def run_ticket_bot():
    logging.info("=== Türkmenistan Airlines Bilet Botu Başlatıldı ===")
    send_telegram("🧪 Test: Bot başladı, Telegram bağlantısı çalışıyor mu?")
    page = None
    with sync_playwright() as p:
        chosen_user_agent = random.choice(USER_AGENT_POOL)
        logging.info(f"Seçilen User-Agent: {chosen_user_agent}")
        browser_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled"
        ]
        launch_options = {"args": browser_args, "headless": True}
        if PROXY_SERVER:
            launch_options["proxy"] = {"server": PROXY_SERVER}
        browser = None
        try:
            browser = p.chromium.launch(**launch_options)
            context_options = {
                "user_agent": chosen_user_agent,
                "viewport": {"width": 1280, "height": 800},
                "locale": "tr-TR",
                "extra_http_headers": {
                    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Connection": "keep-alive"
                }
            }
            context = browser.new_context(**context_options)
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = context.new_page()
            page.set_default_timeout(50000)
            logging.info("Ana sayfaya bağlanılıyor...")
            max_retries = 8
            for attempt in range(1, max_retries + 1):
                try:
                    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=90000)
                    break
                except Exception as e:
                    wait_time = attempt * 12
                    logging.warning(f"Bağlantı denemesi {attempt} başarısız: {e}. {wait_time}sn bekleniyor...")
                    if attempt == max_retries:
                        raise e
                    time.sleep(wait_time)
            time.sleep(3)
            close_unwanted_popups(page)
            run_with_retries("Giriş yapma", login, page, retries=1)
            logging.info("Ana sayfaya geri dönülüyor...")
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            close_unwanted_popups(page)
            logging.info("Form doldurma başlatılıyor...")
            run_with_retries("Dış Hatlar sekmesi", click_international_tab, page)
            page.wait_for_timeout(2000)
            run_with_retries("Nereden şehri", select_city, page, "external-depart-port", ORIGIN_CITY, ORIGIN_CODE)
            page.wait_for_timeout(1500)
            run_with_retries("Nereye şehri", select_city, page, "external-arrival-port", DEST_CITY, DEST_CODE)
            page.wait_for_timeout(1500)
            run_with_retries("Gidiş tarihi", select_departure_date, page, DEPARTURE_DAY, DEPARTURE_MONTH, DEPARTURE_YEAR)
            page.wait_for_timeout(1500)
            close_unwanted_popups(page)
            step1_screenshot = "step1_dasarky.png"
            page.screenshot(path=step1_screenshot)
            send_telegram(
                f"<b>Adım 1:</b> Giriş yapıldı, Dış Hatlar Sekmesinde {ORIGIN_CITY} ➔ {DEST_CITY} ve Tarih Seçildi",
                photo_path=step1_screenshot
            )
            run_with_retries("Arama butonu", click_search_button, page)
            try:
                handle_captcha_if_present(page)
            except Exception as e:
                logging.error(f"Captcha çözüm adımı başarısız: {e}")
                raise
            time.sleep(6)
            page.evaluate("window.scrollTo(0, 250)")
            time.sleep(2)
            logging.info("Arama sonrası ekran yakalanıyor...")
            capture_debug(page, "search_result")
            send_telegram(
                f"🏁 <b>{DEPARTURE_DAY} Ağustos 2026 Uçuş Taraması Tamamlandı</b>\n\n"
                f"✈️ <b>Rota:</b> {ORIGIN_CITY} ➔ {DEST_CITY}\n"
                "📌 İşlemler başarıyla tamamlandı."
            )
        except Exception as e:
            err_msg = f"⚠️ <b>Bot Çalışırken Hata Meydana Geldi!</b>\n\nDetay: <code>{str(e)}</code>"
            logging.error(f"Kritik hata: {e}")
            try:
                if page is not None:
                    page.screenshot(path="hata_durumu.png")
                    send_telegram(err_msg, photo_path="hata_durumu.png")
                else:
                    send_telegram(err_msg)
            except Exception:
                send_telegram(err_msg)
        finally:
            if browser is not None:
                logging.info("Tarayıcı kapatılıyor.")
                browser.close()

if __name__ == "__main__":
    run_ticket_bot()
    
