"""Task: explain, in plain words, a reality-check verdict that the code has ALREADY computed.

The numbers and the verdict level are computed by `app/modules/data/realism.py`; the model never recomputes or changes them.
Its job is to choose what matters, say it clearly in the user's language and ask the right context questions.
Guard: every number in the model's text must come from the supplied facts, otherwise the answer is rejected and the
rule-based text is used instead — a fluent hallucinated figure is worse than a plain correct sentence.

Inputs : {"goal", "series", "unit", "verdict": {...}, "facts": [floats]}
Output : {"summary", "reasons": [str], "suggestion", "questions": [str]}
"""
from __future__ import annotations

import json
import re

from app.ai import privacy, voice
from app.ai.base import Task
from app.core import formatting as F
from app.core import i18n

LANG_NAMES = {"ar": "Arabic", "en": "English", "fr": "French"}
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")

ROLE = """You are the analyst inside a business-planning product. A deterministic engine has ALREADY judged whether a target is realistic, using the company's own history.
You receive its verdict and its numbers. Your only job is to put that judgment into words a manager acts on."""

RULES = """RULES
- Never change the verdict level. Never recompute, round differently or invent a figure: use ONLY numbers present in `facts` or `verdict`, written with their unit.
- `summary`: 1-2 sentences. First say whether the target is realistic and why, using the single most telling comparison (what is asked vs. what history delivered).
- `reasons`: 2-3 sentences, each a different fact from the history (typical change, best change, how many comparable periods, trend, seasonality, volatility). No sentence may repeat the summary.
- `suggestion`: ONE sentence that tells the manager what to do now (keep it, lower it to a figure that was given, or record what would change the picture). If the verdict is "insufficient", say exactly what data is missing.
- `questions`: 0-3 short context questions that could change the judgment (new capacity, price change, new market, seasonality, a one-off contract). Only when the verdict is stretch or unrealistic; each must be answerable in a few words.
- No investment, legal or tax advice."""

EXAMPLE = """{"summary": "رفع المبيعات إلى 150 مليون دج خلال 6 أشهر طموح جدًا: يطلب زيادة 25%، بينما أفضل زيادة في تاريخك لمدة مماثلة بلغت 14%.",
 "reasons": ["عبر 18 فترة مماثلة، كانت الزيادة المعتادة 6% فقط، ومستهدفك أعلى من 95% منها.", "اتجاه آخر 3 أشهر شبه ثابت، فلا يوجد زخم يسند هذه القفزة."],
 "suggestion": "ضع مستهدفًا قرب 137 مليون دج، أو سجّل ما سيتغيّر فعلًا (فرع جديد، تعديل أسعار) ليصبح الرقم الأعلى مبرَّرًا.",
 "questions": ["هل ستضيف طاقة بيع جديدة قبل نهاية الفترة؟", "هل هناك تغيير في الأسعار أو عرض جديد يفسّر هذه القفزة؟"]}"""

SYSTEM = None  # built per request by voice.system(); kept as a name for backward compatibility


def _nice(x):
    """Round a suggested target to a figure a person would actually set (3 significant digits)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return x
    if abs(x) < 10:
        return round(x, 2)
    if abs(x) < 100:
        return round(x, 1)
    import math
    digits = 3 - int(math.floor(math.log10(abs(x)))) - 1
    return round(x, digits) if digits > 0 else float(round(x, digits))

from app.ai.guards import allowed_numbers, check_numbers, clip_list as _clip_list, numbers_in  # noqa: E402,F401  (shared by every task)


class ExplainReality(Task):
    name = "explain_reality"
    description = "Explain an already-computed reality-check verdict for a goal."
    schema = {"type": "object", "properties": {
        "summary": {"type": "string"}, "reasons": {"type": "array", "items": {"type": "string"}},
        "suggestion": {"type": "string"}, "questions": {"type": "array", "items": {"type": "string"}}},
        "required": ["summary", "reasons", "suggestion", "questions"]}

    def prompt(self, inputs, lang):
        body = {"goal": privacy.clip(inputs.get("goal"), 160), "series": privacy.clip(inputs.get("series"), 80), "unit": inputs.get("unit", ""),
                "verdict": inputs["verdict"], "facts": inputs.get("facts", [])}
        system = voice.system(ROLE, RULES, lang, company=inputs.get("_company"), example=EXAMPLE if lang == "ar" else "")
        return system, json.dumps(body, ensure_ascii=False, default=str)

    def validate(self, data, inputs):
        src = json.dumps({k: inputs.get(k) for k in ("goal", "series", "unit")}, ensure_ascii=False, default=str)
        lang = inputs.get("_lang", "ar")
        summary = voice.check_style(privacy.clip(data.get("summary"), 400), lang, source=src)
        out = {"summary": summary, "reasons": voice.clean_list(data.get("reasons"), 3, 260, lang, source=src),
               "suggestion": voice.check_style(privacy.clip(data.get("suggestion"), 300), lang, source=src) if data.get("suggestion") else "",
               "questions": voice.clean_list(data.get("questions"), 3, 200, lang, source=src)}
        if not out["summary"]:
            raise ValueError("empty summary")
        if inputs["verdict"].get("level") not in ("stretch", "unrealistic"):
            out["questions"] = []
        text = " ".join([out["summary"], out["suggestion"], *out["reasons"]])
        if not check_numbers(text, inputs.get("facts")):
            raise ValueError("the answer contains a number that is not in the facts")
        return out

    # -- rule-based explanation (also what is shown when no model is allowed) ---------------------------------------------------
    # Written by code, not poured into one template: it names the thing measured, says from-what-to-what, compares the ask with the
    # history in plain words, never repeats a figure between the summary and the reasons, and advises a concrete next step.
    def fallback(self, inputs, lang):
        v, unit = inputs["verdict"], inputs.get("unit", "")
        t = lambda k, **p: i18n.t(k, lang=lang, **p)
        rel = v.get("measure") == "relative"
        pct = lambda x, d=None: F.fmt_percent(x, (0 if abs(x) >= 0.095 else 1) if d is None else d, lang)
        amt = (lambda x: pct(x)) if rel else (lambda x: F.fmt_value(x, unit, lang=lang))
        val = lambda x: F.fmt_value(x, unit, lang=lang)
        h, rng, mo = v.get("hist") or {}, v.get("range") or {}, v.get("monthly") or {}
        level, months = v["level"], v.get("months", 0)
        lower = v.get("direction") == "lower_better"
        name = privacy.clip(inputs.get("series") or inputs.get("goal"), 60) or t("ai.reality.the_series")
        none = lambda x: "—" if x is None else x
        p = {"name": name, "span": i18n.tn("ai.reality.span", months, lang=lang), "months": months,
             "action": t("ai.reality.action." + ("lower" if lower else "higher"), name=name),
             "from": val(v["start"]) if v.get("start") is not None else none(None), "to": val(v["target"]) if v.get("target") is not None else none(None),
             "required": amt(v["required"]) if v.get("required") is not None else "—", "median": amt(h["median"]) if h.get("median") is not None else "—",
             "best": amt(h["best"]) if h.get("best") is not None else "—", "windows": F.fmt_number(h.get("windows", 0), 0, lang), "points": F.fmt_number(h.get("n_points", 0), 0, lang),
             "latest": val(v["latest"]) if v.get("latest") is not None else "—",
             "typical": val(rng["typical"]) if rng.get("typical") is not None else "—", "high": val(_nice(rng["high"])) if rng.get("high") is not None else "—",
             "m_req": amt(mo["required"]) if mo.get("required") is not None else "—", "m_typ": "—"}
        p["m_typ"] = amt(mo["typical"]) if mo.get("typical") is not None else "—"
        ratio = v.get("ratio_best")
        p["ratio_tail"] = t("ai.reality.ratio_tail", ratio=F.fmt_number(ratio, 1, lang)) if ratio and ratio >= 1.5 else ""
        pc = v.get("percentile")
        p["beat"] = t("ai.reality.beat.all") if pc is not None and pc >= 99.5 else t("ai.reality.beat.some", percentile=F.fmt_number(round(pc or 0), 0, lang))

        summary = t(f"ai.reality.s.{level}", **p)
        reasons = []
        if "scale_mismatch" in v.get("notes", []):
            reasons.append(t("ai.reality.note.scale_mismatch", **p))
        if level != "insufficient" and h.get("windows"):
            reasons.append(t("ai.reality.r.history", **p))
        if level in ("ambitious", "stretch", "unrealistic") and mo.get("required") is not None and mo.get("typical") not in (None, 0):
            reasons.append(t("ai.reality.r.pace", **p))
        for code in [c for c in v.get("notes", []) if c != "scale_mismatch"]:
            key = f"ai.reality.note.{code}"
            if i18n._catalogs().get(lang, key):
                reasons.append(t(key, **p))

        if level in ("stretch", "unrealistic") and rng.get("high") is not None:
            suggestion = t("ai.reality.a.cut", **p)
        elif level == "ambitious":
            suggestion = t("ai.reality.a.ambitious", **p)
        elif level == "insufficient":
            suggestion = t("ai.reality.suggest.more_data")
        else:
            suggestion = t("ai.reality.a.keep", **p)
        qs = []
        if level in ("stretch", "unrealistic"):
            qs = ["capacity", "price"] + (["season"] if v.get("seasonal") else ["market"])
        elif level == "ambitious":
            qs = ["change"]
        return {"summary": summary, "reasons": reasons[:4], "suggestion": suggestion, "questions": [t(f"ai.reality.q.{k}") for k in qs]}


task = ExplainReality()
