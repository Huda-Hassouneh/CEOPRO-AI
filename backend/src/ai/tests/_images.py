"""Test pictures that pass the image quality gate (image_generation.quality_problems): contrast and detail,
like a real photo. A flat single colour is what a provider's failure looks like, and is rejected."""
import io

from PIL import Image, ImageDraw


def scene(width: int, height: int, tint=(200, 120, 40)) -> Image.Image:
    image = Image.new("RGB", (width, height), tint)
    draw = ImageDraw.Draw(image)
    step = max(8, min(width, height) // 20)
    for i in range(0, max(width, height), step):
        x, y = i % width, (i * 7) % height
        draw.ellipse((x, y, x + width // 6, y + height // 6), fill=((i * 3) % 255, (i * 5) % 255, (i * 11) % 255),
                     outline=(20, 20, 20), width=3)
    return image


def scene_bytes(width: int, height: int, fmt: str = "PNG", tint=(200, 120, 40)) -> bytes:
    buffer = io.BytesIO()
    scene(width, height, tint).save(buffer, format=fmt)
    return buffer.getvalue()
