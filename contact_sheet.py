"""Build the contact sheet: the six main posters (01-06) in a 3x2 grid, in order, from the print
files in posters/print/. Writes posters/print/contact-sheet.png and the preview posters/contact-sheet.jpg.
Run: uv run contact_sheet.py"""
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
from pathlib import Path
from PIL import Image

POSTERS = Path(__file__).resolve().parent / "posters"
PRINT = POSTERS / "print"
ORDER = ["01-z06", "02-darkhorse", "03-charger", "04-911turbos", "05-murcielago", "06-296gtb"]
W, H, GAP = 768, 1024, 32  # 3:4 tiles

sheet = Image.new("RGB", (3 * W + 4 * GAP, 2 * H + 3 * GAP), (245, 243, 240))
for i, slug in enumerate(ORDER):
    im = Image.open(PRINT / f"{slug}.png").convert("RGB").resize((W, H), Image.LANCZOS)
    sheet.paste(im, (GAP + (i % 3) * (W + GAP), GAP + (i // 3) * (H + GAP)))
sheet.save(PRINT / "contact-sheet.png")
sheet.save(POSTERS / "contact-sheet.jpg", quality=88, optimize=True, progressive=True)
print("posters/print/contact-sheet.png, posters/contact-sheet.jpg", sheet.size)
