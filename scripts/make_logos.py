"""Generate the PLACEHOLDER logos from config/brand.yaml (name + colors).

Outputs to app/static/brand/:
  logo-full-on-light.svg / logo-full-on-dark.svg      (symbol + Latin wordmark)
  logo-full-ar-on-light.svg / logo-full-ar-on-dark.svg (symbol + Arabic wordmark)
  logo-mark-on-light.svg / logo-mark-on-dark.svg       (symbol only)
  favicon.svg

Text is converted to outlines (HarfBuzz shaping + fontTools), so the SVGs need no font at runtime.
When you design your own logo, just drop your files next to these using the names in brand.yaml.

    python scripts/make_logos.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import uharfbuzz as hb
import yaml
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "static" / "brand"
FONTS = ROOT / "app" / "static" / "fonts"


def load(path: Path):
    f = TTFont(path)
    f.flavor = None
    buf = io.BytesIO()
    f.save(buf)
    data = buf.getvalue()
    return TTFont(io.BytesIO(data)), hb.Font(hb.Face(data))


def outline(text: str, font_file: Path, size: float, rtl: bool = False):
    """Return (svg_path_d, width, ascent_px) for `text`, baseline at y=0, y pointing down."""
    tt, hbfont = load(font_file)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hbfont, buf, {"kern": True, "liga": True})
    upm = tt["head"].unitsPerEm
    s = size / upm
    gs = tt.getGlyphSet()
    order = tt.getGlyphOrder()
    pen_d = []
    x = 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        name = order[info.codepoint]
        pen = SVGPathPen(gs)
        tp = TransformPen(pen, (s, 0, 0, -s, (x + pos.x_offset) * s, -pos.y_offset * s))
        gs[name].draw(tp)
        pen_d.append(pen.getCommands())
        x += pos.x_advance
    return " ".join(d for d in pen_d if d), x * s


def symbol(ink: str, accent: str, primary: str, size: int = 56):
    """Orbit mark: strategic core + execution orbits + measurable initiative node."""
    u = size / 56
    cx = cy = 28 * u
    out = [
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="24" ry="11" transform="rotate(24 {cx:.2f} {cy:.2f})" fill="none" stroke="{primary}" stroke-width="4.2" stroke-linecap="round"/>',
        f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="24" ry="11" transform="rotate(-24 {cx:.2f} {cy:.2f})" fill="none" stroke="{primary}" stroke-width="4.2" stroke-linecap="round"/>',
        f'<path d="M28 13 L43 28 L28 43 L13 28 Z" fill="{ink}"/>',
        f'<path d="M28 19 L37 28 L28 37 L19 28 Z" fill="{primary}"/>',
        f'<circle cx="48" cy="17" r="4.2" fill="{accent}"/>',
    ]
    return ''.join(out)


def build(kind: str, tone: str, name: str, lang: str, cfg: dict) -> str:
    c = cfg["colors"]
    on_light = tone == "on_light"
    text_col = c["ink"] if on_light else "#FFFFFF"
    primary = c["primary"] if on_light else "#FFFFFF"
    accent = c["accent"]
    H = 56
    sym = symbol(text_col, accent, primary, H)
    if kind == "mark":
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {H} {H}" width="{H}" height="{H}" role="img" aria-label="{name}">{sym}</svg>\n'
    if lang == "ar":
        d, w = outline(name, FONTS / "ibm-plex-sans-arabic-arabic-700-normal.woff2", 30, rtl=True)
        base = 42
        gap = 10
        total = H + gap + w
        # RTL reading order: wordmark on the right, symbol on the left is fine for a logo lock-up.
        txt = f'<path transform="translate({H+gap:.2f} {base})" d="{d}" fill="{text_col}"/>'
    else:
        d, w = outline(name, FONTS / "arimo-latin-700-normal.woff2", 30)
        base = 41
        gap = 10
        total = H + gap + w
        txt = f'<path transform="translate({H+gap:.2f} {base})" d="{d}" fill="{text_col}"/>'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total:.1f} {H}" width="{total:.1f}" height="{H}" role="img" aria-label="{name}">'
        f"{sym}{txt}</svg>\n"
    )


def main():
    cfg = yaml.safe_load((ROOT / "config" / "brand.yaml").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    names = cfg["name"]
    for tone in ("on_light", "on_dark"):
        t = tone.replace("_", "-")
        (OUT / f"logo-full-{t}.svg").write_text(build("full", tone, names["en"], "en", cfg), encoding="utf-8")
        (OUT / f"logo-full-ar-{t}.svg").write_text(build("full", tone, names["ar"], "ar", cfg), encoding="utf-8")
        (OUT / f"logo-mark-{t}.svg").write_text(build("mark", tone, names["en"], "en", cfg), encoding="utf-8")
    # favicon: the mark on a rounded tile so it reads on any tab color
    c = cfg["colors"]
    fav = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><rect width="48" height="48" rx="11" fill="%s"/>'
        '<g transform="translate(4 4)">%s</g></svg>\n' % (c["ink"], symbol("#fff", c["accent"], "#FFFFFF", 40))
    )
    (OUT / "favicon.svg").write_text(fav, encoding="utf-8")
    print("wrote", *sorted(p.name for p in OUT.glob("*.svg")))


if __name__ == "__main__":
    sys.exit(main())
