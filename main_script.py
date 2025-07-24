import requests
import json
import logging
import os
from bs4 import BeautifulSoup
from stem import Signal
from stem.control import Controller
from stem.process import launch_tor_with_config
import time
from urllib.parse import urlparse, parse_qs
import concurrent.futures

# Base directory relative to this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_FILES_DIR = os.path.join(BASE_DIR, 'test_files')

# Ensure the directory exists
os.makedirs(TEST_FILES_DIR, exist_ok=True)

# File paths
KEYWORDS_FILE = os.path.join(TEST_FILES_DIR, 'keywords.txt')
RESULTS_FILE = os.path.join(TEST_FILES_DIR, 'searched_links.json')
LOG_FILE = os.path.join(TEST_FILES_DIR, 'main.log')
# Additional log file for skips and reasons
SKIP_LOG_FILE = os.path.join(TEST_FILES_DIR, 'skipped_links.log')

# Ensure files exist
open(KEYWORDS_FILE, 'a').close()
open(RESULTS_FILE, 'a').close()
open(LOG_FILE, 'a').close()
open(SKIP_LOG_FILE, 'a').close() # Ensure skip log exists

# Configure logging
logging.basicConfig(filename=LOG_FILE, level=logging.ERROR, 
                    format='%(asctime)s %(levelname)s:%(message)s')

if os.path.getsize(KEYWORDS_FILE) == 0:  # Only write if empty
    with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
        f.write("bitcoin market\n")
        f.write("hacking forums\n")
        f.write("dark web search\n")



# Configure logging
logging.basicConfig(filename=LOG_FILE, level=logging.ERROR, 
                    format='%(asctime)s %(levelname)s:%(message)s')

# Tor proxy settings
PROXIES = {
    'http':  'socks5h://127.0.0.1:9050',
    'https': 'socks5h://127.0.0.1:9050'
}

SEARCH_ENGINES = [
    {
        'name': 'Ahmia',
        'url': 'http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/search/?q={}',
        'parser': 'parse_ahmia'
    }
]


def parse_ahmia(html):
    from urllib.parse import urlparse, parse_qs
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    for res in soup.select('li.result'):
        a = res.select_one('h4 > a')
        title = a.get_text(strip=True) if a else ''
        link = ''
        if a and a.has_attr('href'):
            parsed = urlparse(a['href'])
            qs = parse_qs(parsed.query)
            link = qs.get('redirect_url', [''])[0]
        heading = res.select_one('p').get_text(strip=True) if res.select_one('p') else ''
        results.append({'title': title, 'heading': heading, 'link': link})
        if len(results) >= 5:
            break
    return results

def parse_torch(html):
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    for res in soup.select('div.wrap > div.web-result'):
        a = res.select_one('a')
        title = a.get_text(strip=True) if a else ''
        link = a['href'] if a else ''
        heading = res.select_one('div.desc').get_text(strip=True) if res.select_one('div.desc') else ''
        results.append({'title': title, 'heading': heading, 'link': link})
    return results

def parse_haystack(html):
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    for res in soup.select('div.result'):
        a = res.select_one('a')
        title = a.get_text(strip=True) if a else ''
        link = a['href'] if a else ''
        heading = res.select_one('div.caption').get_text(strip=True) if res.select_one('div.caption') else ''
        results.append({'title': title, 'heading': heading, 'link': link})
    return results

def parse_duckduckgo(html):
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    for res in soup.select('a.result__a'):
        title = res.get_text(strip=True)
        link = res['href']
        heading = ''
        results.append({'title': title, 'heading': heading, 'link': link})
    return results

def search_engine(engine, keyword, session):
    url = engine['url'].format(requests.utils.quote(keyword))
    print(f"Searching '{keyword}' on {engine['name']}... URL: {url}")
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        parser = globals()[engine['parser']]
        results = parser(resp.text)
        for r in results:
            r['engine'] = engine['name']
        print(f"  Found {len(results)} results on {engine['name']} for '{keyword}'.")
        return results  # Already limited to 5 in parser
    except Exception as e:
        logging.error(f"Error searching {engine['name']} for '{keyword}': {e}")
        print(f"  Error searching {engine['name']} for '{keyword}': {e}")
        return []

def get_current_ip(session):
    try:
        r = session.get('http://check.torproject.org/', timeout=20)
        soup = BeautifulSoup(r.text, 'html.parser')
        ip_tag = soup.find('strong')
        if ip_tag:
            return ip_tag.text.strip()
        return 'Unknown'
    except Exception as e:
        print(f"Could not get current IP: {e}")
        return 'Error'

def read_keywords():
    try:
        with open(KEYWORDS_FILE, 'r', encoding='utf-8') as f:
            keywords = [line.strip() for line in f if line.strip()]
        print(f"Loaded {len(keywords)} keywords.")
        return keywords
    except Exception as e:
        logging.error(f"Error reading keywords: {e}")
        print(f"Error reading keywords: {e}")
        return []

# Add this helper function after the parse_* functions

# Browser-like headers
BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

def log_skip(msg):
    with open(SKIP_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(msg + '\n')

def is_valid_onion_url(url):
    # Accept any URL containing .onion (with or without path/query)
    return '.onion' in url

def is_valid_content(text, title='', heading=''):
    text_lower = text.lower()
    error_phrases = [
        '404 not found', 'not found', 'error', 'page not found', 'does not exist', 'not available', 'forbidden', 'unavailable', 'bad gateway', '502', '503', '504', 'nginx', 'cloudflare', 'tor browser', 'problem loading page'
    ]
    if any(phrase in text_lower for phrase in error_phrases):
        return False
    if len(text.strip()) >= 20:
        return True
    if title or heading:
        return True
    return False

def try_fetch_url(url, session, title='', heading='', max_retries=1):
    last_exc = None
    for attempt in range(max_retries+1):
        try:
            resp = session.get(url, headers=BROWSER_HEADERS, timeout=10)
            status = resp.status_code
            content = resp.text
            log_msg = f"[{url}] HTTP {status} | First 200 chars: {content[:200].replace(chr(10),' ').replace(chr(13),' ')}"
            print(f"      {log_msg}")
            log_skip(log_msg)
            if status == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(content, 'html.parser')
                text = soup.get_text(separator='\n', strip=True)
                if is_valid_content(text, title, heading):
                    return True, text
                else:
                    log_skip(f"[SKIP] {url} - Content not valid after HTTP 200.")
            else:
                log_skip(f"[SKIP] {url} - HTTP status {status}.")
        except Exception as e:
            last_exc = e
            log_skip(f"[EXCEPTION] {url} - {e}")
    return False, None

def is_working_onion_link(url, session, title='', heading=''):
    # Accept any .onion URL
    if not url or not is_valid_onion_url(url):
        log_skip(f"[SKIP] {url} - Not a .onion link.")
        return False, None
    # Try as-is
    ok, text = try_fetch_url(url, session, title, heading)
    if ok:
        return True, text
    # If https, try http
    if url.startswith('https://'):
        http_url = 'http://' + url[len('https://'):]
        log_skip(f"[RETRY] {url} as {http_url}")
        ok, text = try_fetch_url(http_url, session, title, heading)
        if ok:
            return True, text
    return False, None

def main():
    # Assume Tor is already running externally
    print("\n==================== Connecting to Tor ====================")
    controller = Controller.from_port(address='127.0.0.1', port=9051)
    controller.authenticate()
    print("[✓] Connected to Tor!")

    # Request new identity at start
    controller.signal(Signal.NEWNYM)
    print("[✓] Requested new Tor identity (NEWNYM) at start.")
    time.sleep(3)

    keywords = read_keywords()
    if not keywords:
        print("[!] No keywords found. Exiting.")
        controller.close()
        return

    session = requests.session()
    session.proxies = PROXIES

    print("\n==================== Checking IP at Start ====================")
    ip_start = get_current_ip(session)
    print(f"[✓] Current Tor IP at start: {ip_start}")

    # Clear skip log at start
    open(SKIP_LOG_FILE, 'w').close()
    all_results = []
    seen_links = set()
    print("\n==================== Starting Search ====================")
    for keyword in keywords:
        print(f"\n--- Searching for: '{keyword}' ---")
        keyword_results = []
        seen_title_heading = set()  # Reset for each keyword
        for engine in SEARCH_ENGINES:
            print(f"  > Using search engine: {engine['name']}")
            results = search_engine(engine, keyword, session)
            def process_result(r):
                title_heading = (r['title'], r['heading'])
                link = r.get('link', '')
                if title_heading not in seen_title_heading and link and link not in seen_links:
                    print(f"    - Checking link: {link}")
                    working, page_content = is_working_onion_link(link, session, r.get('title',''), r.get('heading',''))
                    if working and page_content:
                        seen_title_heading.add(title_heading)
                        seen_links.add(link)
                        r['keyword'] = keyword  # Add keyword field
                        r['content'] = page_content     # Store the page text
                        print(f"      [✓] Link is working and content is valid. Added.")
                        return r
                    else:
                        print(f"      [✗] Link is not working or content not valid. Skipped.")
                return None
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_result = {executor.submit(process_result, r): r for r in results}
                for future in concurrent.futures.as_completed(future_to_result):
                    r = future.result()
                    if r:
                        all_results.append(r)
                        keyword_results.append(r)
                        if len(keyword_results) >= 5:
                            break
            if len(keyword_results) >= 5:
                break
    print(f"\n==================== Writing Results ====================")
    print(f"[i] Writing {len(all_results)} unique, working results with valid content to {RESULTS_FILE}...")
    try:
        with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False)
        print("[✓] Done writing results.")
    except Exception as e:
        logging.error(f"Error writing results: {e}")
        print(f"[!] Error writing results: {e}")

    # Request new identity before exit
    controller.signal(Signal.NEWNYM)
    print("\n[✓] Requested new Tor identity (NEWNYM) before exit.")
    time.sleep(3)
    print("\n==================== Checking IP at Exit ====================")
    ip_exit = get_current_ip(session)
    print(f"[✓] Current Tor IP at exit: {ip_exit}")

    controller.close()
    print("[✓] Tor control connection closed.")
    print("\n==================== Script Complete ====================\n")

if __name__ == '__main__':
    main()
