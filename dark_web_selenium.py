#!/usr/bin/env python3

import socket
import time
import urllib.parse
import os
import psycopg2
import requests
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, WebDriverException, NoSuchElementException
)

# ───────── CONFIG ─────────
URL = "https://ahmia.fi/"
SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 9150

FIREFOX_BINARY = "/home/bisagn/Downloads/tor-browser/Browser/firefox"
GECKODRIVER = "/snap/bin/geckodriver"

TOP_N = 10
PAGE_TIMEOUT = 60

# ── CHANGED: save images inside Django static folder ──
# This must match your Django project's static directory
DJANGO_PROJECT_DIR = "/media/bisagn/data/TOR/torproject"   # ← your project root
IMAGE_BASE_FOLDER  = os.path.join(DJANGO_PROJECT_DIR, "static", "darkweb_images")

# PostgreSQL
DB_NAME = "tordb"
DB_USER = "postgres"
DB_PASS = "postgres"
DB_HOST = "localhost"
DB_PORT = "5432"

# ───────── DB CONNECT ─────────
conn = psycopg2.connect(
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASS,
    host=DB_HOST,
    port=DB_PORT
)
cur = conn.cursor()

# ───────── CREATE TABLES IF NOT EXISTS ─────────
# ── CHANGED: UNIQUE constraint is now (url, keyword) instead of just url ──
# Same site scraped for a different keyword = allowed (new record)
# Same site scraped for the same keyword    = duplicate (skipped)
cur.execute("""
CREATE TABLE IF NOT EXISTS darkweb_articles (
    id SERIAL PRIMARY KEY,
    keyword TEXT,
    title TEXT,
    url TEXT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(url, keyword)
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS darkweb_images (
    id SERIAL PRIMARY KEY,
    article_id INTEGER REFERENCES darkweb_articles(id) ON DELETE CASCADE,
    image_path TEXT,
    image_type TEXT,
    original_src TEXT
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS darkweb_blocks (
    id SERIAL PRIMARY KEY,
    article_id INTEGER REFERENCES darkweb_articles(id) ON DELETE CASCADE,
    block_order INTEGER,
    block_type TEXT,
    text_content TEXT,
    image_id INTEGER
);
""")

conn.commit()

# ───────── FETCH KEYWORDS ─────────
cur.execute("SELECT name FROM masters_keyword ORDER BY id;")
keywords = [row[0] for row in cur.fetchall()]

if not keywords:
    print("[!] No keywords found.")
    exit()

os.makedirs(IMAGE_BASE_FOLDER, exist_ok=True)

# ───────── WAIT FOR TOR ─────────
print("[+] Waiting for Tor...")
while True:
    try:
        socket.create_connection((SOCKS_HOST, SOCKS_PORT), 2).close()
        break
    except:
        time.sleep(1)

# ───────── FIREFOX SETUP ─────────
def create_driver():
    options = Options()
    options.binary_location = FIREFOX_BINARY
    options.set_preference("network.proxy.type", 1)
    options.set_preference("network.proxy.socks", SOCKS_HOST)
    options.set_preference("network.proxy.socks_port", SOCKS_PORT)
    options.set_preference("network.proxy.socks_remote_dns", True)
    options.set_preference("browser.tabs.warnOnClose", False)
    options.set_preference("browser.sessionstore.resume_from_crash", False)
    drv = webdriver.Firefox(service=Service(GECKODRIVER), options=options)
    drv.set_page_load_timeout(PAGE_TIMEOUT)
    return drv


def safe_get(driver, url, wait, retries=2):
    for attempt in range(retries):
        try:
            driver.get(url)
            current = driver.current_url
            if "about:neterror" in current or "about:blank" in current:
                print(f"  [!] Error page reached: {current}")
                return False
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            return True
        except TimeoutException:
            print(f"  [!] Timeout on attempt {attempt+1} for {url}")
            try:
                driver.execute_script("window.stop();")
            except:
                pass
            if attempt < retries - 1:
                time.sleep(2)
        except WebDriverException as e:
            msg = str(e)
            if "neterror" in msg or "onionServices" in msg:
                print(f"  [!] Onion service error: {url}")
            else:
                print(f"  [!] WebDriver error: {msg[:120]}")
            return False
    return False


proxies = {
    "http": f"socks5h://{SOCKS_HOST}:{SOCKS_PORT}",
    "https": f"socks5h://{SOCKS_HOST}:{SOCKS_PORT}"
}

driver = create_driver()
wait = WebDriverWait(driver, 40)

# ───────── MAIN LOOP ─────────
for keyword in keywords:

    print(f"\n========== Searching: {keyword} ==========")

    safe_keyword = keyword.replace(" ", "_").lower()
    keyword_folder = os.path.join(IMAGE_BASE_FOLDER, safe_keyword)
    os.makedirs(keyword_folder, exist_ok=True)

    try:
        if not safe_get(driver, URL, wait):
            print(f"  [!] Could not load Ahmia for keyword: {keyword}, skipping.")
            continue

        try:
            wait.until(EC.presence_of_element_located((By.ID, "id_q")))
        except TimeoutException:
            print(f"  [!] Ahmia search box not found, skipping keyword: {keyword}")
            continue

        search_box = driver.find_element(By.ID, "id_q")
        search_box.clear()
        search_box.send_keys(keyword)
        search_box.send_keys(Keys.RETURN)

        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ol.searchResults")))
        except TimeoutException:
            print(f"  [!] No results loaded for: {keyword}")
            continue

        results = driver.find_elements(By.CSS_SELECTOR, "ol.searchResults li.result")

        onion_links = []
        for li in results[:TOP_N]:
            try:
                a = li.find_element(By.CSS_SELECTOR, "h4 a")
                redirect = a.get_attribute("href")
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(redirect).query)
                onion = qs.get("redirect_url", [None])[0]
                if onion:
                    onion_links.append((a.text.strip(), onion))
            except (NoSuchElementException, Exception):
                continue

        for title, onion in onion_links:
            try:
                # ── CHANGED: ON CONFLICT checks (url, keyword) pair ──
                # Same URL + different keyword → new row inserted (scraped again)
                # Same URL + same keyword      → conflict → skipped as duplicate
                cur.execute("""
                    INSERT INTO darkweb_articles (keyword, title, url)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (url, keyword) DO NOTHING
                    RETURNING id;
                """, (keyword, title, onion))

                result = cur.fetchone()
                if not result:
                    conn.commit()
                    print("  [!] Duplicate skipped (same site + same keyword)")
                    continue

                article_id = result[0]
                print(f"  [+] New article saved ID: {article_id}")

                article_folder = os.path.join(keyword_folder, f"article_{article_id}")
                os.makedirs(article_folder, exist_ok=True)

                if not safe_get(driver, onion, wait):
                    print(f"  [!] Could not load onion: {onion}")
                    conn.commit()
                    continue

                html = driver.page_source
                soup = BeautifulSoup(html, "html.parser")

                for tag in soup.find_all(["header", "footer", "nav", "aside", "script", "style"]):
                    tag.decompose()

                main = soup.find("main") or soup.find("article") or soup.body
                if not main:
                    conn.commit()
                    continue

                block_order = 1
                image_counter = 1

                for element in main.find_all(["h1", "h2", "h3", "h4", "p", "img"], recursive=True):

                    if element.name in ["h1", "h2", "h3", "h4"]:
                        text = element.get_text(strip=True)
                        if text:
                            cur.execute("""
                                INSERT INTO darkweb_blocks
                                (article_id, block_order, block_type, text_content)
                                VALUES (%s, %s, %s, %s)
                            """, (article_id, block_order, "heading", text))
                            block_order += 1

                    elif element.name == "p":
                        text = element.get_text(strip=True)
                        if text:
                            cur.execute("""
                                INSERT INTO darkweb_blocks
                                (article_id, block_order, block_type, text_content)
                                VALUES (%s, %s, %s, %s)
                            """, (article_id, block_order, "text", text))
                            block_order += 1

                    elif element.name == "img":
                        src = element.get("src")
                        if not src:
                            continue
                        try:
                            r = requests.get(src, proxies=proxies, timeout=20)
                            if r.status_code == 200 and len(r.content) > 2000:
                                ext = ".png" if "png" in r.headers.get("Content-Type", "") else ".jpg"
                                filename = f"img_{image_counter}{ext}"
                                filepath = os.path.join(article_folder, filename)

                                with open(filepath, "wb") as f:
                                    f.write(r.content)

                                # ── CHANGED: store STATIC-relative path ──
                                # e.g. "darkweb_images/india/article_1/img_1.jpg"
                                static_relative = os.path.relpath(filepath, os.path.join(DJANGO_PROJECT_DIR, "static"))

                                cur.execute("""
                                    INSERT INTO darkweb_images
                                    (article_id, image_path, image_type, original_src)
                                    VALUES (%s, %s, %s, %s)
                                    RETURNING id;
                                """, (
                                    article_id,
                                    static_relative,          # ← relative path stored
                                    r.headers.get("Content-Type", "unknown"),
                                    src
                                ))

                                image_id = cur.fetchone()[0]

                                cur.execute("""
                                    INSERT INTO darkweb_blocks
                                    (article_id, block_order, block_type, image_id)
                                    VALUES (%s, %s, %s, %s)
                                """, (article_id, block_order, "image", image_id))

                                block_order += 1
                                image_counter += 1

                        except Exception:
                            continue

                conn.commit()

            except Exception as e:
                print(f"  [!] Article error: {str(e)[:120]}")
                try:
                    conn.rollback()
                except:
                    pass
                try:
                    driver.current_url
                except WebDriverException:
                    print("  [!] Driver died — restarting browser...")
                    try:
                        driver.quit()
                    except:
                        pass
                    driver = create_driver()
                    wait = WebDriverWait(driver, 40)
                continue

    except Exception as e:
        print(f"[!!] Keyword-level error for '{keyword}': {str(e)[:200]}")
        try:
            driver.current_url
        except WebDriverException:
            print("[!!] Driver died — restarting browser...")
            try:
                driver.quit()
            except:
                pass
            driver = create_driver()
            wait = WebDriverWait(driver, 40)
        continue

driver.quit()
cur.close()
conn.close()

print("\n[+] Done.")