import requests

from config import CONFIG


def _to_telegram_html(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("### "):
            lines.append(f"<b>{stripped[4:]}</b>")
        elif stripped.startswith("## "):
            lines.append(f"<b>{stripped[3:]}</b>")
        elif stripped.startswith("- "):
            lines.append(f"• {stripped[2:]}")
        else:
            lines.append(stripped)
    return "\n".join(lines)


def send_message(text: str) -> None:
    token = CONFIG["telegram_bot_token"]
    chat_id = CONFIG["telegram_chat_id"]
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не заданы в .env")

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": _to_telegram_html(text),
            "parse_mode": "HTML",
        },
        timeout=15,
    )
    response.raise_for_status()
