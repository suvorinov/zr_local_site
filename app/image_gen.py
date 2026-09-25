"""Генерация поздравительных открыток.

Создаёт праздничную открытку поверх фоновой картинки:
- композиция из градиента, мягкого золотого сияния, звёзд и рамки;
- заголовок «Поздравляем с днём рождения / юбилеем <ФИО в родительном падеже>!»;
- крупная цифра возраста для юбилейных дат;
- обращение с учётом пола сотрудника («Дорогой» / «Дорогая»);
- пожелание из тематического набора (обычный день рождения / юбилей);
- подпись коллектива.

Текст собирается автоматически из шаблонов по имени, полу и возрасту,
поэтому готовая открытка создаётся для любого количества сотрудников.
"""

import logging
import math
import random
import re
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from petrovich.enums import Case, Gender
from petrovich.main import Petrovich

from app import timeutils
from app.config import settings

logger = logging.getLogger(__name__)

_FONT_DIR = Path(__file__).resolve().parent / "static" / "fonts"
_LOBBY_PATH = _FONT_DIR / "lobster" / "Lobster-Regular.ttf"

_GOLD = (255, 215, 0)
_WHITE = (255, 255, 255)
_DIM_GOLD = (222, 190, 96)

# Юбилейная дата: возраст кратен шагу и не меньше минимума
_JUBILEE_STEP = 5
_JUBILEE_MIN_AGE = 25

_ADDRESS_PREFIX = {"male": "Дорогой", "female": "Дорогая"}

_NEUTRAL_WISHES = (
    "Желаем крепкого здоровья, энергии и новых побед! "
    "Пусть каждый день приносит радость и хорошее настроение.",
    "Пусть сбываются самые смелые мечты, а работа приносит только "
    "удовольствие и уверенность в завтрашнем дне.",
    "Желаем удачи во всех начинаниях, благополучия в семье "
    "и верных друзей рядом. С праздником!",
    "Пусть всё задуманное непременно сбывается, а рядом всегда "
    "будут близкие люди и отличное настроение!",
    "Пусть жизнь дарит яркие моменты, а здоровье остаётся крепким. "
    "Счастья вам и вашим близким!",
    "Желаем стабильности, спокойствия и уверенности в завтрашнем дне. "
    "Пусть все планы легко воплощаются в жизнь.",
    "Пусть работа вдохновляет, а дома ждёт уют и тепло. "
    "Здоровья, сил и доброго настроения!",
    "Желаем, чтобы каждый день приносил повод для улыбки, "
    "а все дела складывались легко и удачно. С праздником!",
    "Пусть удача сопутствует во всём, а рядом будут надёжные люди. "
    "Желаем благополучия, здоровья и душевного равновесия.",
    "Желаем, чтобы жизнь была наполнена интересными событиями, "
    "а каждый новый день открывал новые возможности. С праздником!",
)

_FEMALE_WISHES = (
    "Желаем здоровья, красоты и вдохновения! Пусть каждый день будет "
    "наполнен теплом, улыбками и заботой близких.",
    "Пусть сбываются самые заветные мечты, а настроение всегда "
    "остаётся солнечным и радостным.",
    "Желаем гармонии, взаимопонимания и любви в семье, лёгкости "
    "в делах и ярких впечатлений каждый день.",
    "Пусть в душе всегда цветёт весна, а рядом будут только добрые "
    "и искренние люди. С праздником!",
    "Пусть каждый день начинается с улыбки, а любое дело ладится. "
    "Красоты вам, здоровья и счастья!",
    "Желаем, чтобы жизнь была наполнена теплом, заботой и вниманием. "
    "Пусть всё получается легко, а сердце всегда будет наполнено радостью.",
    "Пусть вдохновение не покидает, а каждый день дарит повод "
    "улыбнуться. Здоровья, красоты и душевного спокойствия!",
    "Желаем, чтобы рядом были те, кто ценит и поддерживает, "
    "а впереди ждали только светлые и радостные дни. С праздником!",
    "Пусть жизнь будет щедрой на приятные сюрпризы, тёплые встречи "
    "и моменты, от которых становится хорошо на душе.",
    "Желаем лёгкости во всём, внутреннего света и уверенности в себе. "
    "Пусть каждый день приносит только хорошие новости!",
)

_JUBILEE_WISHES = (
    "Пусть новый десяток станет самым счастливым! Крепкого здоровья, "
    "энергии и исполнения самых смелых желаний.",
    "Желаем бодрости духа, мудрости и молодости сердца! Пусть всё "
    "задуманное сбывается, а близкие радуют каждый день.",
    "С юбилеем! Пусть впереди будет много светлых дней, верных "
    "друзей и поводов для гордости.",
    "Пусть юбилей станет началом новой главы, полной здоровья, "
    "радости и уважения. С праздником!",
    "Желаем долгих лет в окружении любящих людей, благополучия "
    "дома и признания на работе!",
    "С юбилеем! Пусть накопленный опыт и мудрость помогают "
    "идти вперёд, а впереди ждёт только лучшее. Здоровья и счастья!",
    "Желаем, чтобы каждый новый год жизни приносил новые возможности, "
    "яркие события и поводы для радости. С юбилеем!",
    "Пусть юбилей станет поводом для тёплых воспоминаний "
    "и вдохновения на новые свершения. Крепкого здоровья и благополучия!",
    "С юбилеем! Пусть впереди будет много интересных проектов, "
    "добрых людей рядом и поводов для искренней улыбки.",
    "Желаем, чтобы возраст был лишь цифрой, а в душе всегда жила "
    "молодость, энергия и вера в лучшее. С праздником!",
)


_MALE_PALETTE = (
    ((11, 24, 56, 200), (30, 58, 108, 160)),    # тёмно-синий
    ((22, 28, 56, 200), (58, 96, 148, 160)),    # синий
    ((28, 22, 52, 200), (86, 70, 140, 160)),    # сине-фиолетовый
)

_FEMALE_PALETTE = (
    ((92, 24, 60, 210), (176, 78, 120, 180)),   # бордо → розовый
    ((62, 18, 56, 210), (150, 54, 112, 180)),   # слива → малиновый
    ((124, 44, 52, 210), (198, 122, 92, 180)),  # кирпичный → коралл
)


def _get_font(size: int, decorative: bool = False) -> ImageFont.FreeTypeFont:
    """Загружает шрифт для отрисовки текста.

    Args:
        size: Размер шрифта.
        decorative: Использовать декоративный шрифт (Lobster) для имен
            и заголовков; обычные тексты — DejaVu Sans.

    Returns:
        Объект шрифта.
    """
    if decorative:
        if _LOBBY_PATH.exists():
            return ImageFont.truetype(str(_LOBBY_PATH), size)
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        ]
    else:
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
        ]
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _select_background(gender: str) -> Path:
    """Выбирает случайный фон из каталога соответствующего пола.

    Args:
        gender: Пол сотрудника (male/female).

    Returns:
        Путь к выбранному фоновому изображению.
    """
    bg_dir = settings.background_dir / gender
    if not bg_dir.exists():
        bg_dir.mkdir(parents=True, exist_ok=True)

    images = list(bg_dir.glob("*.[jJ][pP][gG]")) + \
             list(bg_dir.glob("*.[jJ][pP][eE][gG]")) + \
             list(bg_dir.glob("*.[pP][nN][gG]"))

    if not images:
        logger.warning("Фоновые изображения не найдены в %s, будет использован сплошной фон", bg_dir)
        dummy = bg_dir / "_fallback.png"
        if not dummy.exists():
            bg = Image.new("RGB", (1920, 1080), (30, 40, 60))
            bg.save(str(dummy))
        return dummy

    return random.choice(images)


def _draw_gradient(draw: ImageDraw, width: int, height: int,
                   color_top: tuple, color_bottom: tuple) -> None:
    """Рисует вертикальный градиент на всю область.

    Args:
        draw: Объект ImageDraw.
        width: Ширина изображения.
        height: Высота изображения.
        color_top: Цвет сверху (RGBA).
        color_bottom: Цвет снизу (RGBA).
    """
    for y in range(height):
        ratio = y / height
        r = int(color_top[0] + (color_bottom[0] - color_top[0]) * ratio)
        g = int(color_top[1] + (color_bottom[1] - color_top[1]) * ratio)
        b = int(color_top[2] + (color_bottom[2] - color_top[2]) * ratio)
        a = int(color_top[3] + (color_bottom[3] - color_top[3]) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b, a))


def _draw_radial_glow(overlay: Image.Image, cx: int, cy: int,
                      radius: int, color: tuple, alpha: int) -> None:
    """Рисует мягкое радиальное сияние вокруг центра.

    Args:
        overlay: RGBA-слой для наложения.
        cx: Центр по X.
        cy: Центр по Y.
        radius: Радиус сияния.
        color: Цвет (RGB).
        alpha: Максимальная прозрачность в центре.
    """
    w, h = overlay.size
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    for i in range(48, 0, -1):
        r = radius * i // 48
        a = int(alpha * i / 48)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*color, a))
    overlay.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=int(radius * 0.35))))


def _draw_stars(draw: ImageDraw, width: int, height: int) -> None:
    """Рисует рассыпанные праздничные звёзды и точки.

    Args:
        draw: Объект ImageDraw.
        width: Ширина изображения.
        height: Высота изображения.
    """
    colors = [
        (255, 232, 150, 220),   # тёплый золотой
        (255, 255, 255, 200),   # белый
        (255, 210, 90, 200),    # золотой
    ]
    for _ in range(random.randint(16, 26)):
        x = random.randint(40, width - 40)
        y = random.randint(60, height - 60)
        r = random.randint(3, 11)
        color = random.choice(colors)
        if random.random() < 0.7:
            points = []
            for i in range(10):
                rad = r if i % 2 == 0 else r // 2
                a = math.pi * 2 * i / 10 - math.pi / 2
                points.append((x + rad * math.cos(a), y + rad * math.sin(a)))
            draw.polygon(points, fill=color)
        else:
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _draw_vignette(overlay: Image.Image) -> None:
    """Накладывает виньетку (затемнение по краям) на overlay-слой.

    Args:
        overlay: RGBA-изображение-оверлей для наложения виньетки.
    """
    import numpy as np

    height, width = overlay.size[1], overlay.size[0]

    y_coords, x_coords = np.ogrid[:height, :width]
    cx, cy = width / 2, height / 2

    dist_x = np.minimum(x_coords, width - x_coords) / cx
    dist_y = np.minimum(y_coords, height - y_coords) / cy
    ratio = np.minimum(dist_x, dist_y)

    alpha = np.where(ratio < 0.5, ((0.5 - ratio) * 200).astype(np.uint8), 0)

    vignette_img = Image.fromarray(
        np.stack([np.zeros_like(alpha), np.zeros_like(alpha),
                  np.zeros_like(alpha), alpha], axis=-1),
        'RGBA'
    )
    overlay.alpha_composite(vignette_img)


def _draw_text_with_shadow(draw: ImageDraw, xy: tuple[int, int],
                            text: str, font: ImageFont.FreeTypeFont,
                            fill: tuple, shadow_color: str = "black",
                            shadow_offset: int = 4) -> None:
    """Рисует текст с мягкой тенью.

    Args:
        draw: Объект ImageDraw.
        xy: Координаты текста.
        text: Текст.
        font: Шрифт.
        fill: Цвет текста.
        shadow_color: Цвет тени.
        shadow_offset: Смещение тени.
    """
    x, y = xy
    for dx, dy in [(-2, 2), (2, 2), (-2, 0), (2, 0), (0, 3), (0, 5)]:
        draw.text((x + dx, y + dy), text, fill=shadow_color, font=font)
    draw.text((x, y + 2), text, fill=shadow_color, font=font)
    draw.text((x, y), text, fill=fill, font=font)


def _draw_ornament(draw: ImageDraw, cx: int, y: int,
                   width: int, color: tuple, accent: tuple) -> None:
    """Рисует декоративную линию со звёздочками и ромбом по центру.

    Args:
        draw: Объект ImageDraw.
        cx: Центр по X.
        y: Позиция по Y.
        width: Ширина линии.
        color: Цвет линии (RGBA).
        accent: Цвет звёздочек (RGBA).
    """
    span = min(width // 2 - 120, 480)
    half = span // 3
    draw.line([(cx - half, y), (cx - span // 2 - 14, y)], fill=color, width=2)
    draw.line([(cx + half, y), (cx + span // 2 + 14, y)], fill=color, width=2)
    for star_x in (cx - half, cx + half):
        pts = []
        for i in range(10):
            rad = 9 if i % 2 == 0 else 4
            a = math.pi * 2 * i / 10 - math.pi / 2
            pts.append((star_x + rad * math.cos(a), y + rad * math.sin(a)))
        draw.polygon(pts, fill=accent)
    draw.polygon(
        [(cx, y - 7), (cx + 7, y), (cx, y + 7), (cx - 7, y)],
        fill=accent,
    )


def _draw_frame(draw: ImageDraw, width: int, height: int) -> None:
    """Рисует тонкую золотую рамку с декоративными уголками.

    Args:
        draw: Объект ImageDraw.
        width: Ширина изображения.
        height: Высота изображения.
    """
    inset = 34
    gold = (255, 215, 0, 170)
    draw.rectangle([inset, inset, width - inset, height - inset],
                   outline=gold, width=3)
    draw.rectangle([inset + 10, inset + 10, width - inset - 10, height - inset - 10],
                   outline=(255, 215, 0, 70), width=1)
    r = 13
    for cx, cy in ((inset, inset), (width - inset, inset),
                   (inset, height - inset), (width - inset, height - inset)):
        draw.polygon(
            [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
            fill=(255, 215, 0, 90),
        )


def _wrap_lines(draw: ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                max_width: int) -> list[str]:
    """Разбивает текст на строки по ширине.

    Args:
        draw: Объект ImageDraw.
        text: Текст.
        font: Шрифт.
        max_width: Максимальная ширина строки в пикселях.

    Returns:
        Список строк.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = (current + " " + word).strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def is_jubilee_age(age: int | None) -> bool:
    """Определяет, является ли возраст юбилейной датой.

    Args:
        age: Возраст сотрудника (None — неизвестен).

    Returns:
        True, если возраст кратен шагу юбилея и не меньше минимума.
    """
    if not age:
        return False
    return age >= _JUBILEE_MIN_AGE and age % _JUBILEE_STEP == 0


def compute_age(birthday: str | None, today: date | None = None) -> int | None:
    """Вычисляет возраст сотрудника на сегодняшнюю дату.

    Единая точка для расчёта возраста — используется планировщиком,
    роутами и генерацией, чтобы возраст (и имя файла открытки) совпадали
    между всеми потребителями.

    Args:
        birthday: Дата рождения в формате ГГГГ-ММ-ДД.
        today: Опорная дата (по умолчанию — сегодня в часовом поясе приложения).

    Returns:
        Возраст или None, если дата рождения не задана/некорректна.
    """
    if not birthday:
        return None
    try:
        bd = date.fromisoformat(birthday)
    except (ValueError, TypeError):
        return None
    ref = today or timeutils.today()
    return ref.year - bd.year - ((ref.month, ref.day) < (bd.month, bd.day))


def greeting_filename(employee_name: str, age: int | None) -> Path:
    """Возвращает путь к файлу открытки сотрудника.

    Единая формула имени файла: планировщик и роуты должны использовать её,
    чтобы не создавать дублирующие открытки с разными именами.

    Args:
        employee_name: ФИО сотрудника.
        age: Возраст сотрудника (None — без возрастного тега).

    Returns:
        Путь в каталоге greetings.
    """
    safe_name = re.sub(r'[^\w\s-]', '', employee_name).strip().replace(' ', '_')
    tag = f"_{age}" if age else ""
    return settings.greeting_dir / f"greeting_{safe_name}{tag}.jpg"


def _personal_name(full_name: str) -> str:
    """Возвращает имя и отчество из ФИО (слова 2 и 3).

    Args:
        full_name: ФИО сотрудника.

    Returns:
        Имя и отчество сотрудника (без отчества, если его нет).
    """
    parts = full_name.split()
    if len(parts) >= 3:
        return f"{parts[1]} {parts[2]}"
    if len(parts) == 2:
        return parts[1]
    return parts[0] if parts else full_name


_petrovich = Petrovich()


def _decline_word(method, word: str, gender: str) -> str:
    """Склоняет одно слово ФИО в родительный падеж.

    Args:
        method: Метод petrovich (lastname/firstname/middlename).
        word: Слово ФИО.
        gender: Пол сотрудника (male/female).

    Returns:
        Склонённое слово или исходное при ошибке (костыль для редких имён).
    """
    if not word:
        return ""
    try:
        g = Gender.MALE if gender == "male" else Gender.FEMALE
        declined = method(word, Case.GENITIVE, g)
        return declined or word
    except Exception:
        return word


def _genitive_fio(full_name: str, gender: str) -> str:
    """Склоняет ФИО в родительный падеж: «Колесова Максима Сергеевича».

    Args:
        full_name: ФИО сотрудника.
        gender: Пол (male/female).

    Returns:
        Строка в родительном падеже для заголовка открытки.
    """
    parts = full_name.split()
    if not parts:
        return ""
    surname = _decline_word(_petrovich.lastname, parts[0], gender)
    first = _decline_word(_petrovich.firstname, parts[1], gender) if len(parts) > 1 else ""
    middle = _decline_word(_petrovich.middlename, parts[2], gender) if len(parts) > 2 else ""
    return " ".join(x for x in (surname, first, middle) if x)


def generate_greeting(
    employee_name: str,
    gender: str,
    age: int | None = None,
    output_path: str | Path | None = None,
) -> str:
    """Генерирует праздничную поздравительную открытку.

    Композиция собирается по полу и возрасту сотрудника:
    - палитра фона (мужская/женская);
    - заголовок «С Юбилеем!» и крупная цифра возраста для юбилейных дат;
    - обращение «Дорогой/Дорогая <имя> <отчество>!»;
    - пожелание из набора для обычного дня рождения или юбилея;
    - подпись коллектива.

    Args:
        employee_name: ФИО сотрудника.
        gender: Пол сотрудника (male/female).
        age: Возраст сотрудника (для юбилейных дат).
        output_path: Путь для сохранения. По умолчанию генерируется
                     автоматически в каталоге greetings с учётом возраста.

    Returns:
        Абсолютный путь к созданному изображению.
    """
    bg_path = _select_background(gender)
    img = Image.open(bg_path).convert("RGBA")
    img = img.resize((1920, 1080), Image.LANCZOS)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    palette = _MALE_PALETTE if gender == "male" else _FEMALE_PALETTE
    color_top, color_bottom = random.choice(palette)

    _draw_gradient(draw, img.width, img.height, color_top, color_bottom)
    _draw_radial_glow(overlay, img.width // 2, 500, 780, (255, 210, 90), 80)
    _draw_stars(draw, img.width, img.height)
    _draw_vignette(overlay)

    result = Image.alpha_composite(img, overlay)
    draw_result = ImageDraw.Draw(result)

    jubilee = is_jubilee_age(age)
    display_age = age if jubilee else None

    font_head = _get_font(104, decorative=True)

    # Заголовок с ФИО в родительном падеже — различает сотрудников
    # с одинаковыми именами и отчествами. Пример:
    #   «Поздравляем с днём рождения Колесова Максима Сергеевича!»
    occasion = "юбилеем" if jubilee else "днём рождения"
    gen_fio = _genitive_fio(employee_name, gender)
    max_head_w = img.width - 260
    if not gen_fio:
        headline_lines = _wrap_lines(draw_result, f"Поздравляем с {occasion}!", font_head, max_head_w)
    else:
        one_line = f"Поздравляем с {occasion} {gen_fio}!"
        if draw_result.textlength(one_line, font=font_head) <= max_head_w:
            headline_lines = [one_line]
        else:
            # Фразы и ФИО переносятся раздельно, чтобы имя не отрывалось
            # от фамилии: «Поздравляем с юбилеем», «Ковалёвой Анны Викторовны!»
            headline_lines = _wrap_lines(draw_result, f"Поздравляем с {occasion}", font_head, max_head_w)
            headline_lines += _wrap_lines(draw_result, f"{gen_fio}!", font_head, max_head_w)

    address = f"{_ADDRESS_PREFIX.get(gender, 'Дорогой')} {_personal_name(employee_name)}!"
    if jubilee:
        wish = random.choice(_JUBILEE_WISHES)
    elif gender == "female":
        wish = random.choice(_FEMALE_WISHES)
    else:
        wish = random.choice(_NEUTRAL_WISHES)

    font_head = _get_font(104, decorative=True)
    font_num = _get_font(240, decorative=True)
    font_label = _get_font(58, decorative=True)
    font_name = _get_font(92, decorative=True)
    font_wish = _get_font(42)
    font_sign = _get_font(30)

    max_text_w = img.width - 420
    wish_lines = _wrap_lines(draw_result, wish, font_wish, max_text_w)

    blocks: list[dict] = [{"kind": "headline", "lines": headline_lines, "font": font_head,
                           "fill": _GOLD, "glow": True, "gap": 26}]
    if display_age:
        blocks.append({"kind": "text", "text": str(display_age), "font": font_num,
                       "fill": _GOLD, "glow": True, "gap": 10})
        blocks.append({"kind": "text", "text": "лет", "font": font_label,
                       "fill": _WHITE, "glow": False, "gap": 26})
    blocks.append({"kind": "ornament", "gap": 30})
    blocks.append({"kind": "text", "text": address, "font": font_name,
                   "fill": _WHITE, "glow": False, "gap": 34})
    blocks.append({"kind": "wish", "lines": wish_lines, "font": font_wish,
                   "fill": _WHITE, "gap": 8})
    blocks.append({"kind": "ornament", "gap": 30})
    blocks.append({"kind": "text", "text": settings.org_name, "font": font_sign,
                   "fill": _DIM_GOLD, "glow": False, "gap": 24})

    def block_height(b: dict) -> int:
        if b["kind"] == "ornament":
            return 30
        if b["kind"] in ("headline", "wish"):
            font = b["font"]
            asc, desc = font.getmetrics()
            return len(b["lines"]) * (asc + desc + 8)
        font = b["font"]
        asc, desc = font.getmetrics()
        return asc + desc

    total_height = sum(block_height(b) + b.get("gap", 0) for b in blocks)
    y = (img.height - total_height) // 2

    for b in blocks:
        y += b.get("gap", 0)
        if b["kind"] == "ornament":
            _draw_ornament(draw_result, img.width // 2, y + 14,
                           img.width, (255, 215, 0, 150), (255, 215, 0, 220))
            y += 30
            continue
        if b["kind"] in ("headline", "wish"):
            asc, desc = b["font"].getmetrics()
            for line in b["lines"]:
                line_w = draw_result.textlength(line, font=b["font"])
                x = (img.width - line_w) // 2
                if b.get("glow"):
                    _draw_text_with_shadow(draw_result, (x, y), line,
                                           b["font"], b["fill"])
                else:
                    draw_result.text((x, y), line, fill=b["fill"], font=b["font"])
                y += asc + desc + 8
            continue
        text_w = draw_result.textlength(b["text"], font=b["font"])
        x = (img.width - text_w) // 2
        if b.get("glow"):
            _draw_text_with_shadow(draw_result, (x, y), b["text"],
                                   b["font"], b["fill"])
        else:
            draw_result.text((x, y), b["text"], fill=b["fill"], font=b["font"])
        asc, desc = b["font"].getmetrics()
        y += asc + desc

    _draw_frame(draw_result, img.width, img.height)

    if output_path is None:
        output_path = greeting_filename(employee_name, age)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = result.convert("RGB")
    result.save(str(output_path), "JPEG", quality=92)
    return str(output_path)