"""Generate poster ART candidates for one car with gpt-image-2 images.edit.

Art-only method: the AI draws only the hero profile and the front/rear view
boxes in the top ~58% and leaves the bottom ~42% and the top corners as empty backdrop. It writes no
text and draws no logo.
compose.py upscales the pick and sets all text, the spec strip and the speed bar in code.
Inputs sent to the model: assets/style-reference.png (an earlier approved poster with the number,
name block, spec strip, bar and logo painted out), 2-4 real reference photos of the exact car
(side/front/rear/front34.jpg from <refs_dir>, see refs/credits.json). No logo is sent or drawn; the
real logo file from logos/ is placed by compose.py.
Output: work/<slug>/candidates/<slug>-aNN.png (or work/<slug>/views/<slug>-<view>-aNN.png with
--view) plus one JSON line per attempt in work/<slug>/log.jsonl (size used, token usage, estimated
cost).

Run: uv run generate.py <slug> <attempts> [--view side|front|rear] [--dry-run]
The key is read from OPENAI_API_KEY or from .env and never printed.
"""
# /// script
# requires-python = ">=3.11"
# dependencies = ["openai"]
# ///
import argparse, base64, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
STYLE_REF = ROOT / "assets/style-reference.png"  # an approved poster with all text, the bar and the logo painted out
MODEL = "gpt-image-2"
SIZE = "2304x3072"  # 3:4. 2880x3840 tried 2026-11-11: 400 "exceeds the current pixel budget"
BUDGET_USD = 45.0  # stop once the estimated spend in work/*/log.jsonl would pass this
# Estimate only: per-1M-token rates assumed for gpt-image-2 (check current pricing).
RATE = {"text_in": 5.0, "image_in": 8.0, "image_out": 30.0}
FALLBACK_COST = 0.60  # per image, used when the response carries no usage block
BACKDROP = ("one seamless, perfectly even light warm-grey studio backdrop (about #DBD3CB), identical to the "
            "attached style-reference poster, with no visible floor edge, no horizon line and no vignette")


def load_key():
    if os.environ.get("OPENAI_API_KEY"):
        return
    env = ROOT / ".env"
    for line in (env.read_text().splitlines() if env.exists() else []):
        if line.startswith("OPENAI_API_KEY="):
            os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip("\"'")
            return
    sys.exit("OPENAI_API_KEY is not set and not found in .env")


def car_entry(slug):
    cars = json.loads((ROOT / "cars.json").read_text())["cars"]
    for c in cars:
        if c["slug"] == slug:
            return c
    sys.exit(f"unknown slug {slug}; known: {[c['slug'] for c in cars]}")


def prompt_for(c):
    """Art only: the AI draws only the photographs; compose.py sets every word, the logo and the bar."""
    return (
        f"Make a new poster artwork in exactly the same design as the first attached image (the style reference), "
        f"but for the {c['car']}. Portrait 3:4. Keep the photographic style, framing, spacing, box style and backdrop of the "
        f"style reference; change only the car. Everything sits on {BACKDROP}. "
        f"No logo, emblem or graphic anywhere off the car: the top-right and top-left corners are plain empty backdrop, "
        f"exactly like the style reference. Top 58% of the poster only: a large hero studio photograph of the car in pure side profile "
        f"facing right, camera at wheel-axle height with a long lens, the car spanning about 88% of the width; below it two "
        f"thin-framed boxes side by side at the same lighting and scale, a dead-on front view and a dead-on rear view of the "
        f"same car, exactly like the style reference; the bottom edge of the two boxes must sit no lower than 60% of the "
        f"poster height. The bottom 42% of the poster must be completely EMPTY: only the same "
        f"warm-grey backdrop continuing smoothly to the bottom edge, exactly like the empty lower part of the style reference, "
        f"with no text, no numbers, no lines, no rules, no bars, no boxes, no shadows and no objects. Do not write any text "
        f"anywhere on the poster: no title, no 'No.' number, no captions, no labels; the only lettering allowed is the "
        f"badges physically on the car. The photographs are real-looking studio photos of the {c['car']} in {c['colors']}, "
        f"matching the attached reference photos exactly ({c['details']}). Softbox lighting, real paint reflections, "
        f"natural colour, neutral grade. No HDR, no teal-orange grade, no fog, no sparks, no neon, no wet surface, no lens "
        f"flare, no people, no licence plate text."
    )


VIEW_SIZE = {"side": "3072x1408", "front": "2048x1232", "rear": "2048x1232"}  # panel aspect ratios
VIEW_REFS = {"side": ("side", "front34", "rear"), "front": ("front", "front34", "side"), "rear": ("rear", "side", "front34")}


def view_prompt(c, view):
    """One view per image, for compose.py's fixed panels. No text, no logo, no frame."""
    what = {"side": "an exact side elevation (pure side profile), car facing right, camera at wheel-axle height with a "
                    "long lens so there is no perspective distortion; the car spans about 80% of the image width",
            "front": "a dead-on front elevation, camera exactly in front at the car's centre height with a long lens so it "
                     "reads as an orthographic front view, perfectly symmetrical; the car spans about 70% of the image width",
            "rear": "a dead-on rear elevation, camera exactly behind the car at its centre height with a long lens so it "
                    "reads as an orthographic rear view, perfectly symmetrical; the car spans about 70% of the image width"}[view]
    bg = f"on {BACKDROP}, with only a soft natural contact shadow directly under the tyres"
    return (
        f"A single real-looking studio photograph of the {c['car']} in {c['colors']}: {what}, centred, with the whole car "
        f"in frame and generous empty space on every side. Shot {bg}. Match the photographic style, lighting and colour of "
        f"the car photographs in the first attached image (the style reference) and match the attached reference photos of "
        f"the car exactly ({c['details']}). The image is one photograph only: no border, no frame, no box, no text, no "
        f"numbers, no logo, no caption; the only lettering allowed is the badges physically on the car. Softbox lighting, "
        f"real paint reflections, natural colour, neutral grade. No HDR, no teal-orange grade, no fog, no sparks, no neon, "
        f"no wet surface, no lens flare, no people, no licence plate text."
    )


def ref_files(c):
    d = ROOT / c["refs_dir"]
    photos = [d / f"{k}.jpg" for k in ("side", "front", "rear", "front34") if (d / f"{k}.jpg").exists()]
    if len(photos) < 2:
        sys.exit(f"{c['slug']}: need at least 2 reference photos in {d} (side/front/rear/front34.jpg)")
    return [STYLE_REF] + photos[:4]  # no logo: compose.py places the real logo file


def spent_so_far():
    total = 0.0
    for log in WORK.glob("*/log.jsonl"):
        for line in log.read_text().splitlines():
            total += json.loads(line).get("est_usd", 0.0)
    return total


def estimate(usage):
    if not usage:
        return FALLBACK_COST
    u = usage if isinstance(usage, dict) else usage.model_dump()
    det = u.get("input_tokens_details") or {}
    return (det.get("text_tokens", 0) * RATE["text_in"] + det.get("image_tokens", 0) * RATE["image_in"]
            + u.get("output_tokens", 0) * RATE["image_out"]) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug"); ap.add_argument("attempts", type=int)
    ap.add_argument("--view", choices=["side", "front", "rear"], help="one view per image (panel method)")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--size", help="override the image size, e.g. 2304x3072")
    ap.add_argument("--out-dir", help="override output folder (repo-relative)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    c = car_entry(a.slug)
    if a.view:
        d = ROOT / c["refs_dir"]
        refs = [STYLE_REF] + [d / f"{k}.jpg" for k in VIEW_REFS[a.view] if (d / f"{k}.jpg").exists()]
        prompt, size = view_prompt(c, a.view), a.size or VIEW_SIZE[a.view]
        stem = f"{a.slug}-{a.view}"
        out_dir = ROOT / a.out_dir if a.out_dir else WORK / a.slug / "views"
    else:
        refs, prompt, size, stem = ref_files(c), prompt_for(c), SIZE, a.slug
        out_dir = ROOT / a.out_dir if a.out_dir else WORK / a.slug / "candidates"
    if a.dry_run:
        print(json.dumps({"refs": [str(r.relative_to(ROOT)) for r in refs], "prompt": prompt,
                          "spent_so_far_usd": round(spent_so_far(), 2)}, indent=1, ensure_ascii=False))
        return
    load_key()
    from openai import OpenAI
    client = OpenAI()
    out_dir.mkdir(parents=True, exist_ok=True)
    log = WORK / a.slug / "log.jsonl"
    n0 = len(list(out_dir.glob(f"{stem}-a*.png")))
    for i in range(n0 + 1, n0 + a.attempts + 1):
        if spent_so_far() + FALLBACK_COST > BUDGET_USD:
            sys.exit(f"budget stop: estimated spend {spent_so_far():.2f} USD of {BUDGET_USD}")
        fs = [open(r, "rb") for r in refs]
        t = time.time()
        try:
            r = client.images.edit(model=a.model, image=fs, prompt=prompt, size=size, quality="high", n=1)
        except Exception as e:
            sys.exit(f"{a.slug} a{i:02d} {size} failed: {str(e)[:200]}")
        finally:
            for f in fs:
                f.close()
        out = out_dir / f"{stem}-a{i:02d}.png"
        out.write_bytes(base64.b64decode(r.data[0].b64_json))
        usage = getattr(r, "usage", None)
        rec = {"file": str(out.relative_to(ROOT)), "size": size, "model": a.model, "secs": round(time.time() - t),
               "usage": usage.model_dump() if usage else None, "est_usd": round(estimate(usage), 3)}
        with log.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"{a.slug} a{i:02d} ok {size} ~${rec['est_usd']}")
    print(f"estimated spend so far: {spent_so_far():.2f} USD")


if __name__ == "__main__":
    main()
