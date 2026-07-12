"""
Send and edit Telegram messages via the Bot API using httpx.

All functions are async. Use `send_message` for outgoing replies.
"""

from __future__ import annotations

import os

import httpx

_BASE_URL = "https://api.telegram.org/bot{token}/{method}"


def _url(method: str) -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")
    return _BASE_URL.format(token=token, method=method)


async def send_message(
    chat_id: int | str,
    text: str,
    parse_mode: str = "HTML",
    disable_notification: bool = False,
) -> dict:
    """Send a text message to a Telegram chat."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            _url("sendMessage"),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_notification": disable_notification,
            },
        )
        response.raise_for_status()
        return response.json()


async def send_message_sync(chat_id: int | str, text: str) -> dict:
    """Synchronous wrapper for use in non-async cron jobs."""
    import asyncio

    return asyncio.run(send_message(chat_id, text))
