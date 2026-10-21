import os
import json

SOURCE_JSON = r"c:\Users\Leeway\Desktop\chatbot2\scraped_dlf_full.json"
CLIENT_DIR = r"c:\Users\Leeway\Desktop\chatbot2\clients\dlf"
KB_DIR = os.path.join(CLIENT_DIR, "knowledge")

os.makedirs(KB_DIR, exist_ok=True)

with open(SOURCE_JSON, "r", encoding="utf-8") as f:
    data = json.load(f)

company = data["company"]
projects = data["residential_projects"]
commercial = data["commercial_portfolio"]
retail = data["retail_portfolio"]
hospitality = data["hospitality_and_clubs"]
faqs = data["nri_and_legal_faqs"]

# 1. 01_company_and_overview.md
doc1 = f"""# {company['name']} — Company Profile, Heritage & Leadership

## 1. Corporate Identity & Legacy
- **Legal Entity**: {company['legal_name']}
- **Founded**: {company['founded']} by {company['founder']}
- **Chairman**: {company['chairman']}
- **Corporate Headquarters**: {company['headquarters']}
- **Official Website**: {company['website']}
- **Helpline**: {company['support_phone']}
- **Customer Email**: {company['support_email']}
- **Operational Scale**: {company['scale']}

## 2. Unrivalled Track Record
DLF has over 75 years of real estate development and investment track record across India:
1. **Urban Colonization of Delhi**: Pioneered 22 major residential colonies across Delhi including Greater Kailash (GK 1 & 2), South Extension, Hauz Khas, Model Town, Rajouri Garden, Punjabi Bagh, and Shivaji Marg.
2. **Creation of Gurugram (Millennium City)**: Single-handedly transformed agricultural land into India's leading financial and tech powerhouse—DLF City (Phases 1 to 5), Golf Course Road, and DLF Cybercity.
3. **Integrated Community Development**: Developed comprehensive urban ecosystems integrating residential condominiums, Grade-A IT offices, luxury malls, metro connectivity, private clubs, and championship golf courses.

## 3. Global Accreditations & Safety Distinctions
- **World's 1st LEED Platinum for City & Community**: Awarded to DLF Cybercity Gurugram by the U.S. Green Building Council (USGBC).
- **No. 1 Globally in LEED Zero Water & LEED Zero Waste**: Validating DLF's leadership in environmental stewardship.
- **20 Sword of Honour Awards**: Conferred by the British Safety Council—the highest number of Sword of Honour accolades awarded to any single company in the world for workplace health and safety.
- **100% Green Energy**: DLF commercial campuses operate on extensive solar and green energy power purchase agreements.

## 4. Business Segments
1. **DLF Homes**: Super Luxury, Luxury, and Premium residential condominiums, penthouses, independent floors, and plotted colonies.
2. **DLF Offices**: Leased commercial Grade-A office buildings and IT parks spanning Gurugram, Chennai, Hyderabad, Delhi, Kolkata, Chandigarh, and Noida.
3. **DLF Retail**: Premium and luxury shopping malls including DLF Mall of India, DLF Emporio, The Chanakya, DLF Promenade, DLF Avenue, and DLF CyberHub.
4. **DLF Hospitality & Clubs**: DLF Golf & Country Club, residential lifestyle clubs (Club 5/4/3/2), and luxury hotel properties including The Lodhi New Delhi.
"""
with open(os.path.join(KB_DIR, "01_company_and_overview.md"), "w", encoding="utf-8") as f:
    f.write(doc1)

# 2. 02_super_luxury_and_luxury_residences.md
luxury_projects = [p for p in projects if any(k in p['name'].lower() for k in [
    'camellias', 'dahlias', 'kings court', 'golf links', 'arbour', 'privana', 'crest', 'midtown', 'grove', 'westpark', 'aureva', 'ultima', 'skycourt', 'regal'
])]

doc2 = f"""# DLF Super Luxury & Luxury High-Rise Residences

DLF's flagship residential portfolio comprises world-class architectural marvels, ultra-luxury penthouses, and high-rise residences with panoramic views, private elevators, and five-star clubhouses.

"""

for p in luxury_projects:
    doc2 += f"""## {p['name']}
- **Location**: {p['locality']}, {p['city']}
- **Category & Tier**: {p['category']} ({p['tier']})
- **Typology & Configurations**: {p['configurations']} ({p['property_type']})
- **Price Guidance**: {p['estimated_price']}
- **RERA Certification**: {p['rera_id']}
- **Official Portal**: {p['microsite_url']}
- **Project Overview**: {p['description']}

### Key Features & Lifestyle Amenities:
- Exclusive club facilities with temperature-controlled indoor/outdoor swimming pools.
- Multi-tier 24x7 biometric security, private elevator lobbies, and dedicated concierge services.
- VRV/VRF central air conditioning with MERV-14 treated fresh air systems.
- Expansive landscaped decks, sports courts (squash, tennis, badminton), and private banquet lounges.

---

"""

with open(os.path.join(KB_DIR, "02_super_luxury_and_luxury_residences.md"), "w", encoding="utf-8") as f:
    f.write(doc2)

# 3. 03_independent_floors_and_plotted_estates.md
floors_and_plots = [p for p in projects if p not in luxury_projects]

doc3 = f"""# DLF Independent Luxury Floors & Plotted Developments

DLF Independent Floors offer low-rise exclusivity, privacy of single-floor living, dedicated basement storage and staff suites, private terrace rights, and covered stilt parking.

"""

for p in floors_and_plots:
    doc3 += f"""## {p['name']}
- **Location**: {p['locality']}, {p['city']}
- **Property Type**: {p['property_type']}
- **Configurations Available**: {p['configurations']}
- **Price Guidance**: {p['estimated_price']}
- **RERA Certification**: {p['rera_id']}
- **Official Link**: {p['microsite_url']}
- **Overview**: {p['description']}

### Design Highlights:
- Low-rise development (Stilt + 4 Floors) with dedicated passenger elevator.
- One home per floor ensuring complete exclusivity and personal privacy.
- Fully fitted modular kitchen with premium built-in appliances (chimney, hob, microwave, oven).
- Designated staff room with attached bath and exclusive basement home-office / storage space.
- Dedicated covered car parking bays in stilt.

---

"""

with open(os.path.join(KB_DIR, "03_independent_floors_and_plotted_estates.md"), "w", encoding="utf-8") as f:
    f.write(doc3)

# 4. 04_commercial_offices_and_it_parks.md
doc4 = """# DLF Offices — Grade-A Commercial Real Estate & Tech Parks

DLF is India's largest office landlord, managing over 42 million sq. ft. of leasable Grade-A workspaces across prime business districts.

"""
for c in commercial:
    doc4 += f"""## {c['name']}
- **City & Micro-Market**: {c['locality']}, {c['city']}
- **Development Type**: {c['category']}
- **Leasable Area**: {c['leasable_area']}
- **Architectural & Green Credentials**: {c['highlights']}
"""
    if "clients" in c:
        doc4 += f"- **Marquee Occupants**: {c['clients']}\n"
    doc4 += "\n---\n\n"

with open(os.path.join(KB_DIR, "04_commercial_offices_and_it_parks.md"), "w", encoding="utf-8") as f:
    f.write(doc4)

# 5. 05_retail_malls_and_lifestyle_clubs.md
doc5 = """# DLF Retail & Hospitality — Iconic Destinations & Lifestyle Clubs

DLF curates India's premier social, fashion, shopping, dining, and championship sports hubs.

## 1. Flagship Retail Destinations
"""
for r in retail:
    doc5 += f"""### {r['name']} ({r['city']})
- **Location**: {r['locality']}
- **Mall Profile**: {r['category']} ({r['area']})
- **Highlights**: {r['highlights']}

"""

doc5 += """\n## 2. Championship Golf & Residential Lifestyle Clubs\n"""
for h in hospitality:
    doc5 += f"""### {h['name']} ({h['city']})
- **Location**: {h['locality']}
- **Facility Type**: {h['category']}
- **Experience & Inclusions**: {h['highlights']}

"""

with open(os.path.join(KB_DIR, "05_retail_malls_and_lifestyle_clubs.md"), "w", encoding="utf-8") as f:
    f.write(doc5)

# 6. 06_booking_payments_and_loans.md
doc6 = """# DLF Property Booking Process, Payment Plans & Home Loans

## 1. Step-by-Step Property Purchase Workflow
1. **Initial Consultation & Shortlisting**: Customer explores residential typologies, configurations, and pricing via WhatsApp or sales consultation.
2. **Site Visit / Virtual Tour Scheduling**: Dedicated Relationship Manager arranges escorted site visit to model apartments and project sites.
3. **Expression of Interest (EOI) & Application**: Buyer selects unit number, submits KYC documents (PAN card, Aadhaar / Passport, Photographs) and application form.
4. **Booking Token Payment**:
   - Independent Floors: ₹5 Lakhs to ₹10 Lakhs.
   - Luxury Apartments: ₹10 Lakhs to ₹25 Lakhs.
   - Super Luxury (Camellias / Dahlias): ₹50 Lakhs to ₹1.00 Crore.
5. **Allotment Letter & Agreement for Sale (BBA)**: Builder-Buyer Agreement executed within 30 to 45 days in compliance with statutory RERA provisions.
6. **Milestone Payments**: Buyer disburses staged payments as per construction milestones or bank loan schedule.
7. **Possession & Conveyance Deed**: Upon receipt of Occupancy Certificate (OC), final settlement is executed, keys handed over, and property registered with sub-registrar.

## 2. Standard Payment Plans
- **Construction Linked Plan (CLP)**: Payments tied to slab casting, brickwork, MEP, finishing, and possession.
- **Possession Linked Plan (PLP)**: 20-30% upfront, remaining on offer of possession.
- **Down Payment Plan (DPP)**: Upfront payment with developer subvention / upfront discount where applicable.

## 3. Approved Banking Partners & Home Loan Tie-ups
DLF developments are pre-approved by all leading financial institutions for fast-track home loan processing:
- **State Bank of India (SBI)**
- **HDFC Bank**
- **ICICI Bank**
- **Axis Bank**
- **Kotak Mahindra Bank**
- **Bank of Baroda**

## 4. Statutory Charges & Government Dues
- **Stamp Duty & Registration**: Payable as per state government guidelines at the time of registration.
- **GST**: 5% on under-construction non-affordable residential property (0% GST on ready-to-move-in properties with OC).
- **IFMS (Interest-Free Maintenance Security)** & Advance Maintenance Charges: Credited to Residents Welfare Association (RWA) account upon handover.
"""
with open(os.path.join(KB_DIR, "06_booking_payments_and_loans.md"), "w", encoding="utf-8") as f:
    f.write(doc6)

# 7. 07_nri_investments_and_legal_faqs.md
doc7 = """# DLF NRI Property Investment Guidelines & Legal FAQs

DLF welcomes Non-Resident Indians (NRIs), Persons of Indian Origin (PIOs), and Overseas Citizens of India (OCIs) to invest in India's leading real estate assets.

"""
for idx, item in enumerate(faqs, 1):
    doc7 += f"""### Q{idx}: {item['question']}
**Answer**: {item['answer']}

---

"""

with open(os.path.join(KB_DIR, "07_nri_investments_and_legal_faqs.md"), "w", encoding="utf-8") as f:
    f.write(doc7)

print("Generated all 7 Knowledge Base Markdown files in:", KB_DIR)
