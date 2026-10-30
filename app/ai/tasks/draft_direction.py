"""Task: propose the organization's vision, mission and values, so nobody starts from a blank box.

A manager rarely writes these well on the first try, and the three boxes in the profile are the most intimidating in the product.
The model reads the sector, the size and (optionally) one sentence about what the company does, and proposes three short options for the
vision, three for the mission and six values. The user clicks one and edits it: nothing is saved by this task.
Guards: voice check on every string; no digits or invented facts about the company (a year, a count of branches, a market share);
the company's own name is never sent, so a draft never contains one.

Inputs : {"sector": key, "size": key, "about": str}
Output : {"vision": [str], "mission": [str], "values": [str]}
"""
from __future__ import annotations

import json

from app.ai import library, privacy, voice
from app.ai.base import Task

ROLE = """You help the owner of a company draft its vision, mission and values. They would rather click than write. You know the sector and size, and maybe one sentence about what they do.
Offer wording a real company would be proud to print on its wall - specific to the sector, not interchangeable with any other company's."""

RULES = """RULES
- `vision`: three options, each ONE sentence of at most 18 words about the future we want to reach (where, for whom), starting with "أن" or a noun phrase.
- `mission`: three options, each one or two sentences of at most 28 words saying what we do, for whom, and how we do it differently. Present tense, first person plural.
- `values`: exactly six, each one or two words (الجودة، النزاهة...). Pick values that fit the sector; no duplicates.
- Do not invent facts about the company: no years, no counts, no market shares, no awards, no names, no figures of any kind.
- No slogans or empty superlatives ("الأفضل"، "الرائد"، "المتميز") unless the owner's own sentence says so."""

EXAMPLE = """{"vision": ["أن نكون الشريك الأول الموثوق لعملائنا في التجارة والتوزيع", "أن يجد كل بيت وكل متجر في منطقتنا ما يحتاجه عندنا دون عناء"],
 "mission": ["نوفّر لعملائنا منتجات موثوقة بأسعار عادلة وفي الموعد، ونبني معهم علاقة طويلة قائمة على الثقة."],
 "values": ["الجودة", "النزاهة", "الالتزام بالمواعيد", "خدمة العميل", "التعلّم المستمر", "العمل الجماعي"]}"""


class DraftDirection(Task):
    name = "draft_direction"
    description = "Propose vision, mission and values wording from the sector and one sentence."
    schema = {"type": "object", "properties": {"vision": {"type": "array", "items": {"type": "string"}}, "mission": {"type": "array", "items": {"type": "string"}},
                                                "values": {"type": "array", "items": {"type": "string"}}}, "required": ["vision", "mission", "values"]}

    def prompt(self, inputs, lang):
        body = {"sector": inputs.get("sector_label") or inputs.get("sector"), "size": inputs.get("size_label") or inputs.get("size"), "what_we_do": privacy.clip(inputs.get("about"), 300)}
        return voice.system(ROLE, RULES, lang, company=None, example=EXAMPLE if lang == "ar" else ""), json.dumps(body, ensure_ascii=False)

    def validate(self, data, inputs):
        lang = inputs.get("_lang", "ar")
        src = json.dumps({"s": inputs.get("sector_label"), "a": inputs.get("about")}, ensure_ascii=False)
        def many(key, n, width):
            out = voice.clean_list(data.get(key), n, width, lang, source=src)
            return [x for x in out if not library.has_digits(x)]
        out = {"vision": many("vision", 3, 160), "mission": many("mission", 3, 260), "values": [v for v in many("values", 6, 28) if len(v.split()) <= 3]}
        if not out["vision"] and not out["mission"]:
            raise ValueError("no usable wording")
        base = library.direction(inputs.get("sector") or "")
        if not out["values"]:
            out["values"] = base["values"][:6]
        return out

    def fallback(self, inputs, lang):
        d = library.direction(inputs.get("sector") or "")
        return {"vision": d["vision"], "mission": d["mission"], "values": d["values"][:6]}


task = DraftDirection()
