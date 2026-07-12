import os
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    "menu_image_url": "https://freshvote.ru/menu/000000035.jpg",
    "llm_model": "gemini-3.5-flash",
    "gemini_api_key": os.getenv("GEMINI_API_KEY"),
    "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN"),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID"),
}
