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

# Насколько широкое окно вырезаем вокруг найденной по первому проходу позиции
# заголовка — компенсирует погрешность оценки модели.
CROP_MARGIN_ABOVE = 0.08
CROP_MARGIN_BELOW = 0.35


# Gemini иногда отвечает 503 ("high demand") — обычно проходит за минуту-две,
# поэтому есть смысл ретраить с паузой прямо здесь, а не падать с первого раза.
VISION_RETRY_ATTEMPTS = 4
VISION_RETRY_DELAY_SECONDS = 30


def _ask_vision(image_bytes: bytes, prompt: str) -> str:
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
            if not response.text or not response.text.strip():
                raise RuntimeError("Gemini вернул пустой ответ")
            return response.text.strip()
        except genai_errors.ServerError as e:
            last_error = e
            if attempt < VISION_RETRY_ATTEMPTS:
                print(f"⚠️ Gemini недоступен (попытка {attempt}/{VISION_RETRY_ATTEMPTS}): {e}")
                time.sleep(VISION_RETRY_DELAY_SECONDS)
    raise last_error


def _locate_heading_fraction(image_bytes: bytes) -> float:
    raw = _ask_vision(image_bytes, LOCATE_PROMPT)
    match = re.search(r"(?<!\d)(0(?:\.\d+)?|1(?:\.0+)?)(?!\d)", raw)
    if not match:
        return 0.3  # разумное значение по умолчанию, если модель не дала число
    fraction = float(match.group(1))
    return min(max(fraction, 0.0), 1.0)


def _strip_english(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        if line.strip().startswith("-"):
            prefix, _, rest = line.partition("-")
            dish = rest.split("/")[0].strip()
            line = f"{prefix}- {dish}"
        lines.append(line.rstrip())
    return "\n".join(lines)


def get_business_lunch() -> str:
    image_bytes = requests.get(CONFIG["menu_image_url"], timeout=30).content
    image = Image.open(io.BytesIO(image_bytes))
    width, height = image.size

    fraction = _locate_heading_fraction(image_bytes)

    top = max(0, int(height * (fraction - CROP_MARGIN_ABOVE)))
    bottom = min(height, int(height * (fraction + CROP_MARGIN_BELOW)))
    crop = image.crop((0, top, width, bottom))

    buffer = io.BytesIO()
    crop.save(buffer, format="JPEG", quality=95)
    crop_bytes = buffer.getvalue()

    result = _ask_vision(crop_bytes, EXTRACT_PROMPT)
    if result.strip() == "NOT_FOUND":
        raise RuntimeError("Раздел БИЗНЕС ЛАНЧ не найден в вырезанном фрагменте меню")
    return _strip_english(result)
