"""
Procedurally drawn artwork in the style of the Pirate Fighting Simulator
main menu (warm wooden cabin, gold title, green buttons with a light rim).
Everything is generated with Pillow – no game assets are used.
"""
from __future__ import annotations

import random
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---- palette ---------------------------------------------------------------
WOOD_DARK = (46, 26, 14)
WOOD_MID = (104, 58, 30)
WOOD_LIGHT = (156, 96, 50)
GOLD = (226, 170, 84)
GOLD_DARK = (120, 70, 28)
CREAM = (244, 236, 214)
BTN_GREEN = (44, 104, 80)
BTN_GREEN_DARK = (26, 70, 52)
BTN_RIM = (148, 196, 168)
BTN_HOVER = (96, 124, 178)
BTN_HOVER_DARK = (64, 88, 140)
BTN_HOVER_RIM = (190, 206, 236)
BTN_DISABLED = (70, 78, 70)
RED = (226, 96, 80)

_FONT_CANDIDATES = [
    # Windows: classic book serifs that come with every installation
    "C:/Windows/Fonts/palab.ttf",      # Palatino Linotype Bold
    "C:/Windows/Fonts/georgiab.ttf",   # Georgia Bold
    "C:/Windows/Fonts/timesbd.ttf",
    # Linux fallbacks (development)
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
]


@lru_cache(maxsize=None)
def font(size: int) -> ImageFont.FreeTypeFont:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for p in [str(base / "assets" / "font.ttf"), *_FONT_CANDIDATES]:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# ---- small caps text (like "Find Game" in the game menu) --------------------
def smallcaps_size(text: str, size: int) -> tuple[int, int]:
    big, small = font(size), font(int(size * 0.74))
    w = 0
    for word_i, word in enumerate(text.split(" ")):
        if word_i:
            w += int(size * 0.32)
        for i, ch in enumerate(word):
            f = big if (i == 0 or not ch.isalpha() or ch.isupper()) else small
            w += int(f.getlength(ch.upper()))
    return w, size


def draw_smallcaps(draw: ImageDraw.ImageDraw, xy, text: str, size: int, fill, shadow=(0, 0, 0, 160)):
    big, small = font(size), font(int(size * 0.74))
    x, y = xy
    asc_big = big.getmetrics()[0]
    asc_small = small.getmetrics()[0]
    for word_i, word in enumerate(text.split(" ")):
        if word_i:
            x += int(size * 0.32)
        for i, ch in enumerate(word):
            is_big = i == 0 or not ch.isalpha() or ch.isupper()
            f = big if is_big else small
            dy = 0 if is_big else asc_big - asc_small
            if shadow:
                draw.text((x + 2, y + dy + 2), ch.upper(), font=f, fill=shadow)
            draw.text((x, y + dy), ch.upper(), font=f, fill=fill)
            x += int(f.getlength(ch.upper()))


# ---- background --------------------------------------------------------------
def _vary(c, amount, rnd):
    return tuple(max(0, min(255, int(v + rnd.uniform(-amount, amount)))) for v in c)


def background(w: int, h: int, seed: int = 7) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("RGB", (w, h), WOOD_DARK)
    d = ImageDraw.Draw(img)

    # vertical wall boards
    x = -rnd.randint(0, 40)
    while x < w:
        bw = rnd.randint(70, 120)
        base = _vary(WOOD_MID, 7, rnd)
        d.rectangle([x, 0, x + bw, h], fill=base)
        # grain
        for _ in range(int(bw * 1.4)):
            gx = x + rnd.randint(2, bw - 2)
            col = _vary(base, 14, rnd)
            y0 = rnd.randint(-40, h)
            d.line([gx, y0, gx + rnd.randint(-2, 2), y0 + rnd.randint(40, 260)], fill=col, width=1)
        # knots
        for _ in range(rnd.randint(0, 2)):
            kx, ky = x + rnd.randint(10, bw - 10), rnd.randint(0, h)
            r = rnd.randint(4, 9)
            d.ellipse([kx - r, ky - r * 1.6, kx + r, ky + r * 1.6], outline=_vary(WOOD_DARK, 10, rnd), width=2)
        # gaps between boards
        d.line([x, 0, x, h], fill=WOOD_DARK, width=3)
        d.line([x + 3, 0, x + 3, h], fill=_vary(WOOD_LIGHT, 10, rnd), width=1)
        x += bw

    # horizontal ceiling beams
    for by, bh in ((int(h * 0.04), int(h * 0.07)), (int(h * 0.16), int(h * 0.05))):
        d.rectangle([0, by, w, by + bh], fill=(78, 44, 22))
        for _ in range(w // 6):
            gx = rnd.randint(0, w)
            gy = rnd.randint(by + 2, by + bh - 2)
            d.line([gx, gy, gx + rnd.randint(30, 140), gy], fill=_vary((78, 44, 22), 18, rnd))
        d.line([0, by, w, by], fill=(140, 90, 50), width=2)
        d.line([0, by + bh, w, by + bh], fill=WOOD_DARK, width=4)

    # floor planks
    fy = int(h * 0.86)
    d.rectangle([0, fy, w, h], fill=(90, 52, 28))
    for i in range(0, w, 160):
        d.line([i, fy, i - 60, h], fill=WOOD_DARK, width=2)
    d.line([0, fy, w, fy], fill=(150, 98, 54), width=2)

    img = img.filter(ImageFilter.GaussianBlur(0.6))

    # warm lantern light in the centre + dark vignette
    light = Image.new("L", (w, h), 0)
    ld = ImageDraw.Draw(light)
    ld.ellipse([w * 0.18, -h * 0.15, w * 0.82, h * 0.95], fill=255)
    light = light.filter(ImageFilter.GaussianBlur(w // 6))
    warm = Image.new("RGB", (w, h), (255, 170, 90))
    img = Image.composite(Image.blend(img, warm, 0.18), img, light)
    dark = Image.new("RGB", (w, h), (12, 6, 2))
    inv = light.point(lambda v: int((255 - v) * 0.92))
    img = Image.composite(dark, img, inv)
    return img


# ---- title -------------------------------------------------------------------
def title(text_top: str = "Pirate Fighting", text_main: str = "Simulator", sub: str = "QoL Launcher") -> Image.Image:
    s_top, s_main, s_sub = 40, 64, 22
    w = max(smallcaps_size(text_top, s_top)[0], smallcaps_size(text_main, s_main)[0]) + 40
    h = s_top + s_main + s_sub + 50
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    def layer(fill, offset=(0, 0)):
        lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dd = ImageDraw.Draw(lay)
        tw = smallcaps_size(text_top, s_top)[0]
        draw_smallcaps(dd, ((w - tw) // 2 + offset[0], 6 + offset[1]), text_top, s_top, fill, shadow=None)
        tw = smallcaps_size(text_main, s_main)[0]
        draw_smallcaps(dd, ((w - tw) // 2 + offset[0], s_top + 8 + offset[1]), text_main, s_main, fill, shadow=None)
        return lay

    # dark outline / glow
    glow = layer((40, 16, 4, 255))
    for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (3, 4)):
        img.alpha_composite(layer((40, 16, 4, 220), (dx, dy)))
    img = Image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(6)), img)
    # vertical gold gradient fill
    mask = layer((255, 255, 255, 255)).split()[3]
    grad = Image.new("RGBA", (w, h))
    gd = ImageDraw.Draw(grad)
    for y in range(h):
        t = y / h
        c = tuple(int(GOLD[i] * (1 - t * 0.55) + GOLD_DARK[i] * t * 0.55) for i in range(3))
        gd.line([0, y, w, y], fill=c + (255,))
    img.paste(grad, (0, 0), mask)
    # subtitle
    d = ImageDraw.Draw(img)
    tw = smallcaps_size(sub, s_sub)[0]
    draw_smallcaps(d, ((w - tw) // 2, s_top + s_main + 22), sub, s_sub, CREAM)
    return img


# ---- buttons -------------------------------------------------------------------
@lru_cache(maxsize=512)
def button(w: int, h: int, label: str, state: str = "normal", size: int = 22) -> Image.Image:
    if state == "hover":
        top, bottom, rim = BTN_HOVER, BTN_HOVER_DARK, BTN_HOVER_RIM
    elif state == "disabled":
        top, bottom, rim = BTN_DISABLED, (50, 56, 50), (110, 120, 110)
    elif state == "danger":
        top, bottom, rim = (120, 48, 36), (84, 30, 22), (220, 150, 130)
    else:
        top, bottom, rim = BTN_GREEN, BTN_GREEN_DARK, BTN_RIM
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # drop shadow
    d.rounded_rectangle([3, 4, w - 1, h - 1], radius=4, fill=(0, 0, 0, 110))
    # body gradient
    body = Image.new("RGBA", (w - 4, h - 4))
    bd = ImageDraw.Draw(body)
    for y in range(h - 4):
        t = y / (h - 4)
        bd.line([0, y, w, y], fill=tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3)) + (255,))
    m = Image.new("L", body.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, body.size[0] - 1, body.size[1] - 1], radius=4, fill=255)
    img.paste(body, (0, 0), m)
    d.rounded_rectangle([0, 0, w - 5, h - 5], radius=4, outline=(12, 30, 22, 255), width=2)
    d.rounded_rectangle([3, 3, w - 8, h - 8], radius=3, outline=rim + (200,), width=1)
    # label
    tw, _ = smallcaps_size(label, size)
    fill = CREAM if state != "disabled" else (170, 170, 160)
    asc, desc = font(size).getmetrics()
    draw_smallcaps(d, ((w - 4 - tw) // 2, (h - 4 - asc - desc) // 2 + 1), label, size, fill)
    return img


# ---- panels ----------------------------------------------------------------------
def panel(w: int, h: int) -> Image.Image:
    """Dark wooden board with a brass rim (used for options & dialogs)."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 6, w - 1, h - 1], radius=8, fill=(0, 0, 0, 120))
    d.rounded_rectangle([0, 0, w - 5, h - 7], radius=8, fill=(38, 22, 12, 236))
    rnd = random.Random(3)
    for _ in range(w // 3):
        y = rnd.randint(8, h - 16)
        x = rnd.randint(8, w - 60)
        d.line([x, y, x + rnd.randint(20, 120), y], fill=(58, 34, 18, 140))
    d.rounded_rectangle([0, 0, w - 5, h - 7], radius=8, outline=(150, 104, 52, 255), width=3)
    d.rounded_rectangle([6, 6, w - 11, h - 13], radius=6, outline=(90, 58, 28, 255), width=1)
    return img


def toggle(on: bool, w: int = 120, h: int = 40) -> Image.Image:
    return button(w, h, "On" if on else "Off", "normal" if on else "danger", size=20)


def dim(w: int, h: int, alpha: int = 150) -> Image.Image:
    return Image.new("RGBA", (w, h), (0, 0, 0, alpha))


def icon(size: int = 256) -> Image.Image:
    """App icon: green menu button with a gold 'Q'."""
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = s // 6
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=(26, 70, 52, 255))
    d.rounded_rectangle([s // 32, s // 32, s - 1 - s // 32, s - 1 - s // 16], radius=r, fill=BTN_GREEN + (255,))
    d.rounded_rectangle([s // 14, s // 14, s - 1 - s // 14, s - 1 - s // 10], radius=r // 2,
                        outline=BTN_RIM + (255,), width=max(1, s // 40))
    f = font(int(s * 0.62))
    bbox = d.textbbox((0, 0), "Q", font=f)
    tx = (s - (bbox[2] - bbox[0])) // 2 - bbox[0]
    ty = (s - (bbox[3] - bbox[1])) // 2 - bbox[1] - s // 30
    d.text((tx + s // 40, ty + s // 40), "Q", font=f, fill=(20, 10, 4, 200))
    d.text((tx, ty), "Q", font=f, fill=GOLD + (255,))
    return img


# ---- crosshair preview -----------------------------------------------------------
def _scene(w: int, h: int) -> Image.Image:
    """Simple 'in-game' backdrop: sky, sea and a wooden deck."""
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    horizon = int(h * 0.55)
    for y in range(horizon):
        t = y / horizon
        d.line([0, y, w, y], fill=(int(120 + 80 * t), int(170 + 50 * t), int(220 + 20 * t)))
    for y in range(horizon, h):
        t = (y - horizon) / (h - horizon)
        d.line([0, y, w, y], fill=(int(30 + 20 * t), int(90 + 20 * t), int(120 - 30 * t)))
    deck = int(h * 0.78)
    d.rectangle([0, deck, w, h], fill=(120, 72, 38))
    for x in range(0, w, max(8, w // 12)):
        d.line([x, deck, x, h], fill=(70, 40, 20), width=2)
    return img


def crosshair_preview(xh: dict, w: int, h: int, zoom: int = 1) -> Image.Image:
    """Render the crosshair like the mod does (same rectangles, same rounding),
    magnified `zoom` times so single pixels are visible."""
    import math

    import crosshair as X

    gw, gh = max(1, w // zoom), max(1, h // zoom)        # size in game pixels
    img = _scene(w, h).convert("RGBA")
    cx, cy = gw // 2, gh // 2
    for left, top, rw, rh, rgb, alpha in X.rects(xh):
        x0, y0 = math.floor(cx + left), math.floor(cy + top)
        x1, y1 = x0 + max(1, round(rw)), y0 + max(1, round(rh))
        lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(lay).rectangle([x0 * zoom, y0 * zoom, x1 * zoom - 1, y1 * zoom - 1],
                                      fill=rgb + (int(255 * max(0.0, min(1.0, alpha))),))
        img.alpha_composite(lay)
    return img
