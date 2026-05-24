"""Generate splatforge.ico — black rounded square with a bold white 'S'.

Saves a multi-resolution .ico (16, 24, 32, 48, 64, 128, 256) at desktop/icons/splatforge.ico.
Also saves a 1024 PNG for use in screenshots / store listings.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path(__file__).parent / "icons"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    # Try a few common Windows fonts, ordered by visual fit for a bold geometric mark
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf",   # Segoe UI Bold
        r"C:\Windows\Fonts\arialbd.ttf",    # Arial Bold
        r"C:\Windows\Fonts\calibrib.ttf",   # Calibri Bold
        r"C:\Windows\Fonts\seguisb.ttf",    # Segoe UI Semibold
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_icon(size: int) -> Image.Image:
    """Render a single icon at the given pixel size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded black square background with ~22% corner radius
    radius = max(2, round(size * 0.22))
    d.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=(0, 0, 0, 255))

    # Big bold "S" centered. Font size ~75% of the icon (S has padding built in by design)
    font_size = round(size * 0.75)
    font = _find_font(font_size)

    text = "S"
    # Measure
    bbox = d.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    # Center accounting for the actual ink bounds (textbbox gives offset)
    x = (size - tw) / 2 - bbox[0]
    # Visually centered vertically — pull up a hair because letterforms sit on baseline
    y = (size - th) / 2 - bbox[1] - max(1, size * 0.02)

    d.text((x, y), text, fill=(255, 255, 255, 255), font=font)
    return img


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    pages = [render_icon(s) for s in sizes]

    ico_path = OUT_DIR / "splatforge.ico"
    pages[-1].save(ico_path, format="ICO", sizes=[(p.width, p.height) for p in pages], append_images=pages[:-1])

    # Also dump a 1024 PNG for marketing / readme use
    big = render_icon(1024)
    big.save(OUT_DIR / "splatforge_1024.png", format="PNG")

    print(f"Wrote {ico_path}")
    print(f"Wrote {OUT_DIR / 'splatforge_1024.png'}")


if __name__ == "__main__":
    main()
