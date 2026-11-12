# Car posters

Photoreal car posters: gpt-image-2 draws the car photos, Python sets everything else. See README.md for the layout.

## Rules

- The image model draws only car photographs. Text, numbers, logos, frames and the speed bar are drawn by `compose.py`. Don't put any of them in a prompt.
- Spec values live in `cars.json` and must match the table in `specs.md`; `compose.py` exits if they differ. Check new numbers against a manufacturer source and record it in `specs.md`.
- Use real logo files only (`logos/`, sources in `logos/SOURCES.md`). Don't draw, trace or recolour a logo.
- Never read out, print or commit `.env`. `generate.py` reads the key itself.
- Python runs through `uv run <script>`; dependencies are declared inline in each script.

## Making a poster

1. Add the car to `cars.json` and `specs.md`. Put 2-4 reference photos (`side.jpg`, `front.jpg`, `rear.jpg`, `front34.jpg`) in its `refs_dir` and list their source and licence in `credits.json` next to them.
2. Run `uv run generate.py <slug> 1 --dry-run` and read the prompt before spending anything. Real runs cost roughly $0.53 per whole-poster candidate and $0.24 per view, and stop at `BUDGET_USD`. Ask before generating.
3. Generate whole-poster candidates (for the hero profile) and `--view front` / `--view rear` images. Look at them at full size against the reference photos: wheels, lights, proportions, badges. Let the user pick.
4. Point the car's `art` entry at the picks and run `uv run compose.py <slug>`. Check the printed measurements: car widths and baselines should match the other posters within 2 px, and the bar within 1 mph (`measure_bar.py`).
5. Rebuild the contact sheet with `uv run contact_sheet.py` if one of 01-06 changed.
