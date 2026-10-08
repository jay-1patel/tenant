# 📋 Client Onboarding & Details Collection Guide

Welcome! To set up, configure, and launch your **AI-Powered WhatsApp Business Chatbot & Tenant Platform**, please provide the following details and assets.

This guide is tailored specifically to our platform setup with **Send2Digital WhatsApp Gateway**, supported payment gateways (**Razorpay** & **Stripe**), and delivery partners (**BlueDart** & **Xpressbees**).

---

## 📌 Table of Contents
1. [🏢 1. Business & Brand Details](#1-business--brand-details)
2. [💬 2. WhatsApp Number Setup (Powered by Send2Digital)](#2-whatsapp-number-setup-powered-by-send2digital)
3. [📚 3. Knowledge Base, FAQs & Product Catalog](#3-knowledge-base-faqs--product-catalog)
4. [💳 4. Payment Gateway Integration (Razorpay / Stripe)](#4-payment-gateway-integration-razorpay--stripe)
5. [🚚 5. Logistics & Shipping Integration (BlueDart / Xpressbees)](#5-logistics--shipping-integration-bluedart--xpressbees)
6. [🔌 6. Custom API / Webhooks (Optional)](#6-custom-api--webhooks-optional)
7. [🤖 7. Bot Goals, Persona & Escalation Rules](#7-bot-goals-persona--escalation-rules)
8. [👥 8. Team Accounts & User Roles](#8-team-accounts--user-roles)

---

## 1. 🏢 Business & Brand Details

| Required Field | Description | Client Input |
| :--- | :--- | :--- |
| **Legal Business Name** | Registered company name | `[Your Business Name]` |
| **Brand / Display Name** | Name shown to customers on WhatsApp | `[Brand Display Name]` |
| **Tenant ID / Code** | Short unique code for your account (e.g. `leeway`, `brand_code`) | `[e.g., leeway]` |
| **Business Vertical** | Select primary vertical: `[ ] E-commerce / D2C` &nbsp;\|&nbsp; `[ ] FMCG / Retail` &nbsp;\|&nbsp; `[ ] Healthcare` &nbsp;\|&nbsp; `[ ] Real Estate` &nbsp;\|&nbsp; `[ ] Services` &nbsp;\|&nbsp; `[ ] Generic` | `[Select Vertical]` |
| **Official Website URL** | Your company website | `https://...` |
| **Support Email** | Customer care email address | `support@example.com` |
| **Support Phone Number** | Customer care helpline number | `+91 XXXXXXXXXX` |
| **Operating Hours** | Business working hours (e.g. Mon–Sat 9:00 AM – 7:00 PM) | `[Working Hours]` |
| **Timezone & Currency** | Default timezone & currency | `Asia/Kolkata / INR` |
| **Brand Logo & Media** | High-resolution logo (PNG/JPG, min 512x512) | *[Attach files]* |

---

## 2. 💬 WhatsApp Number Setup (Powered by Send2Digital)

You only need to provide the phone number to connect.

| Parameter | Description | Client Input |
| :--- | :--- | :--- |
| **WhatsApp Phone Number** | The mobile number to connect to the AI chatbot (with country code) | `+91 XXXXXXXXXX` |

---

## 3. 📚 Knowledge Base, FAQs & Product Catalog

The AI chatbot uses this information to answer customer inquiries, pitch products, and provide 24/7 automated support.

### A. Frequently Asked Questions (FAQs)
- [ ] Return / Refund / Cancellation policies
- [ ] Warranty, guarantees, and service terms
- [ ] Delivery timelines and shipping charges
- [ ] Office / Store addresses
- [ ] Accepted payment methods

### B. Knowledge Base Documents
- [ ] Product brochures, user manuals, policy documents, or service guides (PDF / DOCX / TXT).

### C. Product / Service Catalog (CSV or Excel)
Please provide your product catalog in a spreadsheet with the following recommended columns:

| Column Header | Description | Example |
| :--- | :--- | :--- |
| `sku` | Unique Product Code / SKU | `PROD-001` |
| `name` | Product Title / Name | `Organic Green Tea 100g` |
| `category` | Product Category | `Beverages` |
| `price` | Price in INR | `299` |
| `description` | Short product summary / benefits | `100% natural antioxidant-rich tea` |
| `image_url` | Direct link to product photo | `https://example.com/images/tea.jpg` |
| `product_url` | Direct buy or product page link *(optional)* | `https://example.com/products/tea` |

---

## 4. 💳 Payment Gateway Integration (Razorpay / Stripe)

*Select the payment gateway you want to connect for collecting payments via WhatsApp links:*

- **Active Gateway Selection**: `[ ] Razorpay` &nbsp;&nbsp;|&nbsp;&nbsp; `[ ] Stripe` &nbsp;&nbsp;|&nbsp;&nbsp; `[ ] Both`

### Option A: Razorpay
| Field | Description | Client Input |
| :--- | :--- | :--- |
| **Environment** | Test / Sandbox or Production / Live | `[Sandbox / Live]` |
| **Razorpay Key ID** | `rzp_test_...` or `rzp_live_...` | `[Key ID]` |
| **Razorpay Key Secret** | Secret key from Razorpay Dashboard | `[Key Secret]` |
| **Webhook Secret (Optional)** | Webhook secret for instant payment status callbacks | `[Webhook Secret]` |

### Option B: Stripe
| Field | Description | Client Input |
| :--- | :--- | :--- |
| **Environment** | Test or Live | `[Test / Live]` |
| **Stripe Publishable Key** | `pk_test_...` or `pk_live_...` | `[Publishable Key]` |
| **Stripe Secret Key** | `sk_test_...` or `sk_live_...` | `[Secret Key]` |
| **Stripe Webhook Secret** | `whsec_...` from Stripe Dashboard | `[Webhook Secret]` |

---

## 5. 🚚 Logistics & Shipping Integration (BlueDart / Xpressbees)

*Select the courier partner you use for live order tracking, AWB generation, and delivery updates on WhatsApp:*

- **Active Logistics Selection**: `[ ] BlueDart` &nbsp;&nbsp;|&nbsp;&nbsp; `[ ] Xpressbees` &nbsp;&nbsp;|&nbsp;&nbsp; `[ ] Both`

### Option A: BlueDart
| Field | Description | Client Input |
| :--- | :--- | :--- |
| **Customer Code / Login ID** | BlueDart customer account code | `[Customer Code]` |
| **License Key** | BlueDart API license key | `[License Key]` |
| **Tracking API URL / Mode** | Testing / Production endpoint | `[Production / Testing]` |

### Option B: Xpressbees
| Field | Description | Client Input |
| :--- | :--- | :--- |
| **Email / Account ID** | Registered Xpressbees account email | `[Account Email]` |
| **API Token / Secret Key** | Xpressbees authorization token | `[API Token]` |
| **Tracking / Order Endpoint** | Production or Staging | `[Production / Staging]` |

---

## 6. 🔌 Custom API / Webhooks *(Optional)*

If you want the WhatsApp bot to communicate with your custom backend, internal CRM, or ERP:

| Integration Detail | Description | Value / Specification |
| :--- | :--- | :--- |
| **Order Lookup API** | Endpoint to verify order status / customer phone | `GET /api/orders/lookup?phone={phone}` |
| **Inventory / Stock API** | Endpoint to check live product stock | `GET /api/inventory/check?sku={sku}` |
| **Lead Capture Webhook** | Webhook URL where new WhatsApp leads are pushed | `POST https://your-crm.com/leads/webhook` |
| **Authorization Header** | Bearer token or API key for secure API communication | `Bearer xxxxx...` |

---

## 7. 🤖 Bot Goals, Persona & Escalation Rules

### A. Primary Bot Objectives *(Select all that apply)*
- [ ] **24/7 Automated FAQ Support** (Answer questions from documents & policies)
- [ ] **Product Discovery & In-Chat Checkout** (Browse catalog & pay via Razorpay/Stripe)
- [ ] **Lead Generation & Qualification** (Collect name, email, interest)
- [ ] **Live Order Tracking** (AWB tracking via BlueDart/Xpressbees)
- [ ] **Customer Complaints & Ticketing** (Register issues & escalate to team)

### B. Persona & Messaging Settings
| Parameter | Configuration Options | Client Selection |
| :--- | :--- | :--- |
| **Bot Tone / Style** | Professional / Friendly / Casual / Luxury / Technical | `[e.g., Friendly & Professional]` |
| **Welcome / Greeting Message** | Custom greeting message sent when user says "Hi" | `[Custom Greeting or Default AI]` |
| **Primary Language(s)** | English, Hindi, Hinglish, or Regional Languages | `[e.g., English + Hindi/Hinglish]` |
| **Human Handoff Trigger** | Auto-escalate when customer asks for "human", "agent", or "support" | Enabled `[Yes / No]` |
| **Handoff Escalation Message** | Message sent when routing to a human agent | `[e.g., "Connecting you to an agent..."]` |
| **Outside Hours Auto-Reply** | Message sent if customer requests human agent when support is offline | `[e.g., "Our team is offline. We'll reply tomorrow morning."]` |
| **Live Alert Notification** | WhatsApp number or Email to alert your team of urgent inquiries | `[Alert Phone / Email]` |

---

## 8. 👥 Team Accounts & User Roles

Please list the team members who will have access to the Admin Dashboard & Live Chat Inbox:

| Full Name | Email Address | Role (`Tenant Admin` / `Sub Admin` / `Support Agent`) | Phone Number |
| :--- | :--- | :--- | :--- |
| 1. | `admin@company.com` | **Tenant Admin** (Full Control) | `+91 ...` |
| 2. | `support@company.com` | **Sub Admin / Support Agent** (Live Inbox & Orders) | `+91 ...` |

---

## 🚀 Submission & Next Steps

1. **Fill In the Tables**: Complete the fields above for your brand.
2. **Attach Files**: Attach your Logo, FAQs, PDF documents, and Product catalog spreadsheet.
3. **Submit to Onboarding Team**: Send this document to your account manager or upload it directly through the Admin Console.
4. **Go-Live**: Our team will configure your sandbox and connect your Send2Digital WhatsApp line for testing within 24–48 hours!

---
*For any questions or assistance, please reach out to our support team.*
