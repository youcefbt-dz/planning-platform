"""Task: understand what each column of an uploaded spreadsheet means (date, numeric value, category, or nothing).

Inputs  : {"sheet", "layout", "headers": [...], "rows": [[...]], "profile": [{"index","type","distinct","nulls","min","max","examples"}], "row_count"}
Output  : {"table_summary", "columns": [{"index","label","role","unit","aggregation","direction","confidence","reason"}],
           "questions": [{"column","question","options": [{"label","role","unit","aggregation"}]}]}

The model is only a *proposal*: `reconcile` checks every claim against the column's measured profile and always asks the user
when confidence is low, so a wrong guess can never go through silently. The rule-based `fallback` uses the same reconcile.
"""
from __future__ import annotations

import json
import re
import unicodedata

from app.ai import privacy
from app.ai.base import Task
from app.core import i18n

ROLES = ("date", "measure", "dimension", "ignore")
AGGS = ("sum", "avg", "last", "none")
DIRECTIONS = ("higher_better", "lower_better")
ASK_BELOW = 0.6


def norm(text) -> str:
    """Lower-case, strip accents / Arabic diacritics and letter variants so 'Quantité' == 'quantite' and 'الإيرادات' == 'الايرادات'."""
    s = unicodedata.normalize("NFKD", str(text or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub("[ـً-ٟ]", "", s)
    return s.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))


def _kw(*words):
    return tuple(norm(w) for w in words)


DATE_KW = _kw("date", "jour", "mois", "month", "periode", "period", "annee", "year", "trimestre", "quarter", "semaine", "week",
              "التاريخ", "تاريخ", "الشهر", "شهر", "الفترة", "فترة", "السنة", "سنة", "يوم", "الاسبوع", "الربع")
MEASURE_KW = _kw("chiffre d'affaires", "ca ", "vente", "sales", "revenue", "revenu", "recette", "montant", "amount", "total", "quantite", "qte", "qty",
                 "quantity", "volume", "cout", "cost", "charge", "depense", "expense", "profit", "marge", "margin", "benefice", "resultat",
                 "effectif", "headcount", "employe", "salaire", "salary", "stock", "solde", "balance", "taux", "rate", "nombre", "nb ", "count",
                 "مبيعات", "المبيعات", "ايراد", "الايرادات", "مبلغ", "المبلغ", "كمية", "الكمية", "تكلفه", "التكلفه", "مصاريف", "مصروف", "ربح",
                 "الربح", "هامش", "عدد", "الرصيد", "رصيد", "راتب", "نسبه", "معدل", "حجم", "اجمالي", "المجموع")
DIM_KW = _kw("region", "wilaya", "ville", "city", "produit", "product", "client", "customer", "agence", "branch", "magasin", "store", "famille",
             "categorie", "category", "commercial", "vendeur", "seller", "departement", "department", "service", "fournisseur", "supplier",
             "الفرع", "فرع", "المنتج", "منتج", "الولايه", "ولايه", "المنطقه", "منطقه", "العميل", "عميل", "الصنف", "صنف", "الفئه", "فئه",
             "القسم", "قسم", "المورد", "مورد", "المدينه", "البائع")
ID_KW = _kw("code", "ref", "reference", "id", "n°", "numero", "no.", "رقم", "الرقم", "رمز", "كود")
PERCENT_KW = _kw("taux", "rate", "%", "pct", "percent", "نسبه", "معدل")
STOCK_KW = _kw("effectif", "headcount", "stock", "solde", "balance", "رصيد", "الرصيد", "عدد الموظفين")
LOWER_KW = _kw("cout", "cost", "charge", "depense", "expense", "retard", "delay", "defaut", "defect", "churn", "rotation", "turnover", "absenteisme",
               "reclamation", "complaint", "تكلفه", "مصاريف", "مصروف", "تاخير", "دوران", "غياب", "شكاوي")
CURRENCY_KW = {"dzd": "DZD", "da": "DZD", "دج": "DZD", "دينار": "DZD", "eur": "EUR", "€": "EUR", "usd": "USD", "$": "USD"}


def _has(text: str, words) -> bool:
    return any(w and w in text for w in words)


def _unit_from(header_norm: str, examples) -> str:
    blob = " ".join([header_norm] + [norm(e) for e in (examples or [])[:5]])
    for token, code in CURRENCY_KW.items():
        if re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", blob):
            return code
    return ""


def heuristic(header: str, prof: dict) -> dict:
    """One column, rule-based. Confidence is deliberately modest unless both the name and the data agree."""
    h = norm(header)
    typ, rows = prof.get("type", "text"), max(1, int(prof.get("rows", 0) or 1))
    distinct = int(prof.get("distinct", 0) or 0)
    out = {"index": prof["index"], "label": privacy.clip(header) or f"#{prof['index'] + 1}", "role": "ignore", "unit": "", "aggregation": "none",
           "direction": "higher_better", "confidence": 0.5, "reason": "unsure"}
    if typ == "empty":
        return {**out, "confidence": 0.95, "reason": "empty"}
    if typ == "date":
        return {**out, "role": "date", "confidence": 0.97 if _has(h, DATE_KW) else 0.9, "reason": "date"}
    if typ == "number":
        if _has(h, ID_KW) and distinct >= 0.9 * rows:
            return {**out, "role": "ignore", "confidence": 0.7, "reason": "id"}
        pct = _has(h, PERCENT_KW) or prof.get("percent_sign")
        agg = "avg" if pct else ("last" if _has(h, STOCK_KW) else "sum")
        base = {**out, "role": "measure", "unit": "%" if pct else _unit_from(h, prof.get("examples")), "aggregation": agg,
                "direction": "lower_better" if _has(h, LOWER_KW) else "higher_better"}
        if _has(h, MEASURE_KW) or pct:
            return {**base, "confidence": 0.88, "reason": "name_and_numbers"}
        return {**base, "confidence": 0.45, "reason": "numbers_only"}
    # text
    if _has(h, DIM_KW):
        return {**out, "role": "dimension", "confidence": 0.88, "reason": "name_and_text"}
    if rows and distinct >= 0.9 * rows and distinct > 20:
        return {**out, "role": "ignore", "confidence": 0.6, "reason": "unique_text"}
    if 0 < distinct <= 50 and distinct <= 0.5 * rows:
        return {**out, "role": "dimension", "confidence": 0.55, "reason": "few_values"}
    return {**out, "confidence": 0.4, "reason": "unsure"}


def _options(typ: str, lang: str) -> list[dict]:
    t = lambda k: i18n.t(k, lang=lang)
    if typ == "number":
        return [
            {"label": t("ai.map.opt_amount"), "role": "measure", "unit": "", "aggregation": "sum"},
            {"label": t("ai.map.opt_quantity"), "role": "measure", "unit": "", "aggregation": "sum"},
            {"label": t("ai.map.opt_percent"), "role": "measure", "unit": "%", "aggregation": "avg"},
            {"label": t("ai.map.opt_level"), "role": "measure", "unit": "", "aggregation": "last"},
            {"label": t("ai.map.opt_ignore"), "role": "ignore", "unit": "", "aggregation": "none"},
        ]
    if typ == "date":
        return [{"label": t("ai.map.opt_date"), "role": "date", "unit": "", "aggregation": "none"},
                {"label": t("ai.map.opt_ignore"), "role": "ignore", "unit": "", "aggregation": "none"}]
    return [{"label": t("ai.map.opt_dimension"), "role": "dimension", "unit": "", "aggregation": "none"},
            {"label": t("ai.map.opt_ignore"), "role": "ignore", "unit": "", "aggregation": "none"}]


def _clean_options(opts, typ, lang):
    out = []
    for o in opts if isinstance(opts, list) else []:
        if not isinstance(o, dict) or o.get("role") not in ROLES or not str(o.get("label", "")).strip():
            continue
        out.append({"label": privacy.clip(o["label"], 60), "role": o["role"], "unit": privacy.clip(o.get("unit", ""), 12),
                    "aggregation": o.get("aggregation") if o.get("aggregation") in AGGS else "none"})
    return out if len(out) >= 2 else _options(typ, lang)


def reconcile(data: dict, inputs: dict, lang: str, trust_notes: bool = False) -> dict:
    """Make any proposal (model or rules) consistent with the measured data. Never trusts a claim the data contradicts."""
    profs = {p["index"]: p for p in inputs["profile"]}
    headers = inputs["headers"]
    explained = {int(k) for k in ((inputs.get("notes") or {}).get("columns") or {})} if trust_notes else set()
    proposed = {}
    for c in data.get("columns", []) if isinstance(data.get("columns"), list) else []:
        try:
            proposed[int(c["index"])] = c
        except (KeyError, TypeError, ValueError):
            continue
    cols, questions = [], []
    qdone = {}
    for q in data.get("questions", []) if isinstance(data.get("questions"), list) else []:
        try:
            qdone[int(q["column"])] = q
        except (KeyError, TypeError, ValueError):
            continue
    for idx, prof in sorted(profs.items()):
        header = headers[idx] if idx < len(headers) else ""
        base = heuristic(header, prof)
        c = proposed.get(idx)
        if c is None:
            col = base
        else:
            role = c.get("role") if c.get("role") in ROLES else "ignore"
            try:
                conf = max(0.0, min(1.0, float(c.get("confidence", 0.5))))
            except (TypeError, ValueError):
                conf = 0.5
            typ = prof.get("type")
            reason = str(c.get("reason", ""))[:160]
            contradicted = True
            if role == "date" and typ != "date":          # the data must really parse as dates
                role, conf = ("dimension" if typ == "text" else "ignore"), min(conf, 0.35)
            elif role == "measure" and typ != "number":
                role, conf = "ignore", min(conf, 0.3)
            elif role == "dimension" and typ == "date":
                role, conf = "date", min(conf, 0.5)
            elif role == "dimension" and typ == "number" and idx not in explained:
                conf = min(conf, ASK_BELOW - 0.01)        # numeric "categories" (codes, years) deserve a question, unless the owner said so
            else:
                contradicted = False
            if idx in explained and not contradicted:      # the owner explained it and the data agrees: no need to ask again
                conf = max(conf, 0.75)
            col = {"index": idx, "label": privacy.clip(c.get("label") or header) or base["label"], "role": role,
                   "unit": privacy.clip(c.get("unit", ""), 12) if role == "measure" else "",
                   "aggregation": c.get("aggregation") if c.get("aggregation") in AGGS else base["aggregation"],
                   "direction": c.get("direction") if c.get("direction") in DIRECTIONS else base["direction"],
                   "confidence": round(conf, 2), "reason": reason}
            if role == "measure" and col["aggregation"] == "none":
                col["aggregation"] = "sum"
            if role != "measure":
                col["aggregation"] = "none"
        cols.append(col)
        # unsure columns always get a question, so a doubtful guess is never accepted silently
        if col["confidence"] < ASK_BELOW and prof.get("type") != "empty":
            q = qdone.get(idx) or {}
            name = col["label"] or header
            questions.append({"column": idx,
                              "question": privacy.clip(q.get("question"), 200) or i18n.t(f"ai.map.q_{prof.get('type', 'text') if prof.get('type') in ('number', 'date') else 'text'}", lang=lang, col=name),
                              "options": _clean_options(q.get("options"), prof.get("type"), lang)})
    questions.sort(key=lambda q: next(c["confidence"] for c in cols if c["index"] == q["column"]))
    summary = str(data.get("table_summary") or "").strip()[:400] or _summary(cols, inputs, lang)
    return {"table_summary": summary, "columns": cols, "questions": questions[:8]}


def _summary(cols, inputs, lang):
    """A plain description of the table made from the mapping: when, by what, and what is measured."""
    return describe(cols, inputs.get("row_count", 0), lang)


def describe(cols, rows, lang):
    pick = lambda role: [c.get("label") or c.get("header") or "" for c in cols if c.get("role") == role]
    dates, dims, ms = pick("date"), pick("dimension"), pick("measure")
    parts = [i18n.t("ai.map.s_rows", lang=lang, rows=rows)]
    if dates:
        parts.append(i18n.t("ai.map.s_date", lang=lang, date=dates[0]))
    if dims:
        parts.append(i18n.t("ai.map.s_dim", lang=lang, dim=dims[0]))
    if ms:
        parts.append(i18n.t("ai.map.s_measures", lang=lang, measures="، ".join(ms[:4]) + (" …" if len(ms) > 4 else "")))
    return " ".join(parts)


LANG_NAMES = {"ar": "Arabic", "en": "English", "fr": "French"}

SYSTEM = """You help a business-planning application understand a spreadsheet that a company exported from Excel (accounting, sales, HR, operations).
For every column decide its ROLE:
  date       - a day, month, quarter or year (the time axis)
  measure    - a number to track over time (revenue, quantity, cost, headcount, a rate)
  dimension  - a category that splits the numbers (branch, product, region, customer, salesperson)
  ignore     - ids, free text, notes, empty or irrelevant columns
For a measure also give: unit (e.g. "DZD", "%", "kg", or "" if unknown), aggregation when several rows fall in one month
(sum for flows like sales or costs, avg for rates and prices, last for stocks like headcount or balance), and direction
(lower_better for costs, delays, defects, turnover; otherwise higher_better).
Headers may be in Arabic, French or English, abbreviated or cryptic. Use the sample values and the column profile, not only the name.
The owner of the file may add `user_notes`: `about_the_file`, and `about_columns` (key = column index). These are facts from the person who knows the data:
follow them over your own guess for role, unit, aggregation and direction, reuse their wording in `label`, and do not ask a question about a column they
explained unless the sample values clearly contradict the note (then say so in `reason`).
Be honest about uncertainty: give a confidence from 0 to 1, and when you are below 0.6 add a short question for the user with 2-4 answer options.
Write `label`, `table_summary`, `reason`, questions and options in {language}. Keep every `reason` under 10 words and write questions only for columns below 0.6 confidence. Return only the requested JSON."""


class MapColumns(Task):
    name = "map_columns"
    description = "Classify the columns of an uploaded spreadsheet and ask the user about the ones that are unclear."
    schema = {
        "type": "object",
        "properties": {
            "table_summary": {"type": "string"},
            "columns": {"type": "array", "items": {"type": "object", "properties": {
                "index": {"type": "integer"}, "label": {"type": "string"},
                "role": {"type": "string", "enum": list(ROLES)}, "unit": {"type": "string"},
                "aggregation": {"type": "string", "enum": list(AGGS)}, "direction": {"type": "string", "enum": list(DIRECTIONS)},
                "confidence": {"type": "number"}, "reason": {"type": "string"}},
                "required": ["index", "role", "confidence"]}},
            "questions": {"type": "array", "items": {"type": "object", "properties": {
                "column": {"type": "integer"}, "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "object", "properties": {
                    "label": {"type": "string"}, "role": {"type": "string", "enum": list(ROLES)},
                    "unit": {"type": "string"}, "aggregation": {"type": "string", "enum": list(AGGS)}}, "required": ["label", "role"]}}},
                "required": ["column", "question", "options"]}},
        },
        "required": ["columns"],
    }

    def prompt(self, inputs, lang):
        prof = [{k: (privacy.clip(v) if isinstance(v, str) else v) for k, v in p.items() if k in ("index", "type", "distinct", "nulls", "min", "max", "examples")} for p in inputs["profile"]]
        for p in prof:
            if "examples" in p:
                p["examples"] = [privacy.clip(e) for e in p["examples"][:4]]
        body = {"sheet": privacy.clip(inputs.get("sheet", "")), "layout": inputs.get("layout", "long"), "row_count": inputs.get("row_count", 0),
                "headers": [privacy.clip(h) for h in inputs["headers"]], "column_profile": prof, "sample_rows": privacy.sample_rows(inputs["rows"])}
        notes = inputs.get("notes") or {}
        if notes.get("file") or notes.get("columns"):
            body["user_notes"] = {"about_the_file": privacy.clip(notes.get("file", ""), 800),
                                  "about_columns": {str(i): privacy.clip(t, 400) for i, t in (notes.get("columns") or {}).items()}}
        return SYSTEM.replace("{language}", LANG_NAMES.get(lang, "English")), json.dumps(body, ensure_ascii=False)

    def validate(self, data, inputs):
        if not isinstance(data.get("columns"), list) or not data["columns"]:
            raise ValueError("no columns in the answer")
        return reconcile(data, inputs, inputs.get("_lang", "ar"), trust_notes=True)

    def fallback(self, inputs, lang):
        cols = [heuristic(inputs["headers"][p["index"]] if p["index"] < len(inputs["headers"]) else "", p) for p in inputs["profile"]]
        return reconcile({"columns": cols}, {**inputs, "_lang": lang}, lang)


task = MapColumns()
