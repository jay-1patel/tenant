import urllib.request
from bs4 import BeautifulSoup
import re

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

urls = [
    ('About Us', 'https://www.dlf.in/about-us.php'),
    ('Offices / Commercial', 'https://www.dlf.in/offices/'),
    ('Retail', 'https://www.dlf.in/retail/'),
    ('NRI Corner & FAQs', 'https://www.dlf.in/nri-corner.php'),
    ('Customer Support', 'https://www.dlf.in/customer-Support.php'),
    ('Business Enquiry', 'https://www.dlf.in/business-enquiry.php'),
]

for label, url in urls:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            # Extract main text
            for tag in soup(['script', 'style', 'nav', 'footer']):
                tag.decompose()
            text = ' '.join(soup.get_text().split())
            print(f"=== {label} ({url}) ===")
            print(f"Title: {soup.title.string if soup.title else 'No Title'}")
            print(f"Sample text ({len(text)} chars):\n{text[:600]}...\n")
    except Exception as e:
        print(f"Error fetching {label} ({url}): {e}")
