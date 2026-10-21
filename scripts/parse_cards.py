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

data = urllib.parse.urlencode({'status': '', 'category': ''}).encode('utf-8')
req = urllib.request.Request('https://www.dlf.in/load-projects.php', data=data, headers=HEADERS)
with urllib.request.urlopen(req, timeout=15) as resp:
    html = resp.read().decode('utf-8', errors='ignore')

soup = BeautifulSoup(html, 'html.parser')

items = []
# print first few cards structure
for card in soup.find_all(class_=lambda c: c and 'col-' in c):
    title = card.find(['h3', 'h4', 'h5', 'h2', 'strong'])
    title_text = title.get_text(strip=True) if title else ""
    link = card.find('a', href=True)
    href = link['href'] if link else ""
    img = card.find('img')
    img_src = img['src'] if img and img.has_attr('src') else ""
    full_text = ' '.join(card.get_text().split())
    items.append({
        'title': title_text,
        'link': href,
        'img': img_src,
        'raw_text': full_text
    })

print(f"Parsed {len(items)} items from load-projects.php:")
for it in items[:6]:
    print(json.dumps(it, indent=2))
