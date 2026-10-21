"""Build Client_Onboarding_Report.docx with dashboard screenshot frames.

Run from repo root:
    venv/Scripts/python.exe reports/client_onboarding/build_report.py

Placeholders live in reports/client_onboarding/screenshot_frames/ as IMG-01.png ...
To use real screenshots: overwrite those PNG files with same names (or replace
the frames inside the .docx via right-click -> Change Picture) and re-run.
"""
import os
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(OUT_DIR, "screenshot_frames")
DOCX_PATH = os.path.join(OUT_DIR, "Client_Onboarding_Report.docx")
FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"
FONT_PATH_REG = r"C:\Windows\Fonts\arial.ttf"

# (id, screen title, capture path, what must be visible)
SHOTS = [
    ("IMG-01", "Registration wizard - step overview",
     "Admin Console -> Register a tenant (wizard opens on first setup)",
     "Wizard header with the steps: Tenant / WhatsApp / Brand & voice / Your business / Notifications / Guardrails / Review"),
    ("IMG-02", "Registration wizard - WhatsApp step",
     "Admin Console -> Register a tenant -> step 'WhatsApp'",
     "'WhatsApp phone number' field with country code, and working-hours fields"),
    ("IMG-03", "Registration wizard - Brand & voice step",
     "Admin Console -> Register a tenant -> step 'Brand & voice'",
     "Display name, tagline, bot name, tone, menu greeting, closing signature fields"),
    ("IMG-04", "Registration wizard - Your business step",
     "Admin Console -> Register a tenant -> step 'Your business'",
     "Company name, website, support email, support phone, sales email, timezone, opening/closing times"),
    ("IMG-05", "Registration wizard - Notifications step",
     "Admin Console -> Register a tenant -> step 'Notifications'",
     "'Where do enquiries go?' support email field"),
    ("IMG-06", "Registration wizard - Guardrails step",
     "Admin Console -> Register a tenant -> step 'Guardrails'",
     "'What must the bot never do?' never-state list and escalation message"),
    ("IMG-07", "Profile editor - Brand & Working hours",
     "Admin Console -> select tenant -> Profile",
     "Brand card (company name, display name, tagline, bot name) and Working hours card (opens/closes/always open, timezone)"),
    ("IMG-08", "Offerings panel - Products & Services",
     "Admin Console -> select tenant -> Offerings",
     "Offering rows with short label, short description, full description, link, group, 'Visible to the bot' toggle"),
    ("IMG-09", "Uploads panel - FAQ & knowledge base files",
     "Admin Console -> select tenant -> Uploads",
     "Uploaded file list (name, type) and the upload button used for FAQ / policy / brochure documents"),
    ("IMG-10", "Menu editor - WhatsApp main menu",
     "Admin Console -> select tenant -> Menu",
     "Menu sections and rows: title, description, icon, header, body, footer, button text"),
    ("IMG-11", "Team & permissions screen",
     "Admin Console -> Team",
     "Team member list with username, email, role and tenant columns, plus the 'New admin' form"),
]


def make_placeholder(img_id: str, title: str, path: str, visible: str) -> str:
    """Render one screenshot frame placeholder PNG; return its path."""
    w, h = 1280, 760
    img = Image.new("RGB", (w, h), "#f4f6f8")
    d = ImageDraw.Draw(img)
    f_big = ImageFont.truetype(FONT_PATH, 34)
    f_med = ImageFont.truetype(FONT_PATH, 22)
    f_small = ImageFont.truetype(FONT_PATH_REG, 19)

    step, length, col = 22, 18, "#94a3b8"
    y = 12
    while y < h - 12:
        d.line([(12, y), (12, min(y + length, h - 12))], fill=col, width=3)
        d.line([(w - 12, y), (w - 12, min(y + length, h - 12))], fill=col, width=3)
        y += step
    x = 12
    while x < w - 12:
        d.line([(x, 12), (min(x + length, w - 12), 12)], fill=col, width=3)
        d.line([(x, h - 12), (min(x + length, w - 12), h - 12)], fill=col, width=3)
        x += step

    def center(text, font, cy, fill):
        tw = d.textlength(text, font=font)
        d.text(((w - tw) / 2, cy), text, font=font, fill=fill)

    center("SCREENSHOT PLACEHOLDER", f_big, 70, "#64748b")
    center(f"{img_id}  |  {title}", f_med, 150, "#1e293b")
    center(f"Capture from: {path}", f_small, 230, "#334155")
    center("Must show: " + visible[:96], f_small, 270, "#475569")
    if len(visible) > 96:
        center(visible[96:192], f_small, 300, "#475569")
    center("Replace this frame in the Word report with the real screenshot", f_small, h - 130, "#94a3b8")
    center("(right-click the image -> Change Picture -> select your screenshot)", f_small, h - 95, "#94a3b8")

    os.makedirs(IMG_DIR, exist_ok=True)
    p = os.path.join(IMG_DIR, f"{img_id}.png")
    img.save(p)
    return p


def add_shot(doc: Document, img_id: str):
    meta = next(s for s in SHOTS if s[0] == img_id)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(make_placeholder(*meta), width=Inches(6.2))
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = cap.add_run(f"{meta[0]} - {meta[1]}   (Capture: {meta[2]})")
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)


def add_table(doc: Document, rows):
    t = doc.add_table(rows=1, cols=3)
    t.style = "Table Grid"
    hdr = t.rows[0].cells
    for i, name in enumerate(("Information to collect", "Description", "Client input")):
        hdr[i].text = name
        for p in hdr[i].paragraphs:
            for r in p.runs:
                r.font.bold = True
    for item, desc, default in rows:
        c = t.add_row().cells
        c[0].text = item
        c[1].text = desc
        c[2].text = default
    for row in t.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(9.5)
    doc.add_paragraph()


BLANK = ""


def build():
    doc = Document()
    for s in doc.sections:
        s.left_margin = Inches(0.8)
        s.right_margin = Inches(0.8)

    # ---- Cover ----
    doc.add_paragraph()
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("Client Onboarding Report")
    r.font.size = Pt(30)
    r.font.bold = True
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("WhatsApp AI Chatbot & Tenant Platform\nInformation and assets to collect from the client")
    r.font.size = Pt(14)
    r.font.color.rgb = RGBColor(0x33, 0x41, 0x55)

    doc.add_paragraph()
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for k, v in (
        ("Client / Brand name", BLANK),
        ("Tenant ID (short code)", BLANK),
        ("Industry", BLANK),
        ("Prepared by", BLANK),
        ("Date", BLANK),
        ("Version", "1.0"),
    ):
        row = t.add_row().cells
        row[0].text = k
        row[1].text = v
        for p in row[0].paragraphs:
            for rr in p.runs:
                rr.font.bold = True

    doc.add_paragraph()
    doc.add_paragraph(
        "Purpose: this document lists every piece of information and every file we need from the client "
        "to set up, configure and launch their WhatsApp AI chatbot. Each section contains a collection table "
        "and a screenshot of the dashboard screen where that information is configured, so the client can see "
        "exactly where their answers end up."
    )
    doc.add_page_break()

    # ---- Onboarding at a glance ----
    doc.add_heading("Onboarding at a Glance", level=1)
    doc.add_paragraph(
        "Onboarding runs through a guided registration wizard in the Admin Console. The client (or our team on "
        "their behalf) walks through the steps below once; everything collected in this report maps onto one of them."
    )
    add_shot(doc, "IMG-01")

    # ---- 1. Business & brand ----
    doc.add_heading("1. Business & Brand Details", level=1)
    add_table(doc, [
        ("Legal company name", "Registered company name", BLANK),
        ("Brand / display name", "Name shown to customers on WhatsApp", BLANK),
        ("Tagline", "One-line brand tagline", BLANK),
        ("Official website", "Company website URL", BLANK),
        ("Support email", "Customer care email shown by the bot", BLANK),
        ("Support phone", "Customer care helpline number", BLANK),
        ("Sales / enquiries email", "Where sales enquiries are sent", BLANK),
        ("Timezone", "Business timezone (e.g. Asia/Kolkata)", BLANK),
        ("Working hours", "Opens / Closes time, or Always open", BLANK),
        ("Out-of-hours message", "Message shown outside working hours", BLANK),
    ])
    add_shot(doc, "IMG-04")
    add_shot(doc, "IMG-07")

    # ---- 2. WhatsApp number ----
    doc.add_heading("2. WhatsApp Business Number", level=1)
    doc.add_paragraph("The mobile number the chatbot will be connected to (the number customers chat with). Provide the number with country code.")
    add_table(doc, [
        ("WhatsApp phone number", "The number to connect the AI chatbot to, with country code (e.g. +91 XXXXXXXXXX)", BLANK),
        ("Number owner confirmation", "Confirm the client owns this number / has access to its SMS verification", BLANK),
    ])
    add_shot(doc, "IMG-02")

    # ---- 3. Bot persona ----
    doc.add_heading("3. AI Bot Persona & Behaviour", level=1)
    add_table(doc, [
        ("Bot name", "The name the AI assistant introduces itself with", BLANK),
        ("Tone / style", "Professional / Friendly / Casual / Luxury / Technical", BLANK),
        ("Menu greeting", "Greeting sent when the customer opens the chat", BLANK),
        ("Closing signature", "Sign-off line appended to bot messages", BLANK),
        ("Languages", "English, Hindi, Hinglish or regional languages", BLANK),
        ("Human handover trigger words", "Words that transfer the chat to a human (e.g. human, agent, support)", BLANK),
        ("Escalation message", "Message sent when the chat is handed to a human agent", BLANK),
    ])
    add_shot(doc, "IMG-03")

    # ---- 4. Guardrails ----
    doc.add_heading("4. Bot Guardrails (What the Bot Must Never Say)", level=1)
    doc.add_paragraph("A list of statements the bot must never make - written carefully, one per line. Examples: promises about guarantees, legal or medical claims, discount commitments.")
    add_table(doc, [
        ("Never-state list", "Statements the bot must never make, one per line", BLANK),
        ("Compliance notes", "Any regulatory wording restrictions for the industry", BLANK),
    ])
    add_shot(doc, "IMG-06")

    # ---- 5. Notifications ----
    doc.add_heading("5. Notifications & Enquiry Routing", level=1)
    add_table(doc, [
        ("Notifications email", "Email address where new enquiries and alerts are delivered", BLANK),
        ("Urgent enquiry alert", "Phone/email to alert the team for urgent inquiries", BLANK),
    ])
    add_shot(doc, "IMG-05")

    # ---- 6. Products & services ----
    doc.add_heading("6. Products & Services Catalog", level=1)
    doc.add_paragraph("First confirm which optional modules should be enabled, then provide the catalog. The catalog can be supplied as an Excel/CSV sheet using the columns below.")
    add_table(doc, [
        ("Modules to enable", "Products / Products & Schemes / Services / Distributors / Campaigns", BLANK),
        ("Short label", "Product or service name shown in the menu (keep it short)", BLANK),
        ("Short description", "One-line summary the bot uses in menus", BLANK),
        ("Full description", "Detailed description the bot uses when answering questions", BLANK),
        ("Link", "Product page or purchase link (https://...)", BLANK),
        ("Group / category", "Grouping used to organise the catalog", BLANK),
        ("Catalog file", "Excel/CSV with all products or a ready catalog PDF (optional)", BLANK),
    ])
    add_shot(doc, "IMG-08")

    # ---- 7. FAQs & KB ----
    doc.add_heading("7. FAQs & Knowledge Base Documents", level=1)
    doc.add_paragraph("The AI uses this content to answer customer questions 24x7. Please provide:")
    for b in (
        "Frequently Asked Questions - question and answer pairs (Excel or document)",
        "Return / refund / cancellation policy",
        "Warranty, guarantee and service terms",
        "Delivery timelines and shipping charges",
        "Store / office addresses and branch locations",
        "Accepted payment methods",
        "Product brochures, user manuals, policy documents (PDF / DOCX / TXT)",
    ):
        p = doc.add_paragraph(b, style="List Bullet")
        for r in p.runs:
            r.font.size = Pt(10)
    add_shot(doc, "IMG-09")

    # ---- 8. Menu structure ----
    doc.add_heading("8. WhatsApp Main Menu Structure", level=1)
    doc.add_paragraph("How the main WhatsApp menu should look. If the client already has a preferred structure, capture it here; otherwise our team designs one from the catalog and FAQs.")
    add_table(doc, [
        ("Menu header / body / footer", "Header text, welcome body text and footer shown on the main menu", BLANK),
        ("Button text", "Text on the menu button (e.g. Show Options)", BLANK),
        ("Menu sections", "Section names and the options under each section", BLANK),
        ("Option titles, descriptions & icons", "Title, one-line description and icon for each menu option", BLANK),
    ])
    add_shot(doc, "IMG-10")

    # ---- 9. Team accounts ----
    doc.add_heading("9. Team Accounts & Roles", level=1)
    doc.add_paragraph("Team members who need access to the Admin Console and Live Chat Inbox.")
    t = doc.add_table(rows=1, cols=5)
    t.style = "Table Grid"
    for i, name in enumerate(("Full name", "Username", "Email", "Role", "Phone")):
        c = t.rows[0].cells[i]
        c.text = name
        for p in c.paragraphs:
            for r in p.runs:
                r.font.bold = True
    for _ in range(4):
        t.add_row()
    roles = doc.add_paragraph()
    r = roles.add_run("Roles: Tenant Admin (full control) / Sub Admin / Support Agent (live inbox & orders) / Distributor (stock & orders only)")
    r.font.size = Pt(9.5)
    r.font.italic = True
    add_shot(doc, "IMG-11")

    # ---- 10. Brand assets ----
    doc.add_heading("10. Brand Assets & Files to Attach", level=1)
    add_table(doc, [
        ("Brand logo", "High-resolution logo, PNG or JPG, minimum 512 x 512 px", BLANK),
        ("Product images", "Images referenced in the catalog (optional)", BLANK),
        ("Catalog PDF", "Ready-made catalog PDF to share with customers (optional)", BLANK),
        ("FAQ / policy documents", "Files listed in section 7", BLANK),
    ])

    # ---- 11. Next steps ----
    doc.add_heading("11. Submission & Next Steps", level=1)
    for i, s in enumerate(
        (
            "Fill in the tables above for your brand.",
            "Attach your logo, FAQ and product/catalog files.",
            "Send this document to your account manager, or upload it through the Admin Console.",
            "Our team configures your workspace and connects your WhatsApp line for testing.",
            "Go live: after your sign-off on the test conversations, the bot is switched to your live number.",
        ),
        start=1,
    ):
        p = doc.add_paragraph(f"{i}. {s}")
        for r in p.runs:
            r.font.size = Pt(10.5)

    # ---- Appendix ----
    doc.add_page_break()
    doc.add_heading("Appendix A - Dashboard Screens to Capture for This Report", level=1)
    doc.add_paragraph(
        "Every grey frame in this report is a placeholder for a screenshot of the dashboard. Capture each screen listed below, "
        "then replace the matching frame in Word (right-click the frame -> Change Picture -> select the screenshot)."
    )
    t = doc.add_table(rows=1, cols=3)
    t.style = "Table Grid"
    for i, name in enumerate(("Frame", "Dashboard screen", "Where to capture it")):
        c = t.rows[0].cells[i]
        c.text = name
        for p in c.paragraphs:
            for r in p.runs:
                r.font.bold = True
    for img_id, title, path, _vis in SHOTS:
        c = t.add_row().cells
        c[0].text = img_id
        c[1].text = title
        c[2].text = path
    for row in t.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(9)

    doc.save(DOCX_PATH)
    print("saved:", DOCX_PATH)
    print("frames:", IMG_DIR)


if __name__ == "__main__":
    build()
