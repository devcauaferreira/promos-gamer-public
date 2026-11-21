from io import BytesIO
from functools import lru_cache
import colorsys
import hashlib
import os
import re
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
import warnings

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps


MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"
MODEL_MD5 = "60024c5c889badc19c04ad937298a77b"
MODEL_MAX_BYTES = 250_000_000
MODEL_CHUNK_BYTES = 1024 * 1024
DEFAULT_SETTINGS = {
    "background_color": "#111827",
    "accent_color": "#22C55E",
    "glow_color": "#00C8FF",
    "auto_colors": True,
    "badge_text": "PROMOS GAMER",
}
CARD_SIZE = (1440, 1440)
MAX_IMAGE_BYTES = 2_950_000
FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)


def validate_settings(settings=None):
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise ValueError("image_card deve ser um objeto")
    result = {**DEFAULT_SETTINGS, **settings}
    for key in ("background_color", "accent_color", "glow_color"):
        if not isinstance(result[key], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", result[key]):
            raise ValueError(f"image_card.{key} deve ser uma cor hexadecimal #RRGGBB")
    if not isinstance(result["auto_colors"], bool):
        raise ValueError("image_card.auto_colors deve ser true ou false")
    badge = result["badge_text"]
    if not isinstance(badge, str) or not badge.strip() or len(badge.strip()) > 30:
        raise ValueError("image_card.badge_text deve ter entre 1 e 30 caracteres")
    result["badge_text"] = badge.strip()
    return result


def _font(size):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _rgb(value):
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def _hex_from_hsv(hue, saturation, value):
    red, green, blue = colorsys.hsv_to_rgb(hue % 1, saturation, value)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


def _product_palette(image, settings):
    if not settings["auto_colors"]:
        red, green, blue = (channel / 255 for channel in _rgb(settings["background_color"]))
        hue, saturation, _ = colorsys.rgb_to_hsv(red, green, blue)
        return {
            "background_color": settings["background_color"],
            "gradient_color": _hex_from_hsv(hue + 0.015, max(saturation, 0.25), 0.15),
            "accent_color": settings["accent_color"],
            "glow_color": settings["glow_color"],
        }

    import numpy as np

    sample = image.copy()
    sample.thumbnail((128, 128), Image.Resampling.LANCZOS)
    pixels = np.asarray(sample.convert("RGBA"), dtype=np.float32) / 255
    alpha = pixels[:, :, 3]
    rgb = pixels[:, :, :3]
    maximum = rgb.max(axis=2)
    minimum = rgb.min(axis=2)
    saturation = np.divide(maximum - minimum, maximum, out=np.zeros_like(maximum), where=maximum > 0)
    value = maximum
    delta = maximum - minimum
    hue = np.zeros_like(maximum)
    non_gray = delta > 1e-6
    red_is_max = (maximum == rgb[:, :, 0]) & non_gray
    green_is_max = (maximum == rgb[:, :, 1]) & non_gray
    blue_is_max = (maximum == rgb[:, :, 2]) & non_gray
    hue[red_is_max] = ((rgb[:, :, 1][red_is_max] - rgb[:, :, 2][red_is_max]) /
                       delta[red_is_max]) % 6
    hue[green_is_max] = ((rgb[:, :, 2][green_is_max] - rgb[:, :, 0][green_is_max]) /
                         delta[green_is_max]) + 2
    hue[blue_is_max] = ((rgb[:, :, 0][blue_is_max] - rgb[:, :, 1][blue_is_max]) /
                        delta[blue_is_max]) + 4
    hue /= 6

    weights = alpha * np.square(saturation) * ((value > 0.12) & (value < 0.98))
    histogram = np.histogram(hue, bins=36, range=(0, 1), weights=weights)[0]
    if float(histogram.max()) < 0.05:
        return {
            "background_color": "#0B1220",
            "gradient_color": "#172843",
            "accent_color": "#22C55E",
            "glow_color": "#00C8FF",
        }

    hue_center = (int(histogram.argmax()) + 0.5) / 36
    return {
        "background_color": _hex_from_hsv(hue_center, 0.64, 0.055),
        "gradient_color": _hex_from_hsv(hue_center + 0.015, 0.68, 0.15),
        "accent_color": _hex_from_hsv(hue_center, 0.82, 0.96),
        "glow_color": _hex_from_hsv(hue_center - 0.025, 0.94, 1),
    }


def _model_path():
    home = Path(os.environ.get("U2NET_HOME", Path.home() / ".u2net")).expanduser()
    return home / "u2net.onnx"


def prepare_background_model():
    path = _model_path()
    if path.is_file():
        digest = hashlib.md5(usedforsecurity=False)
        with path.open("rb") as model:
            for chunk in iter(lambda: model.read(MODEL_CHUNK_BYTES), b""):
                digest.update(chunk)
        if digest.hexdigest() == MODEL_MD5:
            return path
        path.unlink()

    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.md5(usedforsecurity=False)
    byte_count = 0
    temp_path = None
    request = Request(MODEL_URL, headers={"User-Agent": "PromosGamer/1.0"})
    try:
        with urlopen(request, timeout=60) as response:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as model:
                temp_path = Path(model.name)
                while True:
                    chunk = response.read(MODEL_CHUNK_BYTES)
                    if not chunk:
                        break
                    byte_count += len(chunk)
                    if byte_count > MODEL_MAX_BYTES:
                        raise ValueError("Modelo de remoção de fundo excede o limite permitido")
                    digest.update(chunk)
                    model.write(chunk)
        if digest.hexdigest() != MODEL_MD5:
            raise ValueError("Checksum do modelo de remoção de fundo não corresponde")
        temp_path.replace(path)
        return path
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


@lru_cache(maxsize=1)
def _segmentation_session():
    import onnxruntime

    options = onnxruntime.SessionOptions()
    options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
    options.intra_op_num_threads = max(1, min(os.cpu_count() or 1, 4))
    return onnxruntime.InferenceSession(
        str(prepare_background_model()),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )


def remove_background(image):
    import numpy as np

    input_image = image.convert("RGB").resize((320, 320), Image.Resampling.LANCZOS)
    pixels = np.asarray(input_image, dtype=np.float32)
    pixels /= max(float(pixels.max()), 1e-6)
    mean = np.array((0.485, 0.456, 0.406), dtype=np.float32)
    std = np.array((0.229, 0.224, 0.225), dtype=np.float32)
    tensor = ((pixels - mean) / std).transpose((2, 0, 1))[None, ...]

    session = _segmentation_session()
    prediction = session.run(
        None, {session.get_inputs()[0].name: tensor.astype(np.float32)}
    )[0][0, 0]
    minimum, maximum = float(prediction.min()), float(prediction.max())
    if maximum - minimum < 1e-6:
        raise ValueError("O modelo não conseguiu identificar o produto")
    mask = ((prediction - minimum) / (maximum - minimum) * 255).clip(0, 255)
    alpha = Image.fromarray(mask.astype(np.uint8), mode="L")
    alpha = alpha.resize(image.size, Image.Resampling.LANCZOS)
    cutout = image.convert("RGBA")
    cutout.putalpha(alpha)
    return cutout


def _draw_tech_background(card, settings, palette):
    accent_hue = colorsys.rgb_to_hsv(*[channel / 255 for channel in _rgb(palette["accent_color"])])[0]
    complementary = _hex_from_hsv(accent_hue + 0.48, 0.8, 0.92)
    gradient = Image.linear_gradient("L").rotate(90).resize(CARD_SIZE)
    base = Image.new("RGB", CARD_SIZE, palette["background_color"])
    gradient_color = Image.new("RGB", CARD_SIZE, palette["gradient_color"])
    card.paste(Image.composite(gradient_color, base, gradient))

    spotlight = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    spotlight_draw = ImageDraw.Draw(spotlight)
    spotlight_draw.polygon(((390, 105), (1050, 105), (1310, 1020), (120, 1020)),
                           fill=(*_rgb(palette["glow_color"]), 22))
    spotlight = spotlight.filter(ImageFilter.GaussianBlur(105))
    card.paste(spotlight, mask=spotlight.getchannel("A"))

    glow = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for center, color, radius in (
        ((-40, 430), palette["glow_color"], 470),
        ((1500, 850), palette["accent_color"], 440),
        ((1280, -180), complementary, 360),
    ):
        x, y = center
        glow_draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                          fill=(*_rgb(color), 130))
    glow = glow.filter(ImageFilter.GaussianBlur(145))
    card.paste(glow, mask=glow.getchannel("A"))

    architecture = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    architecture_draw = ImageDraw.Draw(architecture)
    neon = _rgb(palette["glow_color"])
    accent = _rgb(palette["accent_color"])
    architecture_draw.line(((88, 260), (88, 810), (230, 980)),
                           fill=(*neon, 145), width=9, joint="curve")
    architecture_draw.line(((1352, 245), (1352, 775), (1210, 980)),
                           fill=(*accent, 150), width=9, joint="curve")
    architecture_draw.line(((245, 160), (555, 160)), fill=(*neon, 115), width=5)
    architecture_draw.line(((885, 160), (1195, 160)), fill=(*accent, 105), width=5)
    architecture_glow = architecture.filter(ImageFilter.GaussianBlur(22))
    card.paste(architecture_glow, mask=architecture_glow.getchannel("A"))
    card.paste(architecture, mask=architecture.getchannel("A"))

    details = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(details)
    for offset in range(-CARD_SIZE[1], CARD_SIZE[0], 105):
        draw.line((offset, 0, offset + CARD_SIZE[1], CARD_SIZE[1]),
                  fill=(130, 170, 220, 10), width=2)
    for x in range(34, CARD_SIZE[0], 96):
        for y in range(36, CARD_SIZE[1], 96):
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(120, 170, 220, 22))
    draw.rounded_rectangle((36, 56, 1404, 1384), radius=42,
                           outline=(117, 161, 212, 45), width=2)
    draw.line((0, 124, 400, 124), fill=(*_rgb(palette["glow_color"]), 190), width=4)
    draw.line((1040, 1316, 1440, 1316),
              fill=(*_rgb(palette["accent_color"]), 190), width=4)
    draw.polygon(((0, 1110), (1440, 1010), (1440, 1320), (0, 1400)),
                 fill=(2, 8, 20, 72))
    draw.line((0, 1110, 1440, 1010), fill=(130, 170, 220, 48), width=3)
    card.paste(details, mask=details.getchannel("A"))


def format_image(data, settings=None):
    settings = validate_settings(settings)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as original:
            if original.width * original.height > 40_000_000:
                raise ValueError("Imagem original excede o limite de resolução permitido")
            source = ImageOps.exif_transpose(original).convert("RGBA")

    original_size = source.size
    if source.getchannel("A").getextrema()[0] >= 250:
        source = remove_background(source).convert("RGBA")
    if source.size != original_size:
        raise ValueError("A remoção do fundo alterou dimensões inesperadamente")
    alpha_min, alpha_max = source.getchannel("A").getextrema()
    if alpha_min >= 250 or alpha_max < 200:
        raise ValueError("Não foi possível separar o produto do fundo com segurança")

    palette = _product_palette(source, settings)
    source.thumbnail((1160, 1060), Image.Resampling.LANCZOS)
    card = Image.new("RGB", CARD_SIZE, palette["background_color"])
    _draw_tech_background(card, settings, palette)

    stage = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    stage_draw = ImageDraw.Draw(stage)
    stage_draw.polygon(((0, 1050), (1440, 1050), (1440, 1440), (0, 1440)),
                       fill=(4, 8, 18, 185))
    stage_draw.ellipse((150, 1030, 1290, 1285), fill=(0, 0, 0, 150))
    stage_draw.ellipse((230, 1070, 1210, 1220),
                       fill=(*_rgb(palette["glow_color"]), 42),
                       outline=(*_rgb(palette["glow_color"]), 120), width=4)
    for x in range(-600, 2100, 150):
        stage_draw.line((720 + (x - 720) // 5, 1052, x, 1440),
                        fill=(137, 166, 205, 24), width=2)
    for y in (1110, 1180, 1270, 1390):
        stage_draw.line((0, y, 1440, y + 24), fill=(137, 166, 205, 20), width=2)
    stage = stage.filter(ImageFilter.GaussianBlur(18))
    card.paste(stage, mask=stage.getchannel("A"))

    position = ((CARD_SIZE[0] - source.width) // 2, 82 + (1100 - source.height) // 2)
    alpha = source.getchannel("A")
    silhouette_glow = Image.new("RGBA", source.size, (*_rgb(palette["glow_color"]), 0))
    silhouette_glow.putalpha(alpha.filter(ImageFilter.GaussianBlur(48)).point(lambda px: px // 3))
    shadow = Image.new("RGBA", source.size, (0, 0, 0, 0))
    shadow.putalpha(alpha.filter(ImageFilter.GaussianBlur(25)).point(lambda px: px // 2))
    shadow_position = (position[0] + 8, position[1] + 25)
    card.paste(silhouette_glow, position, silhouette_glow)
    card.paste(shadow, shadow_position, shadow)

    reflection = source.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    reflection.thumbnail((source.width, 420), Image.Resampling.LANCZOS)
    reflection_alpha = reflection.getchannel("A")
    vertical_fade = Image.new("L", (1, reflection.height))
    vertical_fade.putdata([
        round(255 * (1 - y / max(1, reflection.height - 1)))
        for y in range(reflection.height)
    ])
    vertical_fade = vertical_fade.resize(reflection.size)
    reflection_alpha = ImageChops.multiply(reflection_alpha, vertical_fade)
    reflection_alpha = reflection_alpha.point(lambda px: px * 0.2)
    reflection.putalpha(reflection_alpha)
    reflection_x = position[0] + (source.width - reflection.width) // 2
    card.paste(reflection, (reflection_x, position[1] + source.height - 18), reflection)
    card.paste(source, position, source)

    draw = ImageDraw.Draw(card)
    badge = settings["badge_text"]
    font = _font(30)
    while draw.textbbox((0, 0), badge, font=font)[2] > 500 and font.size > 22:
        font = _font(font.size - 2)
    bounds = draw.textbbox((0, 0), badge, font=font)
    badge_width = bounds[2] - bounds[0] + 86
    badge_height = 58
    badge_x = CARD_SIZE[0] - badge_width - 72
    badge_y = 1300
    draw.rounded_rectangle((badge_x, badge_y, badge_x + badge_width, badge_y + badge_height),
                           radius=badge_height // 2, fill="#101827", outline=palette["accent_color"], width=3)
    draw.ellipse((badge_x + 12, badge_y + 12, badge_x + 46, badge_y + 46),
                 fill=palette["accent_color"])
    draw.text((badge_x + 62, badge_y + badge_height // 2), badge, font=font,
              fill="#EAF3FF", anchor="lm")

    for quality in (90, 85, 80, 75):
        output = BytesIO()
        card.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
        if output.tell() <= MAX_IMAGE_BYTES:
            return output.getvalue()
    raise ValueError("A arte da imagem excede o limite de tamanho para envio")
