"""
database.py  -  Supabase connection (tables not required).
                Connection is established on startup.
                No data is written to any table.
"""

import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Establish connection on import
client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("[DB] Supabase connected successfully.")
    except Exception as e:
        print(f"[DB] Supabase connection failed: {e}")
else:
    print("[DB] Supabase keys not set — running without database.")


def save_message(*args, **kwargs):
    pass   # Connection active but no table writes


def save_lead(*args, **kwargs):
    pass   # Connection active but no table writes
