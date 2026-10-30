"""Language-light word normalisation shared by rules that read free text (Arabic, French, English)."""
from __future__ import annotations

import re
import unicodedata


def norm_word(word: str) -> str:
    """lowercase, no accents/diacritics/tatweel, folded alef/teh-marbuta/alef-maqsura, punctuation removed"""
    w = unicodedata.normalize("NFKD", (word or "").casefold())
    w = "".join(ch for ch in w if not unicodedata.combining(ch))
    w = w.replace("ـ", "").replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    return re.sub(r"[^\w]", "", w)
