"""Turn the downloaded logo files in logos/src/ into poster-ready transparent PNGs.

Only lossless, non-drawing steps: render SVG (cairosvg), drop a plain white backdrop that touches
the border, crop to the emblem, and keep or drop whole connected shapes of the original artwork. No
shape is drawn, traced or recoloured. Sources and terms: logos/SOURCES.md.

Output: logos/<name>.png, trimmed to the emblem, transparent background.
Run: uv run logos/prepare_logos.py
     (cairosvg needs the cairo library; on macOS: brew install cairo, then prefix the command with
     DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib)
"""
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow", "cairosvg", "scipy"]
# ///
import io
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"


def svg(path, height=2400):
    import cairosvg
    return Image.open(io.BytesIO(cairosvg.svg2png(url=str(path), output_height=height))).convert("RGBA")


def trim(im):
    return im.crop(im.getbbox())


def drop_white_border_bg(im, tol=12):
    """Make the white backdrop that is connected to the image border transparent (soft 1-px edge)."""
    a = np.asarray(im.convert("RGBA")).astype(np.float32)
    near_white = (255 - a[..., :3]).max(-1) <= tol
    lab, _ = ndimage.label(near_white)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(border))
    alpha = np.where(bg, 0, 255).astype(np.float32)
    alpha = ndimage.uniform_filter(alpha, 3)  # anti-alias the cut edge by one pixel
    a[..., 3] = np.minimum(a[..., 3], alpha)
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def keep_components(im, keep):
    """Keep only the connected opaque shapes for which keep(bbox, centroid, W, H) is true."""
    a = np.asarray(im.convert("RGBA")).copy()
    lab, n = ndimage.label(a[..., 3] > 8)
    H, W = lab.shape
    objs = ndimage.find_objects(lab)
    cents = ndimage.center_of_mass(np.ones_like(lab), lab, range(1, n + 1))
    keep_ids = [i + 1 for i, (sl, c) in enumerate(zip(objs, cents))
                if keep((sl[1].start, sl[0].start, sl[1].stop, sl[0].stop), (c[1], c[0]), W, H)]
    m = np.isin(lab, keep_ids)
    # keep soft edge pixels next to kept shapes
    m = ndimage.binary_dilation(m, iterations=2) & (a[..., 3] > 0)
    a[..., 3] = np.where(m, a[..., 3], 0)
    return Image.fromarray(a)


def top_block(im):
    """Rows of the first opaque block from the top (e.g. a shield above its wordmark)."""
    a = np.asarray(im)[..., 3] > 8
    rows = a.any(1)
    y = int(np.argmax(rows))
    while y < len(rows) and rows[y]:
        y += 1
    return im.crop((0, 0, im.width, y))


def main():
    out = {}
    out["corvette"] = trim(drop_white_border_bg(Image.open(SRC / "corvette_c8_seeklogo-368597.png")))
    # Mustang running pony in the tricolour corral (688 px tall; the bare chrome pony found was only 217 px)
    out["mustang"] = trim(Image.open(SRC / "mustang_pony_tribar_1000logos.png").convert("RGBA"))
    # SRT Hellcat lockup: keep the Hellcat head (the shapes right of the S-R-T letters)
    hc = trim(Image.open(SRC / "srt_hellcat_1000logos.png").convert("RGBA"))
    out["hellcat"] = trim(keep_components(hc, lambda bb, c, W, H: c[0] > 0.70 * W))
    # Ferrari: the shield is the first block above the "Ferrari" wordmark
    out["ferrari"] = trim(top_block(trim(svg(SRC / "ferrari_worldvectorlogo.svg"))))
    # Porsche: the crest is the first block above the PORSCHE wordmark; drop the small (R) mark
    pc = trim(top_block(trim(svg(SRC / "porsche_worldvectorlogo-2.svg", 4000))))
    out["porsche"] = trim(keep_components(pc, lambda bb, c, W, H: (bb[3] - bb[1]) > 0.2 * H or c[0] < 0.8 * W))
    out["lamborghini"] = trim(svg(SRC / "lamborghini_enwiki.svg"))
    for k, im in out.items():
        im.save(HERE / f"{k}.png")
        print(k, im.size)


if __name__ == "__main__":
    main()
