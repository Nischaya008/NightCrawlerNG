import os
import json
import requests
from bs4 import BeautifulSoup
import sys
import time

# File paths (reuse from main_script.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_FILES_DIR = os.path.join(BASE_DIR, 'test_files')
RESULTS_FILE = os.path.join(TEST_FILES_DIR, 'searched_links.json')

# Tor proxy settings (reuse from main_script.py)
PROXIES = {
    'http':  'socks5h://127.0.0.1:9050',
    'https': 'socks5h://127.0.0.1:9050'
}

# Hugging Face API (updated for chat completions)
HF_API_URL = "https://router.huggingface.co/v1/chat/completions"
HF_MODEL = "mistralai/Mistral-7B-Instruct-v0.3:novita"
HF_API_KEY = os.environ.get("HF_API_KEY")

def get_hf_api_key():
    global HF_API_KEY
    if not HF_API_KEY:
        HF_API_KEY = input("Enter your Hugging Face API key: ").strip()
    return HF_API_KEY

def load_results():
    if not os.path.exists(RESULTS_FILE):
        print(f"Results file not found: {RESULTS_FILE}")
        sys.exit(1)
    with open(RESULTS_FILE, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f"Error loading results: {e}")
            sys.exit(1)
    return data

def get_keywords_with_results(results):
    # Prefer grouping by 'keyword' if present
    keywords = set()
    for r in results:
        if 'keyword' in r and r['keyword']:
            keywords.add(r['keyword'])
    if keywords:
        return list(keywords)
    # Fallback to grouping by title if 'keyword' not present
    return list(set(r['title'] for r in results if r.get('title')))

def select_keyword(keywords):
    print("\n==================== Keywords with Results ====================")
    for idx, kw in enumerate(keywords):
        print(f"  [{idx+1}] {kw}")
    print("==============================================================")
    while True:
        try:
            choice = int(input("\nSelect a keyword by number: "))
            if 1 <= choice <= len(keywords):
                return keywords[choice-1]
        except Exception:
            pass
        print("Invalid choice. Try again.")

def get_links_for_keyword(results, keyword):
    # Return all links for the selected keyword (by 'keyword' field if present, else by title)
    if any('keyword' in r for r in results):
        return [r for r in results if r.get('keyword') == keyword and r.get('link')]
    return [r for r in results if r.get('title') == keyword and r.get('link')]

def fetch_page(url, session):
    try:
        resp = session.get(url, timeout=40)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None

def fetch_all_pages(links):
    contents = []
    print(f"\nUsing {len(links)} landing page(s) from stored content...")
    for idx, r in enumerate(links):
        url = r['link']
        print(f"  [{idx+1}/{len(links)}] {url}")
        print(f"    Title: {r.get('title', '')}")
        if r.get('heading'):
            print(f"    Heading: {r.get('heading', '')}")
        text = r.get('content', '')
        contents.append({'url': url, 'title': r.get('title', ''), 'heading': r.get('heading', ''), 'text': text})
    print("--------------------------------------------------------------")
    return contents

def chunk_text(text, max_tokens=12000):
    # Simple chunking by words (approximate, not exact tokens)
    words = text.split()
    chunk_size = max_tokens * 0.75  # conservative for tokens
    chunk_size = int(chunk_size)
    return [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]

def ask_mistral_chat(question, context, api_key):
    headers = {"Authorization": f"Bearer {api_key}"}
    messages = []
    if context:
        # Add context as a system message if present
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": question})
    payload = {
        "messages": messages,
        "model": HF_MODEL
    }
    response = requests.post(HF_API_URL, headers=headers, json=payload)
    if response.status_code == 200:
        try:
            result = response.json()
            # The response format: {"choices": [{"message": {"role": ..., "content": ...}}], ...}
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[Parse error] {e}"
    else:
        return f"[HTTP {response.status_code}] {response.text}"

def main():
    api_key = get_hf_api_key()
    results = load_results()
    keywords = get_keywords_with_results(results)
    if not keywords:
        print("No keywords with results found.")
        return
    keyword = select_keyword(keywords)
    links = get_links_for_keyword(results, keyword)
    if not links:
        print(f"No links found for keyword '{keyword}'.")
        return
    contents = fetch_all_pages(links)
    if not contents:
        print("No content fetched from landing pages.")
        return
    # Concatenate all content for context (only the actual content)
    full_context = "\n\n".join(c['text'] for c in contents)
    # Print the context for debugging
    print("\n--- DEBUG: Context being sent to the model (first 1000 chars) ---\n")
    print(full_context[:1000])
    print("\n--- END DEBUG ---\n")
    # Chunk if too long
    context_chunks = chunk_text(full_context)
    print(f"\nFetched and prepared context. Entering Q&A mode. Type 'quit' to exit.")
    print("==============================================================")
    while True:
        question = input("\nYour question (or 'quit'): ").strip()
        if question.lower() == 'quit':
            print("Exiting.")
            break
        answers = []
        for chunk_idx, chunk in enumerate(context_chunks):
            ans = ask_mistral_chat(question, chunk, api_key)
            answers.append(ans)
        print("\n====================== Model Answer ==========================")
        for idx, ans in enumerate(answers):
            print(f"\n--- Chunk {idx+1} ---\n{ans.strip()}\n")
        print("==============================================================\n")

if __name__ == '__main__':
    main() 