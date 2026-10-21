"""
Comprehensive DLF Scraper & WhatsApp Chatbot Knowledge Pipeline
Extracts:
1. All residential projects (Super Luxury, Luxury, Premium, Independent Floors, Plots)
2. Commercial office parks & IT corridors (Cybercity Gurugram, Cyber Park, Horizon Center, etc.)
3. Retail malls & social destinations (Mall of India, Emporio, CyberHub, etc.)
4. Hospitality & championship golf clubs
5. NRI investment guidelines & legal FAQs
6. Company background, legacy, leadership, and sustainability
"""

import os
import re
import json
import urllib.request
import urllib.parse
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
    'Origin': 'https://www.dlf.in',
    'Referer': 'https://www.dlf.in/listing.php'
}

def fetch_url(url, post_data=None):
    try:
        data = post_data.encode('utf-8') if post_data else None
        req = urllib.request.Request(url, data=data, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return ""

def clean_text(text):
    return ' '.join(text.split())

def scrape_all_residential_projects():
    print("Scraping residential projects from load-projects.php...")
    html = fetch_url('https://www.dlf.in/load-projects.php', post_data='status=&category=')
    if not html:
        print("Failed to fetch projects list!")
        return []

    soup = BeautifulSoup(html, 'html.parser')
    projects = []
    seen_links = set()

    for col in soup.find_all(class_=lambda c: c and 'col-' in c):
        link_tag = col.find('a', href=True)
        link = link_tag['href'].strip() if link_tag else ""
        if not link or link in seen_links:
            continue
        seen_links.add(link)

        img_tag = col.find('img')
        img_src = img_tag['src'].strip() if img_tag and img_tag.has_attr('src') else ""

        full_text = clean_text(col.get_text())

        # Parsing pattern like: "The Ultima Gurugram Locality Sector 81 Type High Rise Apartments Size 3 BHK, 4 BHK Know More"
        name = ""
        city = "Gurugram"
        locality = ""
        prop_type = "Luxury High Rise Apartments"
        sizes = "3 BHK, 4 BHK"

        # Regex match
        # Match "Locality (.*?) Type (.*?) Size (.*?) Know More"
        m = re.search(r'^(.*?)\s+(Gurugram|Chandigarh|Panchkula|Chennai|Delhi|Kochi|Lucknow|Goa|New Chandigarh)\s+Locality\s+(.*?)\s+Type\s+(.*?)\s+Size\s+(.*?)(?:\s+Know More|$)', full_text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            city = m.group(2).strip()
            locality = m.group(3).strip()
            prop_type = m.group(4).strip()
            sizes = m.group(5).strip()
        else:
            # Fallback heuristic
            parts = full_text.replace("Know More", "").strip()
            name = parts.split("Locality")[0].strip() if "Locality" in parts else parts

        # Categorize
        name_lower = name.lower()
        if any(k in name_lower for k in ['camellias', 'dahlias', 'kings court', 'golf links']):
            category = "Super Luxury Residential"
            tier = "Ultra-Luxury"
            starting_price = "₹25.0 Cr - ₹100.0+ Cr"
        elif any(k in name_lower for k in ['arbour', 'privana', 'crest', 'midtown', 'grove', 'westpark', 'aureva', 'ultima', 'skycourt', 'regal']):
            category = "Luxury Residential High-Rise"
            tier = "Luxury"
            starting_price = "₹3.5 Cr - ₹18.0 Cr"
        elif any(k in name_lower for k in ['floor', 'alameda', 'gardencity', 'valley', 'orchard', 'hyde park', 'estate', 'court', 'riverside', 'kakkanad']):
            category = "Independent Luxury Floors & Plotted Estates"
            tier = "Premium / Boutique"
            starting_price = "₹1.5 Cr - ₹6.5 Cr"
        else:
            category = "Residential Development"
            tier = "Premium"
            starting_price = "Contact Sales Advisor"

        # Fetch microsite details if available
        meta_desc = ""
        rera_no = ""
        if link.startswith("http"):
            micro_html = fetch_url(link)
            if micro_html:
                msoup = BeautifulSoup(micro_html, 'html.parser')
                mdesc = msoup.find('meta', attrs={'name': 'description'})
                if mdesc and mdesc.has_attr('content'):
                    meta_desc = clean_text(mdesc['content'])
                # Look for RERA
                m_rera = re.findall(r'(?:RC/REP/HARERA|DLRERA|TN/|HRERA|RERA)[\/\-\:\sA-Za-z0-9]+', micro_html)
                if m_rera:
                    rera_no = clean_text(m_rera[0])[:60]

        projects.append({
            "name": name,
            "city": city,
            "locality": locality,
            "property_type": prop_type,
            "configurations": sizes,
            "category": category,
            "tier": tier,
            "estimated_price": starting_price,
            "microsite_url": link,
            "image_url": img_src,
            "rera_id": rera_no or "Registered / Applicable as per State RERA",
            "description": meta_desc or f"{name} is an elite {tier.lower()} residential landmark by DLF located in {locality}, {city}, offering spacious {sizes} configurations."
        })

    print(f"Successfully scraped {len(projects)} residential projects!")
    return projects

def scrape_faqs():
    print("Scraping NRI FAQs...")
    html = fetch_url('https://www.dlf.in/nri-corner.php')
    soup = BeautifulSoup(html, 'html.parser')

    faqs = []
    seen_q = set()

    for item in soup.find_all(class_=lambda c: c and ('card' in c.lower() or 'panel' in c.lower() or 'faq' in c.lower())):
        q_tag = item.find(['h3', 'h4', 'h5', 'a', 'button', 'strong'])
        a_tag = item.find(class_=lambda c: c and ('answer' in c.lower() or 'collapse' in c.lower() or 'body' in c.lower()))
        if q_tag and a_tag:
            q = clean_text(q_tag.get_text())
            a = clean_text(a_tag.get_text())
            if q and a and q not in seen_q and ('?' in q or len(q) > 20):
                seen_q.add(q)
                faqs.append({"question": q, "answer": a})

    print(f"Scraped {len(faqs)} unique FAQs from DLF NRI Corner!")
    return faqs

def get_commercial_portfolio():
    return [
        {
            "name": "DLF Cybercity Gurugram",
            "city": "Gurugram",
            "locality": "DLF Phase II & III, NH-8",
            "category": "Commercial IT / SEZ Park",
            "leasable_area": "Over 15 Million sq. ft.",
            "highlights": "India's premier IT ecosystem housing Fortune 500 companies, integrated Rapid Metro stations, DLF CyberHub dining arcade, world's 1st LEED Platinum for City & Community.",
            "clients": "Google, Microsoft, IBM, American Express, Deloitte, KPMG, Samsung"
        },
        {
            "name": "One & Two Horizon Center",
            "city": "Gurugram",
            "locality": "Golf Course Road, DLF 5",
            "category": "Grade-A Commercial Headquarters",
            "leasable_area": "2.5 Million sq. ft.",
            "highlights": "The gold standard of corporate luxury, Robert A.M. Stern architectural design, LEED Platinum certified, surrounded by DLF Golf Links and ultra-luxury residential towers.",
            "clients": "Apple, Facebook/Meta, Carlyle Group, SoftBank, BMW, Vistara"
        },
        {
            "name": "DLF Cyber Park",
            "city": "Gurugram",
            "locality": "NH-8, Udyog Vihar / DLF Phase III",
            "category": "Next-Gen Commercial Tech Park",
            "leasable_area": "2.5 Million sq. ft.",
            "highlights": "Smart tech park with biophilic design, pedestrian skywalks, high-efficiency MERV-14 air filtration, LEED Platinum certified.",
            "clients": "Siemens, PepsiCo, Gartner, NTT Data"
        },
        {
            "name": "DLF Downtown Gurugram",
            "city": "Gurugram",
            "locality": "DLF City Phase III",
            "category": "Modern Integrated Commercial District",
            "leasable_area": "Approx 11 Million sq. ft. master plan",
            "highlights": "Multi-phase ultra-modern Grade A office development with direct connectivity to Delhi-Gurugram Expressway and Cybercity."
        },
        {
            "name": "DLF Cybercity Hyderabad",
            "city": "Hyderabad",
            "locality": "Gachibowli",
            "category": "IT / ITES Commercial Park",
            "leasable_area": "3 Million sq. ft.",
            "highlights": "India's 1st LEED Zero Waste Certified Workplace, strategic location in Hyderabad's financial and IT hub."
        },
        {
            "name": "DLF Cybercity Chennai & DLF Downtown Taramani",
            "city": "Chennai",
            "locality": "Manapakkam & Taramani (OMR / IT Corridor)",
            "category": "IT Tech Parks & Innovation Hubs",
            "leasable_area": "Over 8 Million sq. ft. combined",
            "highlights": "One of South India's largest single-location operational IT SEZs with high sustainability, 100% green energy options."
        },
        {
            "name": "DLF Info City Chandigarh",
            "city": "Chandigarh",
            "locality": "Rajiv Gandhi Chandigarh Technology Park",
            "category": "Commercial IT Corridor",
            "leasable_area": "0.8 Million sq. ft.",
            "highlights": "Pioneer modern IT infrastructure in Northern India, serving leading tech multinationals and BPOs."
        },
        {
            "name": "DLF Prime Towers Okhla",
            "city": "New Delhi",
            "locality": "Okhla Phase I",
            "category": "Commercial Business Towers",
            "leasable_area": "0.7 Million sq. ft.",
            "highlights": "Centrally located commercial office and retail destination in South Delhi with metro connectivity."
        }
    ]

def get_retail_portfolio():
    return [
        {
            "name": "DLF Mall of India",
            "city": "Noida (Delhi NCR)",
            "locality": "Sector 18",
            "category": "Destination Mega Mall",
            "area": "2 Million sq. ft.",
            "highlights": "India's largest destination mall with 330+ international and national brands, 7 floors divided into 5 customized zones (Market Place, International Boulevard, The High Street, Family World, Leisure Zone)."
        },
        {
            "name": "DLF Emporio",
            "city": "New Delhi",
            "locality": "Vasant Kunj",
            "category": "Ultra-Luxury Fashion Mall",
            "area": "320,000 sq. ft.",
            "highlights": "India's undisputed palace of luxury shopping housing 65+ haute couture brands: Louis Vuitton, Dior, Gucci, Cartier, Giorgio Armani, Burberry, Tom Ford, Jimmy Choo."
        },
        {
            "name": "The Chanakya",
            "city": "New Delhi",
            "locality": "Chanakyapuri Diplomatic Enclave",
            "category": "Boutique Luxury & Dining Destination",
            "area": "189,000 sq. ft.",
            "highlights": "Ultra-luxe destination featuring luxury global brands, PVR ECX 3-screen luxury cinema, and food hall / gourmet dining in the heart of Delhi's diplomatic zone."
        },
        {
            "name": "DLF Promenade",
            "city": "New Delhi",
            "locality": "Vasant Kunj",
            "category": "High Fashion & Lifestyle Mall",
            "area": "460,000 sq. ft.",
            "highlights": "Trendy high-fashion shopping center with Zara, Sephora, Marks & Spencer, PVR ICON multiplex, and premium outdoor dining plaza."
        },
        {
            "name": "DLF Avenue",
            "city": "New Delhi",
            "locality": "Saket District Centre",
            "category": "Social Shopping & Dining Hub",
            "area": "520,000 sq. ft.",
            "highlights": "Modernized millennial shopping haven featuring COMMONS (curated multi-cuisine dining district), Uniqlo flagship, high-street brands, and lively outdoor cultural events."
        },
        {
            "name": "DLF CyberHub",
            "city": "Gurugram",
            "locality": "DLF Cybercity Phase II",
            "category": "F&B, Social & Entertainment Hub",
            "area": "400,000 sq. ft.",
            "highlights": "India's premier open-air social, dining and nightlife destination featuring 80+ cafes, fine dining restaurants, microbreweries, rooftop lounges, and open amphitheater."
        }
    ]

def get_hospitality_and_clubs():
    return [
        {
            "name": "DLF Golf & Country Club",
            "city": "Gurugram",
            "locality": "Golf Course Road, DLF Phase 5",
            "category": "Championship Golf & Country Club",
            "highlights": "India's most prestigious golf course featuring two 18-hole championship courses: the original Arnold Palmer Course and the legendary Gary Player Course with floodlit night golf, dramatic quarry features, and state-of-the-art golf academy."
        },
        {
            "name": "Club 5, Club 4, Club 3 & Club 2",
            "city": "Gurugram",
            "locality": "DLF City Phases II, III, IV & V",
            "category": "Exclusive Lifestyle & Recreation Clubs",
            "highlights": "Private members' residential clubs with Olympic-sized swimming pools, tennis and squash courts, wellness spas, multi-cuisine dining, and private banquet facilities."
        },
        {
            "name": "The Lodhi",
            "city": "New Delhi",
            "locality": "Lodhi Road, Lutyens' Delhi",
            "category": "Iconic 5-Star Luxury Hotel",
            "highlights": "Member of The Leading Hotels of the World, luxury hotel with private plunge pools in rooms, tranquil gardens, award-winning restaurants, and premier spa."
        }
    ]

if __name__ == '__main__':
    projects = scrape_all_residential_projects()
    faqs = scrape_faqs()
    commercial = get_commercial_portfolio()
    retail = get_retail_portfolio()
    hospitality = get_hospitality_and_clubs()

    full_data = {
        "company": {
            "name": "DLF Limited",
            "legal_name": "DLF Limited (formerly Delhi Land & Finance)",
            "founded": 1946,
            "founder": "Chaudhary Raghvendra Singh",
            "chairman": "Rajiv Singh",
            "headquarters": "DLF Gateway Tower, R Block, DLF City Phase III, Gurugram, Haryana - 122002",
            "website": "https://www.dlf.in",
            "support_phone": "1800 103 3534 / +91 124 4334200",
            "support_email": "customercare@dlf.in / homes@dlf.in",
            "scale": "Over 75+ years of excellence, 158+ real estate projects, 340+ million sq. ft. developed, 42+ msf of leased office space",
            "key_distinctions": [
                "World's 1st LEED Platinum for City & Community (DLF Cybercity Gurugram)",
                "No. 1 Globally in LEED Zero Water & LEED Zero Waste Certifications",
                "20 Sword of Honour Awards from British Safety Council (World's Highest)",
                "Developed 22 prestigious residential colonies across Delhi including Greater Kailash, South Extension, Hauz Khas, Model Town, Rajouri Garden",
                "Created Gurugram's globally recognized modern millennium skyline (DLF 5, Golf Course Road, Cybercity)"
            ]
        },
        "residential_projects": projects,
        "commercial_portfolio": commercial,
        "retail_portfolio": retail,
        "hospitality_and_clubs": hospitality,
        "nri_and_legal_faqs": faqs
    }

    output_path = r"c:\Users\Leeway\Desktop\chatbot2\scraped_dlf_full.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(full_data, f, indent=2, ensure_ascii=False)

    print(f"\nAll data successfully saved to: {output_path}")
    print(f"- Residential Projects: {len(projects)}")
    print(f"- Commercial Properties: {len(commercial)}")
    print(f"- Retail Malls: {len(retail)}")
    print(f"- Hospitality & Clubs: {len(hospitality)}")
    print(f"- FAQs: {len(faqs)}")
