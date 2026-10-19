import sqlite3

conn = sqlite3.connect('faq.db')
cur = conn.cursor()

cur.execute("""
INSERT OR REPLACE INTO tenants (
    id, company_name, slug, vertical, industry_type, display_name, 
    welcome_message, is_active, status, brand_color
) VALUES (
    10, 'Skyline Realty & Developers', 'skylinerealty', 'real_estate', 'real_estate', 'Skyline Realty',
    'Welcome to Skyline Realty! 🏙️ Discover our premium residential residences & commercial spaces, or schedule a guided site visit today.',
    1, 'active', '#1E3A8A'
)
""")
conn.commit()
print("Tenant inserted successfully!")

cur.execute("SELECT id, slug, company_name, vertical, is_active FROM tenants WHERE slug = 'skylinerealty'")
row = cur.fetchone()
print("Registered row:", row)
conn.close()
