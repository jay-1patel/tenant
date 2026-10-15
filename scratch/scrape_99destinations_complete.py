import urllib.request
from bs4 import BeautifulSoup
import json
import re
import time

BASE_URL = "https://www.99destinations.in/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def fetch(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return ""

def clean_soup(soup):
    for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
        tag.decompose()
    return soup

data = {}

# 1. Main Pages
pages = [
    "about-us",
    "contact-us",
    "terms-condition",
    "privacy-policy",
    "flight-booking",
    "visa-service",
    "cruise-holidays",
    "seema-darshan",
    "rann-utsav",
    "places-to-visit",
    "heritage-stays",
    "indian-holidays",
    "international-tours",
    "indian-tour/gujarat-tourism"
]

for p in pages:
    print(f"Fetching {p}...")
    html = fetch(BASE_URL + p)
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string.strip() if soup.title else ""
        soup = clean_soup(soup)
        text = "\n".join([line.strip() for line in soup.get_text("\n").split("\n") if line.strip()])
        data[p] = {
            "url": BASE_URL + p,
            "title": title,
            "content": text
        }

# 2. Places to visit details
places = ['bhavnagar-1', 'dwarka', 'kutch', 'somnath', 'vadodara', 'ahmedabad', 'junagadh']
data['places_details'] = {}
for pl in places:
    p_url = f"places-to-visit-details/{pl}"
    html = fetch(BASE_URL + p_url)
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string.strip() if soup.title else pl
        soup = clean_soup(soup)
        text = "\n".join([line.strip() for line in soup.get_text("\n").split("\n") if line.strip()])
        data['places_details'][pl] = {
            "title": title,
            "content": text
        }

# 3. Heritage Stays details
stays = ['ahmedabad-1', 'bhavnagar']
data['heritage_details'] = {}
for st in stays:
    s_url = f"heritage-stays-details/{st}"
    html = fetch(BASE_URL + s_url)
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string.strip() if soup.title else st
        soup = clean_soup(soup)
        text = "\n".join([line.strip() for line in soup.get_text("\n").split("\n") if line.strip()])
        data['heritage_details'][st] = {
            "title": title,
            "content": text
        }

# 4. Sample detailed tour packages from Gujarat, Indian, and International
sample_packages = [
    "indian-tour-detail/gujarat-tourism/best-of-gujarat-8-days",
    "indian-tour-detail/gujarat-tourism/best-of-gujarat-13-days",
    "indian-tour-detail/gujarat-tourism/statue-of-unity-3-days",
    "indian-tour-detail/gujarat-tourism/somnath-4-days",
    "indian-tour-detail/gujarat-tourism/lions-calling-3-days",
    "indian-tour-detail/gujarat-tourism/rann-utsav-3-days",
    "indian-tour-detail/gujarat-tourism/saputara-calling-3-days",
    "indian-tour-detail/gujarat-tourism/garvi-gujarat-7-days",
    "indian-tour-detail/gujarat-tourism/spiritual-gujarat-5-days",
    "indian-tour-detail/gujarat-tourism/jyotirling-special-5-days",
    "indian-tour-detail/lakshadweep-tourism/cordelia-cruise-5-days",
    "indian-tour-detail/jammu-kashmir-tourism/classic-kashmir-8-days",
    "indian-tour-detail/leh-ladakh-tourism/roof-top-drive-7-days",
    "indian-tour-detail/rajasthan-tourism/classic-rajasthan-10-days",
    "international-tour-detail/uae/dazzling-dubai-7-days",
    "international-tour-detail/switzerland/switzerland-special-8-days",
    "international-tour-detail/georgia/stunning-georgia-7-days",
    "international-tour-detail/turkey/turkey-golden-triangle-8-days",
    "international-tour-detail/austria/jewels-of-austria-13-days",
    "international-tour-detail/u-s-a/ultimate-usa-16-days"
]

data['tour_packages'] = {}
for pkg in sample_packages:
    print(f"Fetching tour: {pkg}...")
    html = fetch(BASE_URL + pkg)
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string.strip() if soup.title else pkg
        soup = clean_soup(soup)
        text = "\n".join([line.strip() for line in soup.get_text("\n").split("\n") if line.strip()])
        data['tour_packages'][pkg] = {
            "title": title,
            "content": text
        }

with open("scraped_99destinations_full.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("Scrape complete! Saved to scraped_99destinations_full.json")
