"""Is this goal written the way professional OKR practice asks?  Pure rules, no Flask, no model: every check is reproducible.

The checks come from what the OKR tools and their own guidance agree on (Perdoo, Profit.co, Cascade, WhatMatters/Google, Atlassian):
  * an objective is a clear, qualitative direction — not a theme, not a number, not a task
  * it says why it matters ("who cares?") and has a horizon and an owner
  * 2-5 key results, each an OUTCOME you can measure (not an activity), with a start, a target, a unit and a sensible direction
  * a target that history cannot support is a conversation to have (outside factors), not a quiet assumption
The model-based reviewer (app/ai/tasks/review_goal.py) adds what rules cannot see — e.g. whether the key results are enough to
achieve the objective — and proposes wording; these rules are also its offline fallback.
"""
from __future__ import annotations

import re

from app.core.textnorm import norm_word

METRIC_TYPES = ("increase", "decrease", "stay_above", "stay_below")

# First words of a title that describe WORK to do rather than a RESULT to reach. Normalised (no accents/diacritics), lowercase.
ACTIVITY = {
    "en": {"launch", "publish", "implement", "hold", "organize", "organise", "create", "build", "do", "conduct", "write", "develop", "complete", "finish",
           "deploy", "run", "make", "prepare", "start", "plan", "draft", "design", "train", "attend", "visit", "send", "post", "review", "update", "set",
           "install", "introduce", "roll", "migrate", "finalize", "finalise", "hire", "recruit", "open"},
    "fr": {"lancer", "publier", "mettre", "organiser", "realiser", "creer", "developper", "mener", "rediger", "finaliser", "deployer", "elaborer", "preparer",
           "construire", "installer", "former", "animer", "tenir", "effectuer", "faire", "etablir", "ouvrir", "recruter", "migrer", "concevoir", "lancement",
           "publication", "organisation", "creation", "mise"},
    "ar": {"اطلاق", "اطلق", "نشر", "انشر", "تنفيذ", "نفذ", "تنظيم", "نظم", "انشاء", "انشئ", "عقد", "اعداد", "اعد", "بناء", "ابن", "تطوير", "طور", "القيام",
           "انجاز", "انجز", "تركيب", "ركب", "تدريب", "درب", "وضع", "ضع", "تصميم", "صمم", "اصدار", "اصدر", "تحضير", "حضر", "كتابة", "اكتب", "تاسيس", "اسس",
           "تفعيل", "فعل", "افتتاح", "افتح", "توظيف", "وظف", "زيارة", "زر", "ارسال", "ارسل", "تحديث", "حدث", "استكمال", "استكمل", "اتمام", "اتم"},
}


_norm = norm_word


def starts_with_activity(title: str) -> bool:
    words = [_norm(w) for w in (title or "").split()[:2]]
    words = [w for w in words if w]
    if not words:
        return False
    return any(words[0] in v for v in ACTIVITY.values())


def _words(text: str) -> int:
    return len([w for w in re.split(r"\s+", (text or "").strip()) if w])


def _item(code, ok, level="info", target="", **params):
    return {"code": code, "ok": ok, "level": level if not ok else "ok", "target": target, "params": params}


def review(obj: dict, krs: list[dict], *, has_series: bool = False) -> dict:
    """obj: title, rationale, has_horizon, has_owner.   krs: title, type, start, target, unit, measured, verdict (None | realistic | ambitious | stretch | unrealistic), factors (int).
    Returns {"checks": [{code, ok, level, target, params}], "passed", "total", "open"}; a check that passes still appears (the UI folds it)."""
    c: list[dict] = []
    title = (obj.get("title") or "").strip()
    words = _words(title)
    c.append(_item("title_clear", 3 <= words and len(title) <= 120, "warn" if words else "error", "title") if title else _item("title_empty", False, "error", "title"))
    if title and words < 3:
        c[-1]["code"] = "title_short"
    elif len(title) > 120:
        c[-1]["code"] = "title_long"
    if title:
        c.append(_item("title_number", not re.search(r"\d", title), "info", "title"))
    c.append(_item("why", len((obj.get("rationale") or "").strip()) >= 15, "warn", "rationale"))
    c.append(_item("horizon", bool(obj.get("has_horizon")), "warn", "dates"))
    c.append(_item("owner", bool(obj.get("has_owner")), "info", "owner"))

    live = [(i, k) for i, k in enumerate(krs) if (k.get("title") or "").strip()]
    n = len(live)
    c.append(_item("kr_count", 2 <= n <= 5, "error" if n == 0 else "info" if n == 1 else "warn", "krs", n=n))
    if n == 0:
        c[-1]["code"] = "kr_none"
    elif n == 1:
        c[-1]["code"] = "kr_one"
    elif n > 5:
        c[-1]["code"] = "kr_many"

    seen: dict[str, int] = {}
    for i, k in live:
        t = k.get("type") or "increase"
        tgt = f"kr:{i}"
        p = {"n": i + 1, "title": (k["title"] or "").strip()[:60]}
        act = starts_with_activity(k["title"])
        if t in METRIC_TYPES:
            c.append(_item("kr_activity", not act, "warn", tgt, **p))
        else:
            c.append(_item("kr_activity_soft", not act, "info", tgt, **p))
        start, target = k.get("start"), k.get("target")
        if t in ("increase", "decrease"):
            span_ok = start is not None and target is not None and start != target
            c.append(_item("kr_span", span_ok, "error", tgt, **p))
            if span_ok:
                wrong = (t == "increase" and target < start) or (t == "decrease" and target > start)
                c.append(_item("kr_direction", not wrong, "warn", tgt, kind=t, **p))
        elif t in ("stay_above", "stay_below"):
            c.append(_item("kr_threshold", target is not None, "error", tgt, **p))
        elif t == "milestone":
            c.append(_item("kr_steps", target is not None and target >= 2, "info", tgt, **p))
        if t in METRIC_TYPES and not (k.get("unit") or "").strip():
            c.append(_item("kr_unit", False, "info", tgt, **p))
        if has_series and t in METRIC_TYPES:
            c.append(_item("kr_measured", bool(k.get("measured")), "info", tgt, **p))
        v = k.get("verdict")
        if v in ("stretch", "unrealistic"):
            if v == "unrealistic" and not k.get("factors"):
                c.append(_item("kr_needs_factors", False, "warn", tgt, **p))
            elif v == "stretch":
                c.append(_item("kr_beyond_history", bool(k.get("factors")), "info", tgt, **p))
        key = re.sub(r"\W+", " ", (k["title"] or "").casefold()).strip()
        if key in seen:
            c.append(_item("kr_duplicate", False, "warn", tgt, **p))
        seen[key] = i
    bad = [x for x in c if not x["ok"]]
    return {"checks": c, "passed": len(c) - len(bad), "total": len(c), "open": bad}
