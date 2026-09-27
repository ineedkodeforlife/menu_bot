import sys
import time
import traceback

from config import CONFIG
from menu_parser import download_menu, get_business_lunch
from telegram_bot import send_message, send_photo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

MAX_ATTEMPTS = 3          # сколько раз перезапускаем распознавание целиком
RETRY_DELAY_SECONDS = 20  # пауза между перезапусками


def main() -> int:
    print("🍽️ Смотрим меню и ищем бизнес-ланч...\n")

    result = None
    last_error = None
    try:
        image_bytes = download_menu()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            print(f"\n— Попытка {attempt}/{MAX_ATTEMPTS}")
            try:
                result = get_business_lunch(image_bytes, attempt)
                break
            except Exception as e:
                last_error = e
                traceback.print_exc()
                if attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_DELAY_SECONDS)
    except Exception as e:
        last_error = e
        traceback.print_exc()

    if result is None:
        # Все попытки провалились: присылаем хотя бы саму картинку меню
        print("\n❌ Меню распознать не удалось, отправляю картинку")
        caption = (
            f"⚠️ Не получилось распознать бизнес-ланч за {MAX_ATTEMPTS} попытки.\n"
            f"Вот меню целиком.\n\nОшибка: {type(last_error).__name__}: {last_error}"
        )
        try:
            send_photo(CONFIG["menu_image_url"], caption)
        except Exception:
            send_message(caption + f"\n\n{CONFIG['menu_image_url']}")
        return 1  # помечаем запуск как упавший (красный в GitHub Actions)

    print(result)
    print("\n📨 Отправляем в Telegram...")
    send_message(result)
    print("✅ Отправлено")
    return 0


if __name__ == "__main__":
    sys.exit(main())
