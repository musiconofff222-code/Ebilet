import os
import sys
import time
import logging
import warnings
import random
import requests
import ddddocr
import io
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

    raise Exception("Giriş başarısız oldu.")


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
        raise Exception(f"{field_id} alanı bulunamadı")

    field.scroll_into_view_if_needed()
    field.click(force=True)

    try:
        ctx.wait_for_selector(
            f"#{field_id} + ul li:not(.autocomplete__no-results)",
            timeout=timeout
        )
    except PlaywrightTimeoutError:
        raise Exception(f"{field_id}: tıklama sonrası şehir listesi hiç yüklenmedi")

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
        raise Exception(
            f"{field_id}: '{city_name}' ({iata_code}) dropdown'da bulunamadı/seçilemedi"
        )

    try:
        actual_value = ctx.locator(f"#{field_id}").input_value()
    except Exception:
        actual_value = None
    logging.info(f"✅ {field_id} -> {city_name} ({iata_code}) seçildi. Input değeri: '{actual_value}'")


def select_departure_date(page, day: int, month: int, year: int, field_id: str = "external-depart-date", timeout=12000):
    ctx = page
    field = ctx.locator(f"#{field_id}")

    if field.count() == 0 or not field.is_visible():
        raise Exception(f"{field_id} alanı bulunamadı/görünmüyor")

    if not robust_click(ctx, field, timeout):
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
        raise Exception(f"{date_key} tarihi takvimde bulunamadı")

    cls = cell.get_attribute("class") or ""
    if "disabled" in cls:
        raise Exception(f"{date_key} tarihi devre dışı")

    if not robust_click(ctx, cell, timeout):
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


def click_search_button(page, timeout=12000):
    logging.info("Arama butonuna basılıyor...")
    btn = page.locator("#external-ticket-submit")

    if btn.count() == 0:
        raise Exception("external-ticket-submit butonu bulunamadı")

    url_before = page.url
    if not robust_click(page, btn, timeout):
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

    page.wait_for_timeout(2000)
    url_after = page.url

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
            logging.info(f"🧩 Captcha popup tespit edildi (selector: {captcha_sel}).")
            landed_on_home = False

    if landed_on_home:
        raise Exception(f"Arama sonrası ana sayfaya yönlendirildi (önce: {url_before}, sonra: {url_after}).")


def get_last_update_id():
    try:
        resp = requests.get(f"{TELEGRAM_API}/getUpdates", params={"limit": 1, "offset": -1}, timeout=15)
        results = resp.json().get("result", [])
        if results:
            return results[-1]["update_id"]
    except Exception as e:
        logging.warning(f"getUpdates hata: {e}")
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
                return loc, sel
        except Exception:
            continue
    return None, None


def preprocess_captcha_variants(img_bytes):
    variants = []
    try:
        base_img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
        
        # 1. Orijinal
        buf1 = io.BytesIO()
        base_img.save(buf1, format='PNG')
        variants.append(buf1.getvalue())
        
        # 2. Keskinleştirilmiş & Kontrastlı
        img2 = base_img.filter(ImageFilter.SHARPEN)
        img2 = ImageEnhance.Contrast(img2).enhance(2.0)
        buf2 = io.BytesIO()
        img2.save(buf2, format='PNG')
        variants.append(buf2.getvalue())

        # 3. Siyah-Beyaz (Threshold)
        gray = base_img.convert('L')
        threshold = 140
        bw = gray.point(lambda p: 255 if p > threshold else 0)
        buf3 = io.BytesIO()
        bw.save(buf3, format='PNG')
        variants.append(buf3.getvalue())

        # 4. Yüksek Kontrastlı Gri
        gray_enhanced = ImageEnhance.Contrast(gray).enhance(2.5)
        buf4 = io.BytesIO()
        gray_enhanced.save(buf4, format='PNG')
        variants.append(buf4.getvalue())
    except Exception as e:
        logging.warning(f"Görsel işleme hatası: {e}")
        variants = [img_bytes]
    return variants


def handle_captcha_if_present(page, wait_after_click=2000, answer_timeout=300, submit_url_builder=None):
    page.wait_for_timeout(wait_after_click)
    popup, matched_sel = find_captcha_popup(page)
    if popup is None:
        logging.info("Captcha popup görünmüyor, devam ediliyor.")
        return False

    logging.info(f"🧩 Captcha popup tespit edildi (selector: {matched_sel}).")

    ocr = ddddocr.DdddOcr(show_ad=False)
    answer = None
    max_refresh_attempts = 3

    for attempt in range(1, max_refresh_attempts + 1):
        logging.info(f"🔄 Captcha Okuma Denemesi {attempt}/{max_refresh_attempts}...")

        refresh_el = popup.locator("#refreshRecaptcha, .refreshRecaptcha").first
        if refresh_el.count() == 0:
            refresh_el = page.locator("#refreshRecaptcha, .refreshRecaptcha").first

        if attempt > 1 and refresh_el.count() > 0:
            try:
                refresh_el.click(force=True)
                page.wait_for_timeout(1000)
                logging.info("🔄 Captcha görseli yenilendi, yeni kod taranıyor...")
            except Exception as e:
                logging.warning(f"Refresh butonuna tıklanamadı: {e}")

        captcha_img_bytes = None
        try:
            if refresh_el.count() > 0 and refresh_el.is_visible():
                captcha_img_bytes = refresh_el.screenshot()
        except Exception as e:
            logging.warning(f"Captcha elemanının ekran görüntüsü alınamadı: {e}")

        shot_path = "captcha_popup.png"
        if not captcha_img_bytes:
            try:
                popup.screenshot(path=shot_path)
                with open(shot_path, "rb") as f:
                    captcha_img_bytes = f.read()
            except Exception:
                pass

        if captcha_img_bytes:
            variants = preprocess_captcha_variants(captcha_img_bytes)
            for v_idx, var_bytes in enumerate(variants, 1):
                try:
                    parsed_text = ocr.classification(var_bytes)
                    if parsed_text:
                        candidate = str(parsed_text).strip()
                        if len(candidate) == 6 and candidate.isdigit():
                            answer = candidate
                            logging.info(f"🎯 ddddocr {attempt}. denemede (Filtre #{v_idx}) TAM 6 HANELİ kodu yakaladı: {answer}")
                            break
                        else:
                            logging.info(f"🔍 Deneme {attempt} - Filtre #{v_idx}: '{candidate}' (Uzunluk {len(candidate)} != 6, pas geçiliyor)")
                except Exception as e:
                    logging.warning(f"OCR tarama hatası (Filtre #{v_idx}): {e}")

        if answer:
            break

    if not answer:
        logging.warning("⚠️ 3 denemede de 6 haneli net kod okunamadı. Telegram üzerinden manuel yanıt bekleniyor...")
        last_update_id = get_last_update_id()
        shot_path = "captcha_popup.png"
        popup.screenshot(path=shot_path)
        send_telegram(
            "🧩 <b>Captcha net okunamadı!</b>\n\n"
            "Lütfen görseldeki 6 haneli kodu bu sohbete yazın.",
            photo_path=shot_path
        )
        answer, _ = get_telegram_reply(after_update_id=last_update_id, timeout=answer_timeout)

    if not answer:
        send_telegram("⏱️ Captcha cevabı alınamadı, işlem durduruluyor.")
        raise Exception("Captcha cevabı alınamadı (timeout / OCR başarısız)")

    logging.info(f"✅ Kullanılacak captcha cevabı: {answer}")
    send_telegram(f"🤖 <b>Captcha Otomatik Geçiliyor:</b> <code>{answer}</code>")

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
        raise Exception("Captcha input alanı bulunamadı, cevap yazılamadı")

    confirmed = False

    if submit_url_builder is not None:
        try:
            target_url = submit_url_builder(answer)
            if target_url:
                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                confirmed = True
        except Exception as e:
            logging.warning(f"⚠️ submit_url_builder çalıştırılamadı: {e}")
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
        except Exception:
            csrf_token = None

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
            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                confirmed = True
            except Exception:
                pass

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

    page.wait_for_timeout(2000)
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

            run_with_retries("Arama butonu", click_search_button, page)

            try:
                handle_captcha_if_present(page)
            except Exception as e:
                logging.error(f"Captcha çözüm adımı başarısız: {e}")
                raise

            time.sleep(6)
            page.evaluate("window.scrollTo(0, 250)")
            time.sleep(2)

            send_telegram(
                f"🏁 <b>{DEPARTURE_DAY} Ağustos 2026 Uçuş Taraması Tamamlandı</b>\n\n"
                f"✈️ <b>Rota:</b> {ORIGIN_CITY} ➔ {DEST_CITY}\n"
                "📌 İşlemler başarıyla tamamlandı."
            )

            try:
                calendar_href = page.locator("a.data-slider__calendar").first.get_attribute("href")
            except Exception:
                calendar_href = None

            if calendar_href:
                logging.info(f"📅 Aylık takvim sayfasına gidiliyor: {calendar_href}")
                try:
                    page.goto(calendar_href, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(2000)

                    def _calendar_submit_url_builder(captcha_answer, base_url=calendar_href):
                        sep = "&" if "?" in base_url else "?"
                        return f"{base_url}{sep}captcha={captcha_answer}"

                    try:
                        handle_captcha_if_present(page, submit_url_builder=_calendar_submit_url_builder)
                    except Exception as e:
                        logging.error(f"Takvim sayfası captcha çözümü başarısız: {e}")

                    page.wait_for_timeout(3000)
                    calendar_screenshot = "calendar_month.png"
                    page.screenshot(path=calendar_screenshot, full_page=True)
                    send_telegram(
                        f"📅 <b>Ay Takvim Görünümü</b>\n✈️ <b>Rota:</b> {ORIGIN_CITY} ➔ {DEST_CITY}",
                        photo_path=calendar_screenshot
                    )
                except Exception as e:
                    logging.error(f"Takvim sayfasına gidilemedi: {e}")
                    send_telegram(f"⚠️ Takvim sayfasına gidilemedi: <code>{e}</code>")
            else:
                logging.warning("⚠️ Takvim linki bulunamadı, aylık görünüm atlanıyor.")

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
    confirmed = False

    if submit_url_builder is not None:
        try:
            target_url = submit_url_builder(answer)
            if target_url:
                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                confirmed = True
        except Exception as 
