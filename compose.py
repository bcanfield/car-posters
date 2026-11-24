"""Compose a final poster on a fixed, code-owned grid.

Canvas 3600x4800, a flat code-drawn backdrop colour matched to the studio backdrop. Every poster
uses the same rectangles:
  HERO panel (side profile), FRONT and REAR panels below it, all with a hairline frame;
  "No. 0X" top left, the real maker logo (logos/, placed by code) top right;
  the MAKE headline, "MODEL · YEAR", the 4-column spec strip and the 0-300 mph TOP SPEED bar.

Each car photo is auto-fitted into its panel: the car's bounding box is detected against the plain
studio backdrop (corner-sampled colour + difference threshold; the tyre baseline is the lowest row
of near-black tyre pixels, so the soft floor shadow does not count), then scaled so the car width is
a fixed share of the panel width, moved so the tyre baseline sits on a fixed y, and centred. The
photo is tone-matched so its backdrop equals the poster backdrop, feathered at its own edges, and
the panel is filled with that backdrop wherever the photo does not reach. Everything is cropped at
the panel border.

Inputs per car (cars.json "art"): hero = a side view image, or a whole-poster art candidate (the
hero band is cut from its top); front, rear = single-view images from generate.py --view.
Spec values come from cars.json and are cross-checked against specs.md. The print file is written to
posters/print/<slug>.png (gitignored) with a web-size preview at posters/<slug>.jpg, then the print
file is re-measured (car boxes per panel and the speed bar) and the numbers are written to
posters/measurements.json.

Run: uv run compose.py [--16x20] <slug> [<slug> ...]

--16x20 lays the same grid out on a 4:5 canvas (3840x4800, 16x20 in at 240 dpi) instead of 3:4
(3600x4800, 12x16 in at 300 dpi). The extra 240 px go into the panel and text widths, not the
margins. Output goes to posters/print/16x20/<slug>.png and posters/measurements-16x20.json; the
README previews are left alone.
"""
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow"]
# ///
import json, re, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageFilter, ImageFont

HERE = ROOT = Path(__file__).resolve().parent
OUT = ROOT / "posters"
PRINT = OUT / "print"
SIZE_16X20 = "--16x20" in sys.argv
FONT = ROOT / "assets/fonts/Archivo.ttf"  # Archivo (Google Fonts, OFL), variable wght 100-900, wdth 62-125
W, H = (3840, 4800) if SIZE_16X20 else (3600, 4800)
XW = W - 3600  # extra width over the 3:4 layout, added to the panels
BG = (218, 211, 203)          # poster backdrop: the studio grey, measured from the empty lower area of a generated poster
INK = (30, 30, 30)
FRAME = (240, 236, 231)       # hairline panel frame, light, close to the backdrop
FRAME_W = 4
TRACK = (186, 180, 173)

# the grid (x0, y0, x1, y1), identical on every poster
HERO = (110, 420, 3490 + XW, 1900)
FRONT = (110, 1960, 1775 + XW // 2, 3120)
REAR = (1825 + XW // 2, 1960, 3490 + XW, 3120)
FIT = {  # car width as a share of panel width, tyre baseline as a share of panel height
    "hero": (0.86, 0.845),
    "front": (0.76, 0.91),   # 0.91 leaves the tallest view (Charger rear, h/w 0.73) ~60 px of headroom
    "rear": (0.76, 0.91),
}
LOGO_BOX = (W - 220, 253)    # right edge x, centre y (the cap middle of "No. 0X")
LOGO_INK = 30000             # target logo ink area in px²; height clamped to LOGO_H
LOGO_H = (200, 280)          # keeps the logo top >= 113 px (0.47 in) from the trim
TEXT_X = 220
Y_NO = 280
Y_HEAD, Y_SUB = 3600, 3770
Y_RULE, Y_LABEL, Y_VALUE, Y_DIV = 3900, 3995, 4135, (3955, 4175)
COLS = (0.46, 0.27, 0.27)  # spec strip column shares: ENGINE, POWER, 0-60 (top speed is printed at the bar tip)
CELL_PAD = 40               # spec cells are left-aligned this far right of their divider
LABEL_SIZE = 46


def col_edges():
    xs, x = [TEXT_X], TEXT_X
    for f in COLS:
        x += f * (W - 2 * TEXT_X)
        xs.append(x)
    return xs
Y_BAR, TICK_LEN, Y_TICKLABEL = (4340, 4540), 55, 4670  # top speed is printed inside the track


# ---------- text helpers ----------
def font(size, wght, wdth=100):
    f = ImageFont.truetype(str(FONT), size)
    f.set_variation_by_axes([wght, wdth])
    return f


def text_w(d, s, f, tracking=0.0):
    return sum(d.textlength(c, font=f) for c in s) + tracking * f.size * (len(s) - 1)


def ink_x(x, s, f):
    """Start x that puts the first glyph's ink (not its side bearing) exactly on x, so lines of
    different sizes share one optical left edge with the rule and the bar."""
    pad = f.size
    im = Image.new("L", (3 * pad, 3 * pad), 0)
    ImageDraw.Draw(im).text((pad, 2 * pad), s[0], font=f, fill=255, anchor="ls")
    cols = np.flatnonzero((np.asarray(im) > 127).any(0))
    return x - (int(cols[0]) - pad if cols.size else 0)


def draw_text(d, x, y, s, f, tracking=0.0, align="left"):
    w = text_w(d, s, f, tracking)
    x = {"left": x, "center": x - w / 2, "right": x - w}[align]
    for c in s:
        d.text((x, y), c, font=f, fill=INK, anchor="ls")
        x += d.textlength(c, font=f) + tracking * f.size


# ---------- data ----------
def cars():
    return json.loads((HERE / "cars.json").read_text())["cars"]


def car(slug):
    for c in cars():
        if c["slug"] == slug:
            return c
    sys.exit(f"unknown slug {slug}")


def check_specs_md(c):
    for line in (HERE / "specs.md").read_text().splitlines():
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and cells[1] == c["slug"]:
            s = c["specs"]
            want = [s["engine"], s["power"].upper(), s["zero_sixty"].upper(), s["top_speed"].upper()]
            got = [cells[2], cells[3].upper(), cells[4].upper(), cells[5].upper()]
            if want != got:
                sys.exit(f"{c['slug']}: cars.json {want} != specs.md {got}")
            if int(re.match(r"\d+", s["top_speed"]).group()) != c["top_speed"]:
                sys.exit(f"{c['slug']}: top_speed {c['top_speed']} != printed {s['top_speed']}")
            return
    sys.exit(f"{c['slug']}: not in the specs.md table")


# ---------- car detection ----------
def corner_bg(a):
    h, w, _ = a.shape
    k = max(8, min(h, w) // 40)
    patches = [a[:k, :k], a[:k, -k:], a[-k:, :k], a[-k:, -k:]]
    return np.median(np.concatenate([p.reshape(-1, 3) for p in patches]), axis=0)


def row_backdrop(a):
    """Backdrop estimate per row: linear between the medians of the left and right 4% edge strips.
    Follows the vertical gradient/vignette of a studio backdrop, which a single colour does not."""
    h, w, _ = a.shape
    k = max(8, int(0.04 * w))
    left = np.median(a[:, :k], axis=1); right = np.median(a[:, -k:], axis=1)
    t = np.linspace(0, 1, w, dtype=np.float32)[None, :, None]
    return (1 - t) * left[:, None, :] + t * right[:, None, :]


def detect(a, bg=None, thr=45):
    """Car box in an image of one car on a plain backdrop: (x0, top, x1, baseline)."""
    a = a.astype(np.float32)
    h, w, _ = a.shape
    ref = row_backdrop(a) if bg is None else np.asarray(bg, np.float32)
    bg = corner_bg(a) if bg is None else np.asarray(bg, np.float32)
    mask = np.abs(a - ref).max(-1) > thr
    rows = mask.sum(1)
    on = np.flatnonzero(rows > max(3, 0.004 * w))
    if on.size == 0:
        raise ValueError("no car found")
    # tyre baseline: lowest row with a solid run of near-black (tyre) pixels
    lum = a @ np.array([0.299, 0.587, 0.114], np.float32)
    dark = lum < min(70, float(bg @ np.array([0.299, 0.587, 0.114])) - 110)
    drow = np.flatnonzero(dark.sum(1) > 0.01 * w)
    base = drow[-1] if drow.size else on[-1]
    # top: walk up from the baseline through busy rows; stop at the first empty gap of 2% of the height
    busy = rows > max(3, 0.004 * w)
    gap = max(3, int(0.02 * h))
    top = base
    while top - 1 >= 0 and busy[max(0, top - gap):top].any():
        top -= 1
        while top > 0 and busy[top - 1]:
            top -= 1
    # width from rows above the floor shadow: from the top down to 1.5% of the height above the baseline
    cols = mask[top: max(top + 1, base - int(0.03 * (base - top + 1)))].sum(0)
    xs = np.flatnonzero(cols > 2)
    return int(xs[0]), int(top), int(xs[-1]), int(base)


def hero_band(a):
    """Rows of the hero car in a whole-poster art candidate: the first block of busy rows."""
    a32 = a.astype(np.float32)
    h, w, _ = a.shape
    busy = (np.abs(a32 - row_backdrop(a32)).max(-1) > 45).sum(1) > 0.005 * w
    y = int(h * 0.03)
    while y < h and not busy[y]:
        y += 1
    y0 = y
    gap = int(0.015 * h)
    while y < h:
        if not busy[y:y + gap].any():
            break
        y += 1
    y1 = y
    # cut halfway into the empty gaps above and below
    up = y0 - 1
    while up > 0 and not busy[up]:
        up -= 1
    down = y1
    while down < h and not busy[down]:
        down += 1
    return (up + y0) // 2, (y1 + down) // 2


# ---------- panel fitting ----------
SHADOW_LIFT = 10  # 0 -> 10, fading to no change at 80: keeps tyre/grille detail above the paper's darkest black


def lift_shadows(a):
    a = np.asarray(a, np.float32)
    return np.where(a < 80, a + SHADOW_LIFT * (1 - a / 80), a)


def tone_match(a, bg_src):
    gain = np.asarray(BG, np.float32) / np.maximum(bg_src, 1)
    return np.clip(a.astype(np.float32) * gain, 0, 255)


INSET = FRAME_W + 2  # the panel interior that measure() looks at


def _render(base_img, s, cx_src, base_src, pw, ph, base_frac, dx=0.0, dy=0.0):
    img = base_img.resize((max(1, round(base_img.width * s)), max(1, round(base_img.height * s))), Image.LANCZOS)
    if s > 1.05:  # upscaled AI photo: restore some edge contrast lost to the resize
        img = img.filter(ImageFilter.UnsharpMask(radius=1.0 + 0.8 * (s - 1), percent=70, threshold=2))
    # feather the photo's own edges into the backdrop (60 px) so no seam or halo shows
    f = 60
    ramp = np.clip(np.arange(max(img.width, img.height)) / f, 0, 1)
    m = (ramp[:img.width][None, :] * ramp[:img.width][::-1][None, :]
         * ramp[:img.height][:, None] * ramp[:img.height][::-1][:, None])
    ox = round(pw / 2 - cx_src * s + dx)
    oy = round(base_frac * ph - base_src * s + dy)
    canvas = Image.new("RGB", (pw, ph), BG)
    canvas.paste(img, (ox, oy), Image.fromarray((m * 255).astype(np.uint8)))
    return canvas, ox, oy


def fit_into_panel(src, panel, kind):
    """Return (panel image, placement info). Fits, then re-measures the rendered panel with the same
    detector measure() uses and corrects scale and offset until width, centre and baseline are
    within 1 px of the targets (at most 6 passes)."""
    a = np.asarray(src.convert("RGB"))
    x0, top, x1, base = detect(a)
    # backdrop colour = median of every pixel outside the car's box (padded 4%), not the vignetted corners
    h, w, _ = a.shape
    pad = int(0.04 * w)
    keep = np.ones((h, w), bool)
    keep[max(0, top - pad):min(h, base + pad), max(0, x0 - pad):min(w, x1 + pad)] = False
    a = tone_match(a, np.median(a[keep].astype(np.float32), axis=0))
    a = lift_shadows(a)
    # extend the photo's own backdrop outward by 35% on every side (each new row/column continues the
    # mean of the photo's outer 40 px there, plus matching grain), so the panel is filled with the
    # photo's backdrop tone and the feathered edge falls outside the panel. Mirroring is not used: it
    # can reflect tyres or bumpers back into view when a crop is tight.
    py, px = int(0.35 * h), int(0.35 * w)
    a = np.pad(a, ((py, py), (px, px), (0, 0)), mode="mean", stat_length=((40, 40), (40, 40), (1, 1)))
    grain = np.random.default_rng(3).normal(0, 1.5, a.shape).astype(np.float32)
    inner = np.zeros(a.shape[:2], bool); inner[py:py + h, px:px + w] = True
    a = np.where(inner[..., None], a, a + grain)
    x0, x1, top, base = x0 + px, x1 + px, top + py, base + py
    base_img = Image.fromarray(np.clip(a + .5, 0, 255).astype(np.uint8))
    pw, ph = panel[2] - panel[0], panel[3] - panel[1]
    share, base_frac = FIT[kind]
    tw, tcx, tbase = round(share * pw), pw / 2, round(base_frac * ph)
    s = tw / (x1 - x0 + 1)
    dx = dy = 0.0
    for it in range(6):
        tile, ox, oy = _render(base_img, s, (x0 + x1) / 2, base, pw, ph, base_frac, dx, dy)
        t = np.asarray(tile)[INSET:ph - INSET, INSET:pw - INSET]
        mx0, _, mx1, mb = detect(t)
        mw, mcx, mbase = mx1 - mx0 + 1, (mx0 + mx1) / 2 + INSET, mb + INSET
        err = (mw - tw, mcx - tcx, mbase - tbase)
        if abs(err[0]) <= 1 and abs(err[1]) <= 1 and abs(err[2]) <= 1:
            break
        s *= tw / mw
        dx -= err[1]
        dy -= err[2]
    return tile, dict(scale=round(s, 4), offset=[ox, oy], passes=it + 1, residual_px=[round(e, 1) for e in err])


def load_logo(path):
    """Size each logo to the same ink area (LOGO_INK), so a thin pony and a solid crest carry about the
    same visual weight, within the LOGO_H height limits."""
    im = Image.open(path).convert("RGBA")
    im = im.crop(im.getbbox())
    ref = np.asarray(im.resize((max(1, round(im.width * 300 / im.height)), 300)))[..., 3]
    ink = max(1, int((ref > 128).sum()))
    height = int(np.clip(round(300 * (LOGO_INK / ink) ** 0.5), *LOGO_H))
    return im.resize((round(im.width * height / im.height), height), Image.LANCZOS)


# ---------- the poster ----------
def compose(slug):
    c = car(slug)
    check_specs_md(c)
    art = c["art"]
    img = Image.new("RGB", (W, H), BG)

    hero_src = Image.open(ROOT / art["hero"]).convert("RGB")
    if art.get("hero_from_poster"):
        a = np.asarray(hero_src)
        y0, y1 = hero_band(a)
        hero_src = hero_src.crop((0, y0, hero_src.width, y1))
    placed = {}
    for kind, panel, src in (("hero", HERO, hero_src),
                             ("front", FRONT, Image.open(ROOT / art["front"])),
                             ("rear", REAR, Image.open(ROOT / art["rear"]))):
        tile, info = fit_into_panel(src, panel, kind)
        img.paste(tile, panel[:2])
        placed[kind] = info
    d = ImageDraw.Draw(img)
    for p in (HERO, FRONT, REAR):
        d.rectangle(p, outline=FRAME, width=FRAME_W)
    draw_furniture(img, c)
    pdir = PRINT / "16x20" if SIZE_16X20 else PRINT
    pdir.mkdir(parents=True, exist_ok=True)
    out = pdir / f"{slug}.png"
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()  # labs assume sRGB; say so
    img.save(out, optimize=True, dpi=(240, 240) if SIZE_16X20 else (300, 300), icc_profile=icc)
    if not SIZE_16X20:
        save_preview(img, OUT / f"{slug}.jpg")
    return out, placed


def save_preview(img, path, long_edge=2400):
    """Web-size JPEG for the README; the print PNG stays in posters/print/."""
    s = long_edge / max(img.size)
    img.convert("RGB").resize((round(img.width * s), round(img.height * s)), Image.LANCZOS).save(
        path, quality=88, optimize=True, progressive=True)


def draw_furniture(img, c):
    """Everything that is not a car photo: No., logo, name block, spec strip, speed bar."""
    slug = c["slug"]
    d = ImageDraw.Draw(img)
    # No. and logo
    fno = font(74, 560)
    draw_text(d, ink_x(TEXT_X, "N", fno), Y_NO, f"No. {c['number']}", fno)
    lp = ROOT / c["logo_final"]
    if not lp.exists():  # try the other extension, else leave the corner empty and say so
        alt = [q for q in lp.parent.glob(lp.stem + ".*")]
        lp = alt[0] if alt else None
    if lp:
        logo = load_logo(lp)
        img.paste(logo, (LOGO_BOX[0] - logo.width, LOGO_BOX[1] - logo.height // 2), logo)
    else:
        print(f"WARNING {slug}: no logo file for {c['logo_final']}; top-right left empty", file=sys.stderr)

    # name block
    fh, fs = font(HEAD_SIZE, 800, 100), font(96, 560, 108)
    draw_text(d, ink_x(TEXT_X, c["title"], fh), Y_HEAD, c["title"], fh, tracking=-0.01)
    draw_text(d, ink_x(TEXT_X, c["maker_line"], fs), Y_SUB, c["maker_line"], fs, tracking=0.18)

    # spec strip: small tracked-caps labels over large bold values; the engine column is wider
    d.rectangle([TEXT_X, Y_RULE, W - TEXT_X, Y_RULE + 3], fill=INK)
    lab, val = font(LABEL_SIZE, 640, 100), font(VALUE_SIZE, 720, VALUE_WDTH)
    s = c["specs"]
    edges = col_edges()
    for i, (k, v) in enumerate([("ENGINE", s["engine"]), ("POWER", s["power"]), ("0–60", s["zero_sixty"])]):
        x = edges[i] + (CELL_PAD if i else 0)
        draw_text(d, x, Y_LABEL, k, lab, tracking=0.16)
        draw_text(d, x, Y_VALUE, v, val, tracking=0.01)
        if i:
            x = int(edges[i])
            d.rectangle([x - 1, Y_DIV[0], x + 1, Y_DIV[1]], fill=INK)

    # TOP SPEED bar, 0-300 mph; x0..x1 are the outer ends marked by the 0 and 300 ticks
    x0, x1 = TEXT_X, W - TEXT_X
    fill = tuple(int(c["bar_color"][i:i + 2], 16) for i in (1, 3, 5))
    xf = x0 + (x1 - x0) * c["top_speed"] / 300.0
    d.rectangle([x0, Y_BAR[0], x1, Y_BAR[1]], fill=TRACK)
    d.rectangle([x0, Y_BAR[0], int(round(xf)) - 1, Y_BAR[1]], fill=fill)
    d.rectangle([x0, Y_BAR[0], x1, Y_BAR[1]], outline=INK, width=4)
    # the number sits in the grey track right where the colour stops: same contrast on every poster
    cap = val.getbbox("H", anchor="ls")
    ty = (Y_BAR[0] + Y_BAR[1]) / 2 - (cap[1] + cap[3]) / 2
    tx = xf + CELL_PAD
    if tx + text_w(d, s["top_speed"], val, 0.01) > x1 - CELL_PAD:
        sys.exit(f"{slug}: '{s['top_speed']}' does not fit in the track after the fill")
    draw_text(d, tx, ty, s["top_speed"], val, tracking=0.01)
    tl = font(72, 520, 100)
    for k in range(4):
        x = x0 + (x1 - x0) * k / 3
        d.rectangle([int(round(x)) - 2, Y_BAR[1], int(round(x)) + 2, Y_BAR[1] + TICK_LEN], fill=INK)
        draw_text(d, x, Y_TICKLABEL, str(k * 100), tl, align="center")


def measure(path, c):
    """Re-detect each car inside its panel on the saved poster, and the bar fill."""
    a = np.asarray(Image.open(path).convert("RGB"))
    res = {}
    for kind, p in (("hero", HERO), ("front", FRONT), ("rear", REAR)):
        inner = a[p[1] + FRAME_W + 2: p[3] - FRAME_W - 2, p[0] + FRAME_W + 2: p[2] - FRAME_W - 2]
        bx0, btop, bx1, bbase = detect(inner)
        o = (p[0] + FRAME_W + 2, p[1] + FRAME_W + 2)
        res[kind] = dict(x0=bx0 + o[0], x1=bx1 + o[0], top=btop + o[1], baseline=bbase + o[1],
                         width=bx1 - bx0 + 1, cx=round((bx0 + bx1) / 2 + o[0], 1))
    sys.path.insert(0, str(HERE))
    from measure_bar import measure as mbar
    info, _ = mbar(a)
    res["bar"] = dict(measured_mph=info["measured_mph"], printed_mph=c["top_speed"],
                      diff=round(info["measured_mph"] - c["top_speed"], 2))
    return res


def _sizes():
    """One headline size and one spec-value size for every poster (bonus F40 included)."""
    allc = cars()
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    head = 560
    while max(text_w(d, c["title"], font(head, 800), -0.01) for c in allc) > W - 2 * TEXT_X:
        head -= 10
    wdth, val = 78, 160
    span = W - 2 * TEXT_X
    def fits(v):
        for c in allc:
            s = c["specs"]
            for txt, f in zip([s["engine"], s["power"], s["zero_sixty"]], COLS):
                if text_w(d, txt, font(v, 720, wdth), 0.01) > f * span - 2 * CELL_PAD:
                    return False
        return True
    while not fits(val):
        val -= 2
    return head, val, wdth


HEAD_SIZE, VALUE_SIZE, VALUE_WDTH = _sizes()

if __name__ == "__main__":
    mfile = OUT / ("measurements-16x20.json" if SIZE_16X20 else "measurements.json")
    allm = json.loads(mfile.read_text()) if mfile.exists() else {}
    for slug in [a for a in sys.argv[1:] if not a.startswith("--")]:
        c = car(slug)
        out, placed = compose(slug)
        m = measure(out, c)
        m["placement"] = placed
        allm[slug] = m
        print(json.dumps({slug: m}))
    mfile.write_text(json.dumps(allm, indent=1) + "\n")
