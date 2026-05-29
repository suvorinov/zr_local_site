"""Генерация поздравительных изображений.

Создаёт изображение с фоновой картинкой, декоративными элементами
и поздравительным текстом. Каждый раз генерируется уникальная
композиция за счёт случайного выбора цветов, расположения и эффектов.
"""

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.config import settings

_GREETING_TEXTS = (
    "С Днём Рождения!",
    "С Днём Рождения \u2605",
    "Поздравляем с Днём Рождения!",
    "С праздником!",
    "Happy Birthday!",
    "С Днём Рождения \u2728",
)

_DECORATION_PHRASES = (
    "\u2605 \u2605 \u2605",
    "\u2728 \u2728 \u2728",
    "\u2665 \u2665 \u2665",
    "\u2606 \u2606 \u2606",
)

_MALE_PALETTE = (
    ((10, 20, 60, 160), (30, 60, 120, 100)),   # сине-серый
    ((40, 20, 60, 160), (80, 40, 100, 100)),    # фиолетовый
    ((10, 40, 60, 160), (20, 80, 120, 100)),    # синий
    ((30, 30, 30, 160), (80, 80, 80, 100)),     # тёмный
)

_FEMALE_PALETTE = (
    ((120, 20, 60, 160), (180, 60, 100, 100)),   # розовый
    ((140, 40, 80, 160), (200, 80, 120, 100)),   # малиновый
    ((100, 30, 60, 160), (160, 70, 100, 100)),   # пурпурный
    ((180, 100, 40, 160), (220, 140, 60, 100)),  # золотой
)


def _get_font(size: int = 60) -> ImageFont.FreeTypeFont:
    """Загружает шрифт для отрисовки текста.

    Args:
        size: Размер шрифта.

    Returns:
        Объект шрифта.
    """
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for path in font_paths:
        if Path(path).exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _select_background(gender: str) -> Path:
    """Выбирает случайный фон из каталога соответствующего пола.

    Args:
        gender: Пол сотрудника (male/female).

    Returns:
        Путь к выбранному фоновому изображению.

    Raises:
        FileNotFoundError: Если не найдены фоновые изображения.
    """
    bg_dir = settings.background_dir / gender
    if not bg_dir.exists():
        bg_dir.mkdir(parents=True, exist_ok=True)

    images = list(bg_dir.glob("*.[jJ][pP][gG]")) + \
             list(bg_dir.glob("*.[jJ][pP][eE][gG]")) + \
             list(bg_dir.glob("*.[pP][nN][gG]"))

    if not images:
        msg = (
            f"Фоновые изображения не найдены в {bg_dir}. "
            f"Добавьте изображения в каталог {bg_dir}"
        )
        raise FileNotFoundError(msg)

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


def _draw_confetti(draw: ImageDraw, width: int, height: int,
                   palette: list[tuple]) -> None:
    """Рисует декоративные элементы (конфетти, круги, звёзды).

    Args:
        draw: Объект ImageDraw.
        width: Ширина изображения.
        height: Высота изображения.
        palette: Список цветов для элементов.
    """
    colors = [
        (255, 200, 50, 200),   # золотой
        (255, 100, 100, 180),  # красный
        (100, 200, 255, 180),  # голубой
        (200, 100, 255, 180),  # фиолетовый
        (100, 255, 150, 180),  # зелёный
    ]
    random.shuffle(colors)

    for _ in range(random.randint(20, 40)):
        x = random.randint(0, width)
        y = random.randint(0, height)
        r = random.randint(4, 18)
        color = random.choice(colors)
        shape = random.choice(['circle', 'rect', 'star'])

        if shape == 'circle':
            draw.ellipse([x - r, y - r, x + r, y + r],
                         fill=color, outline=None)
        elif shape == 'rect':
            angle = random.randint(0, 45)
            points = [
                (x - r, y - r // 2), (x + r, y - r // 2),
                (x + r, y + r // 2), (x - r, y + r // 2),
            ]
            draw.polygon(points, fill=color)
        elif shape == 'star':
            points = []
            for i in range(10):
                rad = r if i % 2 == 0 else r // 2
                a = math.pi * 2 * i / 10 - math.pi / 2
                points.append((x + rad * math.cos(a),
                               y + rad * math.sin(a)))
            draw.polygon(points, fill=color)


def _draw_text_with_shadow(draw: ImageDraw, xy: tuple[int, int],
                            text: str, font: ImageFont.FreeTypeFont,
                            fill: str, shadow_color: str = "black",
                            shadow_offset: int = 3) -> None:
    """Рисует текст с тенью.

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
    draw.text((x + shadow_offset, y + shadow_offset), text,
              fill=shadow_color, font=font)
    draw.text((x, y), text, fill=fill, font=font)


def _draw_text_with_outline(draw: ImageDraw, xy: tuple[int, int],
                              text: str, font: ImageFont.FreeTypeFont,
                              fill: str, outline_color: str = "black") -> None:
    """Рисует текст с обводкой.

    Args:
        draw: Объект ImageDraw.
        xy: Координаты текста.
        text: Текст.
        font: Шрифт.
        fill: Цвет текста.
        outline_color: Цвет обводки.
    """
    x, y = xy
    for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2),
                   (-2, 0), (2, 0), (0, -2), (0, 2)]:
        draw.text((x + dx, y + dy), text, fill=outline_color, font=font)
    draw.text((x, y), text, fill=fill, font=font)


def _draw_vignette(draw: ImageDraw, width: int, height: int) -> None:
    """Рисует виньетку (затемнение по краям).

    Args:
        draw: Объект ImageDraw.
        width: Ширина изображения.
        height: Высота изображения.
    """
    for x in range(width):
        ratio_x = min(x, width - x) / (width / 2)
        for y in range(height):
            ratio_y = min(y, height - y) / (height / 2)
            ratio = min(ratio_x, ratio_y)
            if ratio < 0.5:
                alpha = int((0.5 - ratio) * 200)
                draw.point((x, y), fill=(0, 0, 0, alpha))


def _draw_decorative_line(draw: ImageDraw, cx: int, y: int,
                            width: int, color: tuple) -> None:
    """Рисует декоративную линию с ромбом по центру.

    Args:
        draw: Объект ImageDraw.
        cx: Центр по X.
        y: Позиция по Y.
        width: Ширина линии.
        color: Цвет (RGBA).
    """
    line_w = min(width // 3, 200)
    draw.line([(cx - line_w, y), (cx + line_w, y)],
              fill=color, width=2)
    draw.polygon([
        (cx, y - 6), (cx + 6, y),
        (cx, y + 6), (cx - 6, y),
    ], fill=color)


def generate_greeting(
    employee_name: str,
    gender: str,
    output_path: str | Path | None = None,
) -> str:
    """Генерирует поздравительное изображение.

    Каждый раз создаётся уникальная композиция:
    - фоновая картинка по полу сотрудника
    - цветной градиент
    - декоративные элементы
    - виньетка
    - случайный вариант поздравительного текста
    - имя сотрудника с декоративными линиями

    Args:
        employee_name: Имя сотрудника.
        gender: Пол сотрудника (male/female).
        output_path: Путь для сохранения. По умолчанию генерируется
                     автоматически в каталоге greetings.

    Returns:
        Относительный путь к созданному изображению.

    Raises:
        FileNotFoundError: Если не найдены фоновые изображения.
    """
    bg_path = _select_background(gender)
    img = Image.open(bg_path).convert("RGBA")
    img = img.resize((1920, 1080), Image.LANCZOS)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    palette = _MALE_PALETTE if gender == "male" else _FEMALE_PALETTE
    colors = random.choice(palette)

    _draw_gradient(draw, img.width, img.height, colors[0], colors[1])

    if random.random() < 0.5:
        img = img.filter(ImageFilter.GaussianBlur(radius=random.uniform(1, 3)))

    _draw_confetti(draw, img.width, img.height, palette)

    _draw_vignette(draw, img.width, img.height)

    result = Image.alpha_composite(img, overlay)

    draw_result = ImageDraw.Draw(result)

    font_large = _get_font(90)
    font_medium = _get_font(50)
    font_small = _get_font(36)

    layout = random.choice(['center', 'bottom', 'top'])

    greeting_text = random.choice(_GREETING_TEXTS)
    decoration = random.choice(_DECORATION_PHRASES)

    bbox = draw_result.textbbox((0, 0), greeting_text, font=font_large)
    text_w = bbox[2] - bbox[0]
    cx = (img.width - text_w) // 2

    bbox_name = draw_result.textbbox((0, 0), employee_name, font=font_medium)
    name_w = bbox_name[2] - bbox_name[0]
    name_cx = (img.width - name_w) // 2

    text_effect = random.choice(['shadow', 'outline', 'none'])

    def draw_styled(d, pos, text, font, color):
        if text_effect == 'shadow':
            _draw_text_with_shadow(d, pos, text, font, color)
        elif text_effect == 'outline':
            _draw_text_with_outline(d, pos, text, font, color)
        else:
            d.text(pos, text, fill=color, font=font)

    if layout == 'center':
        base_y = img.height // 2 - 80

        bbox = draw_result.textbbox((0, 0), decoration, font=font_small)
        dec_w = bbox[2] - bbox[0]
        draw_styled(draw_result,
                    ((img.width - dec_w) // 2, base_y - 30),
                    decoration, font_small, "#FFD700")

        _draw_decorative_line(draw_result, img.width // 2, base_y + 10,
                              img.width, (255, 215, 0, 200))

        draw_styled(draw_result, (cx, base_y + 30),
                    greeting_text, font_large, "#FFFFFF")

        _draw_decorative_line(draw_result, img.width // 2,
                              base_y + 130, img.width, (255, 215, 0, 200))

        draw_styled(draw_result, (name_cx, base_y + 150),
                    employee_name, font_medium, "#FFD700")

        bbox = draw_result.textbbox((0, 0), employee_name, font=font_small)
        dec2_w = bbox[2] - bbox[0]
        draw_styled(draw_result,
                    ((img.width - dec2_w) // 2, base_y + 200),
                    decoration, font_small, "#FFD700")

    elif layout == 'bottom':
        bar_height = 300
        draw_result.rectangle(
            [(0, img.height - bar_height), (img.width, img.height)],
            fill=(0, 0, 0, 180),
        )

        bbox = draw_result.textbbox((0, 0), greeting_text, font=font_large)
        text_y = img.height - bar_height + 30
        draw_styled(draw_result, (cx, text_y),
                    greeting_text, font_large, "#FFFFFF")

        _draw_decorative_line(draw_result, img.width // 2,
                              text_y + 100, img.width, (255, 215, 0, 200))

        draw_styled(draw_result, (name_cx, text_y + 120),
                    employee_name, font_medium, "#FFD700")

        draw_styled(draw_result,
                    ((img.width - text_w) // 2, text_y + 180),
                    decoration, font_small, "#FFFFFF")

    elif layout == 'top':
        bar_height = 280
        draw_result.rectangle(
            [(0, 0), (img.width, bar_height)],
            fill=(0, 0, 0, 160),
        )

        bbox = draw_result.textbbox((0, 0), greeting_text, font=font_large)
        draw_styled(draw_result, (cx, 20),
                    greeting_text, font_large, "#FFFFFF")

        _draw_decorative_line(draw_result, img.width // 2,
                              120, img.width, (255, 215, 0, 200))

        draw_styled(draw_result, (name_cx, 140),
                    employee_name, font_medium, "#FFD700")

        draw_styled(draw_result,
                    ((img.width - text_w) // 2, 200),
                    decoration, font_small, "#FFFFFF")

    if output_path is None:
        filename = f"greeting_{employee_name.replace(' ', '_')}.jpg"
        output_path = settings.greeting_dir / filename

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = result.convert("RGB")
    result.save(str(output_path), "JPEG", quality=92)
    return str(output_path)
