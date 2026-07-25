"""Build the link-preview (og:image) card for the WOLF desk.

Why this exists: the brand assets are 1024x1024 and ~1.4 MB. Chat apps reject
those for previews -- WhatsApp in particular silently shows NO thumbnail above
roughly 300 KB, and a square crops badly in every feed. This renders the
canonical 1200x630 card, palette-correct (silver/steel, not gold), and keeps
it small enough that every app actually fetches it.

Run:  python make_og.py
Out:  og.png  (served at /og.png, referenced by the landing page's og:image)
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "og.png")

W, H = 1200, 630
BG = (10, 14, 21)          # --bg   #0a0e15
LINE = (35, 48, 66)        # --line #233042
CHROME = (199, 210, 221)   # --chrome  #c7d2dd
CHROME2 = (234, 240, 245)  # --chrome2 #eaf0f5
MUT = (135, 145, 160)      # --mut  #8791a0

FONTS = (
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
)
FONTS_REG = (
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
)


def font(size: int, bold: bool = True):
    for p in (FONTS if bold else FONTS_REG):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def spaced(txt: str, px: int) -> str:
    """Crude letter-spacing -- Pillow has no tracking control."""
    return (" " * max(1, px // 6)).join(txt)


def circle_emblem(path: str, size: int) -> Image.Image | None:
    if not os.path.exists(path):
        return None
    im = Image.open(path).convert("RGBA")
    # square-crop from the centre, then scale
    s = min(im.size)
    l, t = (im.width - s) // 2, (im.height - s) // 2
    im = im.crop((l, t, l + s, t + s)).resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4, size * 4), fill=255)
    im.putalpha(mask.resize((size, size), Image.LANCZOS))
    return im


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # soft vignette so the emblem doesn't float on flat black
    for i in range(90):
        a = int(6 * (1 - i / 90))
        d.rectangle((i, i, W - i, H - i), outline=(BG[0] + a, BG[1] + a, BG[2] + a))
    d.rectangle((0, 0, W - 1, H - 1), outline=LINE, width=3)

    emb = circle_emblem(os.path.join(HERE, "staalwag.png"), 300)
    ex, ey = 92, (H - 300) // 2
    if emb:
        ring = Image.new("RGBA", (316, 316), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse((0, 0, 315, 315), outline=LINE + (255,), width=3)
        img.paste(ring, (ex - 8, ey - 8), ring)
        img.paste(emb, (ex, ey), emb)

    tx = ex + 300 + 74
    d.text((tx, 196), "STAALWAG", font=font(76), fill=CHROME2)
    d.text((tx, 292), spaced("GOLD & FX INTRADAY", 3), font=font(23), fill=CHROME)
    d.text((tx, 326), spaced("INTEL DESK", 3), font=font(23), fill=CHROME)
    d.text((tx, 382), "Scored BUY/SELL reads · full case files",
           font=font(21, bold=False), fill=MUT)
    d.text((tx, 412), "public track record · free channels + VIP",
           font=font(21, bold=False), fill=MUT)

    d.line((tx, 366, tx + 300, 366), fill=LINE, width=2)

    img.save(OUT, "PNG", optimize=True)
    kb = os.path.getsize(OUT) / 1024
    print("wrote %s  %dx%d  %.0f KB" % (OUT, W, H, kb))
    if kb > 300:
        print("  WARNING: over 300 KB -- WhatsApp may skip the thumbnail.")


if __name__ == "__main__":
    main()
