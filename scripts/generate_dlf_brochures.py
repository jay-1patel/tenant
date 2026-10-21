import os
import subprocess
import sqlite3

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
KB_DIR = r"c:\Users\Leeway\Desktop\chatbot2\backend\uploaded_files\kb"
CLIENT_BROCHURE_DIR = r"c:\Users\Leeway\Desktop\chatbot2\clients\dlf\brochures"

os.makedirs(KB_DIR, exist_ok=True)
os.makedirs(CLIENT_BROCHURE_DIR, exist_ok=True)

CSS_STYLE = """
@page {
    size: A4;
    margin: 15mm 15mm 15mm 15mm;
    @bottom-right { content: counter(page); }
}
body {
    font-family: 'Segoe UI', Arial, sans-serif;
    color: #1e293b;
    line-height: 1.5;
    background: #ffffff;
    font-size: 13px;
}
.header {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: white;
    padding: 24px;
    border-radius: 6px;
    margin-bottom: 20px;
}
.brand-badge {
    display: inline-block;
    background: #0ea5e9;
    color: white;
    font-size: 11px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
    text-transform: uppercase;
    margin-bottom: 8px;
}
h1 { font-size: 24px; margin: 0 0 6px 0; color: white; }
.sub { color: #94a3b8; font-size: 13px; }
.card {
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 16px;
    margin-bottom: 16px;
    background: #f8fafc;
    page-break-inside: avoid;
}
.card h2 {
    font-size: 16px;
    color: #0f172a;
    margin-top: 0;
    margin-bottom: 8px;
    border-bottom: 2px solid #0ea5e9;
    padding-bottom: 4px;
}
.grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
}
.item-box {
    background: white;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 10px 12px;
}
.item-title { font-weight: 700; color: #0284c7; font-size: 13px; margin-bottom: 3px; }
.item-sub { color: #475569; font-size: 12px; }
.rera-badge {
    background: #fef3c7;
    border: 1px solid #f59e0b;
    color: #92400e;
    font-size: 11px;
    font-weight: 600;
    padding: 4px 8px;
    border-radius: 4px;
    margin-top: 8px;
    display: inline-block;
}
.footer {
    border-top: 1px solid #cbd5e1;
    padding-top: 10px;
    margin-top: 20px;
    font-size: 11px;
    color: #64748b;
    display: flex;
    justify-content: space-between;
}
.page-break { page-break-before: always; }
"""

brochures_data = [
    {
        "filename": "DLF_Master_Residential_Portfolio.pdf",
        "title": "DLF Residential Master Portfolio Deck",
        "subtitle": "Complete Overview of Super Luxury, High-Rise & Independent Floors Across India",
        "doc_title": "DLF Limited — Official Residential Deck",
        "content_html": """
        <div class="card">
            <h2>1. Super Luxury Flagships (Golf Course Road, Gurugram)</h2>
            <div class="grid">
                <div class="item-box">
                    <div class="item-title">The Dahlias (Sector 54, Gurugram)</div>
                    <div class="item-sub">Palatial Sky Mansions & Penthouses with artificial lake frontage. RERA: RC/REP/HARERA/GGM/872/604/2024/99. Price on Request.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">The Camellias (DLF 5, Gurugram)</div>
                    <div class="item-sub">Acclaimed super-luxury apartments facing Gary Player championship golf course with 7-star clubhouse.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">King's Court (GK-II, New Delhi)</div>
                    <div class="item-sub">Ultra-luxe residences in South Delhi with private elevator lobbies, swimming pool & concierge.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">DLF5 Golf Links (Gurugram)</div>
                    <div class="item-sub">The Crest & The Aralias enclave overlooking pristine golf greens.</div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>2. Luxury High-Rise Condominiums</h2>
            <div class="grid">
                <div class="item-box">
                    <div class="item-title">The Arbour (Sector 63, Gurugram)</div>
                    <div class="item-sub">4 BHK Luxury Residences (3,950 sq.ft.) on Golf Course Extn Rd. 85% green cover. RERA: RC/REP/HARERA/GGM/671/403/2023/15. Starting ₹7.5 Cr.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">DLF Privana South / West (Sector 76/77)</div>
                    <div class="item-sub">4 BHK + Utility + Staff (3,577 sq.ft.) & Penthouses nestled by Aravalli foothills. Starting ₹6.5 Cr.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">One Midtown (Moti Nagar, West Delhi)</div>
                    <div class="item-sub">2, 3 & 4 BHK Luxury Condominiums neighboring 128 acres of greenery. 45,000 sq.ft. club. RERA: DLRERA2021P0007. Starting ₹3.8 Cr.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">The Ultima (Sector 81, Gurugram)</div>
                    <div class="item-sub">Ready to Move 3 & 4 BHK + Servant homes neighboring 405 hectares of reserved greenery. Starting ₹3.2 Cr.</div>
                </div>
            </div>
        </div>

        <div class="page-break"></div>

        <div class="card">
            <h2>3. Independent Luxury Floors & Regional Plotted Estates</h2>
            <div class="grid">
                <div class="item-box">
                    <div class="item-title">DLF City Phases I, II, III & IV Floors</div>
                    <div class="item-sub">Low-rise Stilt + 4 floors. 4 BHK with private elevator, basement home office & private terrace. Starting ₹3.2 Cr.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Alameda Floors (Sector 73, Gurugram)</div>
                    <div class="item-sub">3 & 4 BHK boutique low-rise residences in an expansive gated enclave with complete floor privacy. Starting ₹2.8 Cr.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">The Valley Gardens & Orchard (Panchkula)</div>
                    <div class="item-sub">Low-rise floors and plots surrounded by scenic Shivalik mountain foothills. Starting ₹1.8 Cr.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Hyde Park (New Chandigarh) & Parc Estate (Chennai)</div>
                    <div class="item-sub">Plotted estates and ready boutique residences in prime urban growth corridors.</div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2>4. Booking Process & Approved Home Loan Partners</h2>
            <p><strong>Booking Token:</strong> ₹5L–₹10L for Floors | ₹10L–₹25L for Luxury | ₹50L–₹1Cr for Super Luxury.</p>
            <p><strong>Payment Schemes:</strong> Construction Linked Plan (CLP), Possession Linked (25:75), Down Payment with upfront discount.</p>
            <p><strong>Pre-Approved Banks:</strong> State Bank of India (SBI), HDFC Bank, ICICI Bank, Axis Bank, Kotak Mahindra Bank.</p>
            <div class="rera-badge">100% RERA Registered • Clear Freehold Titles • 0% GST on Ready-to-Move OC Units</div>
        </div>
        """
    },
    {
        "filename": "DLF_The_Dahlias_Super_Luxury_Deck.pdf",
        "title": "The Dahlias — Super Luxury Flagship",
        "subtitle": "Golf Course Road, Sector 54, Gurugram • Ultra-Luxury Sky Mansions",
        "doc_title": "The Dahlias by DLF — Project Specifications & Deck",
        "content_html": """
        <div class="card">
            <h2>Project Overview & Master Plan</h2>
            <p>The Dahlias is DLF's most ambitious ultra-luxury residential development following the global acclaim of The Camellias. Set amidst lush greenery with an artificial lake frontage on Sector 54 Golf Course Road, Gurugram.</p>
            <div class="rera-badge">HARERA Registration No.: RC/REP/HARERA/GGM/872/604/2024/99 dated 04.10.2024 (haryanarera.gov.in)</div>
        </div>
        <div class="card">
            <h2>Architectural Highlights & Specifications</h2>
            <div class="grid">
                <div class="item-box">
                    <div class="item-title">Typologies & Areas</div>
                    <div class="item-sub">Grand Palatial Apartments (9,500 sq.ft. to 16,000+ sq.ft.) and Duplex Sky Mansions with private lap pools.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Private Elevators & Lobbies</div>
                    <div class="item-sub">High-speed dual passenger elevators opening into private access-controlled foyer.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">The Grand Clubhouse</div>
                    <div class="item-sub">200,000+ sq.ft. multi-level club with heated indoor pool, outdoor resort pool, spa, fine dining, private theatre.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Air Quality & Sustainability</div>
                    <div class="item-sub">Hospital-grade MERV-14 treated fresh air filtration and VRV central climate control.</div>
                </div>
            </div>
        </div>
        <div class="card">
            <h2>Location & Connectivity</h2>
            <p>Direct frontage on Golf Course Road, DLF Phase 5. Walking distance to Sector 54 Rapid Metro station, Horizon Center, DLF CyberHub, and DLF Golf and Country Club.</p>
        </div>
        """
    },
    {
        "filename": "DLF_The_Arbour_Luxury_Residences.pdf",
        "title": "The Arbour — Luxury High-Rise Residences",
        "subtitle": "Sector 63, Golf Course Extension Road, Gurugram",
        "doc_title": "The Arbour by DLF — Project Brochure",
        "content_html": """
        <div class="card">
            <h2>Project Overview</h2>
            <p>The Arbour is DLF's landmark low-density luxury high-rise development set across 25 acres with 85% dedicated green spaces on Sector 63, Golf Course Extension Road, Gurugram.</p>
            <div class="rera-badge">HARERA Registration No.: RC/REP/HARERA/GGM/671/403/2023/15 dated 23.02.2023</div>
        </div>
        <div class="card">
            <h2>Key Specifications</h2>
            <div class="grid">
                <div class="item-box">
                    <div class="item-title">Configuration</div>
                    <div class="item-sub">Spacious 4 BHK + Utility + Staff Residences (Super Area ~3,950 sq.ft.).</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Low Density Living</div>
                    <div class="item-sub">Only 2 residences per floor with 3 high-speed elevators per core for utmost privacy.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Club Arbour (100,000 sq.ft.)</div>
                    <div class="item-sub">Grand multi-tier clubhouse, temperature-controlled pool, bowling alley, badminton, squash courts, banquet hall.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Price & Payment Plan</div>
                    <div class="item-sub">Starting ₹7.5 Cr. Flexible Construction Linked Payment Plan (CLP) with approved bank loans.</div>
                </div>
            </div>
        </div>
        """
    },
    {
        "filename": "DLF_Privana_South_Project_Brochure.pdf",
        "title": "DLF Privana South & West",
        "subtitle": "Sector 76 & 77, Southern Peripheral Road (SPR), Gurugram",
        "doc_title": "DLF Privana — Project Brochure & Floor Plans",
        "content_html": """
        <div class="card">
            <h2>Integrated 116-Acre Township by DLF</h2>
            <p>DLF Privana represents an expansive master-planned township nestled directly against the scenic Aravalli mountain ranges in Sectors 76 and 77, Gurugram. Direct access to CPR, SPR, and NH-48.</p>
            <div class="rera-badge">Registered under HARERA Gurugram (haryanarera.gov.in)</div>
        </div>
        <div class="card">
            <h2>Residences & Features</h2>
            <div class="grid">
                <div class="item-box">
                    <div class="item-title">Unit Typology</div>
                    <div class="item-sub">4 BHK + Utility + Staff (3,577 sq.ft.) and limited iconic Sky Penthouses (5,500+ sq.ft.).</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Vehicle-Free Surface</div>
                    <div class="item-sub">100% vehicle-free ground boulevard with dedicated underground access for seamless pedestrian safety.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Lifestyle Amenities</div>
                    <div class="item-sub">Grand clubhouse, infinity swimming pool, tennis and pickleball courts, multi-cuisine dining, jogging trails.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Pricing Guidance</div>
                    <div class="item-sub">Starting ₹6.5 Cr. Token booking amount ₹10 Lakhs. Pre-approved home loans from SBI, HDFC & ICICI.</div>
                </div>
            </div>
        </div>
        """
    },
    {
        "filename": "DLF_One_Midtown_Delhi_Brochure.pdf",
        "title": "DLF One Midtown — Luxury Residences",
        "subtitle": "Shivaji Marg / Moti Nagar, West Delhi",
        "doc_title": "One Midtown by DLF — Official Delhi Brochure",
        "content_html": """
        <div class="card">
            <h2>The Green Oasis in Central Delhi</h2>
            <p>One Midtown is DLF's premier luxury residential project in India's capital. Located on Shivaji Marg, Moti Nagar, West Delhi, surrounded by 128 acres of lush green parks with seamless metro connectivity to CP and Airport.</p>
            <div class="rera-badge">Delhi RERA Registration No.: DLRERA2021P0007</div>
        </div>
        <div class="card">
            <h2>Apartment Specifications</h2>
            <div class="grid">
                <div class="item-box">
                    <div class="item-title">Typologies Available</div>
                    <div class="item-sub">2 BHK, 3 BHK & 4 BHK Luxury High-Rise Condominiums (1,732 sq.ft. to 3,030 sq.ft.).</div>
                </div>
                <div class="item-box">
                    <div class="item-title">45,000 sq.ft. Club Midtown</div>
                    <div class="item-sub">Olympic-length swimming pool, salon & spa, squash courts, gymnasium, banquet terrace, multi-cuisine cafe.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Interiors & Finishes</div>
                    <div class="item-sub">Italian marble flooring, VRV air conditioning, double-glazed soundproof glass, modular kitchen with appliances.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Pricing & Possession</div>
                    <div class="item-sub">Starting ₹3.8 Cr. Advanced construction stage with phased possession schedules.</div>
                </div>
            </div>
        </div>
        """
    },
    {
        "filename": "DLF_Independent_Floors_Brochure.pdf",
        "title": "DLF Independent Luxury Floors",
        "subtitle": "DLF City Phases I, II, III & Alameda Sector 73, Gurugram",
        "doc_title": "DLF Independent Floors — Low-Rise Living Deck",
        "content_html": """
        <div class="card">
            <h2>The Luxury of Private, Low-Rise Living</h2>
            <p>DLF Independent Floors offer the independence of villa-style single-floor residences combined with DLF's established urban infrastructure, wide tree-lined avenues, and dedicated security.</p>
        </div>
        <div class="card">
            <h2>Unique Home Features</h2>
            <div class="grid">
                <div class="item-box">
                    <div class="item-title">Stilt + 4 Floors Structure</div>
                    <div class="item-sub">One luxury home per floor with private elevator access and no shared walls.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Dedicated Basement & Terrace</div>
                    <div class="item-sub">Exclusive air-conditioned basement home-office / storage and dedicated terrace rights.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Covered Stilt Parking</div>
                    <div class="item-sub">2 to 3 dedicated covered car parking bays per residence in stilt.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Pricing & Availability</div>
                    <div class="item-sub">Starting ₹2.8 Cr (Alameda) & ₹3.2 Cr (DLF City). Ready & under-construction phases available.</div>
                </div>
            </div>
        </div>
        """
    },
    {
        "filename": "DLF_NRI_Investment_Legal_Handbook.pdf",
        "title": "DLF NRI Property Investment & Legal Guide",
        "subtitle": "FEMA 1999 Rules, RBI General Permissions & Taxation Framework",
        "doc_title": "DLF NRI Advisory & Legal Compliance Handbook",
        "content_html": """
        <div class="card">
            <h2>1. Eligibility & General RBI Permission</h2>
            <p>Under Section 2(v) of FEMA 1999 and Master Direction on Acquisition of Immovable Property, <strong>NRIs, PIOs, and OCIs</strong> have general permission to purchase any residential or commercial property in India without prior RBI approval.</p>
        </div>
        <div class="card">
            <h2>2. Financial Modes & Repatriation</h2>
            <div class="grid">
                <div class="item-box">
                    <div class="item-title">Permitted Accounts</div>
                    <div class="item-sub">Payments can be remitted from overseas via inward banking channels or debited from NRE / FCNR(B) / NRO bank accounts.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Repatriation of Sale Proceeds</div>
                    <div class="item-sub">Sale proceeds of up to two residential properties purchased via foreign exchange/NRE can be freely repatriated up to USD 1 Million per FY.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Home Loans for NRIs</div>
                    <div class="item-sub">Up to 80% home loans available from SBI, HDFC & ICICI for tenure up to 20-30 years based on overseas income.</div>
                </div>
                <div class="item-box">
                    <div class="item-title">Power of Attorney (POA)</div>
                    <div class="item-sub">Overseas buyers can execute registered POA for local execution of Builder-Buyer Agreements and registration.</div>
                </div>
            </div>
        </div>
        """
    }
]

for b in brochures_data:
    fname = b["filename"]
    pdf_path_kb = os.path.join(KB_DIR, fname)
    pdf_path_client = os.path.join(CLIENT_BROCHURE_DIR, fname)
    html_temp = os.path.join(KB_DIR, fname.replace(".pdf", ".html"))

    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{b['doc_title']}</title>
<style>{CSS_STYLE}</style>
</head>
<body>
    <div class="header">
        <div class="brand-badge">DLF Limited • Real Estate Official Document</div>
        <h1>{b['title']}</h1>
        <div class="sub">{b['subtitle']}</div>
    </div>
    {b['content_html']}
    <div class="footer">
        <div>DLF Gateway Tower, DLF City Phase III, Gurugram | Helpline: +91 124 4334200</div>
        <div>Official Portal: www.dlf.in | customercare@dlf.in</div>
    </div>
</body>
</html>"""

    with open(html_temp, "w", encoding="utf-8") as f:
        f.write(full_html)

    # Compile to PDF
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path_kb}",
        html_temp
    ]
    subprocess.run(cmd, capture_output=True, text=True)

    # Copy to client dir
    import shutil
    shutil.copyfile(pdf_path_kb, pdf_path_client)

    if os.path.exists(html_temp):
        os.remove(html_temp)

    size = os.path.getsize(pdf_path_kb)
    print(f"Generated {fname} ({size / 1024:.1f} KB)")

print("\nAll 7 official DLF PDF brochures compiled successfully!")
