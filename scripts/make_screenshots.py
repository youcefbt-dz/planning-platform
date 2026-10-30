"""Capture the landing-page screenshots from the demo workspaces (needs the dev server running).

    flask run --port 5055 &   then   python scripts/make_screenshots.py [http://localhost:5055]

Writes app/static/img/shots/{overview,goal,roadmap}-{ar,en,fr}.png. Re-run after any visual change
or after changing brand.yaml, so the landing page always shows the real product.
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5055"
OUT = Path(__file__).resolve().parents[1] / "app" / "static" / "img" / "shots"
SLUG = {"ar": "demo", "en": "demo-en", "fr": "demo-fr"}
EXE = "/opt/pw-browsers/chromium"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE)
    OUT.mkdir(parents=True, exist_ok=True)
    for lang, slug in SLUG.items():
        pg = b.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=1.5)
        base = f"{BASE}/app/{slug}"
        pg.goto(f"{base}/goals/?lang={lang}")
        ids = re.findall(rf"/app/{slug}/goals/(\d+)\"", pg.content())
        pages = {"overview": f"{base}/?lang={lang}", "roadmap": f"{base}/initiatives/roadmap?lang={lang}",
                 "goal": f"{base}/goals/{ids[0]}?lang={lang}" if ids else f"{base}/goals/?lang={lang}"}
        for name, url in pages.items():
            pg.goto(url)
            pg.wait_for_timeout(500)
            pg.screenshot(path=str(OUT / f"{name}-{lang}.png"))
            print("wrote", name, lang)
        pg.close()
    b.close()
