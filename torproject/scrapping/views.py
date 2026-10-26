"""
report/views_scrape.py

URLs to register in your scrapping/urls.py:
    from .views_scrape import scrape_ahmia_view, scrape_ahmia_run, scrape_ahmia_stream, scrape_ahmia_save

    path('scrape/',        scrape_ahmia_view,   name='scrape_ahmia_view'),
    path('scrape/run/',    scrape_ahmia_run,    name='scrape_ahmia_run'),
    path('scrape/stream/', scrape_ahmia_stream, name='scrape_ahmia_stream'),
    path('scrape/save/',   scrape_ahmia_save,   name='scrape_ahmia_save'),

Requirements (pip install):
    selenium  beautifulsoup4  requests  psycopg2-binary

Tor must be running at 127.0.0.1:9150 (SOCKS5).
Firefox + geckodriver must be installed.
"""

import json
import queue
import socket
import threading
import time
import urllib.parse
import os

import requests as req_lib
from bs4 import BeautifulSoup

from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from masters.models import Keyword, UserKeyword
from report.models import DarkwebArticle, DarkwebBlock, DarkwebImage

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
AHMIA_URL    = "https://ahmia.fi/"
SOCKS_HOST   = "127.0.0.1"
SOCKS_PORT   = 9150

FIREFOX_BINARY = "/home/bisagn/Downloads/tor-browser/Browser/firefox"
GECKODRIVER    = "/snap/bin/geckodriver"

DJANGO_PROJECT_DIR = "/media/bisagn/data/TOR/torproject"
IMAGE_BASE_FOLDER  = os.path.join(DJANGO_PROJECT_DIR, "static", "darkweb_images")

TOP_N_DEFAULT = 10
PAGE_TIMEOUT  = 60

PROXIES = {
    "http":  f"socks5h://{SOCKS_HOST}:{SOCKS_PORT}",
    "https": f"socks5h://{SOCKS_HOST}:{SOCKS_PORT}",
}

# ─────────────────────────────────────────────────────────────────────────────
# In-memory stores
#   _progress_queues  : SSE event queues
#   _scraped_results  : scraped data waiting to be saved  { session_key: [...] }
# ─────────────────────────────────────────────────────────────────────────────
_progress_queues: dict[str, queue.Queue] = {}
_scraped_results: dict[str, list]        = {}   # ← new: pending save buffer
_progress_lock   = threading.Lock()


def _get_queue(session_key: str) -> queue.Queue:
    with _progress_lock:
        if session_key not in _progress_queues:
            _progress_queues[session_key] = queue.Queue(maxsize=500)
        return _progress_queues[session_key]


def _put(q: queue.Queue, event: str, data: dict):
    try:
        q.put_nowait({"event": event, "data": data})
    except queue.Full:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# SELENIUM HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _create_driver():
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service
    from selenium import webdriver

    options = Options()
    options.binary_location = FIREFOX_BINARY
    options.add_argument("--headless")
    options.set_preference("network.proxy.type", 1)
    options.set_preference("network.proxy.socks", SOCKS_HOST)
    options.set_preference("network.proxy.socks_port", SOCKS_PORT)
    options.set_preference("network.proxy.socks_remote_dns", True)
    options.set_preference("browser.tabs.warnOnClose", False)
    options.set_preference("browser.sessionstore.resume_from_crash", False)

    drv = webdriver.Firefox(service=Service(GECKODRIVER), options=options)
    drv.set_page_load_timeout(PAGE_TIMEOUT)
    return drv


def _safe_get(driver, url, wait, retries=2) -> bool:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException

    for attempt in range(retries):
        try:
            driver.get(url)
            current = driver.current_url
            if "about:neterror" in current or "about:blank" in current:
                return False
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            return True
        except TimeoutException:
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            if attempt < retries - 1:
                time.sleep(2)
        except WebDriverException as e:
            msg = str(e)
            if "neterror" in msg or "onionServices" in msg:
                pass
            return False
    return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SCRAPER  — NO DB WRITES, only collects data + emits preview events
# ─────────────────────────────────────────────────────────────────────────────
def _run_scrape(session_key: str, keyword_name: str, color: str, top_n: int = TOP_N_DEFAULT):
    """
    Scrapes content into memory only.
    Emits SSE events so the frontend can show a live preview.
    Does NOT write anything to the database.

    Collected articles are stored in _scraped_results[session_key]
    so that scrape_ahmia_save() can persist them later.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException, WebDriverException, NoSuchElementException
    )

    q = _get_queue(session_key)

    # Reset the pending results buffer for this session
    with _progress_lock:
        _scraped_results[session_key] = []

    def emit(event, **kwargs):
        _put(q, event, kwargs)

    emit("status", msg="⏳ Waiting for Tor SOCKS proxy…")

    # 1. Wait for Tor
    for _ in range(30):
        try:
            socket.create_connection((SOCKS_HOST, SOCKS_PORT), 2).close()
            break
        except Exception:
            time.sleep(1)
    else:
        emit("error", msg="❌ Tor proxy not reachable at 127.0.0.1:9150. Start Tor Browser first.")
        emit("done", total=0, errors=0)
        return

    emit("status", msg="✅ Tor proxy reachable. Launching headless Firefox…")

    try:
        driver = _create_driver()
        wait   = WebDriverWait(driver, 40)
    except Exception as exc:
        emit("error", msg=f"❌ Could not start Firefox: {exc}")
        emit("done", total=0, errors=0)
        return

    emit("status", msg=f"🔍 Searching Ahmia for: «{keyword_name}»…")

    total_found = 0
    error_count = 0

    try:
        # 3. Open Ahmia
        if not _safe_get(driver, AHMIA_URL, wait):
            emit("error", msg="❌ Could not load ahmia.fi through Tor.")
            emit("done", total=0, errors=1)
            return

        # 4. Search
        try:
            wait.until(EC.presence_of_element_located((By.ID, "id_q")))
        except TimeoutException:
            emit("error", msg="❌ Ahmia search box not found.")
            emit("done", total=0, errors=1)
            return

        search_box = driver.find_element(By.ID, "id_q")
        search_box.clear()
        search_box.send_keys(keyword_name)
        search_box.send_keys(Keys.RETURN)

        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ol.searchResults")))
        except TimeoutException:
            emit("warning", msg=f"⚠️ No results for «{keyword_name}».")
            emit("done", total=0, errors=0)
            return

        results     = driver.find_elements(By.CSS_SELECTOR, "ol.searchResults li.result")
        onion_links = []

        emit("status", msg=f"📋 Found {len(results)} search results — will scrape top {top_n}…")

        for li in results[:top_n]:
            try:
                a        = li.find_element(By.CSS_SELECTOR, "h4 a")
                redirect = a.get_attribute("href")
                qs       = urllib.parse.parse_qs(urllib.parse.urlparse(redirect).query)
                onion    = qs.get("redirect_url", [None])[0]
                if onion:
                    onion_links.append((a.text.strip(), onion))
            except (NoSuchElementException, Exception):
                continue

        emit("status", msg=f"🧅 Extracted {len(onion_links)} onion links — scraping content (preview only)…")

        # 5. Loop over onion links — collect into memory, no DB writes
        for idx, (title, onion) in enumerate(onion_links, 1):
            # Progress: only reaches ~90% here; 100% fires on 'done'
            pct_raw = int((idx / len(onion_links)) * 90)
            emit("progress", current=idx, total=len(onion_links),
                 pct=pct_raw, title=title or onion, url=onion)

            try:
                # Check for duplicate URL without saving
                already_exists = DarkwebArticle.objects.filter(url=onion).exists()
                if already_exists:
                    emit("skip", url=onion, title=title or onion)
                    continue

                # Load onion site
                if not _safe_get(driver, onion, wait):
                    emit("warning", msg=f"⚠️ Could not load {onion}")
                    error_count += 1
                    continue

                html = driver.page_source
                soup = BeautifulSoup(html, "html.parser")

                for tag in soup.find_all(["header", "footer", "nav", "aside", "script", "style"]):
                    tag.decompose()

                main = soup.find("main") or soup.find("article") or soup.body
                if not main:
                    emit("warning", msg=f"⚠️ No main content found for {onion}")
                    error_count += 1
                    continue

                # Collect blocks in memory
                blocks         = []
                image_srcs     = []

                for element in main.find_all(["h1", "h2", "h3", "h4", "p", "img"], recursive=True):
                    if element.name in ["h1", "h2", "h3", "h4"]:
                        text = element.get_text(strip=True)
                        if text:
                            blocks.append({"type": "heading", "text": text})

                    elif element.name == "p":
                        text = element.get_text(strip=True)
                        if text:
                            blocks.append({"type": "text", "text": text})

                    elif element.name == "img":
                        src = element.get("src")
                        if src:
                            image_srcs.append(src)
                            blocks.append({"type": "image", "src": src})

                # Derive a short summary (first <p> text, up to 200 chars)
                summary = next(
                    (b["text"][:200] for b in blocks if b["type"] == "text"),
                    ""
                )

                article_data = {
                    "title":      title or "Untitled",
                    "url":        onion,
                    "keyword":    keyword_name,
                    "color":      color,
                    "summary":    summary,
                    "blocks":     blocks,
                    "image_srcs": image_srcs,
                }

                with _progress_lock:
                    _scraped_results[session_key].append(article_data)

                total_found += 1

                # Emit preview event so frontend can render the card immediately
                emit("preview", **{
                    "idx":     total_found,
                    "title":   article_data["title"],
                    "url":     article_data["url"],
                    "summary": article_data["summary"],
                    "blocks":  len(blocks),
                    "images":  len(image_srcs),
                })

            except Exception as exc:
                error_count += 1
                emit("warning", msg=f"⚠️ Error on {onion}: {str(exc)[:120]}")
                # Restart driver if dead
                try:
                    driver.current_url
                except WebDriverException:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    try:
                        driver = _create_driver()
                        wait   = WebDriverWait(driver, 40)
                    except Exception:
                        pass

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # 'done' = 100% on the progress bar
    emit("done", total=total_found, errors=error_count, session_key=session_key)


# ─────────────────────────────────────────────────────────────────────────────
# SAVE ENDPOINT  — called by frontend after user clicks "Save to DB"
# ─────────────────────────────────────────────────────────────────────────────
@login_required
@require_POST
def scrape_ahmia_save(request):
    """
    POST { session_key: str, selected_indices: [0,1,2,...] | "all" }

    Persists the scraped articles (held in _scraped_results) to the DB.
    Returns { ok, saved, skipped, errors, article_ids }
    """
    try:
        body       = json.loads(request.body)
        session_key = body.get("session_key", "")
        selection   = body.get("selected_indices", "all")
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    with _progress_lock:
        pending = _scraped_results.get(session_key, [])

    if not pending:
        return JsonResponse({"ok": False, "error": "No scraped data found for this session. Please scrape first."}, status=400)

    # Determine which articles to save
    if selection == "all":
        to_save = list(pending)
    else:
        try:
            indices = [int(i) for i in selection]
            to_save = [pending[i] for i in indices if 0 <= i < len(pending)]
        except Exception:
            return JsonResponse({"ok": False, "error": "Invalid selected_indices"}, status=400)

    saved      = 0
    skipped    = 0
    errors     = 0
    article_ids = []

    safe_keyword_cache = {}   # keyword_name → folder path

    for article_data in to_save:
        keyword_name = article_data["keyword"]
        color        = article_data["color"]
        title        = article_data["title"]
        url          = article_data["url"]
        blocks       = article_data["blocks"]

        try:
            from django.db import transaction

            with transaction.atomic():
                art, created = DarkwebArticle.objects.get_or_create(
                    url=url,
                    defaults={"keyword": keyword_name, "title": title},
                )

            if not created:
                skipped += 1
                continue

            article_id = art.pk
            article_ids.append(article_id)

            # Prepare image folder
            safe_keyword = keyword_name.replace(" ", "_").lower()
            if safe_keyword not in safe_keyword_cache:
                kw_folder = os.path.join(IMAGE_BASE_FOLDER, safe_keyword)
                os.makedirs(kw_folder, exist_ok=True)
                safe_keyword_cache[safe_keyword] = kw_folder

            article_folder = os.path.join(safe_keyword_cache[safe_keyword], f"article_{article_id}")
            os.makedirs(article_folder, exist_ok=True)

            block_order   = 1
            image_counter = 1

            for block in blocks:
                if block["type"] == "heading":
                    DarkwebBlock.objects.create(
                        article=art,
                        block_order=block_order,
                        block_type="heading",
                        text_content=block["text"],
                    )
                    block_order += 1

                elif block["type"] == "text":
                    DarkwebBlock.objects.create(
                        article=art,
                        block_order=block_order,
                        block_type="text",
                        text_content=block["text"],
                    )
                    block_order += 1

                elif block["type"] == "image":
                    src = block.get("src")
                    if not src:
                        continue
                    try:
                        r = req_lib.get(src, proxies=PROXIES, timeout=20)
                        if r.status_code == 200 and len(r.content) > 2000:
                            ctype = r.headers.get("Content-Type", "")
                            ext   = ".png" if "png" in ctype else ".jpg"
                            fname = f"img_{image_counter}{ext}"
                            fpath = os.path.join(article_folder, fname)

                            with open(fpath, "wb") as f:
                                f.write(r.content)

                            static_rel = os.path.relpath(
                                fpath, os.path.join(DJANGO_PROJECT_DIR, "static")
                            )

                            img_obj = DarkwebImage.objects.create(
                                article=art,
                                image_path=static_rel,
                                image_type=ctype,
                                original_src=src,
                            )

                            DarkwebBlock.objects.create(
                                article=art,
                                block_order=block_order,
                                block_type="image",
                                image=img_obj,
                            )
                            block_order   += 1
                            image_counter += 1
                    except Exception:
                        pass

            saved += 1

        except Exception as exc:
            errors += 1

    # Upsert keyword & assign to user
    try:
        from django.contrib.auth.models import User
        user = User.objects.get(pk=request.user.pk)

        for article_data in to_save:
            kn = article_data["keyword"]
            cl = article_data["color"]
            kw_obj, _ = Keyword.objects.get_or_create(
                name=kn,
                defaults={"color": cl, "created_by": user},
            )
            UserKeyword.objects.get_or_create(
                user=user,
                keyword=kw_obj,
                defaults={"assigned_by": user},
            )
    except Exception:
        pass

    # Clean up pending buffer
    with _progress_lock:
        _scraped_results.pop(session_key, None)

    return JsonResponse({
        "ok":          True,
        "saved":       saved,
        "skipped":     skipped,
        "errors":      errors,
        "article_ids": article_ids,
    })


# ─────────────────────────────────────────────────────────────────────────────
# VIEWS
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def scrape_ahmia_view(request):
    import subprocess

    def _tor_already_running():
        try:
            socket.create_connection((SOCKS_HOST, SOCKS_PORT), timeout=1).close()
            return True
        except OSError:
            return False

    if not _tor_already_running():
        subprocess.Popen([
            "bash", "-c",
            "cd ~/Downloads/tor-browser && ./start-tor-browser.desktop"
        ])

    return render(request, "scrapping/scrapping_ahmia.html", {
        "generated_at": timezone.now(),
    })


@login_required
@require_POST
def scrape_ahmia_run(request):
    """
    POST { keyword, color, top_n }
    Kicks off background scrape (preview only, no DB writes).
    Returns session_key for SSE stream.
    """
    body    = json.loads(request.body)
    keyword = body.get("keyword", "").strip()
    color   = body.get("color", "#2563eb").strip() or "#2563eb"
    top_n   = int(body.get("top_n", TOP_N_DEFAULT))
    top_n   = max(1, min(top_n, 50))
    if not keyword:
        return JsonResponse({"ok": False, "error": "Keyword is required."}, status=400)

    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key

    with _progress_lock:
        _progress_queues[session_key] = queue.Queue(maxsize=500)
        _scraped_results[session_key] = []

    t = threading.Thread(
        target=_run_scrape,
        args=(session_key, keyword, color, top_n),
        daemon=True,
    )
    t.start()

    return JsonResponse({"ok": True, "session_key": session_key})


@login_required
def scrape_ahmia_stream(request):
    """
    SSE endpoint.  GET /scrape/stream/?sk=<session_key>
    """
    session_key = request.GET.get("sk") or request.session.session_key
    q = _get_queue(session_key)

    def event_stream():
        while True:
            try:
                item = q.get(timeout=60)
            except queue.Empty:
                yield 'data: {"event":"heartbeat"}\n\n'
                continue

            yield f"data: {json.dumps(item)}\n\n"

            if item.get("event") == "done":
                with _progress_lock:
                    _progress_queues.pop(session_key, None)
                break

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"]     = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response