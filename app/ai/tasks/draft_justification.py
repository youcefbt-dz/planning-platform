"""Task: write the justification of a target that goes beyond what history supports (it appears in reports).

Everything quantitative comes from code — the history-supported level, the gap, each outside factor and the coverage. The model only
writes it as a short paragraph a board member can read; any number it quotes must be one of the supplied figures.

Inputs : {"goal", "kr", "unit", "level", "target", "supported", "gap", "factors": [{title, kind, effect, certainty}], "coverage": {...}, "facts": [floats]}
Output : {"text"}
"""
from __future__ import annotations

import json

from app.ai import privacy, voice
from app.ai.base import Task
from app.ai.guards import check_numbers
from app.core import formatting as F
from app.core import i18n

ROLE = """You write the justification paragraph of a business target, for a report that managers and a board will read. A target that goes beyond what the company's history supports
must say, honestly, why it is still believable. Facts are supplied: what the organization's own history supports, the target, the gap, the outside factors (with the effect each is expected
to add and how certain it is) and how much of the gap they cover."""

RULES = """RULES
- `text`: 4-5 sentences in one paragraph, in this order: what history supports; what the target asks beyond it (the gap); which outside factors the plan relies on and which of them are confirmed;
  what remains unproven; and the one thing that would confirm or break the plan.
- Be honest about uncertainty. A "hoped" factor is not evidence; say so. No marketing language, no superlatives, no promises.
- Write as the company ("نعتمد"، "تدعم بياناتنا") - first person plural - because the owner will sign this text.
- Use ONLY the numbers given, each with its unit."""

EXAMPLE = """{"text": "تدعم بياناتنا مبيعات تصل إلى 120 مليون دج بنهاية السنة، بينما يطلب الهدف 150، أي 30 مليونًا فوق ما حققناه تاريخيًا. نعتمد في سد هذه الفجوة على افتتاح الفرع الثالث (18 مليونًا، مؤكَّد بعقد الإيجار) وعلى تعديل الأسعار (8 ملايين، محتمل). يبقى 4 ملايين لا يسندها إلا عامل مأمول، أي حملة التصدير، وهي غير مثبتة بعد. سنعيد تقييم الهدف عند أول ربع يُظهر أثر الفرع الجديد."}"""


class DraftJustification(Task):
    name = "draft_justification"
    description = "Draft the justification of an ambitious target from the recorded outside factors."
    schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    def prompt(self, inputs, lang):
        body = {k: inputs.get(k) for k in ("goal", "kr", "unit", "level", "target", "supported", "gap", "coverage")}
        body["factors"] = [{"title": privacy.clip(f.get("title"), 120), "kind": f.get("kind"), "effect": f.get("effect"), "certainty": f.get("certainty"),
                            "evidence": privacy.clip(f.get("evidence"), 160)} for f in (inputs.get("factors") or [])][:10]
        return voice.system(ROLE, RULES, lang, company=inputs.get("_company"), example=EXAMPLE if lang == "ar" else ""), json.dumps(body, ensure_ascii=False, default=str)

    def validate(self, data, inputs):
        lang = inputs.get("_lang", "ar")
        src = json.dumps({k: inputs.get(k) for k in ("goal", "kr", "unit", "factors")}, ensure_ascii=False, default=str)
        text = voice.check_style(privacy.clip(data.get("text"), 1200), lang, source=src)
        if not text:
            raise ValueError("empty")
        if not check_numbers(text, inputs.get("facts")):
            raise ValueError("invented number")
        return {"text": text}

    def fallback(self, inputs, lang):
        t = lambda key, **kw: i18n.t(key, lang=lang, **kw)
        u = inputs.get("unit") or ""
        v = lambda x: F.fmt_value(x, u, lang=lang)
        cov = inputs.get("coverage") or {}
        gap = inputs.get("gap") or 0
        parts = []
        if gap > 0:
            parts.append(t("ai.justify.beyond", supported=v(inputs.get("supported")), target=v(inputs.get("target")), gap=v(gap)))
        else:
            parts.append(t("ai.justify.within", supported=v(inputs.get("supported")), target=v(inputs.get("target"))))
        fs = inputs.get("factors") or []
        if fs:
            items = t("ai.justify.join").join(t("ai.justify.factor", title=f["title"], effect=v(f["effect"]), certainty=t(f"ai.justify.certainty.{f['certainty']}")) for f in fs)
            parts.append(t("ai.justify.relies", items=items))
            if gap > 0:
                parts.append(t(f"ai.justify.status.{cov.get('status', 'partial')}", confirmed=v(cov.get("confirmed", 0)), total=v(cov.get("total", 0)), gap=v(gap)))
                if cov.get("status") != "covered":
                    parts.append(t("ai.justify.close"))
        elif gap > 0:
            parts.append(t("ai.justify.none"))
        return {"text": " ".join(parts)}


task = DraftJustification()
