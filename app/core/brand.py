"""Brand layer — name, logos, colors, fonts, all read from config/brand.yaml.

Nothing else in the code base hard-codes the product name or a logo path.
Templates use:  brand.name   {{ logo('full', 'on_light') }}   {{ brand_css() }}
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from flask import current_app, url_for
from markupsafe import Markup, escape

ROOT = Path(__file__).resolve().parents[2]
BRAND_FILE = ROOT / "config" / "brand.yaml"

_DEFAULTS = {
    "placeholder": True,
    "name": {"ar": "المنتج"},
    "name_short": {},
    "domain": "example.com",
    "logos": {"full": {}, "mark": {}, "favicon": "logo.png", "height": {"full": 56, "mark": 56}},
    "colors": {
        "primary": "#5864FF",
        "primary_text": "#4652EA",
        "ink": "#162447",
        "body": "#5B657E",
        "accent": "#FDD446",
        "tint": "#F3F5FF",
    },
    "fonts": {"heading": "Arimo", "body": "Open Sans", "arabic": "IBM Plex Sans Arabic"},
    "social": {},
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Brand:
    """Read-only view over brand.yaml with per-language helpers."""

    def __init__(self, data: dict | None = None, path: Path = BRAND_FILE):
        if data is None:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.data = _merge(_DEFAULTS, data)
        self.static_dir = ROOT / "app" / "static" / "brand"

    # -- identity ---------------------------------------------------------
    @property
    def placeholder(self) -> bool:
        return bool(self.data["placeholder"])

    @property
    def domain(self) -> str:
        return self.data["domain"]

    @property
    def colors(self) -> dict:
        return self.data["colors"]

    @property
    def fonts(self) -> dict:
        return self.data["fonts"]

    @property
    def social(self) -> dict:
        return {k: v for k, v in self.data["social"].items() if v}

    def name_for(self, lang: str) -> str:
        names = self.data["name"]
        return names.get(lang) or names.get("ar") or next(iter(names.values()))

    def short_for(self, lang: str) -> str:
        names = self.data["name_short"] or {}
        return names.get(lang) or self.name_for(lang)

    # -- logos ------------------------------------------------------------
    def logo_file(self, kind: str, tone: str, lang: str) -> str | None:
        """Resolve a logo file. Per-language override > default; None if the file is absent."""
        entry = self.data["logos"].get(kind) or {}
        candidates = []
        lang_entry = entry.get(lang)
        if isinstance(lang_entry, dict):
            candidates.append(lang_entry.get(tone))
        candidates.append(entry.get(tone))
        for name in candidates:
            if name and (self.static_dir / name).is_file():
                return name
        return None

    def logo_height(self, kind: str) -> int:
        return int((self.data["logos"].get("height") or {}).get(kind, 32))

    def favicon(self) -> str | None:
        name = self.data["logos"].get("favicon")
        return name if name and (self.static_dir / name).is_file() else None

    # -- css --------------------------------------------------------------
    def css_vars(self) -> str:
        c = self.colors
        f = self.fonts
        ar = f["arabic"]
        pairs = {
            "--brand-primary": c["primary"],
            "--brand-primary-text": c["primary_text"],
            "--brand-ink": c["ink"],
            "--brand-body": c["body"],
            "--brand-accent": c["accent"],
            "--brand-tint": c["tint"],
            "--font-heading": f"'{f['heading']}', '{ar}', system-ui, sans-serif",
            "--font-body": f"'{f['body']}', '{ar}', system-ui, sans-serif",
        }
        return ":root{" + ";".join(f"{k}:{v}" for k, v in pairs.items()) + "}"


def get_brand() -> Brand:
    return current_app.extensions["brand"]


def _wordmark(name: str) -> Markup:
    """"PlanWise" -> Plan + Wise (two weights). A name without an inner capital stays one piece."""
    m = re.match(r"^([A-Za-z][a-z]+)([A-Z][A-Za-z]+)$", name)
    if not m:
        return Markup(escape(name))
    return Markup(f'<span class="lk-a">{escape(m.group(1))}</span><span class="lk-b">{escape(m.group(2))}</span>')


def logo_html(kind: str = "full", tone: str = "on_light", lang: str = "ar", cls: str = "") -> Markup:
    """The mark (a PNG) next to the product name. The name is real Latin text in every language, never translated:
    the lockup is always left-to-right, even on an Arabic page. `tone` picks the white or the blue mark and the text colour."""
    brand = get_brand()
    file = brand.logo_file(kind, tone, lang)
    name = brand.name_for(lang)
    tone_cls = "is-dark" if tone == "on_dark" else "is-light"
    if not file:
        return Markup(f'<span class="logo-lockup {tone_cls} {escape(cls)}" dir="ltr" aria-label="{escape(name)}"><span class="logo-lockup__text">{_wordmark(name)}</span></span>')

    src = url_for("static", filename=f"brand/{file}")
    if kind == "full":
        return Markup(
            f'<span class="logo-lockup {tone_cls} {escape(cls)}" dir="ltr" aria-label="{escape(name)}">'
            f'<img class="logo-lockup__mark" src="{src}" alt="" height="{brand.logo_height("full")}">'
            f'<span class="logo-lockup__text" aria-hidden="true">{_wordmark(name)}</span></span>'
        )
    return Markup(f'<img class="logo logo-mark {tone_cls} {escape(cls)}" src="{src}" alt="{escape(name)}" height="{brand.logo_height("mark")}">')
