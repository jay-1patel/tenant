from __future__ import annotations

from pathlib import Path
import io

import fitz
from PIL import Image

import make_report as mr

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports' / 'chatbot-client-onboarding-guide.pdf'
ASSETS = ROOT / 'reports' / 'assets' / 'onboarding'

PAGE_W, PAGE_H = mr.PAGE_W, mr.PAGE_H
MARGIN = mr.MARGIN
CONTENT_W = mr.CONTENT_W
INK, MUTED, PURPLE, ORANGE, GREEN = mr.INK, mr.MUTED, mr.PURPLE, mr.ORANGE, mr.GREEN

# The base-14 PDF fonts cannot encode bullets, middle dots or arrows — those
# glyphs silently render as U+FFFD. Transliterate everything to ASCII instead.
_ASCII_MAP = {
    '\u2022': '-', '\u00b7': '-', '\u2014': '--', '\u2013': '-',
    '\u2610': '[ ]', '\u2192': '->', '\u2713': 'v',
    '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
    '\u00d7': 'x', '\u2264': '<=', '\u20b9': 'Rs.',
}


def ascii_clean(value: str) -> str:
    value = ''.join(_ASCII_MAP.get(ch, ch) for ch in value)
    return value.encode('latin-1', 'replace').decode('latin-1')


mr.clean = ascii_clean


class Guide(mr.Report):
    """The client-onboarding guide: a complete field-by-field data
    specification (every input the client must provide), followed by a photo
    of every admin panel page."""

    def _footer(self):
        self.page.draw_line((MARGIN, PAGE_H - 35), (PAGE_W - MARGIN, PAGE_H - 35), color=mr.LINE, width=0.6)
        self.page.insert_text((MARGIN, PAGE_H - 20), 'AI WHATSAPP CHATBOT  /  CLIENT ONBOARDING GUIDE', fontsize=7.5, fontname='helv', color=MUTED)
        self.page.insert_text((PAGE_W - MARGIN - 22, PAGE_H - 20), f'{self.pages:02d}', fontsize=8, fontname='hebo', color=PURPLE)

    def bullet(self, text, checked=False, level=0):
        prefix = '[ ]' if checked else '-'
        xoff = level * 14
        self._ensure(28)
        self.page.insert_text((MARGIN + xoff, self.y + 11), prefix, fontsize=10, fontname='hebo', color=PURPLE if checked else GREEN)
        old_y = self.y
        self.y += 1
        self._text(text, 9.1, INK, width=CONTENT_W - xoff - 14, leading=12.1)
        self.y = max(self.y, old_y + 14) + 3

    # ── data-specification table ─────────────────────────────────────
    def _wrap(self, text, font, size, width):
        words = ascii_clean(text).split()
        lines, current = [], ''
        for word in words:
            trial = f'{current} {word}'.strip()
            if fitz.get_text_length(trial, fontname=font, fontsize=size) <= width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def subhead(self, title):
        self._ensure(30)
        self.page.insert_text((MARGIN, self.y + 12), ascii_clean(title), fontsize=11, fontname='hebo', color=PURPLE)
        self.y += 24

    def spec_table(self, rows, widths=(118, 168, 230), font_size=7.3):
        """rows: (field, what to enter, example / options). Header row first."""
        pad, lh = 6, font_size * 1.42
        for idx, row in enumerate(rows):
            cells = []
            for j, cell in enumerate(row):
                avail = widths[j] - 2 * pad
                cells.append(self._wrap(cell, 'hebo' if (idx == 0 and j == 0) or False else 'helv', font_size, avail))
            row_h = max(20, max(len(c) for c in cells) * lh + 8)
            self._ensure(row_h)
            y0 = self.y
            bg = PURPLE if idx == 0 else (mr.PALE if idx % 2 else (0.985, 0.985, 0.992))
            fg = (1, 1, 1) if idx == 0 else INK
            self.page.draw_rect(fitz.Rect(MARGIN, y0, PAGE_W - MARGIN, y0 + row_h), color=mr.LINE, fill=bg, width=0.35)
            x = MARGIN
            for j, cell in enumerate(cells):
                font = 'hebo' if (idx == 0 or j == 0) else 'helv'
                for k, line in enumerate(cell):
                    self.page.insert_text((x + pad, y0 + 11 + k * lh), line, fontsize=font_size, fontname=font, color=fg)
                x += widths[j]
            self.y += row_h
        self.y += 10

    def note(self, text):
        self.paragraph(text, size=7.9, color=MUTED)

    # ── screenshots ───────────────────────────────────────────────────
    def _trim(self, path: Path) -> bytes:
        """Screenshots are 1600x1900 with empty canvas below the app; trim that
        uniform band so the guide does not ship a page of background."""
        with Image.open(path) as image:
            image = image.convert('RGB')
            width, height = image.size
            px = image.load()
            bottom = px[width // 2, height - 4]

            def uniform(y: int) -> bool:
                return all(px[x, y] == bottom for x in range(0, width, 40))

            last = height - 1
            while last > 400 and uniform(last):
                last -= 1
            last = min(height, last + 24)
            buffer = io.BytesIO()
            image.crop((0, 0, width, last)).save(buffer, format='PNG', optimize=True)
            return buffer.getvalue()

    def image(self, filename, caption, max_h=420):
        path = ASSETS / filename
        if not path.exists():
            return False
        data = self._trim(path)
        with Image.open(io.BytesIO(data)) as image:
            iw, ih = image.size
        scale = min(CONTENT_W / iw, max_h / ih)
        width, height = iw * scale, ih * scale
        if height > PAGE_H - 2 * MARGIN - 90:
            scale = (PAGE_H - 2 * MARGIN - 90) / height
            width, height = width * scale, height * scale
        self._ensure(height + 30)
        rect = fitz.Rect(MARGIN, self.y, MARGIN + width, self.y + height)
        self.page.draw_rect(fitz.Rect(rect.x0 - 1, rect.y0 - 1, rect.x1 + 1, rect.y1 + 1), color=mr.LINE, width=0.7)
        self.page.insert_image(rect, stream=data)
        self.y += height + 7
        self._text(caption, 7.9, MUTED, width=CONTENT_W)
        self.y += 8
        return True

    def walkthrough(self, number, title, subtitle, purpose, fields_pointer, filename, caption, max_h=430):
        """One console page: what it is, which Part A data it holds, and the photo."""
        self._new_page()
        self.heading(f'{number} · {title}', subtitle)
        self.paragraph(purpose, size=9.2)
        self.callout('Data on this page', fields_pointer, color=GREEN, height=0)
        if self.y + 120 > PAGE_H - 60:
            self._new_page()
        self.image(filename, caption, max_h=max_h)

    def save(self):
        if self.page is not None:
            self._footer()
        self.doc.set_metadata({
            'title': 'Client Onboarding Guide — AI WhatsApp Chatbot',
            'author': 'Tenant Console Onboarding Team',
            'subject': 'Every field the client provides, with an admin panel photo per page',
            'keywords': 'onboarding, WhatsApp, chatbot, Tenant Console, client intake, data specification',
        })
        self.doc.save(OUT, garbage=4, deflate=True)
        self.doc.close()


# ══════════════════════════════════════════════════════════════════════
#  PART A — the complete intake data
# ══════════════════════════════════════════════════════════════════════

def part_a(g: Guide):
    g._new_page()
    g.heading('Part A · Every field the client provides', 'The complete data specification. Each table lists every input, what to enter, and an example. Sections marked * are required.')

    g.subhead('A1 · Register wizard — step 1: Company')
    g.spec_table([
        ('Field', 'What to enter', 'Example / options'),
        ('Company name *', 'Legal or registered business name.', 'Leeway Softech Pvt. Ltd.'),
        ('Tenant id *', 'Short unique code, lowercase letters/digits. Used in URLs and APIs.', 'leeway-softech'),
        ('Display name', 'Name customers see on WhatsApp. Defaults to company name.', 'Leeway Softech'),
        ('Website', 'Public website URL.', 'https://example.com'),
        ('Company logo', 'Logo file upload, shown in menus and the console.', 'PNG, min 512 x 512 px'),
        ('Business field (vertical) *', 'Industry. Drives the questions asked, the bot vocabulary and default features.', 'E-commerce & retail / Software & IT services / Tours & travel / Banking & insurance / Finance & accounting / Healthcare & clinics / Real estate & property / Something else'),
    ])

    g.subhead('A1 · Register wizard — step 2: WhatsApp')
    g.spec_table([
        ('Field', 'What to enter', 'Example / options'),
        ('WhatsApp phone number *', 'The business line the bot answers, with country code.', '+91 8000305305'),
        ('WABA phone number id', 'Only if the onboarding team asks you to bind a WhatsApp Business API number.', 'not bound'),
        ('Timezone *', 'Working timezone.', 'Asia/Kolkata'),
        ('Opens *', 'Opening time.', '09:30'),
        ('Closes *', 'Closing time.', '18:30'),
        ('Open on', 'Working days of the week.', 'Mon, Tue, Wed, Thu, Fri, Sat'),
        ('Always open', 'Switch on for 24x7 availability (disables the times above).', 'on / off'),
        ('Out-of-hours message', 'Message customers receive while the business is closed.', "We're closed right now. We'll reply at 9:30 AM."),
    ])

    g.subhead('A1 · Register wizard — step 3: Brand & voice')
    g.spec_table([
        ('Field', 'What to enter', 'Example / options'),
        ('Bot name *', 'The assistant name customers see.', 'Asha'),
        ('Tone', 'How the bot speaks. Vertical default is suggested.', 'Friendly and helpful / Professional and confident / Formal and compliant / Warm and helpful / Calm and empathetic / Concise and direct'),
        ('Tagline', 'One-line brand tagline used in the menu.', 'Software that ships'),
        ('Closing signature', 'Sign-off on bot messages.', '-- Team Leeway'),
        ('Support email *', 'Customer care email.', 'support@example.com'),
        ('Support phone *', 'Country code + 10 digits.', '+91 98765 43210'),
        ('Menu greeting', 'Body of the WhatsApp menu. Blank uses the default.', "Hi! I'm Asha from Leeway Softech. How can I help?"),
    ])

    g.subhead('A1 · Register wizard — step 4: Your business')
    g.note('Vertical-specific questions (see A2) plus the optional module switches (see A3): Campaigns, Distributors, Services, Products, Products & Schemes. Answer every required question — these answers become the words the bot recognises.')

    g.subhead('A1 · Register wizard — step 5: Notifications')
    g.spec_table([
        ('Field', 'What to enter', 'Example / options'),
        ('Sales / enquiries email *', 'Where leads, quotes and handoffs are pushed. Without a destination, leads nobody reads collect.', 'sales@example.com'),
        ('Support email', 'Second notification destination.', 'support@example.com'),
    ])

    g.subhead('A1 · Register wizard — step 6: Guardrails')
    g.spec_table([
        ('Field', 'What to enter', 'Example / options'),
        ('Never state (one per line)', 'Claims the bot must refuse. Empty = vertical default applies.', 'We guarantee delivery in 24 hours / Our stock is always in sync / No hidden charges, ever'),
        ('Forbidden terms', 'Tags the bot refuses to discuss.', 'legal advice'),
        ('Handoff keywords', 'Tags that pause the bot and call a human.', 'human, agent'),
        ('Escalate immediately on', 'Tags that escalate instantly, no bot reply.', 'complaint, fraud, urgent'),
        ('Escalation message', 'What the customer sees on escalation.', 'Let me connect you to a team member right away.'),
    ])
    g.note('Keep "Never state" and "Forbidden terms" disjoint — the linter flags a profile when a forbidden term leaks into its own copy. Step 7 (Review) is a read-only confirmation; sub admins submit for approval instead of publishing.')

    # ── A2 verticals ──────────────────────────────────────────────────
    g._new_page()
    g.subhead('A2 · Business questions per vertical (step 4)')
    g.note('Pick the rows for the client vertical. "chips" = one-tap multi-select tags; "select" = one option from the list. * = required.')

    g.spec_table([
        ('E-commerce & retail', 'Type', 'Example / options'),
        ('Product categories', 'chips', 'Fashion, Electronics, Home, Beauty, Sports, Grocery (+ your own)'),
        ('Payment methods you accept', 'chips', 'UPI, Card, Net banking, Cash on delivery, Pay later'),
        ('Delivery & returns policy in one line', 'text', 'Free delivery above Rs.999, 7-day returns'),
        ('Order reference prefix', 'text', 'TG'),
    ])
    g.spec_table([
        ('Software & IT services', 'Type', 'Example / options'),
        ('Technologies you work with', 'chips', 'React, Node.js, Python, AWS, Azure, Mobile apps, DevOps, AI/ML'),
        ('How you work with clients', 'select', 'Fixed-price projects / Time and materials / Retainers & support plans'),
        ('Typical engagement size', 'text', 'Projects from Rs.2,00,000 / retainers from Rs.25,000 per month'),
        ('After-sales support', 'textarea', 'Free support window, AMC plans, SLA commitments...'),
    ])
    g.spec_table([
        ('Tours & travel', 'Type', 'Example / options'),
        ('Destinations you sell', 'chips', 'Kerala, Goa, Kashmir, Rajasthan, Andaman, Dubai, Europe, Bali'),
        ('Trip types', 'chips', 'Honeymoon, Family, Group, Solo, Corporate, Adventure'),
        ('Booking and cancellation policy', 'textarea', 'Advance booking, cancellation windows, payment terms...'),
        ('Seasonality', 'select', 'Year-round / Oct-Mar peak / Apr-Jun peak / Nov-Feb peak / Seasonal'),
    ])
    g.spec_table([
        ('Banking & insurance', 'Type', 'Example / options'),
        ('Products on offer', 'chips', 'Savings account, Current account, Fixed deposit, Loans, Cards, Insurance'),
        ('Regulatory note', 'textarea', 'How the bot must phrase regulated information, and what it must never state.'),
    ])
    g.spec_table([
        ('Finance & accounting', 'Type', 'Example / options'),
        ('Services you offer', 'chips', 'ITR filing, GST, Audit, Company setup, Payroll, Advisory'),
        ('Key deadlines the bot should mention', 'text', 'ITR due 31 July, GST monthly by the 20th'),
    ])
    g.spec_table([
        ('Healthcare & clinics', 'Type', 'Example / options'),
        ('Departments', 'chips', 'General medicine, Dental, Paediatrics, Orthopaedics, Dermatology, Diagnostics'),
        ('Triage and escalation rule *', 'textarea', 'The bot must never give a diagnosis; emergencies go straight to reception.'),
    ])
    g.spec_table([
        ('Real estate & property', 'Type', 'Example / options'),
        ('Property types', 'chips', '2 BHK Apartments, 3 BHK Luxury Flats, Villas, Commercial Offices, Plots'),
        ('RERA registration details', 'text', 'RERA Registration No. PR/GJ/AHMEDABAD/...'),
    ])
    g.spec_table([
        ('Something else (generic)', 'Type', 'Example / options'),
        ('What do you sell or offer?', 'chips', 'Products, Services, Courses, Memberships, Subscriptions'),
    ])

    # ── A3 features ──────────────────────────────────────────────────
    g._new_page()
    g.subhead('A3 · Capability switches (step 4 optional modules, later in Profile)')
    g.note('Anything switched off stays hidden from the console and the WhatsApp menu. Pre-selected flags differ per vertical; the full list:')
    g.spec_table([
        ('Group', 'Switch', 'What it does'),
        ('Selling online', 'Cart', 'Customers collect items before checking out.'),
        ('Selling online', 'Buy now', 'One-tap purchase from a product page.'),
        ('Selling online', 'Orders', 'Order records and order status.'),
        ('Selling online', 'Track order', 'Customers look up an order with a number.'),
        ('Selling online', 'Returns', 'Return / refund requests and policy.'),
        ('Selling online', 'Distributors', 'A separate reseller price list.'),
        ('Brochure', 'Offerings / Offering details', 'Browse what you sell; price, specs and images per item.'),
        ('Brochure', 'Services / Products / Products & Schemes', 'Which catalogue menu entries exist.'),
        ('Brochure', 'Brochure PDF', 'Send a downloadable brochure.'),
        ('Enquiries & bookings', 'Lead capture', 'Collect name, phone and email.'),
        ('Enquiries & bookings', 'Quotes', 'Collect requirements and send a quote request.'),
        ('Enquiries & bookings', 'Callback', 'Offer to call the customer back.'),
        ('Enquiries & bookings', 'Appointments', 'Book a slot with the team.'),
        ('Self-service support', 'FAQ', 'Answer from an uploaded FAQ file.'),
        ('Self-service support', 'Knowledge base', 'Answer from indexed documents.'),
        ('Self-service support', 'Complaints', 'Register and track complaints.'),
        ('Self-service support', 'Campaigns', 'Scheduled broadcast messages.'),
        ('Human handover', 'Handoff', 'Pause the bot and alert a human.'),
        ('Human handover', 'Human handover', 'Always allow a person to take over.'),
    ])

    # ── A4 catalog ────────────────────────────────────────────────────
    g._new_page()
    g.subhead('A4 · Catalogue / records — one row per item you sell')
    g.note('The panel name depends on the vertical: Products (retail), Packages (travel), Services (IT), Schemes (banking). Columns are the tenant own; the bot reads every one.')
    g.spec_table([
        ('Field', 'What to enter', 'Example / options'),
        ('Item name *', 'Name of the product, service or package.', 'Web development / Kerala Honeymoon Package / Savings account'),
        ('Group', 'Category the item belongs to (select or type a new one).', 'Vertical presets: Web development, Mobile apps, Cloud & DevOps, UI/UX, Consulting / Honeymoon, Family, Group, Adventure, Corporate / Accounts, Cards, Loans, Insurance, Deposits / Fashion, Electronics, Home, Beauty, Sports, Grocery'),
        ('Short description', 'One-line description the bot reads out in listings.', 'React and Node.js build'),
        ('Full description', 'Details shown when the customer asks more.', 'Multi-sentence text'),
        ('Price', 'The vertical decides the label; blank if you do not sell at list price.', 'Price (retail) / Starting price (IT, real estate) / Package price (travel) / Interest or fee (banking) / Fee (finance) / Consultation fee (healthcare)'),
        ('Short label', 'Compact button label used in menus.', 'Web dev'),
        ('Link', 'Purchase or details URL.', 'https://...'),
        ('Visible to the bot', 'Switch: hidden items stay out of answers.', 'on / off'),
        ('Extra columns', 'Per-vertical detail fields, stored as attributes.', 'See the table below'),
    ])
    g.spec_table([
        ('Vertical', 'Extra columns to provide per item', 'Examples'),
        ('E-commerce & retail', 'SKU; In stock; Warranty', 'TG-1042; 42 units; 12 months'),
        ('Software & IT', 'Tech stack; Typical timeline; Engagement model', 'React, Node.js, AWS; 8-10 weeks; Fixed price'),
        ('Tours & travel', 'Duration; Destinations; Includes', '5 nights / 6 days; Kerala, Munnar; Hotel, transfers, guide'),
        ('Banking & insurance', 'Eligibility; Charges', 'Salaried, 21-60 years; Zero annual fee'),
        ('Finance & accounting', 'Next deadline; Documents needed', 'ITR due 31 July; PAN, ITR, bank statement'),
        ('Healthcare & clinics', 'Timings; Department head', 'Mon-Sat, 9:00-18:00; Dr. ...'),
        ('Real estate & property', 'Configuration; Carpet area; Location; Possession date', '2 BHK; 1,250 sq.ft.; Prime Avenue, City Center; Ready to Move'),
        ('Generic', 'Availability; Lead time', 'In stock / On request; 2-3 working days'),
    ])

    # ── A5 menu ───────────────────────────────────────────────────────
    g._new_page()
    g.subhead('A5 · WhatsApp menu data')
    g.spec_table([
        ('Field', 'What to enter', 'Example / options'),
        ('Menu header', 'Top line of the WhatsApp menu.', 'Leeway Softech'),
        ('Menu body', 'Greeting paragraph under the header.', 'What would you like to do today?'),
        ('Menu footer', 'Small line at the bottom.', 'Reply with a number or tap a button'),
        ('Button text', 'Main CTA when the menu has one call-to-action.', 'Talk to us'),
    ])
    g.spec_table([
        ('Per menu option', 'What to enter', 'Example / options'),
        ('Id', 'Unique identifier for the option.', 'menu_quote'),
        ('Title', 'Customer-facing label.', 'Get a Quote'),
        ('Section', 'Which list section it sits under (or create a new section).', 'Services / Support / Talk To Us'),
        ('Icon', 'Emoji shown before the title.', 'tools, phone, star'),
        ('Description', 'Sub-line in list menus.', 'Send us your requirements'),
        ('Requires feature', 'Hides the option when that capability is off.', 'quote, callback, handoff...'),
        ('Starts flow', 'Conversation flow the option launches.', 'flow_name'),
        ('Routes to intent', 'Intent triggered instead of a flow.', 'intent_name'),
        ('Answer text', 'Direct answer when neither flow nor intent applies.', 'We reply within one working day.'),
        ('Keywords', 'Free-typed phrases that also trigger this option.', 'pricing, estimate, quote'),
        ('Show only out of hours', 'Option appears only while closed.', 'on / off'),
    ])

    # ── A6 intents ────────────────────────────────────────────────────
    g.subhead('A6 · Intent data (what the bot recognises)')
    g.spec_table([
        ('Field', 'What to enter', 'Example / options'),
        ('Name', 'snake_case intent id.', 'services_info'),
        ('Answer', 'The reply the bot sends when the intent matches.', 'We build web and mobile apps...'),
        ('Keywords', 'Tags the classifier matches on.', 'services, work, build, develop'),
        ('Examples', 'Sample customer phrases for the matcher.', 'what do you do, what services do you offer'),
        ('Requires feature', 'Hides the intent when a feature is off.', 'callback, quote...'),
        ('Flow', 'Conversation flow launched instead of a plain answer.', 'flow_name'),
        ('Enabled', 'Switch. Disabled intents stay in draft, invisible live.', 'on / off'),
    ])
    g.note('Intent changes go to draft and need publishing — a customer never sees them until the profile version is published.')

    # ── A7 uploads ────────────────────────────────────────────────────
    g.subhead('A7 · Knowledge uploads (documents the bot learns from)')
    g.spec_table([
        ('Field', 'What to enter', 'Example / options'),
        ('Module', 'What the file is for.', 'FAQ / Knowledge base / Brochure / New releases'),
        ('File', 'One file per upload; extracted, embedded and made searchable for this tenant only.', 'PDF, DOC, DOCX, TXT, XLS, XLSX, MD, CSV'),
        ('Size limit', 'Per file.', '20 MB'),
        ('Search', 'Console filter for uploaded files.', 'by file name'),
    ])
    g.note('Provide current, approved documents: FAQ sheets, policy documents, product manuals, brochures, price lists. Confirm every document is cleared for automated customer support use.')

    # ── A8 team ───────────────────────────────────────────────────────
    g._new_page()
    g.subhead('A8 · Team accounts data')
    g.spec_table([
        ('Field', 'What to enter', 'Example / options'),
        ('Full name', 'Person behind the account.', 'Priya Sharma'),
        ('Username *', 'Login name, lowercase.', 'priya'),
        ('Password *', 'Minimum 6 characters. Always via the secure handoff, never in this document.', 'managed by onboarding team'),
        ('Email', 'For alerts and audit.', 'priya@company.com'),
        ('Phone', 'For urgent escalations.', '+91 98xxxxxx10'),
        ('Role', 'super_admin (everything) / admin / sub_admin (restricted by permissions).', 'sub_admin'),
        ('Tenant scope', 'Bind the account to one brand, or leave empty for platform-wide.', 'leeway-softech'),
        ('Permissions', 'Tick the rights this person needs (list below).', 'subset of 29 permissions'),
    ])
    g.spec_table([
        ('Permission group', 'Permissions', ''),
        ('Tenant configuration', 'Manage operations (profiles, menus, tenants)', ''),
        ('Team', 'Manage admins', ''),
        ('Content', 'Upload FAQ files; Upload KB files; View uploaded files; Delete uploaded files', ''),
        ('Products & brochure', 'View products; Add / Edit / Remove catalogue entries; Manage brochure and new releases', ''),
        ('Conversations', 'Use admin chat; View chat history; Live inbox', ''),
        ('Operations', 'View orders; Edit/delete orders; View complaints; Handle complaints; View customers', ''),
        ('Growth', 'Campaigns; Edit/delete campaigns; View analytics', ''),
        ('Distributors (B2B)', 'Distributors; Add/edit/delete distributors', ''),
        ('IT vertical pages', 'Add/edit/delete services; Edit the projects, technologies, careers and benefits pages', ''),
    ])

    # ── A9 integrations ───────────────────────────────────────────────
    g._new_page()
    g.subhead('A9 · Integration credentials (API access page)')
    g.note('Collect the provider choice and environment first; keys and secrets go through the secure handoff only, never in this document.')
    g.spec_table([
        ('Provider', 'Fields to provide', 'Example'),
        ('Environment (all providers)', 'Test / sandbox or production / live.', 'Test'),
        ('Stripe', 'Secret key; Publishable key; Webhook secret', 'sk_test_51Mz...; pk_test_51Mz...; whsec_...'),
        ('Razorpay', 'Key ID; Key Secret; Webhook secret (optional)', 'rzp_test_1DP5mmOlF5G5ag; ...; ...'),
        ('Custom payment gateway', 'Custom API endpoint URL; Authorization header / bearer token; Webhook signing secret', 'https://api.mygateway.com/v1/checkout; Bearer your_secret_token; ...'),
        ('Blue Dart', 'Customer code; License key; Login ID', '123456; ...; BD_USER'),
        ('Xpressbees', 'Account email; Password; or API token (bearer)', 'merchant@example.com; password; Bearer token'),
        ('Custom carrier', 'Endpoint URL; Authorization header; Webhook signing secret', 'https://api.carrier.com; Bearer ...; ...'),
        ('Integration request', 'Integration category; Provider; Purpose (business justification)', 'Payments - Stripe - collect order payments in WhatsApp'),
        ('Payment test data', 'A test Order ID and Amount (INR)', 'ORD-1001; 1499'),
        ('Delivery test data', 'Origin pincode and destination pincode for a live booking test.', '380015; 110001'),
    ])

    # ── A10 campaigns ─────────────────────────────────────────────────
    g.subhead('A10 · Campaigns data (optional module)')
    g.spec_table([
        ('Field', 'What to enter', 'Example / options'),
        ('Template name *', 'snake_case template id.', 'diwali_restock_offer'),
        ('Category *', 'WhatsApp template category.', 'Marketing / Utility / Authentication'),
        ('Language', 'One locale per template (Meta requirement).', 'en, hi, gu'),
        ('Header (optional)', 'Short title line.', 'Diwali Restock Offer'),
        ('Footer (optional)', 'Closing line.', 'Reply STOP to unsubscribe'),
        ('Sample values', 'Example values for the variables, for template approval.', 'Rajesh, 20%'),
        ('Template body *', 'The message with {{variables}}.', 'Hi {{name}}, get {{discount}} off on your Diwali restock.'),
        ('Segment name *', 'Name of the audience segment.', 'High-Value Customers'),
        ('Audience type *', 'Who the segment selects.', 'Customers / Distributors'),
        ('Segment filters', 'State / region; city; tier(s); product interests; sales volume >= (Rs.); or hand-picked selection by search (name, number, city).', 'Gujarat; Ahmedabad; Tier 1+2; chikki; Rs.50,000'),
    ])

    # ── A11 distributors ──────────────────────────────────────────────
    g.subhead('A11 · Distributor data (optional B2B module)')
    g.spec_table([
        ('Field', 'What to enter', 'Example / options'),
        ('WhatsApp ID', 'Distributor WhatsApp account id.', '012345678901234'),
        ('Name *', 'Distributor or firm name.', 'Patel Traders'),
        ('Phone', 'Contact number.', '+91 98xxxxxx10'),
        ('Email', 'Contact email.', 'sales@pateltraders.com'),
        ('Region *', 'State or region they cover.', 'Gujarat'),
        ('City', 'City.', 'Ahmedabad'),
        ('Tier', 'Pricing tier.', 'Tier 1 / Tier 2 / Tier 3'),
        ('Product interests', 'What they stock.', 'chikki, snacks'),
        ('Address', 'Business address.', 'street, city, pincode'),
        ('Service area', 'Pincodes or areas served.', '380001-380060'),
        ('Sales volume', 'Monthly or yearly volume.', 'Rs.2,00,000 / month'),
        ('Outstanding payments', 'Any pending dues.', 'Rs.15,000'),
        ('Notes', 'Free text.', 'Prefers evening delivery'),
    ])


# ══════════════════════════════════════════════════════════════════════
#  PART B — photo of every admin panel page
# ══════════════════════════════════════════════════════════════════════

def part_b(g: Guide):
    g.walkthrough(
        1, 'Sign in', 'The entry point to the admin panel.',
        'Every console feature sits behind this sign-in; sessions are stored locally in the browser. Accounts come from the onboarding team on the Team page.',
        'Client provides the team member list (A8: names, usernames, emails, roles). Passwords are created through the secure handoff only.',
        'login.png', 'Page 1. Admin panel sign-in for the Tenant Console.',
    )
    g.walkthrough(
        2, 'Tenants', 'All chatbot brands configured on the platform.',
        'The tenant list is the platform home: one row per client brand with vertical and status. Selecting a tenant opens its console.',
        'Tenant id, company name, display name and vertical (A1 step 1) decide the row. The industry vertical sets the vocabulary and default questions.',
        'tenant-list.png', 'Page 2. Tenant list: every brand the platform serves, with vertical and status.',
    )
    g.walkthrough(
        3, 'Register a tenant', 'The guided questionnaire that collects the client basics.',
        'The register wizard is the intake form: seven steps from company basics to review. Every field is listed in A1; the business questions in A2 and module switches in A3.',
        'All of A1 (7 steps), A2 business answers and A3 module switches. Super admins publish directly; sub admins submit for approval.',
        'register.png', 'Page 3. Register wizard - the intake questionnaire, seven steps from company basics to review.',
    )
    g.walkthrough(
        4, 'Tenant change requests', 'The approval queue for registrations and profile publishes.',
        'Registrations and profile changes submitted by admins wait here; approving applies the change exactly as reviewed. Nothing reaches the live bot without this step.',
        'The client names the approval owner (who signs off profile changes) and agrees the review turnaround.',
        'tenant-requests.png', 'Page 4. Tenant change requests - submissions waiting for approval before they go live.',
    )
    g.walkthrough(
        5, 'API access requests', 'Approval of external Payment API and Order API access.',
        'A tenant requests eligibility for payment and order integrations; approving grants the eligibility the API Access page needs for live keys.',
        'A9 first block: which integrations, environment (test or live) and the business justification recorded with the request.',
        'api-requests.png', 'Page 5. API access requests - grant eligibility for payments and order APIs.',
    )
    g.walkthrough(
        6, 'Audit history', 'Every administrator action, across tenants.',
        'Actor, client, request and change details for each console action, with presets and filters. The evidence trail for go-live reviews.',
        'The client nominates who may review audit history; the sign-off record is kept against this log.',
        'audit-history.png', 'Page 6. Audit history - the change log behind every configuration move.',
    )
    g.walkthrough(
        7, 'Team & permissions', 'Console accounts and what each person can do.',
        'Every admin sees the console through their own permissions: a screen or an action they do not hold is hidden.',
        'All of A8: full name, username, email, phone, role, tenant scope and the exact permission tick-list per account.',
        'team.png', 'Page 7. Team & permissions - accounts, roles and the rights each one carries.',
    )
    g.walkthrough(
        8, 'Overview', 'The status board for one chatbot.',
        'Identity, live version, capability groups, WhatsApp menu and active intents at a glance. Shared at every status call.',
        'No new data - it reports what was loaded from A1-A7. Confirm the shown identity, capabilities and menu match the agreed scope.',
        'overview.png', 'Page 8. Overview - profile status, capabilities and menu of one tenant.',
    )
    g.walkthrough(
        9, 'Profile', 'The data layer the bot answers from.',
        'Saving writes a draft; publishing validates, versions and swaps the live profile. Brand, hours, contacts, vocabulary, notifications and guardrails all live here.',
        'A1 steps 2-3 and 5-6 (re-editable here): brand fields, working hours, notifications, vocabulary nouns and domain keywords, guardrails, and the A3 feature switches.',
        'profile.png', 'Page 9. Profile editor - brand, hours, contacts, vocabulary, notifications and guardrails; drafts publish only after review.',
    )
    g.walkthrough(
        10, 'Catalog (Services / Packages / Products)', 'The table the bot reads.',
        'One row per item you sell. Columns are the tenant own: add any column the business needs and the bot can use it.',
        'All of A4: item rows with name, group, descriptions, price, link, visibility and the vertical extra columns (SKU, stock, tech stack, duration, eligibility...).',
        'records.png', 'Page 10. Records panel - the offering table with tenant-defined columns.',
    )
    g.walkthrough(
        11, 'Customers', 'Everyone who has talked to the bot.',
        'Customer details aggregated across orders, complaints and chat history, keyed by WhatsApp number. It fills itself as the bot runs.',
        'No client input. Confirm storing customer chat data in the platform is approved, and who may view customer records.',
        'customers.png', 'Page 11. Customers - aggregated profiles keyed by WhatsApp number.',
    )
    g.walkthrough(
        12, 'Menu', 'The WhatsApp menu as customers see it.',
        'Rendered live from the tenant profile with smart switch: quick-reply buttons for three options or fewer, a list menu for more.',
        'A5 first table: header, body, footer and button text - confirm the final wording here before publishing.',
        'menu.png', 'Page 12. Menu preview - the exact WhatsApp menu the bot will present.',
    )
    g.walkthrough(
        13, 'Menu editor', 'Every menu option, editable.',
        'Each WhatsApp menu option can be renamed, reordered, gated behind a feature flag or pointed at a flow, an intent or a direct answer.',
        'A5 second table, one entry per menu option: id, title, section, icon, description, feature gate, flow / intent / answer text, keywords, out-of-hours only.',
        'menu-edit.png', 'Page 13. Menu editor - per-option wording, order and feature gates.',
    )
    g.walkthrough(
        14, 'Intents editor', 'What the bot recognises and where it routes.',
        'Add, edit, enable and disable intents - the customer phrases mapped to answers, flows and actions.',
        'All of A6: one intent per topic with name, answer, keywords, example phrases, feature gate, flow and enabled switch.',
        'intents.png', 'Page 14. Intents editor - phrases in, routing out; draft until published.',
    )
    g.walkthrough(
        15, 'Uploads', 'Documents the bot learns from.',
        'A successful upload is extracted, embedded and made searchable for this tenant only. FAQs, brochures, policies and manuals become bot knowledge here.',
        'All of A7: files up to 20 MB each (PDF, DOC, DOCX, TXT, XLS, XLSX, MD, CSV) tagged to the right module: FAQ, Knowledge base, Brochure or New releases.',
        'uploads.png', 'Page 15. Uploads - each file is extracted, embedded and searchable per tenant.',
    )
    g.walkthrough(
        16, 'Admin chat', 'The internal team channel.',
        'Private per-brand chat between the tenant admins - coordination for the team, not customer conversations.',
        'A8 team list: which members take part in the internal chat.',
        'chat.png', 'Page 16. Team chat - internal coordination, private to the brand.',
    )
    g.walkthrough(
        17, 'Chat history', 'Every recorded customer exchange.',
        'What the bot answered and what agents said, filterable by customer - the evidence for acceptance testing.',
        'The acceptance test questions and expected answers (verified here), plus retention expectations for transcripts.',
        'chat-history.png', 'Page 17. Chat history - the full transcript record per conversation.',
    )
    g.walkthrough(
        18, 'Live inbox', 'Conversations handed over to a human.',
        'Conversations the bot handed over or a person took over. Replying pauses the bot until released.',
        'A1 step 6 guardrails: handoff keywords and escalation message; plus inbox owners, coverage hours and response-time expectation.',
        'inbox.png', 'Page 18. Live inbox - handover conversations; replying pauses the bot.',
    )
    g.walkthrough(
        19, 'Complaints', 'Tickets customers raise through the bot.',
        'Issues raised via the bot, with status workflow: reply to reopen the conversation or move the ticket to resolution.',
        'Complaint owners, status flow (open, in progress, resolved) and priority / auto-escalation rules.',
        'complaints.png', 'Page 19. Complaints - ticket queue with status workflow.',
    )
    g.walkthrough(
        20, 'Callbacks', 'Call-back requests booked from WhatsApp.',
        'Requests customers raise through the bot. Schedule them with a Google Meet link, mark done, or cancel.',
        'The Google account to connect for Meet links, callback team members and their availability windows.',
        'callbacks.png', 'Page 20. Callbacks - schedule with a Meet link, complete or cancel.',
    )
    g.walkthrough(
        21, 'API tokens', 'Tenant-scoped publish tokens.',
        'A tenant token can read and publish exactly one tenant profile and nothing else - for clients whose own systems update the bot configuration programmatically.',
        'Whether the client systems integrate via API token, the token owner, and how the token is stored client-side (secure handoff).',
        'tokens.png', 'Page 21. API tokens - one token, one tenant, publish rights only.',
    )
    g.walkthrough(
        22, 'API access & live integrations', 'Payments, logistics and custom APIs.',
        'Connect real payment gateways and shipping carriers, test them with a live order, and manage order lookups.',
        'All of A9: provider choice, environment, every key / secret field per provider (via secure handoff), test order data and test pincodes.',
        'api-access.png', 'Page 22. API access - gateway and carrier credentials, tests and order lookups.',
    )
    g.walkthrough(
        23, 'Versions', 'Immutable publish history.',
        'Publishing appends a version and swaps the live profile; rollback never deletes anything. This is the audit point for what exactly is live.',
        'Which published version is the go-live version, and who may publish / roll back on the client side.',
        'versions.png', 'Page 23. Versions - publish history with instant rollback.',
    )
    g.walkthrough(
        24, 'Layers', 'How the final profile is assembled.',
        'A profile merges in one direction only: vertical defaults, then the client file, then published database overrides.',
        'Any vertical default the client wants overridden (vocabulary, menu wording, answers) - applied as a published override layer.',
        'layers.png', 'Page 24. Layers - vertical defaults, client file, published overrides.',
    )
    g.walkthrough(
        25, 'Test and smoke', 'Prove the live bot before sign-off.',
        'Run an utterance through the tenant live intent matcher and assert the runtime is data-driven; smoke checks flag issues like forbidden terms leaking into profile copy.',
        'The client acceptance questions with expected routing, and sign-off that every smoke check passes on the go-live version.',
        'test.png', 'Page 25. Test and smoke - utterance checks and the pre-launch smoke results.',
    )


def main():
    g = Guide()

    # ── Cover ──────────────────────────────────────────────────────
    g.page.draw_rect(fitz.Rect(0, 0, PAGE_W, PAGE_H), color=None, fill=(0.97, 0.96, 1.0))
    g.page.draw_rect(fitz.Rect(0, 0, PAGE_W, 270), color=None, fill=(0.12, 0.10, 0.21))
    g.page.draw_rect(fitz.Rect(0, 270, PAGE_W, 277), color=None, fill=PURPLE)
    g.page.insert_text((MARGIN, 66), 'ADMIN PANEL  /  TENANT CONSOLE', fontsize=8.5, fontname='hebo', color=(0.76, 0.69, 1))
    g.page.insert_text((MARGIN, 128), 'Building Your Chatbot', fontsize=31, fontname='hebo', color=(1, 1, 1))
    g.page.insert_text((MARGIN, 160), 'Client onboarding & complete data specification', fontsize=15, fontname='helv', color=(0.91, 0.89, 0.98))
    g.page.insert_text((MARGIN, 196), 'Every field we need from you, page by page of the admin panel', fontsize=10, fontname='helv', color=(0.80, 0.79, 0.88))
    cover = ASSETS / 'overview.png'
    if cover.exists():
        g.page.insert_image(fitz.Rect(MARGIN, 310, PAGE_W - MARGIN, 560), filename=str(cover), keep_proportion=True)
    g.page.insert_text((MARGIN, 596), ascii_clean('PART A: YOUR DATA  →  PART B: WHERE IT GOES'), fontsize=9, fontname='hebo', color=PURPLE)
    g.page.insert_text((MARGIN, 630), 'Prepared for new chatbot clients', fontsize=11, fontname='hebo', color=INK)
    g.page.insert_text((MARGIN, 650), 'Admin panel reference captured 21 October 2026 - prominent-faster-dropper.ngrok-free.dev', fontsize=8, fontname='helv', color=MUTED)
    g.page.insert_text((MARGIN, 692), 'Share credentials and API keys only through the agreed secure handoff - never in this document.', fontsize=8, fontname='helv', color=ORANGE)

    # ── How onboarding works ────────────────────────────────────────
    g._new_page()
    g.heading('How we build your chatbot', 'What this document is: Part A lists every field you provide. Part B shows the admin panel page where each part goes.')
    g.table([
        ('1 · Register', 'You (or your onboarding manager) complete the register wizard: company basics, WhatsApp line, brand voice, business answers, notifications, guardrails.'),
        ('2 · Configure', 'The onboarding team loads your profile, catalog, menu, intents and knowledge documents into the console.'),
        ('3 · Review', 'Submitted registrations and profile changes wait in a review queue; an approved change is applied exactly as reviewed.'),
        ('4 · Test', 'Sample customer questions run through the live bot and the built-in smoke checks before sign-off.'),
        ('5 · Go live', 'Publishing creates an immutable version and swaps the live profile. Rollback is instant and never loses history.'),
    ])
    g.callout('Two ways to read this guide', 'Part A is the checklist to fill in: every field, what to enter, an example. Part B is the tour: a photo of every admin panel page with the fields that live there.', color=GREEN)
    g.section('What we need from you - at a glance', [
        'A1 Register wizard: company, WhatsApp line, brand voice, notifications, guardrails.',
        'A2 Your business answers: the vertical-specific questions for your industry.',
        'A3 Capability switches: which modules your bot switches on.',
        'A4 Catalogue rows: every product, service or package you sell.',
        'A5 WhatsApp menu options; A6 intents: the phrases customers use.',
        'A7 Knowledge documents: FAQs, policies, brochures, price lists.',
        'A8 Team accounts: who gets admin, support or distributor access.',
        'A9 Integrations (optional): payment gateway and logistics credentials.',
        'A10 Campaigns (optional): broadcast templates and audience segments.',
        'A11 Distributors (optional): your reseller network records.',
    ])

    part_a(g)
    part_b(g)

    # ── Launch checklist ────────────────────────────────────────────
    g._new_page()
    g.heading('Go-live checklist', 'Confirm every item with the onboarding owner before the bot receives real customers.')
    g.section('Ready to publish when', [
        'Every A1-A7 field is provided and confirmed by the client.',
        'Catalogue rows, menu options and intents are loaded and reviewed.',
        'Knowledge documents are uploaded and answers spot-checked.',
        'Integrations (A9, if any) are connected, tested in the agreed environment and approved.',
        'Team accounts (A8) exist with the right roles; the approval owner is known.',
        'Guardrails are set: never-state list, forbidden terms, handoff keywords, escalation message.',
    ])
    g.section('Launch day', [
        'Publish the final version (or approve the pending change request).',
        "Run the client's acceptance questions through Test and smoke; all checks green.",
        'Confirm the live version on Overview and the wording on Menu.',
        'Send a real WhatsApp message and verify routing, handoff and notifications.',
        'Confirm who monitors the inbox, complaints and callbacks from day one.',
    ])
    g.callout('Reminder', 'A saved draft, a passing screenshot or a pending request is not a launch. The published version number on the Overview page plus a verified live test is the sign-off.', color=ORANGE)

    g.save()
    print(OUT)


if __name__ == '__main__':
    main()
