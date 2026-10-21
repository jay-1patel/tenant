import urllib.request
from bs4 import BeautifulSoup
import json
import re

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

microsites = [
    ('The Dahlias', 'https://www.dlf.in/homes/superluxury/thedahlias/'),
    ('The Camellias', 'https://thecamellias.dlf.in/'),
    ('The Arbour', 'https://www.dlf.in/homes/luxury/thearbour/'),
    ('Privana South / West', 'https://www.dlf.in/homes/luxury/privana/'),
    ('One Midtown', 'https://www.dlf.in/homes/luxury/onemidtown/'),
    ('The Ultima', 'https://theultima.dlf.in/'),
    ('The Crest', 'https://thecrestproject.dlf.in/'),
]

for name, url in microsites:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            # Extract meta description
            desc = soup.find('meta', attrs={'name': 'description'})
            desc_txt = desc['content'] if desc and desc.has_attr('content') else ""
            # Extract text
            for tag in soup(['script', 'style', 'nav']):
                tag.decompose()
            body_text = ' '.join(soup.get_text().split())
            # Find RERA
            rera = re.findall(r'(?:RERA|rera)[\s\:\-\#a-zA-Z0-9\/]+', body_text)
            print(f"=== {name} ({url}) ===")
            print(f"Title: {soup.title.string.strip() if soup.title else 'No Title'}")
            print(f"Meta Desc: {desc_txt[:150]}")
            if rera:
                print(f"RERA match: {rera[:3]}")
            print(f"Body snippet: {body_text[:250]}...\n")
    except Exception as e:
        print(f"Failed {name} ({url}): {e}\n")
