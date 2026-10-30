"""Task: say in a few sentences what the goal-health screen shows and what deserves attention this week.

Every figure comes from the rows the code computed (progress, projected range, data age); the model chooses what matters and phrases it.

Inputs : {"counts": {status: n}, "rows": [{title, status, progress, projected: {low, mid, high}|None, target, unit, data_age_days, confidence}], "facts": [floats]}
Output : {"summary", "watch": [str]}
"""
from __future__ import annotations

import json

from app.ai import privacy, voice
from app.ai.base import Task
from app.ai.guards import check_numbers
from app.core import formatting as F
from app.core import i18n

ROLE = """You brief a manager on the health of their goals, the way a chief of staff would before a Monday meeting: what the overall picture is and what deserves attention this week.
You receive, per key result: status (on_track / at_risk / off_track / no_data), progress, where history says it is likely to end (a range) against the target, how old the latest data is, and the owner's confidence."""

RULES = """RULES
- Use ONLY the numbers given. Never invent a figure, a cause or an owner's name.
- `summary`: 2 sentences. Sentence 1: the overall picture in words a manager repeats to the team (how many are fine, how many are not). Sentence 2: the single most important thing to do or decide.
- `watch`: up to 3 items, one per key result that most needs attention, worst first. Each item starts with the key result's name, then WHY (the likely end vs. the target, or how stale the data is) in one short sentence.
- If the data behind a key result is old, say that the status may be out of date rather than judging it.
- If nothing needs attention, say so plainly and leave `watch` empty."""

EXAMPLE = """{"summary": "7 من 10 نتائج رئيسية تسير كما خُطّط لها، لكن اثنتين خرجتا عن المسار وواحدة بلا بيانات حديثة. أولويتك هذا الأسبوع هي مبيعات الفرع الشرقي.",
 "watch": ["مبيعات الفرع الشرقي: يشير التاريخ إلى نحو 80 مليون دج في النهاية مقابل هدف قدره 100.", "زمن التسليم: آخر بيانات عمرها 75 يومًا، فقد تكون حالته الحقيقية مختلفة."]}"""


class SummarizeHealth(Task):
    name = "summarize_health"
    description = "Brief the manager on the health of the goals."
    schema = {"type": "object", "properties": {"summary": {"type": "string"}, "watch": {"type": "array", "items": {"type": "string"}}}, "required": ["summary", "watch"]}

    def prompt(self, inputs, lang):
        body = {"counts": inputs.get("counts"), "key_results": [
            {"title": privacy.clip(r.get("title"), 100), "status": r.get("status"), "progress_percent": r.get("progress"), "target": r.get("target"), "unit": r.get("unit"),
             "likely_end": r.get("projected"), "data_age_days": r.get("data_age_days"), "owner_confidence_1_to_10": r.get("confidence")} for r in (inputs.get("rows") or [])][:25]}
        return voice.system(ROLE, RULES, lang, company=inputs.get("_company"), example=EXAMPLE if lang == "ar" else ""), json.dumps(body, ensure_ascii=False, default=str)

    def validate(self, data, inputs):
        lang = inputs.get("_lang", "ar")
        src = json.dumps(inputs.get("rows"), ensure_ascii=False, default=str)
        out = {"summary": voice.check_style(privacy.clip(data.get("summary"), 500), lang, source=src), "watch": voice.clean_list(data.get("watch"), 3, 240, lang, source=src)}
        if not out["summary"]:
            raise ValueError("empty")
        if not check_numbers(" ".join([out["summary"], *out["watch"]]), inputs.get("facts")):
            raise ValueError("invented number")
        return out

    def fallback(self, inputs, lang):
        t = lambda key, **kw: i18n.t(key, lang=lang, **kw)
        c = {k: v for k, v in (inputs.get("counts") or {}).items() if v}
        total = sum(c.values())
        if not total:
            return {"summary": t("ai.health.empty"), "watch": []}
        order = ("on_track", "at_risk", "off_track", "no_data")
        present = [k for k in order if c.get(k)]
        if present == ["on_track"]:
            first = i18n.tn("ai.health.all_on", total, lang=lang)
        else:
            parts = [i18n.tn(f"ai.health.n.{k}", c[k], lang=lang) for k in present]
            first = t("ai.health.overall", total=i18n.tn("ai.health.kr", total, lang=lang), parts=t("ai.health.and").join(parts))
        rank = {"off_track": 0, "at_risk": 1, "no_data": 2}
        worst = sorted([r for r in inputs.get("rows") or [] if r.get("status") in rank], key=lambda r: (rank[r["status"]], r.get("progress") or 0))
        second = t("ai.health.focus." + worst[0]["status"], title=privacy.clip(worst[0]["title"], 60)) if worst else t("ai.health.focus.none")
        watch = []
        for r in worst[:3]:
            u, st, mid = r.get("unit") or "", r["status"], (r.get("projected") or {}).get("mid")
            title, age = privacy.clip(r["title"], 60), r.get("data_age_days")
            target = F.fmt_value(r.get("target"), u, lang=lang)
            if st == "no_data":
                watch.append(t("ai.health.watch.no_data_old", title=title, age=i18n.tn("ai.health.days", age, lang=lang)) if age else t("ai.health.watch.no_data", title=title))
            elif mid is None:
                watch.append(t(f"ai.health.watch.{st}_noproj", title=title, progress=F.fmt_number(r.get("progress") or 0, 0, lang), target=target))
            else:
                watch.append(t(f"ai.health.watch.{st}", title=title, target=target, mid=F.fmt_value(mid, u, lang=lang)))
        stale = [r for r in inputs.get("rows") or [] if (r.get("data_age_days") or 0) > 60 and r.get("status") != "no_data"]
        if stale and len(watch) < 3:
            watch.append(i18n.tn("ai.health.stale", len(stale), lang=lang))
        return {"summary": f"{first} {second}", "watch": watch}


task = SummarizeHealth()
