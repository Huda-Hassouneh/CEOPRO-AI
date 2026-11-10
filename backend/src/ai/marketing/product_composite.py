"""
KEEL - put the owner's REAL product photo into the advertisement.

No integrated image model can take the product photo as an input on a free
plan (see MARKETING_AI_CAPABILITIES.md), and sending customers' photos to an
outside service needs the owner's approval. So the real product is kept
exact by doing the product part here, on our own server:

1. cut the product out of its photo - an existing transparent background is
   used as it is; otherwise the local background remover (rembg, when it is
   installed and configured - it runs on this server); otherwise a plain
   studio background is keyed out by colour (works for product shots taken
   on a white/plain backdrop, which is how most product photos are taken);
2. the picture model is asked for the SCENE only - from text, never the
   photo - with an empty place in the middle (scene_prompt());
3. the cut-out product is placed into that scene here, sized and positioned
   for the format, with a contact shadow, a soft drop shadow and a light
   colour match so it sits in the scene rather than on top of it.

The product's shape, label, colours and proportions are therefore the
photo's own pixels - nothing about the product is invented. Only the
product's name and the scene description leave KEEL.
"""
import io
import logging
from typing import Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageStat

from src.ai.marketing import background_removal

logger = logging.getLogger("CEOPRO_AI_MARKETING_COMPOSITE")

# How much of the frame the product may take, per format (width, height).
_PRODUCT_BOX = {
    "SQUARE": (0.58, 0.66), "PORTRAIT": (0.62, 0.62), "STORY": (0.72, 0.56),
    "LANDSCAPE": (0.40, 0.70), "WIDE": (0.34, 0.72),
}
# Where the product's base sits, as a share of the frame height.
_BASELINE = {"SQUARE": 0.84, "PORTRAIT": 0.80, "STORY": 0.72, "LANDSCAPE": 0.88, "WIDE": 0.90}


class CompositeError(Exception):
    pass


def scene_prompt(product_name: str, setting: str) -> str:
    """Text for the scene model: the setting only, with the centre left empty.
    `setting` is the campaign's creative direction / image description."""
    name = " ".join((product_name or "the product").split())[:80]
    setting = " ".join((setting or "").split())[:500]
    return (f"Empty background scene for a professional advertisement of {name}: {setting} "
            "Leave the centre of the frame and the surface in front completely empty - no product, no bottle, "
            "no box, no packaging, no people, no hands - only the surface, props at the edges, light and background, "
            "so a product photo can be placed in the middle.").strip()


def _has_real_alpha(image: Image.Image) -> bool:
    if image.mode not in ("RGBA", "LA") and not (image.mode == "P" and "transparency" in image.info):
        return False
    alpha = image.convert("RGBA").getchannel("A")
    lo, hi = alpha.getextrema()
    return lo < 250 and hi > 5


def _key_out_plain_background(image: Image.Image) -> Optional[Image.Image]:
    """Removes a plain, even studio background by colour distance from the
    border's colour. Returns None when the border is not plain (a busy
    background cannot be keyed out safely)."""
    rgb = image.convert("RGB")
    w, h = rgb.size
    strip = max(2, min(w, h) // 40)
    border = Image.new("RGB", (w * 2 + h * 2, strip))
    border.paste(rgb.crop((0, 0, w, strip)), (0, 0))
    border.paste(rgb.crop((0, h - strip, w, h)), (w, 0))
    border.paste(rgb.crop((0, 0, strip, h)).rotate(90, expand=True), (w * 2, 0))
    border.paste(rgb.crop((w - strip, 0, w, h)).rotate(90, expand=True), (w * 2 + h, 0))
    stat = ImageStat.Stat(border)
    if max(stat.stddev) > 18:  # not a plain backdrop
        return None
    bg = tuple(int(c) for c in stat.median)
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg)).convert("L")
    # Soft edge: within ~18 of the backdrop is background, beyond ~46 is product.
    mask = diff.point(lambda v: 0 if v < 18 else 255 if v > 46 else int((v - 18) * 255 / 28))
    # Only backdrop-coloured areas CONNECTED to the photo's border are background.
    # A white label or highlight inside the product (enclosed by the product) is
    # part of the product and must stay - keying it out would cut a hole in it.
    candidate = diff.point(lambda v: 255 if v <= 46 else 0)
    padded = Image.new("L", (w + 2, h + 2), 255)
    padded.paste(candidate, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128)
    outside = padded.crop((1, 1, w + 1, h + 1)).point(lambda v: 255 if v == 128 else 0)
    mask = ImageChops.lighter(mask, ImageChops.invert(outside))  # enclosed areas: fully product
    mask = mask.filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.GaussianBlur(1))
    if mask.getbbox() is None:
        return None
    out = rgb.convert("RGBA")
    out.putalpha(mask)
    return out


def cutout(photo: bytes) -> Tuple[Image.Image, str]:
    """The product with a transparent background, and how it was cut out:
    'transparent' (the photo already was), 'rembg' (local remover) or
    'plain-backdrop'. Raises CompositeError when none works."""
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(photo)))
        image.load()
    except Exception as err:  # noqa: BLE001 - any undecodable upload
        raise CompositeError("The product photo could not be read.") from err
    if _has_real_alpha(image):
        product, how = image.convert("RGBA"), "transparent"
    else:
        product, how = None, ""
        if background_removal.get_background_removal_capability().get("available"):
            try:
                removed = background_removal.remove_background(photo)
                product, how = Image.open(io.BytesIO(removed.content)).convert("RGBA"), "rembg"
            except Exception as err:  # noqa: BLE001 - fall back to keying
                logger.warning("Local background removal failed, trying the plain-backdrop key: %s", err)
        if product is None:
            product, how = _key_out_plain_background(image), "plain-backdrop"
        if product is None:
            raise CompositeError("The product's background is not plain enough to cut out here; "
                                 "use a photo on a plain background or a transparent PNG.")
    box = product.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    if not box:
        raise CompositeError("No product was found in the photo.")
    return product.crop(box), how


def _match_light(product: Image.Image, scene: Image.Image, strength: float = 0.12) -> Image.Image:
    """Tints the product slightly toward the scene's average light colour."""
    mean = tuple(int(c) for c in ImageStat.Stat(scene.convert("RGB").resize((32, 32))).mean)
    rgb = Image.blend(product.convert("RGB"), Image.new("RGB", product.size, mean), strength)
    out = rgb.convert("RGBA")
    out.putalpha(product.getchannel("A"))
    return out


def composite(scene: Image.Image, product: Image.Image, image_format: str) -> Image.Image:
    """Places the cut-out product into the scene for the given format."""
    canvas = scene.convert("RGBA")
    W, H = canvas.size
    bw, bh = _PRODUCT_BOX.get(image_format, _PRODUCT_BOX["SQUARE"])
    scale = min(W * bw / product.width, H * bh / product.height)
    item = product.resize((max(1, int(product.width * scale)), max(1, int(product.height * scale))), Image.LANCZOS)
    item = _match_light(item, scene)
    x = (W - item.width) // 2
    y = int(H * _BASELINE.get(image_format, 0.84)) - item.height
    alpha = item.getchannel("A")

    # Contact shadow: a soft dark ellipse right under the base.
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ew, eh = int(item.width * 0.86), max(6, int(item.height * 0.07))
    ellipse = Image.new("L", (ew, eh), 0)
    ImageDraw.Draw(ellipse).ellipse((0, 0, ew - 1, eh - 1), fill=150)
    shadow.paste(Image.new("RGBA", (ew, eh), (0, 0, 0, 255)), (x + (item.width - ew) // 2, y + item.height - eh // 2), ellipse)
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(4, eh // 2)))
    # Soft drop shadow from the product's own silhouette, offset down-right.
    drop = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    silhouette = Image.new("RGBA", item.size, (0, 0, 0, 255))
    silhouette.putalpha(alpha.point(lambda v: int(v * 0.35)))
    drop.paste(silhouette, (x + int(item.width * 0.03), y + int(item.height * 0.02)), silhouette)
    drop = drop.filter(ImageFilter.GaussianBlur(max(6, item.width // 30)))

    canvas = Image.alpha_composite(canvas, shadow)
    canvas = Image.alpha_composite(canvas, drop)
    canvas.alpha_composite(item, (x, y))
    return canvas.convert("RGB")


def to_bytes(image: Image.Image, fmt: str = "JPEG") -> Tuple[bytes, str]:
    buffer = io.BytesIO()
    if fmt == "PNG":
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), "image/png"
    image.convert("RGB").save(buffer, format="JPEG", quality=92)
    return buffer.getvalue(), "image/jpeg"
