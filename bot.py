#!/usr/bin/env python3
"""
Inline YouTube search bot (polling). 
Usage: enable Inline Mode in BotFather, then type "@YourBotUsername cats" in any chat.
Set env vars TELEGRAM_TOKEN and YOUTUBE_API_KEY before running.
"""
import os
import asyncio
import base64
import json
import html
import requests
from typing import Optional

from telegram import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import Application, InlineQueryHandler, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
if not TELEGRAM_TOKEN or not YOUTUBE_API_KEY:
    raise SystemExit("Set TELEGRAM_TOKEN and YOUTUBE_API_KEY as environment variables.")

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
RESULTS_PER_PAGE = 10  # show 10 cards per inline page


async def youtube_search(query: str, page_token: Optional[str] = None, max_results: int = RESULTS_PER_PAGE):
    """Run a blocking requests.get inside a thread so we don't block the event loop."""
    def _sync():
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "key": YOUTUBE_API_KEY,
        }
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=8)
        r.raise_for_status()
        return r.json()
    return await asyncio.to_thread(_sync)


def encode_offset(query: str, page_token: Optional[str]) -> str:
    payload = {"q": query, "pageToken": page_token}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_offset(offset: str):
    try:
        decoded = base64.urlsafe_b64decode(offset.encode()).decode()
        obj = json.loads(decoded)
        return obj.get("q"), obj.get("pageToken")
    except Exception:
        return None, None


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    iq = update.inline_query
    query = (iq.query or "").strip()
    offset = iq.offset or ""
    page_token = None

    # If offset was set by our previous response and the query is the same,
    # use the encoded pageToken. Otherwise start fresh.
    if offset:
        oq, otoken = decode_offset(offset)
        if oq == query:
            page_token = otoken

    if not query:
        # If empty query, we return nothing (you could return trending here).
        await iq.answer([], is_personal=True, cache_time=1, next_offset="")
        return

    try:
        data = await youtube_search(query, page_token)
    except Exception as e:
        # On error, respond with nothing (client won't crash). Check logs.
        print("YouTube API error:", e)
        await iq.answer([], is_personal=True, cache_time=1, next_offset="")
        return

    items = data.get("items", [])
    next_token = data.get("nextPageToken", "")

    results = []
    for it in items:
        vid = it["id"].get("videoId")
        if not vid:
            continue
        s = it["snippet"]
        title = s.get("title", "YouTube video")
        channel = s.get("channelTitle", "")
        desc = (s.get("description") or "")[:120]
        # prefer medium thumbnail if present
        thumb = s.get("thumbnails", {}).get("medium", s.get("thumbnails", {}).get("default", {})).get("url")
        url = f"https://youtu.be/{vid}"
        input_text = html.escape(f"{title}\n{url}")
        # When the user selects the inline result, this text is inserted/sent to chat.
        input_content = InputTextMessageContent(input_text, parse_mode="HTML")

        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Open on YouTube", url=url)]])

        results.append(
            InlineQueryResultArticle(
                id=vid,
                title=title,
                description=(channel or desc),
                thumb_url=thumb,
                input_message_content=input_content,
                reply_markup=kb,
            )
        )

    next_offset = encode_offset(query, next_token) if next_token else ""
    # is_personal=True so results aren't cached across users (good for personal queries)
    await iq.answer(results, is_personal=True, cache_time=30, next_offset=next_offset)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Inline YouTube search bot ready! To use: in any chat type @YourBotUsername <search term>\n"
        "Example: @YourBotUsername lo-fi beats"
    )


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(InlineQueryHandler(inline_query_handler))
    # polling is fine for a Render background worker
    app.run_polling(allowed_updates=["inline_query", "message"])
    

if __name__ == "__main__":
    main()
