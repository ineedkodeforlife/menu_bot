import io
import re
import time

import requests
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from PIL import Image

from config import CONFIG

client = genai.Client(api_key=CONFIG["gemini_api_key"])


class MenuParseError(RuntimeError):
    """Меню скачалось, но бизнес-ланч распознать не удалось."""


LOCATE_PROMPT = """Это меню столовой в виде одной длинной вертикальной картинки (страницы уложены
друг под другом). Где-то в верхней половине находится раздел с крупным зелёным заголовком
БИЗНЕС ЛАНЧ / BUSINESS LUNCH (не путай с БИЗНЕС ЗАВТРАК / BUSINESS BREAKFAST, который идёт раньше).

Оцени, на какой ДОЛЕ высоты картинки (0.0 — самый верх, 1.0 — самый низ) находится этот зелёный
заголовок БИЗНЕС ЛАНЧ. Не рассуждай, не объясняй. Ответ должен состоять ТОЛЬКО из одного числа
от 0 до 1, например: 0.42"""

EXTRACT_PROMPT = """На этом кропе меню столовой может быть ДВА похожих списка блюд по категориям
(Салаты/Супы/Горячие блюда/Гарниры/Напитки): один — часть общего раздела "Обед", другой — под
отдельным крупным зелёным заголовком "БИЗНЕС ЛАНЧ / BUSINESS LUNCH".

Тебе нужен ТОЛЬКО второй список — тот, что расположен НЕПОСРЕДСТВЕННО ПОСЛЕ зелёного заголовка
"БИЗНЕС ЛАНЧ / BUSINESS LUNCH" и текста "ФОРМУЛА ПРАВИЛЬНОГО ОБЕДА", и ДО следующего зелёного
разделителя/логотипа. Полностью проигнорируй любой список блюд, который находится ВЫШЕ этого
заголовка.

Перечисли блюда раздела БИЗНЕС ЛАНЧ по категориям (Салаты, Супы, Горячие блюда, Гарниры, Напитки)
ровно как они написаны на картинке. Важно:
- Название блюда — это ЖИРНЫЙ текст. Мелкий серый текст под ним — это состав (ингредиенты), а
  не отдельное блюдо. Не превращай ингредиенты в отдельные пункты списка.
- На картинке у каждого блюда название дано на русском и через "/" — перевод на английском
  (например "Гречка отварная/Buckwheat"). Указывай ТОЛЬКО русскую часть, без "/" и без
  английского перевода.
- В каждой категории обычно 2-4 блюда — внимательно проверь, что ты нашёл ВСЕ блюда категории,
  а не только первое.
- НЕ указывай цену рядом с блюдами: у блюд БИЗНЕС ЛАНЧа нет отдельной цены, есть только общая
  цена комплекса (332 руб / 305 руб) — не приписывай её к каждому блюду.
- Ничего не выдумывай и не добавляй блюда из других разделов. Если какой-то категории в этом
  разделе нет, пропусти её.

Если раздела БИЗНЕС ЛАНЧ на этом кропе вообще нет, ответь только: "NOT_FOUND".

Формат ответа — markdown:

## Бизнес-ланч
### Салаты
- ...
### Супы
- ...
### Горячие блюда
- ...
### Гарниры
- ...
### Напитки
- ...
"""

# Окно вокруг найденного заголовка для каждой попытки: (сверху, снизу).
# Каждая следующая попытка режет шире, последняя — вся картинка без обрезки.
CROP_STRATEGIES = [
    (0.08, 0.35),
    (0.20, 0.50),
    None,  # None = отправляем всё меню целиком
]

# Минимум, чтобы считать ответ осмысленным, а не галлюцинацией/обрывком.
MIN_CATEGORIES = 2
MIN_DISHES = 4

VISION_RETRY_ATTEMPTS = 4
VISION_RETRY_DELAY_SECONDS = 30
DOWNLOAD_RETRY_ATTEMPTS = 3
DOWNLOAD_RETRY_DELAY_SECONDS = 20


def _ask_vision(image_bytes: bytes, prompt: str) -> str:
    """Запрос к Gemini с ретраями на 5xx, 429 и пустой ответ."""
    last_error = None
    for attempt in range(1, VISION_RETRY_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(
                model=CONFIG["llm_model"],
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    prompt,
                ],
            )
            text = (response.text or "").strip()
            if not text:
                raise MenuParseError("Gemini вернул пустой ответ")
            return text
        except genai_errors.ClientError as e:
            # 429 (лимит) имеет смысл переждать, остальные 4xx (ключ, модель) — нет
            if getattr(e, "code", None) != 429:
                raise
            last_error = e
        except (genai_errors.ServerError, MenuParseError, requests.RequestException) as e:
            last_error = e

        if attempt < VISION_RETRY_ATTEMPTS:
            print(f"⚠️ Gemini: попытка {attempt}/{VISION_RETRY_ATTEMPTS} не удалась: {last_error}")
            time.sleep(VISION_RETRY_DELAY_SECONDS)
    raise last_error


def download_menu() -> bytes:
    last_error = None
    for attempt in range(1, DOWNLOAD_RETRY_ATTEMPTS + 1):
        try:
            response = requests.get(CONFIG["menu_image_url"], timeout=30)
            response.raise_for_status()
            # Проверяем, что это действительно картинка, а не HTML-заглушка
            Image.open(io.BytesIO(response.content)).verify()
            return response.content
        except Exception as e:
            last_error = e
            if attempt < DOWNLOAD_RETRY_ATTEMPTS:
                print(f"⚠️ Скачивание меню: попытка {attempt}/{DOWNLOAD_RETRY_ATTEMPTS}: {e}")
                time.sleep(DOWNLOAD_RETRY_DELAY_SECONDS)
    raise RuntimeError(f"Не удалось скачать картинку меню: {last_error}")


def _locate_heading_fraction(image_bytes: bytes) -> float:
    raw = _ask_vision(image_bytes, LOCATE_PROMPT)
    match = re.search(r"(?<!\d)(0(?:\.\d+)?|1(?:\.0+)?)(?!\d)", raw)
    if not match:
        print(f"⚠️ Модель не вернула число ({raw!r}), беру 0.3")
        return 0.3
    return min(max(float(match.group(1)), 0.0), 1.0)


def _strip_english(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        if line.strip().startswith("-"):
            prefix, _, rest = line.partition("-")
            dish = rest.split("/")[0].strip()
            line = f"{prefix}- {dish}"
        lines.append(line.rstrip())
    return "\n".join(lines)


def _validate(result: str) -> None:
    if "NOT_FOUND" in result:
        raise MenuParseError("Раздел БИЗНЕС ЛАНЧ не найден на фрагменте")
    categories = sum(1 for l in result.splitlines() if l.strip().startswith("### "))
    dishes = sum(1 for l in result.splitlines() if l.strip().startswith("- ") and len(l.strip()) > 3)
    if categories < MIN_CATEGORIES or dishes < MIN_DISHES:
        raise MenuParseError(
            f"Ответ выглядит неполным: категорий {categories}, блюд {dishes}\n{result}"
        )


def get_business_lunch(image_bytes: bytes, attempt: int = 1) -> str:
    """attempt (1..N) выбирает стратегию обрезки: чем дальше, тем шире окно."""
    strategy = CROP_STRATEGIES[min(attempt, len(CROP_STRATEGIES)) - 1]

    if strategy is None:
        print("🔎 Стратегия: всё меню целиком")
        target_bytes = image_bytes
    else:
        above, below = strategy
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = image.size
        fraction = _locate_heading_fraction(image_bytes)
        top = max(0, int(height * (fraction - above)))
        bottom = min(height, int(height * (fraction + below)))
        print(f"🔎 Заголовок ~{fraction:.2f}, режем {top}..{bottom} из {height}px")

        buffer = io.BytesIO()
        image.crop((0, top, width, bottom)).save(buffer, format="JPEG", quality=95)
        target_bytes = buffer.getvalue()

    result = _strip_english(_ask_vision(target_bytes, EXTRACT_PROMPT))
    _validate(result)
    return result
