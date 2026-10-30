"""Locale-aware numbers and dates.

Digits: Latin by default (config/modules.yaml -> defaults.digits), native on request.
Dates are composed from CLDR month names (Babel), not from locale patterns, so the
digit system and the Arabic month set (MSA `ar` vs Algerian `ar_DZ`) stay under our control.
"""
from __future__ import annotations

from datetime import date, datetime

from babel import Locale
from babel.numbers import format_decimal
from flask import current_app
from markupsafe import Markup, escape

from app.core.i18n import current_lang

_NATIVE = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def _settings() -> dict:
    return current_app.config.get("PRODUCT_DEFAULTS", {})


def _digits(s: str, lang: str) -> str:
    if lang == "ar" and _settings().get("digits") == "native":
        return s.translate(_NATIVE)
    return s


def _month_locale(lang: str) -> Locale:
    if lang == "ar":
        return Locale.parse(_settings().get("arabic_locale", "ar"))
    return Locale.parse(lang)


def fmt_number(n, decimals: int | None = None, lang: str | None = None) -> str:
    lang = lang or current_lang()
    if n is None:
        return "—"
    if decimals is None:
        decimals = 0 if float(n).is_integer() else 1
    pattern = "#,##0" + ("." + "0" * decimals if decimals else "")
    try:
        s = format_decimal(n, format=pattern, locale=Locale.parse(lang), numbering_system="latn")
    except Exception:  # pragma: no cover
        s = f"{n:,.{decimals}f}"
    return _digits(s, lang)


def fmt_percent(ratio, decimals: int = 0, lang: str | None = None) -> str:
    """ratio 0..1 -> '72%'  (percent sign placement follows the language)."""
    lang = lang or current_lang()
    if ratio is None:
        return "—"
    num = fmt_number(round(ratio * 100, decimals), decimals if decimals else 0, lang)
    if lang == "fr":
        return f"{num} %"
    return f"{num}%"


def fmt_date(d, style: str = "medium", lang: str | None = None) -> str:
    """style: medium '3 Mar 2026' | long '3 March 2026' | short '03/03/2026' | month 'March 2026' | day '3 Mar'."""
    lang = lang or current_lang()
    if d is None:
        return "—"
    if isinstance(d, datetime):
        d = d.date()
    loc = _month_locale(lang)
    if style == "short":
        s = f"{d.day:02d}/{d.month:02d}/{d.year}"
    else:
        width = "wide" if style in ("long", "month") else "abbreviated"
        month = loc.months["format"][width][d.month]
        if style == "month":
            s = f"{month} {d.year}"
        elif style == "day":
            s = f"{d.day} {month}"
        else:
            s = f"{d.day} {month} {d.year}"
    return _digits(s, lang)


def month_names(lang: str | None = None) -> list[tuple[int, str]]:
    """[(1, 'يناير'), …] in the configured month-name style (MSA or Algerian), for <select> options."""
    loc = _month_locale(lang or current_lang())
    return [(m, loc.months["format"]["wide"][m]) for m in range(1, 13)]


# Units are stored as typed (or as the seed wrote them); the screen shows the Arabic wording.
UNIT_AR = {"DZD": "دج", "M DZD": "مليون دج", "MDZD": "مليون دج", "K DZD": "ألف دج", "KDZD": "ألف دج", "EUR": "أورو", "USD": "دولار",
           "day": "يوم", "days": "يوم", "h": "ساعة", "hours": "ساعة", "pts": "نقطة"}


def unit_text(unit: str | None) -> str:
    u = (unit or "").strip()
    return UNIT_AR.get(u, UNIT_AR.get(u.upper(), u))


def fmt_value(value, unit_label: str | None = None, metric_type: str = "number", lang: str | None = None) -> str:
    """A measured value with its unit: 12 500 دج · 45% · 8.5."""
    if value is None:
        return "—"
    if metric_type == "percent":
        return fmt_number(value, None, lang) + "%"
    unit_label = unit_text(unit_label)
    s = fmt_number(value, None, lang)
    if unit_label == "%":
        return s + "%"
    return f"{s} {unit_label}".strip() if unit_label else s


def bdi(text) -> Markup:
    """Wrap numbers/Latin runs so they keep their direction inside RTL text."""
    return Markup(f"<bdi>{escape(text)}</bdi>")
