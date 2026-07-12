"""
WarungOS FastAPI app.

Endpoints:
    GET  /health    — liveness probe for Hugging Face Space
    POST /webhook   — Telegram Bot API webhook
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response

from bot.handlers import dispatch
from bot.parser import parse
from bot.sender import send_message

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="WarungOS")

# Only messages from this chat_id are processed.
# Set MERCHANT_CHAT_ID in .env (your Telegram user id or group chat id).
_MERCHANT_CHAT_ID = os.environ.get("MERCHANT_CHAT_ID", "")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    """
    Receive a Telegram Update, parse the message, write to DB, and reply.

    The webhook returns 200 immediately even if processing fails so Telegram
    does not retry the same message in a loop.
    """
    try:
        update = await request.json()
        await _process_update(update)
    except Exception as exc:
        logger.error("Error processing update: %s", exc, exc_info=True)

    return Response(status_code=200)


async def _process_update(update: dict) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return  # callbacks, channel posts, etc. — ignore for now

    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if not chat_id or not text:
        return

    # Only respond to the registered merchant chat to prevent abuse.
    if _MERCHANT_CHAT_ID and str(chat_id) != str(_MERCHANT_CHAT_ID):
        logger.warning("Message from unknown chat_id %s — ignored.", chat_id)
        return

    logger.info("Received from %s: %r", chat_id, text)

    intent = parse(text)
    logger.info("Parsed intent: %s", intent)

    reply = dispatch(intent, chat_id)
    await send_message(chat_id, reply)
