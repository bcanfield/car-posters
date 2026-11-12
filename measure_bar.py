"""Measure the TOP SPEED bar on a finished poster, independently of the code that drew it.

What a viewer reads is the fill end against the printed 0 and 300 ticks, so that is what this
measures: it finds the bar (the long two-colour horizontal band in the bottom 30%), the dark tick
marks hanging under it, and the fill/track boundary on the bar's middle rows, then reports
value = (fill_end - tick_0) / (tick_300 - tick_0) * 300.

Run: uv run measure_bar.py POSTER.png EXPECTED_MPH [--crop OUT.png]
Exit 0 if |measured - expected| <= 1 mph, 1 if not, 2 if the bar or ticks cannot be found.
"""
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow"]
# ///
import argparse, json, sys
import numpy as np
from PIL import Image, ImageDraw


def lum(a):
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def runs(mask):
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    out, s, p = [], idx[0], idx[0]
    for i in idx[1:]:
        if i != p + 1:
            out.append((s, p)); s = i
        p = i
    out.append((s, p))
    return out


def measure(a):
    H, W, _ = a.shape
    top = int(H * 0.70)
    reg = a[top:].astype(np.float32)
    bg = np.median(reg.reshape(-1, 3), axis=0)
    off = np.sqrt(((reg - bg) ** 2).sum(-1)) > 30
    # bar rows: a single run of non-backdrop pixels spanning >= 50% of the width
    rows = []
    for y in range(reg.shape[0]):
        rr = runs(off[y])
        if rr:
            s, e = max(rr, key=lambda r: r[1] - r[0])
            if e - s >= 0.5 * W:
                rows.append((y + top, s, e))
    if not rows:
        raise ValueError("no bar found")
    # take the thickest contiguous band whose two ends differ in colour (fill vs track)
    bands, cur = [], [rows[0]]
    for r in rows[1:]:
        if r[0] == cur[-1][0] + 1:
            cur.append(r)
        else:
            bands.append(cur); cur = [r]
    bands.append(cur)
    best = None
    for b in bands:
        y0, y1 = b[0][0], b[-1][0]
        x0 = int(np.median([r[1] for r in b])); x1 = int(np.median([r[2] for r in b]))
        ym = (y0 + y1) // 2
        L = x1 - x0
        left = a[ym, x0 + int(.03 * L): x0 + int(.06 * L)].astype(np.float32).mean(0)
        right = a[ym, x1 - int(.06 * L): x1 - int(.03 * L)].astype(np.float32).mean(0)
        if np.linalg.norm(left - right) > 25 and (best is None or len(b) > best[4]):
            best = (y0, y1, x0, x1, len(b), left, right)
    if best is None:
        raise ValueError("no two-colour bar found")
    y0, y1, x0, x1, _, fill_c, track_c = best
    # fill end on the middle third of the bar's rows: last column closer to the fill colour
    core = a[y0 + (y1 - y0) // 3: y1 - (y1 - y0) // 3 + 1, x0:x1 + 1].astype(np.float32).mean(0)
    isfill = np.linalg.norm(core - fill_c, axis=1) < np.linalg.norm(core - track_c, axis=1)
    fr = [r for r in runs(isfill) if r[0] <= 0.1 * (x1 - x0)]
    if not fr:
        raise ValueError("fill does not start at the left end")
    s0, e0 = max(fr, key=lambda r: r[1] - r[0])  # longest: ignores 1-px anti-aliased edge pixels
    fill_end = x0 + e0 + 0.5
    # ticks: thin dark vertical marks starting within a few px below the bar
    below = lum(a[y1 + 1: y1 + 1 + int(0.03 * H)].astype(np.float32)) < lum(bg) - 60
    cols = np.array([below[:6, x].any() and below[:, x].sum() >= max(6, int(0.004 * H)) for x in range(W)])
    ticks = [(s + e) / 2 for s, e in runs(cols) if e - s < 0.01 * W and x0 - 30 <= (s + e) / 2 <= x1 + 30]
    if len(ticks) < 2:
        raise ValueError(f"ticks not found ({len(ticks)})")
    t0, t300 = ticks[0], ticks[-1]
    value = (fill_end - t0) / (t300 - t0) * 300
    return dict(bar_rows=[int(y0), int(y1)], track=[int(x0), int(x1)], ticks=[round(t, 1) for t in ticks],
                fill_end_x=round(float(fill_end), 1), measured_mph=round(float(value), 1)), (y0, y1, fill_end, ticks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("poster"); ap.add_argument("expected", type=float); ap.add_argument("--crop")
    a = ap.parse_args()
    img = Image.open(a.poster).convert("RGB")
    try:
        info, (y0, y1, fe, ticks) = measure(np.asarray(img))
    except ValueError as e:
        print(json.dumps({"poster": a.poster, "error": str(e)})); sys.exit(2)
    info.update(poster=a.poster, expected_mph=a.expected, diff_mph=round(info["measured_mph"] - a.expected, 2))
    info["ok"] = abs(info["diff_mph"]) <= 1.0
    if a.crop:
        d = img.copy(); dr = ImageDraw.Draw(d)
        dr.line([fe, y0 - 40, fe, y1 + 40], fill=(0, 120, 255), width=2)
        for t in ticks:
            dr.line([t, y1 + 2, t, y1 + 60], fill=(0, 200, 0), width=1)
        d.crop((0, y0 - 140, img.width, min(img.height, y1 + 200))).save(a.crop)
    print(json.dumps(info))
    sys.exit(0 if info["ok"] else 1)


if __name__ == "__main__":
    main()
