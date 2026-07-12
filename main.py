import sys

from menu_parser import get_business_lunch
from telegram_bot import send_message

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def main():
    print("🍽️ Смотрим меню и ищем бизнес-ланч...\n")
    result = get_business_lunch()
    print(result)

    print("\n📨 Отправляем в Telegram...")
    send_message(result)
    print("✅ Отправлено")


if __name__ == "__main__":
    main()
