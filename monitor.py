import os
import time
import json
import hashlib
import logging
import requests
from bs4 import BeautifulSoup
from stem.control import Controller
from stem import Signal

# Directories and files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_FILES_DIR = os.path.join(BASE_DIR, 'test_files')
MONITOR_LINKS_FILE = os.path.join(TEST_FILES_DIR, 'monitor_links.txt')
HASHES_FILE = os.path.join(TEST_FILES_DIR, 'monitor_hashes.json')
LOG_FILE = os.path.join(TEST_FILES_DIR, 'monitor.log')

# Ensure files exist
os.makedirs(TEST_FILES_DIR, exist_ok=True)
open(MONITOR_LINKS_FILE, 'a').close()
open(HASHES_FILE, 'a').close()
open(LOG_FILE, 'a').close()

# Logging
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, 
                    format='%(asctime)s %(levelname)s:%(message)s')

# Tor proxy
PROXIES = {
    'http':  'socks5h://127.0.0.1:9050',
    'https': 'socks5h://127.0.0.1:9050'
}

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

def is_valid_onion_url(url):
    return '.onion' in url

def fetch_onion_content(url, session):
    try:
        resp = session.get(url, headers=BROWSER_HEADERS, timeout=30)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            text = soup.get_text(separator='\n', strip=True)
            return text
        else:
            logging.warning(f"Non-200 status for {url}: {resp.status_code}")
            return None
    except Exception as e:
        logging.error(f"Error fetching {url}: {e}")
        return None

def hash_content(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def load_hashes():
    if not os.path.exists(HASHES_FILE) or os.path.getsize(HASHES_FILE) == 0:
        return {}
    with open(HASHES_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return {}

def save_hashes(hashes):
    with open(HASHES_FILE, 'w', encoding='utf-8') as f:
        json.dump(hashes, f, indent=2)

def notify_change(url):
    msg = f"[CHANGE DETECTED] {url} has changed!"
    print(msg)
    logging.info(msg)

def read_monitor_links():
    with open(MONITOR_LINKS_FILE, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip() and is_valid_onion_url(line.strip())]

def main():
    print("Connecting to Tor...")
    controller = Controller.from_port(address='127.0.0.1', port=9051)
    controller.authenticate()
    print("[✓] Connected to Tor!")
    session = requests.session()
    session.proxies = PROXIES
    print("Starting monitoring loop...")
    while True:
        links = read_monitor_links()
        hashes = load_hashes()
        changed = False
        for url in links:
            print(f"Checking {url} ...")
            content = fetch_onion_content(url, session)
            if content is None:
                print(f"  [!] Could not fetch content for {url}")
                continue
            content_hash = hash_content(content)
            if url in hashes:
                if hashes[url] != content_hash:
                    notify_change(url)
                    changed = True
                else:
                    print(f"  [=] No change for {url}")
            else:
                print(f"  [+] First time monitoring {url}")
                logging.info(f"First time monitoring {url}")
            hashes[url] = content_hash
        save_hashes(hashes)
        if changed:
            controller.signal(Signal.NEWNYM)
            print("[✓] Requested new Tor identity (NEWNYM) after change.")
            time.sleep(3)
        print("Sleeping for 1 hour...")
        time.sleep(3600)

if __name__ == '__main__':
    main()
