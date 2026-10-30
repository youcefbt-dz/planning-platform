"""Internationalisation — Arabic only (RTL), kept key-based so another language can be added later by adding LANGS + <lang>.yaml files.

Catalogs are YAML, nested, flattened to dotted keys:
  app/i18n/<lang>.yaml                      -> keys as written          (core)
  app/site/i18n/<lang>.yaml                 -> prefixed  "site."
  app/modules/<id>/i18n/<lang>.yaml         -> prefixed  "<id>."

A value is either a string, or a plural table (zero/one/two/few/many/other),
used through tn(key, n). Arabic uses the full CLDR set via Babel.
Fallback chain: requested lang -> default lang -> the key itself (and the miss is logged).
"""
from __future__ import annotations

import logging
import string
from pathlib import Path

import yaml
from babel import Locale
from flask import current_app, g, has_request_context
from markupsafe import Markup, escape

log = logging.getLogger(__name__)

LANGS = ("ar",)
DEFAULT_LANG = "ar"
RTL = {"ar"}
PLURAL_KEYS = {"zero", "one", "two", "few", "many", "other"}
BABEL_LOCALE = {"ar": "ar"}


def _flatten(node, prefix: str, out: dict) -> None:
    if isinstance(node, dict):
        if node and set(node) <= PLURAL_KEYS:  # a plural table is a leaf
            out[prefix] = {k: str(v) for k, v in node.items()}
            return
        for k, v in node.items():
            _flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif node is not None:
        out[prefix] = str(node)


def _load_file(path: Path, prefix: str) -> dict:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict = {}
    _flatten(data, prefix, out)
    return out


class Catalogs:
    """All translation tables, built once at boot from core + site + enabled/present modules."""

    def __init__(self, app_dir: Path, module_ids: list[str]):
        self.tables: dict[str, dict] = {lang: {} for lang in LANGS}
        self.sources: dict[str, list[str]] = {lang: [] for lang in LANGS}
        for lang in LANGS:
            self._add(lang, app_dir / "i18n" / f"{lang}.yaml", "")
            self._add(lang, app_dir / "site" / "i18n" / f"{lang}.yaml", "site")
            self._add(lang, app_dir / "ai" / "i18n" / f"{lang}.yaml", "ai")
            for mid in module_ids:
                self._add(lang, app_dir / "modules" / mid / "i18n" / f"{lang}.yaml", mid)

    def _add(self, lang: str, path: Path, prefix: str) -> None:
        t = _load_file(path, prefix)
        if t:
            self.tables[lang].update(t)
            self.sources[lang].append(str(path))

    def get(self, lang: str, key: str):
        for l in (lang, DEFAULT_LANG):
            v = self.tables[l].get(key)
            if v is not None:
                return v
        return None


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _fmt(template: str, params: dict) -> str:
    return string.Formatter().vformat(template, (), _Safe(params))


def plural_category(lang: str, n) -> str:
    try:
        return Locale.parse(BABEL_LOCALE[lang]).plural_form(n)
    except Exception:  # pragma: no cover
        return "one" if n == 1 else "other"


# -- request-bound helpers ----------------------------------------------------
def current_lang() -> str:
    if has_request_context() and getattr(g, "lang", None):
        return g.lang
    return DEFAULT_LANG


def _catalogs() -> Catalogs:
    return current_app.extensions["catalogs"]


def t(key: str, lang: str | None = None, **params) -> str:
    lang = lang or current_lang()
    v = _catalogs().get(lang, key)
    if v is None:
        log.warning("i18n miss: %s [%s]", key, lang)
        return key
    if isinstance(v, dict):
        v = v.get("other") or next(iter(v.values()))
    return _fmt(v, params) if params else v


def tn(key: str, n, lang: str | None = None, **params) -> str:
    """Plural-aware translation. {n} is always available in the template."""
    lang = lang or current_lang()
    v = _catalogs().get(lang, key)
    if v is None:
        log.warning("i18n miss: %s [%s]", key, lang)
        return key
    if isinstance(v, str):
        return _fmt(v, {"n": n, **params})
    cat = plural_category(lang, n)
    if cat not in v:
        cat = "one" if n == 1 and "one" in v else "other"
    tpl = v.get(cat) or v.get("other") or next(iter(v.values()))
    from app.core.formatting import fmt_number  # local import: avoids a cycle

    return _fmt(tpl, {"n": fmt_number(n), **params})


def th(key: str, lang: str | None = None, **params) -> Markup:
    """Like t() but the catalog string may hold trusted markup (<b>, <a>); params are escaped."""
    lang = lang or current_lang()
    v = _catalogs().get(lang, key) or key
    if isinstance(v, dict):
        v = v.get("other", "")
    safe = {k: escape(val) for k, val in params.items()}
    return Markup(_fmt(v, safe))


def pick_lang() -> str:
    """Arabic only for now; kept as the single place to change when another language is added."""
    return DEFAULT_LANG


def direction(lang: str) -> str:
    return "rtl" if lang in RTL else "ltr"


def load_glossary(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("terms", [])
