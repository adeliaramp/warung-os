"""
Supabase client singleton.

All database access goes through `get_client()`. The client is initialized
once on first call and reused. If credentials are missing the function raises
RuntimeError with a clear message.
"""

import os
from functools import lru_cache

from supabase import Client, create_client


@lru_cache(maxsize=1)
def get_client() -> Client:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment. "
            "Copy .env.example to .env and fill in your credentials."
        )
    return create_client(url, key)
