"""Dates and numbers as people really write them in Algerian / French / Arabic spreadsheets."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")

MONTHS = {
    1: ["jan", "janv", "janvier", "january", "جانفي", "يناير", "كانون الثاني"],
    2: ["feb", "fev", "fevr", "fevrier", "february", "فيفري", "فبراير", "شباط"],
    3: ["mar", "mars", "march", "مارس", "اذار"],
    4: ["apr", "avr", "avril", "april", "افريل", "ابريل", "نيسان"],
    5: ["may", "mai", "ماي", "مايو", "ايار"],
    6: ["jun", "juin", "june", "جوان", "يونيو", "حزيران"],
    7: ["jul", "juil", "juillet", "july", "جويلية", "يوليو", "تموز"],
    8: ["aug", "aout", "august", "اوت", "اغسطس", "اب"],
    9: ["sep", "sept", "septembre", "september", "سبتمبر", "سبتمبر", "ايلول"],
    10: ["oct", "octobre", "october", "اكتوبر", "تشرين الاول"],
    11: ["nov", "novembre", "november", "نوفمبر", "تشرين الثاني"],
    12: ["dec", "decembre", "december", "ديسمبر", "كانون الاول"],
}


def fold(text) -> str:
    """Lower-case, no accents, no Arabic diacritics / hamza variants, digits normalised, single spaces."""
    s = unicodedata.normalize("NFKD", str(text if text is not None else "").translate(AR_DIGITS).lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub("[ـً-ٟ]", "", s).translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))
    return re.sub(r"\s+", " ", s).strip()


_MONTH_LOOKUP = {fold(name): m for m, names in MONTHS.items() for name in names}
_QUARTER = re.compile(r"^(?:q|t|trim\.?|trimestre|quarter|ر|الربع)\s*([1-4])(?:\D+(\d{2,4}))?$|^(?:([1-4])\s*(?:er|e|eme|st|nd|rd|th)?\s*(?:trimestre|quarter|trim|q))\s*(\d{2,4})?$")
_QUARTER_AR = {"الاول": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4}


def _year(v: str | None) -> int | None:
    if v is None:
        return None
    y = int(v)
    return 2000 + y if y < 100 else y


def month_of(token) -> int | None:
    """'janv.' -> 1, 'ديسمبر' -> 12; None if not a month name."""
    t = re.sub(r"[.\-_/]", " ", fold(token)).strip()
    return _MONTH_LOOKUP.get(t) or _MONTH_LOOKUP.get(t.rstrip("."))


def parse_period(value) -> tuple[date, str] | None:
    """-> (first day of the period, kind) where kind is day | month | quarter | year.  None if it is not a date at all."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date(), "day"
    if isinstance(value, date):
        return value, "day"
    if isinstance(value, (int, float)):
        if float(value).is_integer() and 1990 <= int(value) <= 2100:
            return date(int(value), 1, 1), "year"
        return None
    s = fold(value)
    if not s or len(s) > 40:
        return None
    if re.fullmatch(r"(19|20)\d{2}", s):
        return date(int(s), 1, 1), "year"
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ t]\d.*)?", s)
    if m:
        return _safe(int(m[1]), int(m[2]), int(m[3]), "day")
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})(?: \d.*)?", s)           # day first: the convention in Algeria and France
    if m:
        a, b, y = int(m[1]), int(m[2]), _year(m[3])
        return _safe(y, b, a, "day") or _safe(y, a, b, "day")
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})", s)
    if m:
        return _safe(int(m[1]), int(m[2]), 1, "month")
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{4})", s)
    if m:
        return _safe(int(m[2]), int(m[1]), 1, "month")
    m = re.fullmatch(r"([^\d\s.\-/]+\.?)[\s.\-/']*(\d{2,4})", s)                    # janv-25, january 2025, يناير 2025
    if m and (mon := month_of(m[1])):
        return _safe(_year(m[2]), mon, 1, "month")
    m = re.fullmatch(r"(\d{2,4})[\s.\-/]*([^\d\s.\-/]+\.?)", s)                      # 2025 janvier
    if m and (mon := month_of(m[2])):
        return _safe(_year(m[1]), mon, 1, "month")
    m = _QUARTER.match(s)
    if m:
        q, y = int(m[1] or m[3]), _year(m[2] or m[4])
        return (date(y, (q - 1) * 3 + 1, 1), "quarter") if y else None
    m = re.fullmatch(r"الربع (الاول|الثاني|الثالث|الرابع)\s*(\d{4})", s)
    if m:
        return date(int(m[2]), (_QUARTER_AR[m[1]] - 1) * 3 + 1, 1), "quarter"
    return None


def _safe(y, m, d, kind):
    try:
        return date(y, m, d), kind
    except (TypeError, ValueError):
        return None


_CURRENCY = re.compile(r"(?i)(dzd|\bda\b|دج|دينار|eur|usd|€|\$|£)")


def parse_number(value):
    """-> (float, had_percent_sign) or None. Handles '1 234,56', '1.234,56', '(1 200)', '12 %', '4 500 DA', Arabic-Indic digits."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value), False
    s = str(value).translate(AR_DIGITS).strip()
    if not s or s in {"-", "—", "–", "n/a", "N/A", "#N/A", "#DIV/0!", "#REF!"}:
        return None
    pct = "%" in s or "٪" in s
    neg = s.startswith("(") and s.endswith(")")
    s = _CURRENCY.sub("", s).replace("%", "").replace("٪", "").replace(" ", "").replace(" ", "").replace(" ", "").strip("()")
    if s.startswith("-") or s.startswith("−"):
        neg, s = True, s[1:]
    if not re.fullmatch(r"\d[\d.,]*|[.,]\d+", s):
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        n = float(s)
    except ValueError:
        return None
    return (-n if neg else n), pct


TOTAL_WORDS = ("total", "totaux", "sous-total", "sous total", "somme", "grand total", "subtotal", "المجموع", "مجموع", "الاجمالي", "اجمالي", "الإجمالي")


def is_total_label(value) -> bool:
    s = fold(value)
    return bool(s) and any(s == fold(w) or s.startswith(fold(w) + " ") for w in TOTAL_WORDS)
