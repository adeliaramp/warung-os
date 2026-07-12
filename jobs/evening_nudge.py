"""
Evening nudge job — runs via GitHub Actions cron at 19:00 WIB (12:00 UTC).

If no sales were recorded today, sends a friendly reminder to the merchant
to log the day's sales before closing.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def run() -> None:
    from bot.db import get_client
    from bot.sender import send_message

    chat_id = os.environ.get("MERCHANT_CHAT_ID", "")
    if not chat_id:
        print("ERROR: MERCHANT_CHAT_ID is not set.")
        sys.exit(1)

    today = datetime.date.today().isoformat()

    result = get_client().table("sales").select("sale_id").eq("sale_date", today).limit(1).execute()
    has_sales_today = bool(result.data)

    if has_sales_today:
        print(f"Sales already logged for {today}. No nudge needed.")
        return

    message = (
        f"Halo! Hari ini ({today}) belum ada penjualan yang tercatat.\n\n"
        "Kalau ada yang terjual, ketik nama barang dan jumlahnya ya.\n"
        "Contoh: indomie 3\n\n"
        "Terima kasih!"
    )

    print("Sending evening nudge:")
    print(message)
    await send_message(chat_id, message)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(run())
