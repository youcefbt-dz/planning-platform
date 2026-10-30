"""Task: turn ONE rough line ("نريد رفع المبيعات") into well-formed goals the manager can pick from and edit.

The point is to remove the blank page: nobody should have to compose an objective, its "why" and its key results from nothing.
The model proposes up to three options, each with a title, a short "why it matters" and two to four key results (title + type + unit).
It NEVER proposes a start value or a target: those come from the organization's own data and history (the reality check), not from a model.
Guards: every string passes the voice check; a key result that describes an activity is dropped; any figure not typed by the user is rejected.
Offline: `app/ai/library.py` (templates matched against the typed text).

Inputs : {"intent": str}
Output : {"options": [{"title", "rationale", "krs": [{"title", "type", "unit"}]}], "matched": bool}
"""
from __future__ import annotations

import json

from app.ai import library, privacy, voice
from app.ai.base import Task
from app.ai.guards import check_numbers, numbers_in

KR_TYPES = ("increase", "decrease", "stay_above", "stay_below", "binary", "milestone")

ROLE = """You help a busy manager who dislikes writing to turn a rough idea into a well-formed objective with its key results (OKR practice).
They typed ONE line. Propose up to three options that approach it from genuinely different angles (for example growth vs. efficiency vs. customers)."""

RULES = """RULES
- `title`: the objective - a clear direction in one sentence of at most 14 words. Not a number, not a task, no verb of work (launch, organize, implement, prepare...).
- `rationale`: one or two sentences saying WHY it matters to this kind of company ("who cares?"), concrete, no slogans.
- `krs`: two to four key results per option. Each is a measurable OUTCOME (something that changes in the business), never an activity.
  `type` is one of: increase, decrease, stay_above, stay_below, binary, milestone. `unit` is a short label (دج, %, عميل, يوم, ساعة...) or "".
- NEVER write any start value, target, percentage or other figure. Targets come later from the company's own data. The key result titles contain no digits.
- Use the manager's own words and terms where possible; do not repeat their sentence back unchanged."""

EXAMPLE = """{"options": [
 {"title": "تنمية مبيعاتنا نموًّا منتظمًا ومستدامًا", "rationale": "المبيعات هي ما يموّل بقية أهدافنا، ونموّها المنتظم يمنحنا قدرة على الاستثمار.",
  "krs": [{"title": "الإيراد الشهري", "type": "increase", "unit": "دج"}, {"title": "عدد العملاء النشطين", "type": "increase", "unit": "عميل"}]},
 {"title": "رفع إيراداتنا من عملائنا الحاليين قبل البحث عن غيرهم", "rationale": "بيع أكثر لعميل يعرفنا أرخص وأسرع من اكتساب عميل جديد.",
  "krs": [{"title": "نسبة العملاء الذين يكررون الشراء", "type": "increase", "unit": "%"}, {"title": "متوسط قيمة الطلب", "type": "increase", "unit": "دج"}]}]}"""


def _is_activity(title: str) -> bool:
    """The goals coach's own rule (a work verb as first word). Soft dependency: without the goals module nothing is dropped."""
    try:
        from app.modules.goals.coach import starts_with_activity
    except Exception:  # module switched off or absent
        return False
    return starts_with_activity(title)


class DraftGoal(Task):
    name = "draft_goal"
    description = "Propose well-formed objectives and key results from one typed line."
    schema = {"type": "object", "properties": {"options": {"type": "array", "items": {"type": "object", "properties": {
        "title": {"type": "string"}, "rationale": {"type": "string"},
        "krs": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "type": {"type": "string"}, "unit": {"type": "string"}},
                                           "required": ["title", "type"]}}}, "required": ["title", "rationale", "krs"]}}}, "required": ["options"]}

    def prompt(self, inputs, lang):
        body = {"manager_typed": privacy.clip(inputs.get("intent"), 200)}
        return voice.system(ROLE, RULES, lang, company=inputs.get("_company"), example=EXAMPLE if lang == "ar" else ""), json.dumps(body, ensure_ascii=False)

    def validate(self, data, inputs):
        if data.get("matched") is False:      # the offline fallback found no template: an honest empty answer, not an error
            return {"options": [], "matched": False}
        lang = inputs.get("_lang", "ar")
        intent = privacy.clip(inputs.get("intent"), 200)
        allowed = numbers_in(intent)
        options = []
        for o in (data.get("options") or [])[:3]:
            try:
                title = voice.check_style(privacy.clip(o.get("title"), 160), lang, source=intent)
                why = voice.check_style(privacy.clip(o.get("rationale"), 300), lang, source=intent) if o.get("rationale") else ""
            except ValueError:
                continue
            if not title or library.has_digits(title) and not allowed:
                continue
            krs, seen = [], set()
            for k in o.get("krs") or []:
                try:
                    kt = voice.check_style(privacy.clip(k.get("title"), 160), lang, source=intent)
                except (ValueError, AttributeError):
                    continue
                kind = k.get("type") if k.get("type") in KR_TYPES else "increase"
                if not kt or kt in seen or _is_activity(kt) or (library.has_digits(kt) and not allowed):
                    continue
                seen.add(kt)
                krs.append({"title": kt, "type": kind, "unit": voice.clean(privacy.clip(k.get("unit"), 24))})
            if krs:
                options.append({"title": title, "rationale": why, "krs": krs[:4]})
        if not options:
            raise ValueError("no usable option")
        text = " ".join(x for o in options for x in (o["title"], o["rationale"], *[k["title"] for k in o["krs"]]))
        if not check_numbers(text, allowed):
            raise ValueError("the options contain figures the manager did not give")
        return {"options": options, "matched": True}

    def fallback(self, inputs, lang):
        options = library.draft(inputs.get("intent") or "")
        return {"options": options, "matched": bool(options)}


task = DraftGoal()
