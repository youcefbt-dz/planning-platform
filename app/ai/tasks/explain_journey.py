"""Explain an organization's journey map as a short, grounded spoken briefing.

The model chooses what deserves narration and how to say it. Every figure and
entity is supplied by the server and checked before it reaches the browser.
"""
from __future__ import annotations

import json

from app.ai import privacy, voice
from app.ai.base import Task
from app.ai.guards import check_numbers

ROLE = """You are the chief-of-staff narrator of an organization's strategy map.
The listener is a manager looking at the map while you explain it aloud. Speak naturally,
with calm confidence, like a concise executive briefing — never like a screen reader."""

RULES = """OUTPUT
Return 3 to 6 narration segments. Each segment is one short paragraph of 1–2 sentences.
For each segment return only:
- kind: exactly `org`, `unit`, or `goal`
- id: an exact id from the supplied organization, department or goal lists
- text: the spoken Arabic paragraph (roughly 25–45 words)

STORY
1. Start with `org`: explain the overall position using the current progress and elapsed-time comparison.
2. Explain the one or two most important goals or departments. Prioritize off-track, at-risk, and goals furthest behind expected progress. If a focus target is supplied, explain it first after the opening.
3. Finish with `org`: give one practical management priority grounded in the statuses and relationships you were given.

FACTUAL DISCIPLINE
- Use only the facts, names and numbers in the input. Do not invent a cause, forecast, owner, event, or recommendation that needs missing evidence.
- A status is a signal, not an explanation of why it happened. Say what is visible and what should be checked.
- Never claim an objective is complete unless its status says completed.
- Do not read every number. Explain what the figures mean together.
- Use the exact goal or department names when referring to them. Do not create new names.
- If time progress is unavailable, do not compare progress with time.

STYLE
- Write in clear Modern Standard Arabic suitable for speaking aloud.
- Avoid headings, bullets, markdown, emoji, and English terms.
- Use short, natural sentences, not stiff translations or robotic repetition.
- Never open with filler such as "من الجدير بالذكر" or end with pleasantries.
- Keep each segment under 300 characters where possible.
- Output JSON only."""


class ExplainJourney(Task):
    name = "explain_journey"
    description = "Create a concise, grounded spoken briefing for the organization's strategy map."
    schema = {
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "minItems": 3,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["org", "unit", "goal"]},
                        "id": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["kind", "id", "text"],
                },
            }
        },
        "required": ["segments"],
    }

    def prompt(self, inputs, lang):
        body = {
            "organization": inputs.get("org"),
            "performance": inputs.get("stats"),
            "departments": inputs.get("units") or [],
            "goals": inputs.get("goals") or [],
            "dependencies": inputs.get("dependencies") or [],
            "focus_target": inputs.get("focus_target"),
        }
        return voice.system(ROLE, RULES, lang, company=inputs.get("_company")), json.dumps(body, ensure_ascii=False)

    def validate(self, data, inputs):
        units = {str(x["id"]): x for x in inputs.get("units") or []}
        goals = {str(x["id"]): x for x in inputs.get("goals") or []}
        allowed = {("org", "org")}
        allowed.update(("unit", key) for key in units)
        allowed.update(("goal", key) for key in goals)

        nums = []
        for value in (inputs.get("stats") or {}).values():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                nums.append(value)
        for group in (inputs.get("units") or [], inputs.get("goals") or []):
            for row in group:
                for value in row.values():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        nums.append(value)
                for kr in row.get("key_results", []):
                    for value in kr.values():
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            nums.append(value)

        source = json.dumps({k: inputs.get(k) for k in ("org", "stats", "units", "goals", "dependencies", "focus_target")}, ensure_ascii=False)
        out, seen = [], set()
        for item in data.get("segments") if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            kind, entity_id = str(item.get("kind", "")), str(item.get("id", ""))
            if (kind, entity_id) not in allowed or (kind, entity_id) in seen and kind != "org":
                continue
            try:
                spoken = voice.check_style(privacy.clip(item.get("text"), 320), inputs.get("_lang", "ar"), source=source)
            except ValueError:
                continue
            if len(spoken) < 25 or not check_numbers(spoken, nums):
                continue
            if kind != "org":
                seen.add((kind, entity_id))
            out.append({"kind": kind, "id": entity_id, "text": spoken})
            if len(out) >= 6:
                break

        # Keep the narrative coherent: it must open and close on the organization.
        if len(out) < 3 or out[0]["kind"] != "org" or out[-1]["kind"] != "org":
            raise ValueError("the narration must open and close with the organization and contain at least one grounded focus")
        if (inputs.get("goals") or inputs.get("units")) and not any(x["kind"] in ("unit", "goal") for x in out[1:-1]):
            raise ValueError("the narration must explain at least one supplied department or goal")
        return {"segments": out}

    def fallback(self, inputs, lang):
        stats = inputs.get("stats") or {}
        org_name = (inputs.get("org") or {}).get("name") or "المؤسسة"
        progress = int(stats.get("journey") or 0)
        elapsed = stats.get("time")
        risk = int(stats.get("goals_at_risk") or 0)
        off = int(stats.get("goals_off_track") or 0)
        completed = int(stats.get("goals_completed") or 0)
        total = int(stats.get("goals_count") or len(inputs.get("goals") or []))
        opening = f"يبلغ التقدم الحالي في {org_name} {progress}%."
        if elapsed is not None:
            gap = progress - int(elapsed)
            if gap > 0:
                opening += f" يتقدم الإنجاز على الوقت المنقضي بفارق {gap} نقاط."
            elif gap < 0:
                opening += f" ويتأخر الإنجاز عن الوقت المنقضي بفارق {abs(gap)} نقاط."
            else:
                opening += " ويتوافق الإنجاز مع الوقت المنقضي من الدورة."
        if total:
            opening += f" عدد الأهداف المسجلة {total}؛ منها {completed} مكتملة و{risk + off} تحتاج إلى متابعة." if (risk + off) else f" ويبلغ عدد الأهداف المسجلة {total}، ولا تظهر أهداف متأخرة عن مسارها حاليًا."
        out = [{"kind": "org", "id": "org", "text": opening}]

        focus = inputs.get("focus_target") or {}
        goals = list(inputs.get("goals") or [])
        priority = lambda x: (0 if x.get("status") == "off_track" else 1 if x.get("status") == "at_risk" else 2,
                              int(x.get("progress") or 0) - int(x.get("expected") or 0))
        goals.sort(key=priority)
        if focus.get("kind") == "goal":
            goals.sort(key=lambda x: (0 if str(x.get("id")) == str(focus.get("id")) else 1, *priority(x)))
        elif focus.get("kind") == "unit":
            unit_goals = sorted((x for x in goals if str(x.get("unit_id")) == str(focus.get("id"))), key=priority)
            other_goals = [x for x in goals if str(x.get("unit_id")) != str(focus.get("id"))]
            goals = unit_goals + other_goals

        if not goals and focus.get("kind") != "unit":
            for unit in (inputs.get("units") or [])[:2]:
                out.append({"kind": "unit", "id": str(unit["id"]),
                            "text": f"قسم «{unit.get('name') or 'القسم'}» لا يضم أهدافًا مسجلة حاليًا؛ أضف أهدافه حتى يظهر إسهامه في تنفيذ خطة المؤسسة."})

        if focus.get("kind") == "unit":
            unit = next((x for x in (inputs.get("units") or []) if str(x.get("id")) == str(focus.get("id"))), None)
            if unit:
                name = unit.get("name") or "القسم"
                unit_count = int(unit.get("goals_count") or 0)
                unit_text = (f"لا توجد أهداف مسجلة في قسم «{name}» حتى الآن."
                             if not unit_count else
                             f"عدد الأهداف المسجلة في قسم «{name}» هو {unit_count}، ومتوسط التقدم فيها {int(unit.get('average_progress') or 0)}%.")
                if int(unit.get("off_track") or 0) or int(unit.get("at_risk") or 0):
                    unit_text += " توجد أهداف تحتاج إلى متابعة داخل هذا القسم؛ ابدأ بمراجعة النتائج الرئيسية المرتبطة بها."
                else:
                    unit_text += " لا تظهر أهداف متأخرة عن مسارها في هذا القسم وفق البيانات الحالية."
                out.append({"kind": "unit", "id": str(unit["id"]), "text": unit_text})

        selected = goals[:2]
        for goal in selected:
            title = goal.get("title") or "الهدف"
            p, e = int(goal.get("progress") or 0), int(goal.get("expected") or 0)
            text = f"يبلغ التقدم في هدف «{title}» {p}%، مقابل {e}% متوقعة حتى الآن."
            if goal.get("status") == "off_track":
                text += " الهدف خارج المسار، ويحتاج إلى مراجعة النتائج الرئيسية المرتبطة به وتحديد موضع التعثر."
            elif goal.get("status") == "at_risk":
                text += " الهدف معرّض للخطر؛ راجع النتائج الرئيسية التي لم تواكب المسار المتوقع."
            elif goal.get("status") == "completed":
                text += " الهدف مكتمل وفق الحالة المسجلة في المخطط."
            elif p < e:
                text += " التقدم أقل من المتوقع، لذا ينبغي التحقق من أحدث تحديثات النتائج الرئيسية."
            else:
                text += " التقدم يواكب المسار المتوقع أو يتجاوزه وفق البيانات الحالية."
            out.append({"kind": "goal", "id": str(goal["id"]), "text": text})

        if len(out) == 1:
            out.append({"kind": "org", "id": "org", "text": "لا توجد أهداف كافية لتقديم قراءة تفصيلية. أضف أهدافًا ونتائج رئيسية ليتضح ترابط التنفيذ داخل المؤسسة."})
        closing = "الأولوية الآن هي متابعة الأهداف التي خرجت عن المسار، ثم مراجعة الأهداف المعرّضة للخطر، مع تحديث بيانات النتائج قبل اتخاذ قرار بشأن أسباب التعثر."
        if not risk and not off:
            closing = "حافظ على وتيرة التحديث، وراجع النتائج الرئيسية دوريًا حتى تبقى قراءة التقدم مبنية على بيانات حديثة."
        out.append({"kind": "org", "id": "org", "text": closing})
        # Do not duplicate the same target: merge the closing into the first org segment when necessary.
        return {"segments": out[:6]}


task = ExplainJourney()
