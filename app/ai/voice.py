"""The voice of the AI: how it writes Arabic, and the check that an answer really is written that way.

Why this file exists
  A model that is only told "answer in Arabic" writes translated-sounding text: it opens with filler, repeats the question,
  calls everything "هذا المؤشر", transliterates English terms and sometimes leaks Chinese or Cyrillic characters.
  Every task therefore builds its system prompt through `system()` (one shared style guide, the project glossary, the company
  context, a worked example) and passes every sentence the model returns through `clean()` + `check_style()`.

Pure Python: no Flask import at module level, so the rules are unit-testable (tests/test_ai_voice.py).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

GLOSSARY = Path(__file__).resolve().parents[1] / "i18n" / "glossary.yaml"

LANG_NAMES = {"ar": "Arabic", "en": "English", "fr": "French"}

# Openers and padding that make a text read as machine-written. Matched on normalised text, anywhere in the answer.
FILLER_AR = (
    "من الجدير بالذكر", "تجدر الإشارة", "تجدر الاشارة", "يمكن القول", "بشكل عام", "في الواقع", "في الختام", "بناءً على ما سبق", "بناء على ما سبق",
    "كنموذج", "كذكاء اصطناعي", "آمل أن", "أتمنى أن", "لا تتردد", "في عالم الأعمال", "في عصرنا", "يعد من الأمور", "من المهم جدا", "من المهم جدًا",
    "بالتأكيد!", "بكل تأكيد", "بالطبع،",
)

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
_FOREIGN = re.compile(r"[\u0400-\u04FF\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7AF\u0E00-\u0E7F\u0590-\u05FF]")   # Cyrillic, Kana, CJK, Hangul, Thai, Hebrew
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_\-/%.]*")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_TASHKEEL = re.compile(r"[\u064B-\u065F\u0670\u0640]")

# Latin tokens that are fine in Arabic business prose even when the input did not contain them.
LATIN_OK = {"OKR", "KPI", "DZD", "EUR", "USD", "SAR", "AED", "MAD", "TND", "EGP", "kg", "km", "m2", "m3", "Excel", "CSV", "PDF", "SWOT", "TVA", "HT", "TTC"}


# -- glossary -----------------------------------------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def glossary() -> list[dict]:
    try:
        data = yaml.safe_load(GLOSSARY.read_text(encoding="utf-8")) or {}
    except OSError:
        return []
    return [t for t in data.get("terms") or [] if isinstance(t, dict)]


def avoided_terms() -> list[str]:
    """Every Arabic form the glossary forbids in the UI (transliterations and loose synonyms)."""
    out: list[str] = []
    for t in glossary():
        out += [str(x).strip() for x in t.get("avoid_ar") or [] if str(x).strip()]
    return out


def vocabulary(limit: int = 28) -> str:
    """'English = العربية' lines for the terms a planning text actually uses, so the model reuses the product's words."""
    wanted = ("objective", "key_result", "indicator", "initiative", "milestone", "alignment", "baseline", "target", "owner", "cycle", "org_unit",
              "organization", "workspace", "overview", "check_in", "stakeholder", "status", "on_track", "at_risk", "off_track", "balanced_scorecard", "perspective")
    rows = []
    for t in glossary():
        if t.get("id") in wanted and t.get("ar") and t.get("en"):
            rows.append(f"{t['en']} = {t['ar']}")
    return "; ".join(rows[:limit])


# -- the prompt -----------------------------------------------------------------------------------------------------------------------
STYLE_AR = """HOW TO WRITE THE ARABIC (this decides whether the text is useful or embarrassing):
- Plain Modern Standard Arabic of a sharp management consultant writing to a busy manager. Not a translation, not academic, not promotional.
- Open with the conclusion. One idea per sentence, about 20 words at most. Active verbs. Address the reader directly ("تاريخك", "مستهدفك", "عليك").
- Name the specific thing every time: the goal, the series, the figure WITH its unit ("1.2 مليون دج", "12%"). Never write "هذا المؤشر" or "الأمر" when you can name it.
- Say what to DO, not what it "could" mean. If something is uncertain, give ONE honest caveat and say what would settle it.
- Never open with filler or praise ("بشكل عام"، "من الجدير بالذكر"، "في الواقع"، "بالطبع") and never close with pleasantries. Do not mention that you are an AI.
- Use the product's own terms exactly (see VOCABULARY). Never transliterate English words (no «داشبورد»، «أوكيار»، «ميلستون»، «ستيك هولدر»).
- Latin digits (0-9) only. No markdown, no bullets inside strings, no emoji, no English words except units and currency codes.
- Do not repeat the same sentence shape twice in a row; do not restate the question; do not pad."""

STYLE_OTHER = """HOW TO WRITE: plain, concrete, specific. Open with the conclusion; one idea per sentence; name the exact thing and its figure with its unit;
say what to do; no filler openers, no closing pleasantries, no markdown, no emoji; never mention that you are an AI."""


def company_line(company: dict | None) -> str:
    """One sentence of context the model may use to choose better examples (sector and size only — never a name or a person)."""
    c = company or {}
    bits = [x for x in (c.get("sector_label"), c.get("size_label")) if x]
    cur = c.get("currency")
    if not bits and not cur:
        return ""
    return "COMPANY CONTEXT (use it to pick relevant examples; do not mention it): " + " — ".join(bits) + (f"; currency {cur}" if cur else "") + "."


def system(role: str, rules: str, lang: str, *, company: dict | None = None, example: str = "", language_note: str = "") -> str:
    """Compose a task's system prompt: role, task rules, the shared voice, vocabulary, company context and one worked example."""
    style = STYLE_AR if lang == "ar" else STYLE_OTHER
    parts = [role.strip(), "", f"Write every string of your answer in {LANG_NAMES.get(lang, 'English')}.", rules.strip(), "", style]
    if lang == "ar":
        vocab = vocabulary()
        if vocab:
            parts += ["", "VOCABULARY (use these Arabic terms): " + vocab + "."]
        avoid = avoided_terms()
        if avoid:
            parts += ["NEVER write these forms: " + "، ".join(avoid[:24]) + "."]
    ctx = company_line(company)
    if ctx:
        parts += ["", ctx]
    if language_note:
        parts += ["", language_note.strip()]
    if example:
        parts += ["", "EXAMPLE OF THE VOICE AND THE SHAPE (figures here are illustrative; in your answer use ONLY the figures you are given):", example.strip()]
    parts += ["", "Return only the JSON object, nothing before or after it."]
    return "\n".join(parts)


# -- the check -----------------------------------------------------------------------------------------------------------------------
def normalise(text: str) -> str:
    t = _TASHKEEL.sub("", text or "")
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    return re.sub(r"\s+", " ", t)


def clean(text) -> str:
    """Repair what is harmless (digits, markdown, bullets, stray quotes, doubled spaces); `check_style` rejects what is not."""
    s = "" if text is None else str(text)
    s = s.translate(_AR_DIGITS)
    s = re.sub(r"(\*\*|__|`)", "", s)
    s = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", s, flags=re.M)
    s = re.sub(r"^\s*#{1,6}\s+", "", s, flags=re.M)
    s = s.replace("\u200f", "").replace("\u200e", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\s*\n\s*", " ", s)
    s = re.sub(r"\s+([،؛؟.!,:;])", r"\1", s)
    return s.strip().strip("\"'«»“”").strip()


def check_style(text: str, lang: str = "ar", *, source: str = "") -> str:
    """Return the cleaned text, or raise ValueError when it reads as machine-made.

    `source` is whatever the model was shown (the inputs, as text): a Latin word that appears there — a product name, a unit —
    is the user's own and is allowed in the answer.
    """
    s = clean(text)
    if not s:
        return s
    if _FOREIGN.search(s):
        raise ValueError("answer contains characters of another script")
    if _EMOJI.search(s):
        raise ValueError("answer contains emoji")
    if lang != "ar":
        return s
    n = normalise(s)
    for f in FILLER_AR:
        if normalise(f) in n:
            raise ValueError(f"filler phrase: {f}")
    base = re.findall(r"[\u0600-\u06FF]+", n)
    words = {w[i:] for w in base for i in (0, 1, 2, 3) if len(w) - i >= 2}     # «الداشبورد» must be caught as «داشبورد»
    raw_words = set(re.findall(r"[\u0600-\u06FF]+", s))
    for bad in avoided_terms():
        if _TASHKEEL.search(bad):          # «بُعد» only differs from the everyday «بعد» by its vowel mark: compare with the marks kept
            hit = bad in raw_words
        else:
            nb = normalise(bad)
            hit = bool(nb) and ((nb in n) if " " in nb else (nb in words))
        if hit:
            raise ValueError(f"avoided term: {bad}")
    src = (source or "")
    for w in _LATIN_WORD.findall(s):
        w0 = w.strip(".-/%")
        if not w0 or w0 in LATIN_OK or w0.upper() in LATIN_OK or w0 in src or re.fullmatch(r"[A-Za-z]{0,3}\d[\w.%/-]*", w0):
            continue
        raise ValueError(f"unexpected Latin word: {w0}")
    letters = re.findall(r"[\u0600-\u06FFA-Za-z]", s)
    if len(letters) >= 12 and sum(1 for c in letters if "A" <= c <= "z") / len(letters) > 0.6:
        raise ValueError("answer is mostly Latin letters in an Arabic answer")
    return s


def clean_list(items, n: int, width: int, lang: str = "ar", *, source: str = "") -> list[str]:
    """A list of short sentences: cleaned, de-duplicated, clipped; a bad item is dropped rather than failing the whole answer."""
    out, seen = [], set()
    for x in items if isinstance(items, list) else []:
        if not isinstance(x, str) or not x.strip():
            continue
        try:
            s = check_style(x, lang, source=source)
        except ValueError:
            continue
        key = normalise(s)
        if s and key not in seen:
            seen.add(key)
            out.append(s if len(s) <= width else s[: width - 1].rstrip() + "…")
    return out[:n]


def company_context(org, lang: str = "ar") -> dict:
    """Sector, size and currency of the organization, as words. No name, no person, no goal text."""
    try:
        from app.core import i18n
        from app.core import profile as P

        prof = P.profile(org) if org is not None else {}
        out = {}
        if prof.get("sector"):
            out["sector_label"] = i18n.t(f"profile.sectors.{prof['sector']}", lang=lang)
        if prof.get("size"):
            out["size_label"] = i18n.t(f"profile.sizes.{prof['size']}", lang=lang)
        if prof.get("currency"):
            out["currency"] = prof["currency"]
        return out
    except Exception:  # context is a nicety; it must never stop a feature
        return {}
