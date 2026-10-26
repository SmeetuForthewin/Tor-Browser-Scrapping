import os
import time
import requests
import django

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException

# ─────────────────────────────
# DJANGO SETUP
# ─────────────────────────────

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "torproject.settings")
django.setup()

from report.models import BlackMarketCategory, BlackMarketProduct


# ─────────────────────────────
# TOR CONFIG
# ─────────────────────────────

SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 9150

FIREFOX_BINARY = "/home/bisagn/Downloads/tor-browser/Browser/firefox"
GECKODRIVER = "/snap/bin/geckodriver"

TARGET_URL = "http://blkmlgth6kmd3pzvmpmkt4zsp3blekza4rrglyfx7b5ejt2dz2tbwyqd.onion/product-category/hacking-spam/"

IMAGE_FOLDER = "/media/bisagn/data/TOR/torproject/static/black_market"
os.makedirs(IMAGE_FOLDER, exist_ok=True)

# Max retries for a page load failure
MAX_RETRIES = 3
RETRY_WAIT  = 20   # seconds to wait between retries


# ─────────────────────────────
# TOR DRIVER
# ─────────────────────────────

def create_driver():
    options = Options()
    options.binary_location = FIREFOX_BINARY

    options.set_preference("network.proxy.type", 1)
    options.set_preference("network.proxy.socks", SOCKS_HOST)
    options.set_preference("network.proxy.socks_port", SOCKS_PORT)
    options.set_preference("network.proxy.socks_remote_dns", True)

    driver = webdriver.Firefox(
        service=Service(GECKODRIVER),
        options=options
    )
    driver.set_page_load_timeout(120)
    return driver


# ─────────────────────────────
# SAFE PAGE LOADER  ← NEW
# Retries up to MAX_RETRIES times on connection errors.
# Returns True if loaded OK, False if all retries failed.
# ─────────────────────────────

def safe_get(driver, url, wait_after=6):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            driver.get(url)
            time.sleep(wait_after)
            return True
        except WebDriverException as e:
            print(f"  ⚠ Connection error (attempt {attempt}/{MAX_RETRIES}): {e.msg[:80]}")
            if attempt < MAX_RETRIES:
                print(f"  ↺ Retrying in {RETRY_WAIT}s ...")
                time.sleep(RETRY_WAIT)
            else:
                print(f"  ✗ Giving up on: {url}")
                return False


# ─────────────────────────────
# IMAGE DOWNLOADER (TOR)
# ─────────────────────────────

def download_image(url):
    if not url:
        return ""
    try:
        proxies = {
            "http": f"socks5h://{SOCKS_HOST}:{SOCKS_PORT}",
            "https": f"socks5h://{SOCKS_HOST}:{SOCKS_PORT}"
        }
        filename = url.split("/")[-1].split("?")[0]
        save_path = os.path.join(IMAGE_FOLDER, filename)
        r = requests.get(url, proxies=proxies, timeout=120)
        with open(save_path, "wb") as f:
            f.write(r.content)
        return "black_market/" + filename
    except Exception as e:
        print("  Image error:", e)
        return ""


# ─────────────────────────────
# TAB HELPER
# ─────────────────────────────

def get_tab_content(driver, tab_link_selector, panel_selector, wait):
    try:
        tab = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, tab_link_selector))
        )
        driver.execute_script("arguments[0].click();", tab)
        time.sleep(1)
        panel = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, panel_selector))
        )
        return panel.text.strip()
    except Exception as e:
        print(f"  Tab error [{tab_link_selector}]: {e.msg if hasattr(e, 'msg') else ''}")
        return ""


# ─────────────────────────────
# PAGINATION HELPER
# ─────────────────────────────

def get_all_product_links(driver, category_url):
    all_links  = []
    current_url = category_url
    page_num   = 1

    while True:
        print(f"  → Page {page_num}: {current_url}")

        if not safe_get(driver, current_url, wait_after=8):
            print("  ✗ Could not load category page, skipping.")
            break

        products = driver.find_elements(
            By.CSS_SELECTOR,
            "ul.products li.product a.woocommerce-LoopProduct-link"
        )
        page_links = [p.get_attribute("href") for p in products if p.get_attribute("href")]
        all_links.extend(page_links)
        print(f"     Found {len(page_links)} products on page {page_num}")

        try:
            next_btn = driver.find_element(By.CSS_SELECTOR, "a.next.page-numbers")
            next_url = next_btn.get_attribute("href")
            if not next_url or next_url == current_url:
                break
            current_url = next_url
            page_num += 1
        except Exception:
            break

    # Deduplicate
    seen, unique_links = set(), []
    for link in all_links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)

    print(f"  ✓ Total unique products in category: {len(unique_links)}")
    return unique_links


# ─────────────────────────────
# DRIVER START
# ─────────────────────────────

driver = create_driver()
wait   = WebDriverWait(driver, 10)

print("Opening marketplace...")
safe_get(driver, TARGET_URL, wait_after=15)


# ─────────────────────────────
# GET CATEGORIES
# ─────────────────────────────

categories     = driver.find_elements(By.CSS_SELECTOR, "ul.product-categories li a")
category_links = []

for cat in categories:
    name = cat.text.strip()
    link = cat.get_attribute("href")
    if not name:
        continue
    print("Category:", name)
    category_obj, _ = BlackMarketCategory.objects.get_or_create(name=name, url=link)
    category_links.append((category_obj, link))


# ─────────────────────────────
# SCRAPE EACH CATEGORY
# ─────────────────────────────

for category_obj, link in category_links:

    print(f"\n{'='*55}")
    print(f"Visiting category: {category_obj.name}")
    print(f"{'='*55}")

    product_links = get_all_product_links(driver, link)

    for idx, product_url in enumerate(product_links, 1):

        # ── RESUME: skip already-saved products ──────────────────────  ← NEW
        if BlackMarketProduct.objects.filter(url=product_url).exists():
            print(f"[{idx}/{len(product_links)}] ↷ Already saved, skipping: {product_url}")
            continue

        print(f"\n[{idx}/{len(product_links)}] Opening: {product_url}")

        # ── Load page with retry ──────────────────────────────────────
        if not safe_get(driver, product_url, wait_after=6):
            print("  ✗ Skipping this product due to repeated connection failures.")
            continue

        # ── Basic fields ──────────────────────────────────────────────

        def safe_text(selector):
            try:
                return driver.find_element(By.CSS_SELECTOR, selector).text.strip()
            except:
                return ""

        title         = safe_text("h1.post-title")
        price         = safe_text("p.price")
        btc_price     = safe_text("#price-BTC")
        shipping      = safe_text("dl.compact")
        vendor        = safe_text(".wcfm_dashboard_item_title")
        vendor_rating = safe_text(".wcfmmp-store-rating strong.rating")
        shipping_time = safe_text(".wcfmmp_shipment_processing_display")

        # ── Image ─────────────────────────────────────────────────────
        try:
            image = driver.find_element(By.CSS_SELECTOR, "img.wp-post-image").get_attribute("src")
        except:
            image = ""
        image_path = download_image(image)

        # ── Description tab ───────────────────────────────────────────
        description = ""
        try:
            desc_panel = driver.find_element(By.CSS_SELECTOR, "#tab-description")
            if desc_panel.get_attribute("style") and "display: none" in desc_panel.get_attribute("style"):
                driver.execute_script(
                    "arguments[0].click();",
                    driver.find_element(By.CSS_SELECTOR, "#tab-title-description a")
                )
                time.sleep(1)
            description = desc_panel.text.strip()
        except Exception as e:
            print("  Description error:", e)

        # ── More Offers tab ───────────────────────────────────────────
        more_offers = get_tab_content(
            driver,
            tab_link_selector="#tab-title-wcfm_product_multivendor_tab a",
            panel_selector="#tab-wcfm_product_multivendor_tab",
            wait=wait
        )

        # ── Store Policies tab ────────────────────────────────────────
        store_policies = get_tab_content(
            driver,
            tab_link_selector="#tab-title-wcfm_policies_tab a",
            panel_selector="#tab-wcfm_policies_tab",
            wait=wait
        )

        # ── Inquiries tab ─────────────────────────────────────────────
        inquiries = get_tab_content(
            driver,
            tab_link_selector="#tab-title-wcfm_enquiry_tab a",
            panel_selector="#tab-wcfm_enquiry_tab",
            wait=wait
        )

        # ── Save to DB ────────────────────────────────────────────────
        obj, created = BlackMarketProduct.objects.get_or_create(
            url=product_url,
            defaults={
                "category":       category_obj,
                "title":          title,
                "price":          price,
                "btc_price":      btc_price,
                "vendor":         vendor,
                "vendor_rating":  vendor_rating,
                "shipping":       shipping,
                "shipping_time":  shipping_time,
                "description":    description,
                "more_offers":    more_offers,
                "store_policies": store_policies,
                "inquiries":      inquiries,
                "image_path":     image_path,
            }
        )

        print("  ✓ Saved:" if created else "  ↷ Duplicate skipped:", title)

driver.quit()
print("\nScraping finished.")