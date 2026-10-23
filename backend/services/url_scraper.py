"""Universal Website Scraper & Multimodal Auto-Onboarding Engine.

Extracts rich business data across ANY industry/vertical:
- Real Estate: Projects, apartments, plots, towers, prices, localities, RERA, floor plans, and photos.
- E-Commerce & Retail: Products, SKU, categories, prices, MRP, discounts, specs, and product images.
- Tours & Travel: Packages, itineraries, durations, destinations, inclusions, pricing, and scenic photos.
- Healthcare & Clinics: Treatments, procedures, doctor names, consultation fees, and clinic photos.
- Restaurants & Food: Menu items, categories, dietary tags (Veg/Non-Veg), prices, and food photos.
- IT & SaaS: Services, solutions, tech stacks, tiers, pricing plans, and feature lists.
- Education: Courses, curriculum duration, certifications, pricing, and course banners.
- Financial & Banking: Loans, interest rates, eligibility, investment options.
- Generic / Any Service.

Key Features:
1. Universal Card & Offering Detector (extracts repeating product/service cards with high-res images).
2. Schema.org / JSON-LD structured data parser (extracts pristine Product, RealEstateListing, MenuItem, TouristTrip data).
3. Image Downloader & Cache: Downloads product images to backend/uploaded_files/product_images/ so WhatsApp and the console always have permanent, working media.
4. Brand Logo & OpenGraph extraction.
5. Ingests directly into SQLite 'products' (with media_url and attrs_json) and 'faq_dataset' with vector embeddings.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import time
import urllib.parse
import urllib.robotparser
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from bs4 import BeautifulSoup

from database import (
    get_db_context,
    list_products,
    record_admin_audit_event,
    save_product,
    update_product,
)
from shared.tenancy import cache as tenancy_cache
from shared.tenancy import loader as tenancy_loader
from shared.tenancy import schemas as tenancy_schemas
from shared.tenancy import store as tenancy_store

logger = logging.getLogger("url_scraper")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Politeness defaults: seconds between page fetches when robots.txt gives no
# crawl-delay, and the JS-shell heuristic thresholds below which a statically
# fetched page is considered client-side rendered and re-fetched via Playwright.
DEFAULT_CRAWL_DELAY = 1.0
JS_RENDER_TEXT_THRESHOLD = 800
JS_SCRIPT_TAG_THRESHOLD = 5


def _js_render_enabled(explicit: Optional[bool] = None) -> bool:
    """JS rendering is on by default; SCRAPER_JS_RENDER=off disables it."""
    if explicit is not None:
        return explicit
    return os.getenv("SCRAPER_JS_RENDER", "auto").strip().lower() not in {"off", "0", "false"}


def looks_like_js_shell(html: str) -> bool:
    """Heuristic: markup with script tags but almost no server-rendered text,
    typical of a React/Vue/Angular shell that only paints client-side."""
    if not html:
        return False
    stripped = re.sub(r"<script\b.*?</script>", " ", html, flags=re.S | re.I)
    stripped = re.sub(r"<style\b.*?</style>", " ", stripped, flags=re.S | re.I)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    visible_text = re.sub(r"\s+", " ", stripped).strip()
    script_tags = len(re.findall(r"<script\b", html, flags=re.I))
    return len(visible_text) < JS_RENDER_TEXT_THRESHOLD and script_tags >= JS_SCRIPT_TAG_THRESHOLD


def render_with_playwright(url: str, timeout: float = 15.0) -> Optional[str]:
    """Render a JS-heavy page with headless Chromium via Playwright.

    Returns the fully-rendered HTML, or None when Playwright (or its browser)
    is not installed — the crawler then keeps the static HTML. Optional
    dependency: pip install playwright && playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.debug("Playwright not installed; JS rendering skipped for %s", url)
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
                page.wait_for_timeout(1200)  # let late XHR content paint
                return page.content()
            finally:
                browser.close()
    except Exception as e:
        logger.warning("Playwright render failed for %s: %s", url, e)
        return None


class RobotsTxtPolicy:
    """robots.txt gate for the crawler.

    Uses the stdlib robotparser. A missing or unreachable robots.txt means
    'allowed' (standard crawler behaviour); a parse failure also degrades to
    allowed rather than blocking the crawl.
    """

    def __init__(self, base_url: str, timeout: float = 8.0):
        self._parser: Optional[urllib.robotparser.RobotFileParser] = None
        self.crawl_delay: Optional[float] = None
        parsed = urllib.parse.urlparse(normalize_url(base_url))
        robots_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(robots_url, headers={"User-Agent": USER_AGENT})
            if resp.status_code != 200:
                return
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(resp.text.splitlines())
            self._parser = parser
            try:
                self.crawl_delay = parser.crawl_delay(USER_AGENT)
            except Exception:
                self.crawl_delay = None
        except Exception as e:
            logger.debug("robots.txt fetch failed for %s: %s", robots_url, e)

    def can_fetch(self, url: str) -> bool:
        if self._parser is None:
            return True
        return self._parser.can_fetch(USER_AGENT, url)

BASE_DIR = Path(__file__).resolve().parent.parent
PRODUCT_IMAGES_DIR = BASE_DIR / "uploaded_files" / "product_images"
PRODUCT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# Subpage discovery keywords across all verticals
KEYWORD_BUCKETS = {
    "about": [
        "about", "about-us", "company", "who-we-are", "our-story", "story", "overview", "legacy"
    ],
    "offerings": [
        "products", "product", "services", "service", "offerings", "catalog", "catalogue",
        "shop", "store", "collection", "projects", "homes", "properties", "residences",
        "menu", "dishes", "food", "packages", "destinations", "tours", "trips",
        "treatments", "procedures", "doctors", "courses", "programs", "pricing", "plans",
        "solutions", "features"
    ],
    "faq": [
        "faq", "faqs", "help", "support", "frequently-asked-questions", "questions",
        "policies", "terms", "refund", "shipping", "cancellation", "warranty"
    ],
    "contact": [
        "contact", "contact-us", "reach-us", "locations", "branches", "offices", "get-in-touch"
    ],
}


def normalize_url(raw_url: str) -> str:
    """Ensure scheme and clean whitespace."""
    url = (raw_url or "").strip()
    if not url:
        return ""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def clean_text(text: str) -> str:
    """Normalize spaces and clean line breaks."""
    if not text:
        return ""
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def slugify(text: str) -> str:
    """Produce clean lowercase slug."""
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "item"


def extract_best_image_url(img_tag: Any, base_url: str) -> Optional[str]:
    """Extract highest quality image URL from an img tag (handling data-src, srcset, src)."""
    if not img_tag or not hasattr(img_tag, "get"):
        return None

    candidate_urls: List[str] = []

    # 1. Check srcset (e.g. 'img-300.jpg 300w, img-800.jpg 800w')
    srcset = img_tag.get("srcset") or img_tag.get("data-srcset")
    if srcset:
        parts = str(srcset).split(",")
        for part in reversed(parts):
            tokens = part.strip().split()
            if tokens:
                candidate_urls.append(tokens[0])

    # 2. Check lazy load & zoom attributes
    for attr in [
        "data-highres",
        "data-zoom-image",
        "data-large_image",
        "data-src",
        "data-original",
        "data-lazy-src",
        "data-url",
        "src",
    ]:
        val = img_tag.get(attr)
        if val and isinstance(val, str) and val.strip():
            candidate_urls.append(val.strip())

    # 3. Filter and resolve candidate URLs
    for raw_url in candidate_urls:
        if raw_url.startswith("data:image"):
            continue
        lower = raw_url.lower()
        if any(ign in lower for ign in [
            ".svg", "1x1", "pixel", "spacer", "spinner", "loader", "favicon",
            "facebook", "twitter", "instagram", "linkedin", "youtube", "cart",
            "arrow", "star", "badge", "payment", "visa", "mastercard"
        ]):
            continue

        resolved = urllib.parse.urljoin(base_url, raw_url)
        if resolved.startswith("http://") or resolved.startswith("https://"):
            return resolved

    return None


def download_and_store_image(
    image_url: str,
    tenant_id: str,
    item_slug: str,
    timeout: float = 8.0,
) -> Optional[str]:
    """Download image to local product_images directory and return served path."""
    if not image_url or not (image_url.startswith("http://") or image_url.startswith("https://")):
        return None

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(image_url, headers={"User-Agent": USER_AGENT})
            if resp.status_code != 200:
                return image_url

            content_type = resp.headers.get("content-type", "").lower()
            if not content_type.startswith("image/"):
                return image_url

            ext = mimetypes.guess_extension(content_type) or ".jpg"
            if ext in {".jpe", ".jpeg"}:
                ext = ".jpg"

            # Check minimum size (> 2KB to exclude tracking pixels)
            if len(resp.content) < 2048:
                return None

            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:6]
            clean_item_slug = slugify(item_slug)[:30]
            filename = f"{tenant_id}_{clean_item_slug}_{url_hash}{ext}"
            file_path = PRODUCT_IMAGES_DIR / filename

            with open(file_path, "wb") as f:
                f.write(resp.content)

            logger.info("STORED_PRODUCT_IMAGE | tenant=%s | file=%s", tenant_id, filename)
            return f"/uploaded_files/product_images/{filename}"
    except Exception as e:
        logger.debug("Failed downloading image %s: %s", image_url, e)
        return image_url


class UniversalWebExtractor:
    """Extracts structured offerings, brand info, and FAQs from HTML and JSON-LD."""

    @staticmethod
    def extract_json_ld(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
        """Extract structured offerings directly from Schema.org JSON-LD."""
        extracted_items: List[Dict[str, Any]] = []

        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string.strip())
                items_to_check = data if isinstance(data, list) else [data]

                for item in items_to_check:
                    if not isinstance(item, dict):
                        continue

                    if "@graph" in item and isinstance(item["@graph"], list):
                        items_to_check.extend(item["@graph"])
                        continue

                    schema_type = str(item.get("@type", "")).lower()

                    # 1. Products / E-Commerce
                    if any(t in schema_type for t in ["product", "offer"]):
                        name = item.get("name")
                        if name:
                            img = item.get("image")
                            img_url = img[0] if isinstance(img, list) else (img.get("url") if isinstance(img, dict) else img)
                            if img_url:
                                img_url = urllib.parse.urljoin(base_url, str(img_url))

                            offers = item.get("offers", {})
                            if isinstance(offers, list) and offers:
                                offers = offers[0]
                            price = offers.get("price") if isinstance(offers, dict) else None
                            currency = offers.get("priceCurrency", "") if isinstance(offers, dict) else ""
                            price_str = f"{currency} {price}".strip() if price else "On Request"

                            extracted_items.append({
                                "name": str(name).strip(),
                                "category": item.get("category") or "Catalog",
                                "price": price_str,
                                "short_description": clean_text(str(item.get("description", "")))[:150],
                                "description": clean_text(str(item.get("description", ""))),
                                "media_url": img_url,
                                "detail_url": item.get("url") or base_url,
                                "attrs": {
                                    "sku": item.get("sku"),
                                    "brand": item.get("brand", {}).get("name") if isinstance(item.get("brand"), dict) else item.get("brand"),
                                },
                            })

                    # 2. Real Estate (Accommodation, SingleFamilyResidence, Apartment)
                    elif any(t in schema_type for t in ["residence", "apartment", "realestate", "accommodation", "house"]):
                        name = item.get("name")
                        if name:
                            img = item.get("image")
                            img_url = urllib.parse.urljoin(base_url, str(img)) if img else None
                            extracted_items.append({
                                "name": str(name).strip(),
                                "category": "Residential Project",
                                "price": "On Request",
                                "short_description": clean_text(str(item.get("description", "")))[:150],
                                "description": clean_text(str(item.get("description", ""))),
                                "media_url": img_url,
                                "detail_url": item.get("url") or base_url,
                                "attrs": {
                                    "bedrooms": item.get("numberOfRooms"),
                                    "address": str(item.get("address", "")),
                                },
                            })

                    # 3. Restaurant Menu Item
                    elif "menuitem" in schema_type:
                        name = item.get("name")
                        if name:
                            img = item.get("image")
                            img_url = urllib.parse.urljoin(base_url, str(img)) if img else None
                            extracted_items.append({
                                "name": str(name).strip(),
                                "category": "Menu",
                                "price": str(item.get("offers", {}).get("price") or "Price on Menu"),
                                "short_description": clean_text(str(item.get("description", "")))[:150],
                                "description": clean_text(str(item.get("description", ""))),
                                "media_url": img_url,
                                "detail_url": base_url,
                                "attrs": {"diet": item.get("suitableForDiet")},
                            })

                    # 4. Tour Trip / Travel Package
                    elif any(t in schema_type for t in ["trip", "tour", "touristtrip"]):
                        name = item.get("name")
                        if name:
                            img = item.get("image")
                            img_url = urllib.parse.urljoin(base_url, str(img)) if img else None
                            extracted_items.append({
                                "name": str(name).strip(),
                                "category": "Tour Package",
                                "price": "Starting on Request",
                                "short_description": clean_text(str(item.get("description", "")))[:150],
                                "description": clean_text(str(item.get("description", ""))),
                                "media_url": img_url,
                                "detail_url": item.get("url") or base_url,
                                "attrs": {"itinerary": item.get("itinerary")},
                            })
            except Exception as e:
                logger.debug("Failed parsing JSON-LD script: %s", e)

        return extracted_items

    @staticmethod
    def extract_visual_cards(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
        """Identify repeating card/listing elements and extract title, price, image, and link."""
        cards: List[Dict[str, Any]] = []
        seen_names = set()

        card_selectors = [
            "[class*='product-card']", "[class*='product-item']", "[class*='product_item']",
            "[class*='project-card']", "[class*='project-box']", "[class*='property-card']",
            "[class*='listing-card']", "[class*='listing-item']", "[class*='tour-card']",
            "[class*='package-card']", "[class*='menu-item']", "[class*='dish-card']",
            "[class*='service-card']", "[class*='service-item']", "[class*='course-card']",
            ".col-md-4", ".col-lg-4", ".col-sm-6", "article.product", "li.product"
        ]

        elements = []
        for sel in card_selectors:
            found = soup.select(sel)
            if len(found) >= 2:
                elements.extend(found)

        if not elements:
            for div in soup.find_all(["div", "article", "li"], class_=True):
                class_str = " ".join(div.get("class", [])).lower()
                if any(w in class_str for w in ["item", "card", "box", "grid", "col-"]):
                    if div.find(["h2", "h3", "h4"]) and div.find("img"):
                        elements.append(div)

        for elem in elements[:30]:
            title_tag = elem.find(["h2", "h3", "h4", "h5", "a"])
            name = clean_text(title_tag.get_text()) if title_tag else ""
            if not name or len(name) < 3 or len(name) > 80 or name.lower() in seen_names:
                continue
            if any(ign in name.lower() for ign in ["cart", "sign in", "login", "menu", "search", "newsletter"]):
                continue

            seen_names.add(name.lower())

            img_tag = elem.find("img")
            img_url = extract_best_image_url(img_tag, base_url) if img_tag else None

            link_tag = elem.find("a", href=True)
            detail_url = urllib.parse.urljoin(base_url, link_tag["href"].strip()) if link_tag else base_url

            price = "On Request"
            price_match = re.search(r"(?:₹|\$|Rs\.?|EUR|€|GBP|£|AED)\s*[\d,]+(?:\.\d+)?(?:\s*(?:Cr|Lakh|k|M|/mo|per night))?", elem.get_text(), re.I)
            if price_match:
                price = price_match.group(0).strip()

            p_tag = elem.find("p")
            desc = clean_text(p_tag.get_text()) if p_tag else f"Detailed information about {name}."

            cards.append({
                "name": name,
                "category": "Catalog Offering",
                "price": price,
                "short_description": desc[:140],
                "description": desc,
                "media_url": img_url,
                "detail_url": detail_url,
                "attrs": {},
            })

        return cards

    @staticmethod
    def extract_brand_logo(soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Find the official company logo."""
        for sel in [
            "header img[src*='logo' i]", "nav img[src*='logo' i]",
            "a[class*='logo' i] img", ".navbar-brand img",
            "img[alt*='logo' i]", "img[id*='logo' i]"
        ]:
            logo_img = soup.select_one(sel)
            if logo_img:
                url = extract_best_image_url(logo_img, base_url)
                if url:
                    return url

        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            return urllib.parse.urljoin(base_url, str(og_img["content"]).strip())

        return None


class WebScraperCrawler:
    """Universal multi-page website crawler with image & structured data capture."""

    def __init__(
        self,
        base_url: str,
        max_pages: int = 8,
        timeout_seconds: float = 12.0,
        respect_robots: bool = True,
        request_delay: float = DEFAULT_CRAWL_DELAY,
        enable_js_render: Optional[bool] = None,
    ):
        self.root_url = normalize_url(base_url)
        self.max_pages = max_pages
        self.timeout = timeout_seconds
        self.respect_robots = respect_robots
        self.request_delay = request_delay
        self.enable_js_render = _js_render_enabled(enable_js_render)
        self.robots: Optional[RobotsTxtPolicy] = None
        parsed = urllib.parse.urlparse(self.root_url)
        self.domain = parsed.netloc.lower()
        self.visited_urls: Set[str] = set()
        self.skipped_urls: List[Dict[str, str]] = []
        self.js_rendered_urls: List[str] = []
        self._last_fetch_ts: float = 0.0

    def _is_same_domain(self, target_url: str) -> bool:
        parsed = urllib.parse.urlparse(target_url)
        return parsed.netloc.lower() in {self.domain, f"www.{self.domain}".replace("www.www.", "www.")}

    def _polite_delay(self) -> None:
        """Sleep so fetches respect the robots.txt crawl-delay (or the default)."""
        delay = self.request_delay
        if self.robots and self.robots.crawl_delay:
            delay = max(delay, float(self.robots.crawl_delay))
        elapsed = time.monotonic() - self._last_fetch_ts
        if elapsed < delay:
            time.sleep(delay - elapsed)

    def _fetch_html(self, client: httpx.Client, url: str) -> Optional[str]:
        self._polite_delay()
        try:
            resp = client.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
                timeout=self.timeout,
                follow_redirects=True,
            )
            self._last_fetch_ts = time.monotonic()
            # Back off once when the server pushes back (429/503), then retry.
            if resp.status_code in (429, 503):
                retry_after = resp.headers.get("Retry-After", "")
                backoff = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 5.0
                backoff = min(backoff, 30.0)
                logger.debug("Backoff %.1fs after %s on %s", backoff, resp.status_code, url)
                time.sleep(backoff)
                resp = client.get(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
                    timeout=self.timeout,
                    follow_redirects=True,
                )
                self._last_fetch_ts = time.monotonic()
            if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                if self.enable_js_render and looks_like_js_shell(resp.text):
                    rendered = render_with_playwright(url, timeout=self.timeout)
                    if rendered:
                        self.js_rendered_urls.append(url)
                        return rendered
                return resp.text
        except Exception as e:
            logger.debug("Failed fetching %s: %s", url, e)
        return None

    def _extract_page_data(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract title, meta, text chunks, contact hints, visual cards, and images."""
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
        if not meta_tag:
            meta_tag = soup.find("meta", attrs={"property": "og:description"})
        if meta_tag and meta_tag.get("content"):
            meta_desc = str(meta_tag["content"]).strip()

        logo_url = UniversalWebExtractor.extract_brand_logo(soup, url)
        json_ld_offerings = UniversalWebExtractor.extract_json_ld(soup, url)
        visual_cards = UniversalWebExtractor.extract_visual_cards(soup, url)

        full_html_text = soup.get_text()
        emails = list(set(re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", full_html_text)))
        phones = list(set(re.findall(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}", full_html_text)))
        phones = [p.strip() for p in phones if len(re.sub(r"\D", "", p)) >= 10 and len(re.sub(r"\D", "", p)) <= 14]

        page_images = []
        for img in soup.find_all("img"):
            best_img = extract_best_image_url(img, url)
            if best_img and best_img not in page_images:
                page_images.append(best_img)

        headings = []
        for h in soup.find_all(["h1", "h2", "h3"]):
            txt = clean_text(h.get_text())
            if txt and len(txt) > 3 and txt not in headings:
                headings.append(txt)

        clean_soup = BeautifulSoup(str(soup), "html.parser")
        for tag in clean_soup(["script", "style", "noscript", "svg", "header", "footer"]):
            tag.decompose()

        text_blocks = []
        for elem in clean_soup.find_all(["p", "li", "article", "section", "table"]):
            txt = clean_text(elem.get_text())
            if len(txt) > 35 and txt not in text_blocks:
                text_blocks.append(txt)

        combined_text = "\n\n".join(text_blocks[:40])

        return {
            "url": url,
            "title": title,
            "meta_description": meta_desc,
            "logo_url": logo_url,
            "emails": emails[:3],
            "phones": phones[:3],
            "headings": headings[:15],
            "content": combined_text[:6000],
            "json_ld_offerings": json_ld_offerings,
            "visual_cards": visual_cards,
            "page_images": page_images[:10],
        }

    def _discover_links(self, soup: BeautifulSoup, current_url: str) -> List[Tuple[str, str]]:
        """Find internal links categorized by bucket."""
        scored_links: List[Tuple[str, str]] = []
        seen_targets = set()

        for a in soup.find_all("a", href=True):
            raw_href = a["href"].strip()
            if not raw_href or raw_href.startswith("#") or raw_href.startswith("javascript:"):
                continue

            target_url = urllib.parse.urljoin(current_url, raw_href)
            parsed_target = urllib.parse.urlparse(target_url)
            clean_target = urllib.parse.urlunparse((parsed_target.scheme, parsed_target.netloc, parsed_target.path, "", "", ""))

            if clean_target in seen_targets or clean_target in self.visited_urls:
                continue
            if not self._is_same_domain(clean_target):
                continue
            if re.search(r"\.(pdf|png|jpg|jpeg|svg|css|js|zip|mp4)$", clean_target, re.I):
                continue

            seen_targets.add(clean_target)
            path_lower = (parsed_target.path or "").lower()
            text_lower = (a.get_text() or "").lower()

            bucket_found = "other"
            for bucket, kws in KEYWORD_BUCKETS.items():
                if any(kw in path_lower or kw in text_lower for kw in kws):
                    bucket_found = bucket
                    break

            if bucket_found != "other":
                scored_links.append((clean_target, bucket_found))

        return scored_links

    def crawl(self) -> Dict[str, Any]:
        """Execute autonomous crawl."""
        crawled_pages: List[Dict[str, Any]] = []
        to_crawl: List[Tuple[str, str]] = [(self.root_url, "home")]

        with httpx.Client(timeout=self.timeout) as client:
            if self.respect_robots:
                self.robots = RobotsTxtPolicy(self.root_url, timeout=self.timeout)
                if not self.robots.can_fetch(self.root_url):
                    logger.warning("ROBOTS_DISALLOW_ROOT | %s", self.root_url)
                    return {
                        "root_url": self.root_url,
                        "domain": self.domain,
                        "pages_crawled_count": 0,
                        "pages": [],
                        "skipped_urls": [{"url": self.root_url, "reason": "robots.txt disallow"}],
                        "blocked_by_robots": True,
                    }

            while to_crawl and len(crawled_pages) < self.max_pages:
                curr_url, category = to_crawl.pop(0)
                if curr_url in self.visited_urls:
                    continue
                self.visited_urls.add(curr_url)

                if self.respect_robots and not self.robots.can_fetch(curr_url):
                    self.skipped_urls.append({"url": curr_url, "reason": "robots.txt disallow"})
                    continue

                html = self._fetch_html(client, curr_url)
                if not html:
                    continue

                soup = BeautifulSoup(html, "html.parser")
                page_data = self._extract_page_data(soup, curr_url)
                page_data["category"] = category
                crawled_pages.append(page_data)

                discovered = self._discover_links(soup, curr_url)
                priority_order = {"offerings": 0, "about": 1, "faq": 2, "contact": 3, "other": 4}
                discovered.sort(key=lambda x: priority_order.get(x[1], 4))
                for d_url, d_cat in discovered:
                    if d_url not in self.visited_urls and not any(d_url == tc[0] for tc in to_crawl):
                        to_crawl.append((d_url, d_cat))

        return {
            "root_url": self.root_url,
            "domain": self.domain,
            "pages_crawled_count": len(crawled_pages),
            "pages": crawled_pages,
            "skipped_urls": self.skipped_urls,
            "js_rendered_urls": self.js_rendered_urls,
        }


class UrlAutoOnboarder:
    """Transforms crawled website data into live tenant database records and FAISS index."""

    def __init__(self, tenant_id: Optional[str] = None, actor: Optional[dict] = None):
        self.tenant_id = (tenant_id or "").strip().lower()
        self.actor = actor or {
            "username": "universal_scraper",
            "role": "super_admin",
            "tenant_id": self.tenant_id,
        }

    def _call_llm(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
        """Call LLM with fallback for JSON output."""
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            try:
                import requests
                for model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama3-70b-8192"):
                    resp = requests.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            "response_format": {"type": "json_object"},
                            "temperature": 0.1,
                            "max_tokens": 4096,
                        },
                        timeout=45,
                    )
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        match = re.search(r"(\{.*\})", content, re.DOTALL)
                        if match:
                            return json.loads(match.group(1))
            except Exception as e:
                logger.warning("Groq extraction error: %s", e)

        mistral_key = os.getenv("MISTRAL_API_KEY")
        if mistral_key:
            try:
                import requests
                resp = requests.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {mistral_key}", "Content-Type": "application/json"},
                    json={
                        "model": os.getenv("MISTRAL_MODEL", "open-mistral-7b"),
                        "messages": [
                            {"role": "system", "content": system_prompt + "\nOUTPUT ONLY RAW JSON."},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 4096,
                    },
                    timeout=45,
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    match = re.search(r"(\{.*\})", content, re.DOTALL)
                    if match:
                        return json.loads(match.group(1))
            except Exception as e:
                logger.warning("Mistral extraction error: %s", e)

        return None

    def _heuristic_extraction(self, crawl_res: Dict[str, Any], domain: str) -> Dict[str, Any]:
        """Deterministic universal fallback combining JSON-LD, visual cards, and text."""
        pages = crawl_res.get("pages", [])
        home = next((p for p in pages if p.get("category") == "home"), pages[0] if pages else {})
        title = home.get("title", domain)
        clean_name = title.split("|")[0].split("-")[0].strip() or domain

        logo_url = home.get("logo_url")
        emails: List[str] = []
        phones: List[str] = []
        for p in pages:
            emails.extend(p.get("emails", []))
            phones.extend(p.get("phones", []))
            if not logo_url and p.get("logo_url"):
                logo_url = p.get("logo_url")

        all_text = " ".join([p.get("content", "") + " " + " ".join(p.get("headings", [])) for p in pages]).lower()
        vertical = "generic"
        if any(w in all_text for w in ["property", "real estate", "residence", "apartment", "villa", "bhk", "rera"]):
            vertical = "real_estate"
        elif any(w in all_text for w in ["tour", "travel", "package", "flight", "hotel", "vacation", "destination"]):
            vertical = "tours_travel"
        elif any(w in all_text for w in ["clinic", "hospital", "doctor", "health", "patient", "medical", "treatment"]):
            vertical = "healthcare"
        elif any(w in all_text for w in ["menu", "restaurant", "cafe", "dish", "food", "cuisine", "chef"]):
            vertical = "restaurant" if "restaurant" in tenancy_schemas.VERTICALS else "generic"
        elif any(w in all_text for w in ["cart", "checkout", "shop", "ecommerce", "store", "buy now"]):
            vertical = "ecommerce"
        elif any(w in all_text for w in ["software", "cloud", "saas", "api", "developer", "platform"]):
            vertical = "it_software"
        elif any(w in all_text for w in ["course", "curriculum", "coaching", "academy", "training", "learn"]):
            vertical = "education" if "education" in tenancy_schemas.VERTICALS else "generic"

        offerings: List[Dict[str, Any]] = []
        seen_names = set()

        for p in pages:
            for item in p.get("json_ld_offerings", []):
                nm = item.get("name", "").strip()
                if nm and nm.lower() not in seen_names:
                    seen_names.add(nm.lower())
                    offerings.append(item)

            for card in p.get("visual_cards", []):
                nm = card.get("name", "").strip()
                if nm and nm.lower() not in seen_names:
                    seen_names.add(nm.lower())
                    offerings.append(card)

        if not offerings:
            for p in pages:
                for h in p.get("headings", [])[:6]:
                    if len(h) > 5 and len(h) < 65 and h.lower() not in seen_names:
                        seen_names.add(h.lower())
                        img = p.get("page_images", [None])[0]
                        offerings.append({
                            "name": h,
                            "category": "Services",
                            "price": "On Request",
                            "short_description": f"Learn more about {h}.",
                            "description": f"Quality {h} tailored to customer requirements.",
                            "media_url": img,
                            "detail_url": p.get("url"),
                            "attrs": {},
                        })

        faqs = [
            {
                "question": f"How can I contact {clean_name}?",
                "answer": f"You can reach us at {emails[0] if emails else 'support@' + domain} or call {phones[0] if phones else 'our customer care'}.",
                "category": "Support",
            },
            {
                "question": f"What services or products does {clean_name} offer?",
                "answer": f"{clean_name} offers {title}. Browse our interactive menu to view available offerings.",
                "category": "Offerings",
            },
            {
                "question": "What are your operating business hours?",
                "answer": "We are open Monday through Saturday from 9:30 AM to 6:30 PM.",
                "category": "General",
            },
        ]

        return {
            "vertical": vertical,
            "brand": {
                "name": clean_name,
                "bot_name": f"{clean_name} Assistant",
                "tagline": home.get("meta_description") or f"Official WhatsApp Assistant for {clean_name}",
                "website": crawl_res.get("root_url"),
                "logo_url": logo_url or "",
                "support_email": emails[0] if emails else f"support@{domain}",
                "support_phone": phones[0] if phones else "+91 9999999999",
                "signature": f"— The {clean_name} Team",
            },
            "business_hours": {
                "timezone": "Asia/Kolkata",
                "open": "09:30",
                "close": "18:30",
                "open_days": [0, 1, 2, 3, 4, 5],
            },
            "menu_items": [
                {"id": "browse_offerings", "title": "Explore Offerings", "description": "Browse catalog and services", "section": "Services", "action": "offerings"},
                {"id": "book_callback", "title": "Request Callback", "description": "Speak directly with our team", "section": "Support", "action": "book_callback"},
                {"id": "faq_help", "title": "FAQs & Info", "description": "Answers to frequent questions", "section": "Support", "action": "faq"},
            ],
            "intents": [
                {"name": "browse_offerings", "description": "User wants to explore products/services", "keywords": ["offerings", "products", "services", "catalog"], "examples": ["What do you sell?", "Show products"], "flow": None},
                {"name": "human_support", "description": "User wants to talk to a person", "keywords": ["human", "agent", "call", "help"], "examples": ["Can someone call me?", "Talk to agent"], "flow": "book_callback"},
            ],
            "offerings": offerings[:15],
            "faqs": faqs,
            "knowledge_articles": [
                {
                    "title": f"About {clean_name}",
                    "category": "Company",
                    "markdown_content": f"# About {clean_name}\n\n{home.get('meta_description', '')}\n\n" + "\n\n".join(home.get("content", "").split("\n\n")[:5]),
                }
            ],
        }

    def extract_bifurcation(self, crawl_res: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze website with LLM and multimodal extraction."""
        pages = crawl_res.get("pages", [])
        domain = crawl_res.get("domain", "business")

        pre_extracted_offerings = []
        for p in pages:
            pre_extracted_offerings.extend(p.get("json_ld_offerings", []))
            pre_extracted_offerings.extend(p.get("visual_cards", []))

        corpus_blocks = []
        for p in pages:
            corpus_blocks.append(
                f"=== Page: {p.get('title')} ({p.get('url')}) | Category: {p.get('category')} ===\n"
                f"Headings: {', '.join(p.get('headings', []))}\n"
                f"Meta: {p.get('meta_description')}\n"
                f"Emails: {', '.join(p.get('emails', []))} | Phones: {', '.join(p.get('phones', []))}\n"
                f"Content:\n{p.get('content')}\n"
            )
        corpus_text = "\n\n".join(corpus_blocks)[:16000]

        system_prompt = """You are a Universal Enterprise Onboarding AI Agent for WhatsApp Business.
You handle ANY type of business/vertical:
- Real Estate (properties, residential, commercial, floor plans, pricing, RERA, locality, project photos)
- E-Commerce & Retail (products, SKU, categories, prices, discounts, specs, product images)
- Tours & Travel (itineraries, tour packages, destinations, duration, inclusions, rates, photos)
- Healthcare & Clinics (treatments, procedures, doctor names, consultation fees, clinic photos)
- Restaurants & Food (dishes, appetizers, mains, beverages, prices, dietary tags, food photos)
- IT Services & SaaS (solutions, tech stacks, tiers, plans, feature lists)
- Education & Coaching (courses, syllabus, fees, duration, course banners)
- Financial & Banking (loans, interest rates, eligibility, investment schemes)
- Generic / Any Service.

Analyze the crawled website content and output STRICT JSON conforming to this schema:
{
  "vertical": "real_estate" | "tours_travel" | "ecommerce" | "it_software" | "healthcare" | "generic",
  "brand": {
    "name": "Official Business / Brand Name",
    "bot_name": "Friendly Assistant Name",
    "tagline": "1-2 sentence compelling value proposition",
    "website": "Canonical Website URL",
    "logo_url": "Direct URL to brand logo",
    "support_email": "Official contact email",
    "support_phone": "Official phone number with country code",
    "signature": "Closing sign-off line"
  },
  "business_hours": {
    "timezone": "Asia/Kolkata",
    "open": "09:30",
    "close": "18:30",
    "open_days": [0, 1, 2, 3, 4, 5]
  },
  "menu_items": [
    {
      "id": "browse_offerings",
      "title": "Explore Offerings",
      "description": "Browse catalog and solutions",
      "section": "Explore",
      "action": "offerings"
    }
  ],
  "intents": [
    {
      "name": "intent_slug",
      "description": "Short description",
      "keywords": ["kw1", "kw2"],
      "examples": ["question 1", "question 2"],
      "flow": "book_callback" | "get_quote" | "raise_ticket" | null
    }
  ],
  "offerings": [
    {
      "name": "Product / Project / Package / Dish / Treatment Name",
      "category": "Specific Category / Segment",
      "price": "Price or Starting rate (or 'On Request')",
      "short_description": "1 punchy sentence highlight (<= 120 chars)",
      "description": "Detailed features, inclusions, and specifications",
      "unit": "unit / flat / package / serving / session / month",
      "media_url": "Direct Image URL for this item (if available from crawled images or cards)",
      "detail_url": "Direct link to item page",
      "attrs": {"key": "val"}
    }
  ],
  "faqs": [
    {
      "question": "Realistic customer question?",
      "answer": "Accurate, helpful answer based on site content.",
      "category": "Pricing / Support / Booking / Policies"
    }
  ],
  "knowledge_articles": [
    {
      "title": "Article Title",
      "category": "Company / FAQ",
      "markdown_content": "# Title\\n\\nDetailed content..."
    }
  ]
}

CRITICAL INSTRUCTIONS:
- Whenever an item has an associated image URL from the pre-extracted cards or images, ALWAYS set "media_url" in the offering!
- Return ONLY valid raw JSON.
"""

        user_prompt = (
            f"Pre-extracted Card Data (with images):\n{json.dumps(pre_extracted_offerings[:15], indent=2)}\n\n"
            f"Crawled Website Content for domain '{domain}':\n\n{corpus_text}"
        )

        extracted = self._call_llm(system_prompt, user_prompt)
        if not extracted or not isinstance(extracted, dict) or "brand" not in extracted:
            logger.info("Using universal heuristic extraction for %s", domain)
            extracted = self._heuristic_extraction(crawl_res, domain)

        # Merge pre-extracted card images into offerings if LLM missed any image
        extracted_offerings = extracted.get("offerings", [])
        for off in extracted_offerings:
            if not off.get("media_url"):
                for card in pre_extracted_offerings:
                    if card.get("media_url") and (
                        card.get("name", "").lower() in off.get("name", "").lower()
                        or off.get("name", "").lower() in card.get("name", "").lower()
                    ):
                        off["media_url"] = card["media_url"]
                        break

        return extracted

    def execute_onboarding(
        self,
        url: str,
        target_tenant_id: Optional[str] = None,
        auto_publish: bool = True,
        max_pages: int = 8,
    ) -> Dict[str, Any]:
        """Crawl, extract, cache images, save to DB, compute embeddings, and configure live tenant."""
        crawler = WebScraperCrawler(base_url=url, max_pages=max_pages)
        crawl_res = crawler.crawl()

        if crawl_res.get("blocked_by_robots"):
            raise ValueError(f"robots.txt disallows crawling this site: {url}")
        if not crawl_res.get("pages"):
            raise ValueError(f"Could not reach or crawl website: {url}. Please verify URL is accessible.")

        bifurcation = self.extract_bifurcation(crawl_res)

        brand_data = bifurcation.get("brand", {})
        extracted_name = brand_data.get("name") or crawl_res.get("domain", "brand")
        final_tenant_id = (target_tenant_id or self.tenant_id or slugify(extracted_name)).lower().strip()

        vertical = bifurcation.get("vertical", "generic")
        if vertical not in tenancy_schemas.VERTICALS:
            vertical = "generic"

        # 1. Download & cache brand logo
        logo_url = brand_data.get("logo_url")
        if logo_url:
            cached_logo = download_and_store_image(logo_url, final_tenant_id, "brand_logo")
            if cached_logo:
                brand_data["logo_url"] = cached_logo

        # 2. Download & cache product images
        for idx, off in enumerate(bifurcation.get("offerings", [])):
            img_url = off.get("media_url")
            if img_url:
                cached_img = download_and_store_image(
                    img_url, final_tenant_id, off.get("name") or f"item_{idx}"
                )
                if cached_img:
                    off["media_url"] = cached_img

        # 3. Ensure tenant in database
        tenancy_store.ensure_tenant(
            tenant_id=final_tenant_id,
            slug=final_tenant_id,
            vertical=vertical,
            display_name=extracted_name,
            status="active",
        )

        # 4. Save Brand Profile Draft & Publish
        try:
            from services.auto_bifurcator import AutoBifurcator
            bifurcator = AutoBifurcator(tenant_id=final_tenant_id, actor=self.actor)
            summary = bifurcator.apply_bifurcation(
                bifurcation=bifurcation,
                raw_files=[{"filename": p.get("url"), "text": p.get("content")} for p in crawl_res.get("pages", [])],
                auto_publish=auto_publish,
            )
        except Exception as e:
            logger.error("AutoBifurcator apply failed: %s, executing direct commit", e)
            summary = self._direct_commit(final_tenant_id, bifurcation, vertical, auto_publish)

        # 5. Ensure products table receives media_url, detail_url, and attrs
        self._sync_products_with_images(final_tenant_id, bifurcation.get("offerings", []))

        # 6. Ingest explicit FAQs into faq_dataset with embeddings
        faqs_created = self._ingest_faqs_dataset(final_tenant_id, bifurcation.get("faqs", []))
        summary["faqs_created"] = faqs_created

        # 7. Rebuild Hybrid FAQ FAISS Index
        try:
            from faq.service import faq_index
            faq_index.build(force=True)
            logger.info("HYBRID_FAQ_INDEX_REBUILT | tenant=%s", final_tenant_id)
        except Exception as faq_err:
            logger.warning("Could not rebuild FAQ index: %s", faq_err)

        summary["tenant_id"] = final_tenant_id
        summary["website_url"] = crawl_res.get("root_url")
        summary["pages_crawled"] = [p.get("url") for p in crawl_res.get("pages", [])]
        summary["brand"] = brand_data
        summary["vertical"] = vertical
        summary["offerings_with_images_count"] = sum(1 for o in bifurcation.get("offerings", []) if o.get("media_url"))
        return summary

    def _sync_products_with_images(self, tenant_id: str, offerings: List[Dict[str, Any]]):
        """Guarantee products table stores media_url, media_type, detail_url, and attrs."""
        if not offerings:
            return

        existing = {p["name"].lower(): p for p in list_products(tenant_id=tenant_id)}

        for off in offerings:
            name = off.get("name", "").strip()
            if not name:
                continue

            cat = off.get("category", "General")
            price = str(off.get("price", "On Request"))
            short_desc = off.get("short_description") or name
            desc = off.get("description") or short_desc
            media_url = off.get("media_url")
            detail_url = off.get("detail_url")
            unit = off.get("unit") or "unit"
            attrs = off.get("attrs") or {}

            if name.lower() in existing:
                prod_id = existing[name.lower()]["id"]
                update_product(
                    prod_id,
                    tenant_id=tenant_id,
                    price=price,
                    description=desc,
                    short_description=short_desc,
                    category=cat,
                    media_url=media_url,
                    media_type="image" if media_url else None,
                    detail_url=detail_url,
                    unit=unit,
                    attrs_json=attrs,
                )
            else:
                slug = f"{tenant_id}-{slugify(name)}"[:50]
                save_product(
                    name=name,
                    slug=slug,
                    category=cat,
                    price=price,
                    short_description=short_desc,
                    description=desc,
                    unit=unit,
                    media_url=media_url,
                    media_type="image" if media_url else None,
                    detail_url=detail_url,
                    attrs_json=attrs,
                    tenant_id=tenant_id,
                    actor=self.actor,
                )

    def _direct_commit(
        self, tenant_id: str, bifurcation: Dict[str, Any], vertical: str, auto_publish: bool
    ) -> Dict[str, Any]:
        """Direct database commit."""
        brand = bifurcation.get("brand", {})
        offerings = bifurcation.get("offerings", [])
        self._sync_products_with_images(tenant_id, offerings)

        return {
            "tenant_id": tenant_id,
            "offerings_created": len(offerings),
            "offerings_sample": [o.get("name") for o in offerings[:5]],
            "status": "configured",
        }

    def _ingest_faqs_dataset(self, tenant_id: str, faqs: List[Dict[str, Any]]) -> int:
        """Insert QA pairs into faq_dataset table with vector embeddings."""
        if not faqs:
            return 0

        import numpy as np
        import sqlite3
        from routing.config import DB_PATH, EMBEDDING_MODEL_PATH
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(EMBEDDING_MODEL_PATH)

        qa_chunks = []
        for f in faqs:
            q = f.get("question", "").strip()
            a = f.get("answer", "").strip()
            if q and a:
                qa_text = f"Question: {q}\nAnswer: {a}"
                qa_chunks.append((q, qa_text, f.get("category", "Website FAQ")))

        if not qa_chunks:
            return 0

        texts = [c[1] for c in qa_chunks]
        embeddings = model.encode(texts, batch_size=16, convert_to_numpy=True)
        embeddings = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-10)

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        count = 0
        try:
            for (q, qa_text, cat), emb in zip(qa_chunks, embeddings):
                emb_blob = emb.astype(np.float32).tobytes()
                cur.execute("""
                    INSERT INTO faq_dataset (
                        source_file, content_type, content, page_number,
                        embedding, media_url, media_type, module, tenant_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    f"website_faq_{cat.lower().replace(' ', '_')}.md",
                    "qa",
                    qa_text,
                    1,
                    emb_blob,
                    None,
                    None,
                    "faq",
                    tenant_id,
                ))
                count += 1
            conn.commit()
        finally:
            conn.close()

        logger.info("INGESTED_FAQS_DATASET | tenant=%s | count=%d", tenant_id, count)
        return count
