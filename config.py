import os
from dotenv import load_dotenv
load_dotenv()

def int_env(name, default=0):
    raw=os.getenv(name,'').strip()
    try:return int(raw) if raw else default
    except ValueError:return default

BOT_TOKEN=os.getenv('BOT_TOKEN','').strip()
OWNER_TELEGRAM_ID=int_env('OWNER_TELEGRAM_ID')
STAFF_GROUP_ID=int_env('STAFF_GROUP_ID')
CLICK_PROVIDER_TOKEN=os.getenv('CLICK_PROVIDER_TOKEN','').strip()
PAYME_PROVIDER_TOKEN=os.getenv('PAYME_PROVIDER_TOKEN','').strip()
