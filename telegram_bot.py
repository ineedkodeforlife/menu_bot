import html
import time

import requests

from config import CONFIG

SEND_RETRY_ATTEMPTS = 3
SEND_RETRY_DELAY_SECONDS = 10


def _to_telegram_html(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("### "):
            lines.append(f"<b>{html.escape(stripped[4:])}</b>")
        elif stripped.startswith("## "):
            lines.append(f"<b>{html.escape(stripped[3:])}</b>")
        elif stripped.startswith("- "):
            lines.append(f"• {html.escape(stripped[2:])}")
        else:
            lines.append(html.escape(stripped))
    return "\n".join(lines)


def _call(method: str, payload: dict) -> None:
    token = CONFIG["telegram_bot_token"]
    chat_id = CONFIG["telegram_chat_id"]
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не заданы")

    last_error = None
    for attempt in range(1, SEND_RETRY_ATTEMPTS + 1):
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/{method}",
                json={"chat_id": chat_id, **payload},
                timeout=15,
            )
            response.raise_for_status()
            return
        except requests.RequestException as e:
            last_error = e
            if attempt < SEND_RETRY_ATTEMPTS:
                print(f"⚠️ Telegram: попытка {attempt}/{SEND_RETRY_ATTEMPTS}: {e}")
                time.sleep(SEND_RETRY_DELAY_SECONDS)
    raise last_error


def send_message(text: str) -> None:
    _call("sendMessage", {"text": _to_telegram_html(text), "parse_mode": "HTML"})


def send_photo(photo_url: str, caption: str) -> None:
    _call("sendPhoto", {"photo": photo_url, "caption": caption[:1024]})
