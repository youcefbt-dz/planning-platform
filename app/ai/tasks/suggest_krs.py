"""Task: propose key results for an objective from the organization's own uploaded series.

The model only CHOOSES which series fits the objective and phrases the key result; the numbers (start, the three target levels) are computed
from the series by the reality engine afterwards. A suggestion that names a series the organization does not have is dropped.

Inputs : {"objective": {title, rationale}, "series": [{id, name, unit, direction, latest, dataset}]}
Output : {"krs": [{"series_id", "title", "type"}], "matched": bool}
"""
from __future__ import annotations

import json

from app.ai import privacy
from app.ai.base import Task
from app.core import i18n
from app.core.textnorm import norm_word as _norm

LANG_NAMES = {"ar": "Arabic", "en": "English", "fr": "French"}
TYPES = ("increase", "decrease", "stay_above", "stay_below")
SYSTEM = """You help a manager turn an objective into measurable key results using the data they already uploaded. Answer in {language}.
You receive the objective and the list of their data series (id, name, unit, direction, latest value). Choose up to 3 series that would
genuinely prove progress on THIS objective and phrase each key result as an outcome (a measured result, never an activity). Do not invent series ids
or numbers. `type`: increase | decrease | stay_above | stay_below, consistent with the series direction. If nothing fits, return an empty list. Return only the JSON."""

# words that mean the same thing in the three languages (normalised); used by the offline matcher
GROUPS = [
    {"sales", "sale", "revenue", "revenues", "turnover", "ventes", "vente", "chiffre", "affaires", "ca", "مبيعات", "ايرادات", "دخل", "رقم"},
    {"margin", "margins", "marge", "marges", "profit", "profits", "benefice", "هامش", "ربح", "ارباح", "ربحيه"},
    {"customer", "customers", "client", "clients", "churn", "retention", "satisfaction", "nps", "عملاء", "عميل", "زبائن", "زبون", "رضا"},
    {"delivery", "deliveries", "livraison", "livraisons", "shipping", "delay", "delays", "delai", "delais", "توصيل", "تسليم", "تاخير", "تاخيرات", "شحن"},
    {"cost", "costs", "cout", "couts", "charges", "expense", "expenses", "spend", "تكلفه", "تكاليف", "مصاريف", "نفقات", "مصروفات"},
    {"employee", "employees", "staff", "headcount", "effectif", "effectifs", "personnel", "turnover", "موظفين", "موظف", "عمال", "عماله", "قوه"},
    {"quality", "qualite", "defect", "defects", "defaut", "defauts", "rejet", "return", "returns", "retours", "جوده", "عيوب", "مرتجعات", "مردود"},
    {"market", "marche", "share", "part", "حصه", "سوق"},
    {"production", "output", "volume", "units", "unites", "produced", "انتاج", "كميه", "كميات", "وحدات"},
    {"stock", "inventory", "inventaire", "stocks", "مخزون", "مخزن"},
    {"time", "cycle", "lead", "duree", "temps", "وقت", "مده", "زمن"},
]


def _tokens(text: str) -> set[str]:
    out = set()
    for raw in (text or "").replace("_", " ").replace("-", " ").split():
        w = _norm(raw)
        if w.startswith("ال") and len(w) > 4:
            w = w[2:]
        if len(w) >= 2:
            out.add(w)
            if w.endswith("s") and len(w) > 3:
                out.add(w[:-1])
    return out


def _score(obj_tokens: set[str], name: str) -> int:
    st = _tokens(name)
    score = 3 * len(obj_tokens & st)
    for g in GROUPS:
        if obj_tokens & g and st & g:
            score += 2
    return score


class SuggestKRs(Task):
    name = "suggest_krs"
    description = "Pick the uploaded series that would measure an objective and phrase key results for them."
    schema = {"type": "object", "properties": {"krs": {"type": "array", "items": {"type": "object", "properties": {
        "series_id": {"type": "integer"}, "title": {"type": "string"}, "type": {"type": "string"}}, "required": ["series_id", "title", "type"]}}}, "required": ["krs"]}

    def prompt(self, inputs, lang):
        o = inputs.get("objective") or {}
        body = {"objective": {"title": privacy.clip(o.get("title"), 200), "why_it_matters": privacy.clip(o.get("rationale"), 300)},
                "series": [{"id": s["id"], "name": privacy.clip(s.get("name"), 80), "unit": s.get("unit"), "direction": s.get("direction"), "latest": s.get("latest")}
                           for s in (inputs.get("series") or [])][:40]}
        return SYSTEM.replace("{language}", LANG_NAMES.get(lang, "English")), json.dumps(body, ensure_ascii=False, default=str)

    def validate(self, data, inputs):
        ids = {s["id"]: s for s in inputs.get("series") or []}
        out, seen = [], set()
        for k in data.get("krs") or []:
            try:
                sid, title, typ = int(k["series_id"]), privacy.clip(k["title"], 160), k.get("type")
            except (KeyError, TypeError, ValueError):
                continue
            if sid in ids and sid not in seen and title:
                seen.add(sid)
                out.append({"series_id": sid, "title": title, "type": typ if typ in TYPES else ("decrease" if ids[sid].get("direction") == "lower_better" else "increase")})
        return {"krs": out[:3], "matched": bool(out)}

    def fallback(self, inputs, lang):
        series = [s for s in inputs.get("series") or []]
        o = inputs.get("objective") or {}
        toks = _tokens(o.get("title", "")) | _tokens(o.get("rationale", ""))
        ranked = sorted(((_score(toks, s["name"]) - (1 if " — " in s["name"] else 0), s) for s in series), key=lambda x: -x[0])
        picks = [s for sc, s in ranked if sc > 0][:3]
        matched = bool(picks)
        if not picks:
            picks = [s for s in series if " — " not in s["name"]][:3]
        return {"krs": [{"series_id": s["id"], "title": s["name"], "type": "decrease" if s.get("direction") == "lower_better" else "increase"} for s in picks], "matched": matched}


task = SuggestKRs()
