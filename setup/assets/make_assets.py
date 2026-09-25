"""Generuje grafike Achai: ikone (achaja.ico, achaja.png) i obrazy kreatora instalatora (wizard*.bmp).

Wymaga Pillow (poza projektem, np. w osobnym venv):  python make_assets.py
Wynik trafia obok tego pliku; gotowe pliki sa w repozytorium, wiec do budowania instalatora Pillow nie jest potrzebny.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
TOP, BOTTOM = (132, 100, 255), (76, 44, 190)      # fiolet jak w formularzu ustawien
WHITE = (255, 255, 255)


def gradient(size, top=TOP, bottom=BOTTOM):
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        row = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        for x in range(w):
            px[x, y] = row
    return img


def glyph(draw, box, color=WHITE):
    """Litera A z fala dzwieku zamiast poprzeczki. box = (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    stroke = w * 0.13
    apex = (x0 + w / 2, y0)
    left, right = (x0, y1), (x1, y1)
    for a, b in ((apex, left), (apex, right)):
        draw.line([a, b], fill=color, width=round(stroke))
        for p in (a, b):
            r = stroke / 2
            draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color)
    # fala: slupki rownomiernie w poprzek litery, najwyzszy w srodku
    cy = y0 + h * 0.66
    heights = (0.10, 0.22, 0.34, 0.22, 0.10)
    span = w * 0.62
    bw = span / (len(heights) * 1.9)
    for i, hh in enumerate(heights):
        cx = x0 + w / 2 - span / 2 + (i + 0.5) * span / len(heights)
        half = h * hh / 2
        draw.rounded_rectangle([cx - bw / 2, cy - half, cx + bw / 2, cy + half], radius=bw / 2, fill=color)


def icon(size=1024):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=size * 0.22, fill=255)
    img.paste(gradient((size, size)), (0, 0), mask)
    m = size * 0.2
    glyph(ImageDraw.Draw(img), (m, m * 1.05, size - m, size - m * 0.95))
    return img


def font(px):
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def wizard(size):
    w, h = size
    img = gradient(size)
    glow = Image.new("RGB", size, (0, 0, 0))
    ImageDraw.Draw(glow).ellipse([-w * 0.6, h * 0.55, w * 1.6, h * 1.5], fill=(160, 130, 255))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(w * 0.25)), 0.25)
    d = ImageDraw.Draw(img)
    g = w * 0.46
    glyph(d, ((w - g) / 2, h * 0.25, (w + g) / 2, h * 0.25 + g * 1.02))
    f = font(round(w * 0.17))
    text = "Achaja"
    tw = d.textlength(text, font=f)
    d.text(((w - tw) / 2, h * 0.25 + g * 1.02 + w * 0.12), text, font=f, fill=WHITE)
    return img


def main():
    big = icon()
    big.resize((256, 256), Image.LANCZOS).save(HERE / "achaja.png")
    big.save(HERE / "achaja.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    for scale in (1, 2):
        wizard((164 * scale, 314 * scale)).save(HERE / f"wizard{'' if scale == 1 else '@2x'}.bmp")
        small = Image.new("RGB", (55 * scale, 55 * scale), WHITE)
        s = icon(512).resize((55 * scale, 55 * scale), Image.LANCZOS)
        small.paste(s, (0, 0), s)
        small.save(HERE / f"wizard-small{'' if scale == 1 else '@2x'}.bmp")
    print("Zapisano:", ", ".join(sorted(p.name for p in HERE.iterdir() if p.suffix in (".ico", ".png", ".bmp"))))


if __name__ == "__main__":
    main()
