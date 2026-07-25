"""Build the STAALWAG favicon / home-screen icons from staalwag.png.

The raw emblem is 1024x1024 and ~1.4 MB -- too heavy for a favicon and the
wrong job for an Apple touch icon (iOS wants a small, opaque square it can
round the corners of itself). This renders the sizes phones actually ask for:

  favicon-32.png       browser tab / chat-preview favicon
  apple-touch-icon.png 180x180, opaque bg -- iOS "Add to Home Screen"
  icon-192.png         Android home screen / PWA
  icon-512.png         Android splash / PWA maskable

Run:  python make_icons.py
"""
from __future__ import annotations

import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "staalwag.png")
BG = (10, 14, 21)   # --bg #0a0e15, so iOS doesn't put the emblem on white

SIZES = {
    "favicon-32.png": (32, True),
    "apple-touch-icon.png": (180, True),
    "icon-192.png": (192, True),
    "icon-512.png": (512, True),
}


def square(im: Image.Image) -> Image.Image:
    s = min(im.size)
    l, t = (im.width - s) // 2, (im.height - s) // 2
    return im.crop((l, t, l + s, t + s))


def main() -> None:
    base = square(Image.open(SRC).convert("RGBA"))
    for name, (size, opaque) in SIZES.items():
        icon = base.resize((size, size), Image.LANCZOS)
        if opaque:
            # flatten onto the brand background: Apple/Android show icons on a
            # solid tile and transparency reads as ugly white.
            bg = Image.new("RGB", (size, size), BG)
            bg.paste(icon, (0, 0), icon)
            out = bg
        else:
            out = icon
        p = os.path.join(HERE, name)
        out.save(p, "PNG", optimize=True)
        print("wrote %-22s %dx%d  %.0f KB"
              % (name, size, size, os.path.getsize(p) / 1024))


if __name__ == "__main__":
    main()
