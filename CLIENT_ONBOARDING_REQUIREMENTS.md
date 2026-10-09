# 📋 Client Onboarding & Details Collection Guide

Welcome! To setup, configure & launch your AI-Powered WhatsApp Business Chatbot & Tenant Platform, kindly provide below information & assets.

This guide is specific to our platform setup with Send2Digital WhatsApp Gateway, enabled payment gateways (Razorpay & Stripe) and delivery partners (BlueDart & Xpressbees).
---
---

## 1. 🏢 Business & Brand Details

| Parameter | Description | Client Input |
| :--- | :--- | :--- |
| Legal Business Name | Registered company name | `[Your Business Name]` |
| Brand / Display Name | Name shown to customers on WhatsApp | `[Brand Display Name]` |

| Tenant ID / Code | Short unique code for your account (e.g. `leeway`, `brand_code`) | `[e.g., leeway]` |
| Industry / Category | E-commerce, Healthcare, Real Estate, Retail, D2C, etc. | `[Industry]` |
| Official Website URL | Your company website | `https://...` |
| Support Email | Customer care email address | `support@example.com` |
| Support Phone Number | Customer care helpline number | `+91 XXXXXXXXXX` |
| Operating Hours | Business working hours (e.g. Mon–Sat 9:00 AM – 7:00 PM) | `[Working Hours]` |
| Timezone & Currency | Default timezone & currency | `Asia/Kolkata / INR` |
| Brand Logo & Media | High-resolution logo (PNG/JPG, min 512x512) | [Attach files] |
---
## 2. 💬 WhatsApp Number Setup (Powered by Send2Digital)
You just need to provide the phone number to connect.

| Parameter | Description | Client Input |
| :--- | :--- | :--- |
| WhatsApp Phone Number | The mobile number that you use to connect to the AI chatbot (with country code) | `+91 XXXXXXXXXX` |
---

## 3. 📚 Knowledge Base, FAQs & Product Catalog
The AI chatbot uses this information to answer customer questions, pitch products and offer 24x7 automated support.
- [ ] Frequently Asked Questions (FAQs):
- Return / Refund / Cancellation policies
- Warranty, guarantees and service terms
- Delivery timelines and shipping charges
- Store / Office addresses and branch locations
- Accepted payment methods
- [ ] Product / Service Catalog:
- Products CSV or Excel sheet with: Name, SKU, Category, Price, Description, Images, and Purchase Links.
- [ ] Knowledge Base Documents (PDF / DOCX / TXT):
- Product brochures, user manuals, policy documents, or service guides.
---
## 4. 💳 Payment Gateway Integration (Razorpay / Stripe)
Select the payment gateway you wish to connect to, for collecting payments via WhatsApp links.
- Active Gateway Selection: `[ ] Razorpay`   |   `[ ] Stripe`   |   `[ ] Both`
### Option A: Razorpay
| Field | Description | Client Input |
| :--- | :--- | :--- |
| Environment | Test / Sandbox or Production / Live | `[Sandbox / Live]` |
| Razorpay Key ID | `rzp_test_...` or `rzp_live_...` | `[Key ID]` |
| Razorpay Key Secret | Secret key from Razorpay Dashboard | `[Key Secret]` |
| Webhook Secret (Optional) | Webhook secret for instant payment status callbacks | `[Webhook Secret]` |
### Option B: Stripe
| Field | Description | Client Input |
| :--- | :--- | :--- |
| Environment | Test or Live | `[Test / Live]` |
| Stripe Publishable Key | `pk_test_...` or `pk_live_...` | `[Publishable Key]` |
| Stripe Secret Key | `sk_test_...` or `sk_live_...` | `[Secret Key]` |
| Stripe Webhook Secret | `whsec_...` from Stripe Dashboard | `[Webhook Secret]` |
---
## 5. 🚚 Logistics & Shipping Integration (BlueDart / Xpressbees)
Select the courier partner you use for live order tracking, AWB generation and delivery updates on WhatsApp.
- Active Logistics Selection: `[ ] BlueDart`   |   `[ ] Xpressbees`   |   `[ ] Both`
### Option A: BlueDart
| Field | Description | Client Input |
| :--- | :--- | :--- |
| Customer Code / Login ID | BlueDart customer account code | `[Customer Code]` |
| License Key | BlueDart API license key | `[License Key]` |
| Tracking API URL / Mode | Testing / Production endpoint | `[Production / Testing]` |
### Option B: Xpressbees
| Field | Description | Client Input |
| :--- | :--- | :--- |
| Email / Account ID | Registered Xpressbees account email | `[Account Email]` |
| API Token / Secret Key | Xpressbees authorization token | `[API Token]` |
| Tracking / Order Endpoint | Production or Staging | `[Production / Staging]` |
---
## 6. 🔌 Custom API / Webhooks (Optional)
If you wish the WhatsApp bot to communicate with your custom backend, internal CRM, or ERP:
| Integration Detail | Description | Value / Specification |
| :--- | :--- | :--- |
| Order Lookup API | Endpoint to verify order status / customer phone | `GET /api/orders/lookup?phone={phone}` |
| Inventory / Stock API | Endpoint to check live product stock | `GET /api/inventory/check?sku={sku}` |
| Lead Capture Webhook | Webhook URL where new WhatsApp leads are pushed | `POST https://your-crm.com/leads/webhook` |
| Authorization Header | Bearer token or API key for secure API communication | `Bearer xxxxx...` |
---
## 7. 🤖 AI Bot Persona & Human Escalation Rules
| Parameter | Configuration Options | Client Selection |
| :--- | :--- | :--- |
| Bot Tone / Style | Professional / Friendly / Casual / Luxury / Technical | `[e.g., Friendly & Professional]` |
| Welcome / Greeting Message | Custom greeting message sent when user says "Hi" | `[Custom Greeting or Default AI]` |
| Primary Language(s) | English, Hindi, Hinglish, or Regional Languages | `[e.g., English + Hindi/Hinglish]` |
| Fallback & Escalation Message | Message sent when human agent intervention is requested | `[Custom Fallback Message]` |
| Human Handoff Trigger | Auto-escalate when customer asks for "human", "agent", or "support" | Enabled `[Yes / No]` |
| Live Alert Notification | WhatsApp number or Email to alert your team of urgent inquiries | `[Alert Phone / Email]` |
---
## 8. 👥 Team Accounts & User Roles
Kindly list the team members who will have access to the Admin Dashboard & Live Chat Inbox:
| Full Name | Email Address | Role (`Tenant Admin` / `Sub Admin` / `Support Agent` / `Distributor`) | Phone Number |
| :--- | :--- | :--- | :--- |
| 1. | `admin@company.com` | Tenant Admin (Full Control) | `+91 ...` |
| 2. | `support@company.com` | Sub Admin / Support Agent (Live Inbox & Orders) | `+91 ...` |
| 3. | `distributor@company.com` | Distributor (Stock & Orders only) | `+91 ...` |
---
## 🚀 Submission & Next Steps
1. Fill In the Tables: Complete the fields above for your brand.
2. Attach Files: Attach your Logo, FAQs, and Product/Catalog files.
3. Submit to Onboarding Team: Send this document to your account manager or upload it directly through the Admin Console.
4. Go-Live: Our team will configure your sandbox and connect your Send2Digital WhatsApp line for testing within 24-48 hours!
---

For any questions or assistance, please reach out to our support team.