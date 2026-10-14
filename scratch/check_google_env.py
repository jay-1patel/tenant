import os
from dotenv import load_dotenv

load_dotenv('routing/.env')
load_dotenv('.env')

keys = ['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_REFRESH_TOKEN', 'GOOGLE_SERVICE_ACCOUNT_JSON', 'GOOGLE_CALENDAR_ID', 'GOOGLE_REDIRECT_URI']
for k in keys:
    val = os.getenv(k)
    print(f"{k}: {'SET' if val else 'NOT SET'}")
