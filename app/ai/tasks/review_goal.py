"""Task: review how a goal is WRITTEN, like a seasoned OKR coach.

The rules (app/modules/goals/coach.py) have already run: their findings are an input here and the offline fallback. The model adds what
rules cannot see — whether the key results are enough to achieve the objective, clearer wording, what is missing — and may only
rewrite wording: it never changes a number (any figure in a rewrite must already appear in the goal).

Inputs : {"objective": {title, rationale, commitment}, "krs": [{title, type, start, target, unit, measured}], "findings": [{code, target, level}], "facts": [floats]}
Output : {"summary", "objective_rewrite", "kr_rewrites": [{"index", "title"}], "missing": [str], "sufficiency": str}
"""
from __future__ import annotations

import json

from app.ai import privacy, voice
from app.ai.base import Task
from app.ai.guards import check_numbers
from app.core import i18n

ROLE = """You are a seasoned OKR coach reviewing how ONE goal is written, inside a business-planning product. Simple rule-based checks have already run; their findings are given.
You add what rules cannot see: whether the key results are enough to achieve the objective, wording that is vague or describes work instead of a result, and what is missing."""

RULES = """PRINCIPLES
- An objective is a clear, inspiring direction (not a theme, not a number, not a task) and says why it matters. A key result is a measurable OUTCOME with a start, a target and a unit - never an activity (launch, organize, implement...).
- Two to five key results. If every key result were achieved, the objective must be achieved.
RULES
- Never change or invent a number. A rewrite keeps the owner's meaning, terminology and figures; rewrite only when it is clearly better, otherwise leave the field empty.
- `summary`: 1-2 sentences, honest and specific to THIS goal: name what is strong and the one thing that most needs fixing. Do not list the rule findings again.
- `objective_rewrite`: a better title in one line (direction, not a number), or "" if the title is already good.
- `kr_rewrites`: only key results that describe an activity or are vague; rewrite as the outcome it should produce: {"index": 0-based, "title": ...}.
- `missing`: up to 2 key results the objective still needs, written as outcomes without invented figures.
- `sufficiency`: ONE sentence answering "if every key result were achieved, would the objective be achieved?" - say what is covered and what is not."""

EXAMPLE = """{"summary": "الهدف واضح، لكن نتيجتين من ثلاث تصفان عملًا لا أثرًا، ولا شيء يقيس رضا العملاء الذي يقوم عليه الهدف.",
 "objective_rewrite": "أن نصبح الخيار الأول للعملاء في الجزائر العاصمة",
 "kr_rewrites": [{"index": 1, "title": "رفع نسبة العملاء الذين يعيدون الشراء خلال 90 يومًا"}],
 "missing": ["خفض زمن التسليم المتوسط"],
 "sufficiency": "تحقق النتائج الثلاث كاملةً نموّ المبيعات، لكنها لا تضمن أن العملاء أصبحوا أكثر رضًا، وهذا لبّ الهدف."}"""


def _soft(text, lang, src):
    """A secondary field that fails the style check is dropped, not the whole answer."""
    try:
        return voice.check_style(text, lang, source=src) if text else ""
    except ValueError:
        return ""


class ReviewGoal(Task):
    name = "review_goal"
    description = "Coach the wording and completeness of an objective and its key results."
    schema = {"type": "object", "properties": {
        "summary": {"type": "string"}, "objective_rewrite": {"type": "string"},
        "kr_rewrites": {"type": "array", "items": {"type": "object", "properties": {"index": {"type": "integer"}, "title": {"type": "string"}}, "required": ["index", "title"]}},
        "missing": {"type": "array", "items": {"type": "string"}}, "sufficiency": {"type": "string"}},
        "required": ["summary", "objective_rewrite", "kr_rewrites", "missing", "sufficiency"]}

    def prompt(self, inputs, lang):
        o = inputs.get("objective") or {}
        body = {"objective": {"title": privacy.clip(o.get("title"), 200), "why_it_matters": privacy.clip(o.get("rationale"), 300), "commitment": o.get("commitment")},
                "key_results": [{"index": i, "title": privacy.clip(k.get("title"), 160), "type": k.get("type"), "start": k.get("start"), "target": k.get("target"), "unit": k.get("unit")}
                                for i, k in enumerate(inputs.get("krs") or [])][:8],
                "rule_findings": [{"code": f.get("code"), "where": f.get("target")} for f in (inputs.get("findings") or [])][:20]}
        return voice.system(ROLE, RULES, lang, company=inputs.get("_company"), example=EXAMPLE if lang == "ar" else ""), json.dumps(body, ensure_ascii=False, default=str)

    def validate(self, data, inputs):
        lang = inputs.get("_lang", "ar")
        src = json.dumps({"o": inputs.get("objective"), "k": inputs.get("krs")}, ensure_ascii=False, default=str)
        n = len(inputs.get("krs") or [])
        rewrites = []
        for r in data.get("kr_rewrites") or []:
            try:
                i, title = int(r["index"]), voice.check_style(privacy.clip(r["title"], 200), lang, source=src)
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= i < n and title and title != (inputs["krs"][i].get("title") or "").strip():
                rewrites.append({"index": i, "title": title})
        out = {"summary": voice.check_style(privacy.clip(data.get("summary"), 400), lang, source=src),
               "objective_rewrite": _soft(privacy.clip(data.get("objective_rewrite"), 200), lang, src),
               "kr_rewrites": rewrites[:5], "missing": voice.clean_list(data.get("missing"), 2, 200, lang, source=src),
               "sufficiency": _soft(privacy.clip(data.get("sufficiency"), 260), lang, src)}
        if not out["summary"]:
            raise ValueError("empty summary")
        if out["objective_rewrite"] == (inputs.get("objective") or {}).get("title", "").strip():
            out["objective_rewrite"] = ""
        text = " ".join([out["summary"], out["objective_rewrite"], out["sufficiency"], *out["missing"], *[r["title"] for r in rewrites]])
        if not check_numbers(text, inputs.get("facts")):
            raise ValueError("invented number")
        return out

    def fallback(self, inputs, lang):
        t = lambda key, **kw: i18n.t(key, lang=lang, **kw)
        rank = {"error": 0, "warn": 1, "info": 2}
        open_ = sorted([f for f in inputs.get("findings") or [] if f.get("level") in rank], key=lambda f: rank[f["level"]])
        phrases, seen = [], set()
        for f in open_:
            code, tgt = f.get("code"), str(f.get("target") or "")
            n = int(tgt.split(":")[1]) + 1 if tgt.startswith("kr:") and tgt.split(":")[1].isdigit() else ""
            key = f"ai.review.focus.{code}"
            if (code, n) in seen or not i18n._catalogs().get(lang, key):
                continue
            seen.add((code, n))
            phrases.append(t(key, n=n))
        if not open_:
            summary = t("ai.review.clean")
        else:
            lead = t("ai.review.lead." + ("errors" if open_[0]["level"] == "error" else "warns" if open_[0]["level"] == "warn" else "minor"))
            summary = f"{lead} {t('ai.review.and').join(phrases[:2])}." if phrases else lead
        kr_n = len(inputs.get("krs") or [])
        suff = t("ai.review.sufficiency." + ("none" if kr_n == 0 else "one" if kr_n == 1 else "many")) if inputs.get("krs") is not None else t("ai.review.sufficiency.many")
        return {"summary": summary, "objective_rewrite": "", "kr_rewrites": [], "missing": [], "sufficiency": suff}


task = ReviewGoal()
