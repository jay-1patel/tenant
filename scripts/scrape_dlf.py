import urllib.request
import re
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode('utf-8', errors='ignore')

html = fetch('https://www.dlf.in/listing.php')
soup = BeautifulSoup(html, 'html.parser')
scripts = soup.find_all('script')
for idx, s in enumerate(scripts):
    txt = s.get_text()
    if 'locality' in txt:
        print(f"=== SCRIPT {idx} ===")
        print(txt[:4000])
        with open('c:/Users/Leeway/Desktop/chatbot2/scripts/listing_script.js', 'w', encoding='utf-8') as f:
            f.write(txt)
        print("Wrote full script to listing_script.js! Length:", len(txt))
