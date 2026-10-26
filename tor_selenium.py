#!/usr/bin/env python3

import socket, time, urllib.parse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.common.exceptions import TimeoutException

SEARCH_QUERY = "india"
URL = "https://ahmia.fi/"
SOCKS_HOST = "127.0.0.1"
SOCKS_PORT = 9150

FIREFOX_BINARY = "/home/bisagn/Downloads/tor-browser/Browser/firefox"
GECKODRIVER = "/snap/bin/geckodriver"

TOP_N = 5
PAGE_TIMEOUT = 35

# ───────── WAIT FOR TOR ─────────
print("[+] Waiting for Tor...")
while True:
    try:
        socket.create_connection((SOCKS_HOST, SOCKS_PORT), 2).close()
        break
    except:
        time.sleep(1)

# ───────── FIREFOX ─────────
options = Options()
options.binary_location = FIREFOX_BINARY
options.set_preference("network.proxy.type", 1)
options.set_preference("network.proxy.socks", SOCKS_HOST)
options.set_preference("network.proxy.socks_port", SOCKS_PORT)
options.set_preference("network.proxy.socks_remote_dns", True)

driver = webdriver.Firefox(service=Service(GECKODRIVER), options=options)
driver.set_page_load_timeout(PAGE_TIMEOUT)

# ───────── SEARCH ─────────
driver.get(URL)
time.sleep(5)

box = driver.find_element(By.ID, "id_q")
box.send_keys(SEARCH_QUERY)
box.send_keys(Keys.RETURN)
time.sleep(20)

# ───────── COLLECT LINKS ─────────
results = driver.find_elements(By.CSS_SELECTOR, "ol.searchResults li.result")
targets = []

for li in results[:TOP_N]:
    a = li.find_element(By.CSS_SELECTOR, "h4 a")
    redirect = a.get_attribute("href")

    qs = urllib.parse.parse_qs(urllib.parse.urlparse(redirect).query)
    onion = qs.get("redirect_url", [None])[0]

    if onion:
        targets.append({
            "title": a.text.strip(),
            "onion": onion
        })

# ───────── EXTRACTOR ─────────
def extract_main_text():
    return driver.execute_script("""
        let best="";
        document.querySelectorAll("article,main,section,div").forEach(e=>{
            let t=e.innerText||"";
            if(t.length>best.length) best=t;
        });
        return best || document.body.innerText;
    """)

# ───────── PROCESS ONE BY ONE (SAME TAB) ─────────
for i, t in enumerate(targets, 1):
    print("\n" + "="*70)
    print(f"[+] {i}. {t['title']}")
    print(f"[+] {t['onion']}")
    print("="*70)

    try:
        start = time.time()
        driver.get(t["onion"])

        while time.time() - start < PAGE_TIMEOUT:
            try:
                if driver.execute_script("return document.readyState") == "complete":
                    break
            except:
                pass
            time.sleep(1)

        driver.execute_script("window.stop();")
        time.sleep(2)

        text = extract_main_text()
        text = "\n".join(l for l in text.splitlines() if len(l.strip()) > 40)

        print("\n----- MAIN CONTENT -----\n")
        print(text[:4000])
        print("\n------------------------\n")

    except TimeoutException:
        print("[!] Timeout – skipping")

    except Exception as e:
        print(f"[!] Error: {e}")

    # 🔙 BACK TO RESULTS PAGE (THIS IS THE KEY)
    driver.back()
    time.sleep(6)

driver.quit()
print("\n[+] Done.")