import urllib.request
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

req = urllib.request.Request('https://www.dlf.in/nri-corner.php', headers=HEADERS)
with urllib.request.urlopen(req, timeout=15) as resp:
    html = resp.read().decode('utf-8', errors='ignore')

soup = BeautifulSoup(html, 'html.parser')

faqs = []
# Look for accordion, faq items
faq_items = soup.find_all(class_=lambda c: c and ('faq' in c.lower() or 'accordion' in c.lower() or 'card' in c.lower() or 'panel' in c.lower()))
print("Total potential FAQ blocks:", len(faq_items))
for item in faq_items:
    q = item.find(['h3', 'h4', 'h5', 'a', 'button', 'strong'])
    ans = item.find(class_=lambda c: c and ('answer' in c.lower() or 'body' in c.lower() or 'collapse' in c.lower() or 'desc' in c.lower()))
    q_txt = q.get_text(strip=True) if q else ""
    a_txt = ans.get_text(strip=True) if ans else ""
    if q_txt and ('?' in q_txt or len(q_txt) > 15):
        faqs.append((q_txt, a_txt or item.get_text(strip=True)))

print(f"Extracted {len(faqs)} FAQs:")
for idx, (q, a) in enumerate(faqs[:10], 1):
    print(f"\nQ{idx}: {q}")
    print(f"A{idx}: {a[:200]}...")
