import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
import json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
    'Origin': 'https://www.dlf.in',
    'Referer': 'https://www.dlf.in/listing.php'
}

statuses = ['construction', 'ready', 'sold', '']
categories = ['', 'luxury', 'super-luxury', 'premium']

all_projects = {}

for st in statuses:
    for cat in categories:
        data = urllib.parse.urlencode({'status': st, 'category': cat}).encode('utf-8')
        req = urllib.request.Request('https://www.dlf.in/load-projects.php', data=data, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_text = resp.read().decode('utf-8', errors='ignore')
                soup = BeautifulSoup(resp_text, 'html.parser')
                cards = soup.find_all(class_=lambda c: c and ('card' in c or 'col-' in c or 'item' in c or 'box' in c))
                # Let's search for project links, titles, images, descriptions
                for a in soup.find_all('a', href=True):
                    h = a['href']
                    t = a.get_text(strip=True)
                    if t and not h.startswith('#') and not h.startswith('javascript'):
                        all_projects[h] = t
                print(f"status='{st}', category='{cat}' -> response len: {len(resp_text)}, a tags: {len(soup.find_all('a'))}")
        except Exception as e:
            print(f"Error for status={st}, category={cat}: {e}")

print(f"\nTotal unique project links found: {len(all_projects)}")
for h, t in sorted(all_projects.items(), key=lambda x: x[1]):
    print(f"  {t[:40]:<42} -> {h}")
