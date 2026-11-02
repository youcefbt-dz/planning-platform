"""Task: understand what each column of an uploaded spreadsheet means (date, numeric value, category, or nothing).

Inputs  : {"sheet", "layout", "headers": [...], "rows": [[...]], "profile": [{"index","type","distinct","nulls","min","max","examples"}], "row_count"}
Output  : {"table_summary", "highlights": [str],
           "columns": [{"index","label","role","unit","aggregation","direction","confidence","reason","meaning"}],
           "questions": [{"column","question","options": [{"label","role","unit","aggregation"}]}]}
`meaning` is what the column MEANS in this business (not its name, not its type); `table_summary` says what the table records, at what grain and over what
period; `highlights` are things worth knowing before using the data; Every figure in any of
them must come from the profile: an answer that quotes one it was not given is rejected (and the model is told why), and a summary that does not name the
real columns is rejected as generic.

The model is only a *proposal*: `reconcile` checks every claim against the column's measured profile and always asks the user
when confidence is low, so a wrong guess can never go through silently. The rule-based `fallback` uses the same reconcile.
"""
from __future__ import annotations

import json
import re
import unicodedata

from app.ai import privacy
from app.ai.base import Task
from app.ai.guards import check_numbers, numbers_in
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


# -- what a column MEANS: well-known business concepts, used when no model answers (and as the safety net when a model's text is rejected) ----------------
CONCEPTS = {
    "delivery": _kw("livraison", "delivery", "on-time", "on time", "ontime", "تسليم", "التسليم", "توصيل", "التوصيل"),
    "margin": _kw("marge", "margin", "هامش"),
    "profit": _kw("profit", "benefice", "resultat net", "ربح", "الربح", "صافي الدخل"),
    "revenue": _kw("chiffre d'affaires", "revenue", "revenu", "recette", "ايراد", "الايرادات", "ايرادات"),
    "sales": _kw("vente", "sales", "مبيعات", "المبيعات"),
    "cost": _kw("cout", "cost", "charge", "تكلفه", "التكلفه", "تكاليف", "التكاليف"),
    "expense": _kw("depense", "expense", "مصاريف", "مصروف", "المصاريف"),
    "salary": _kw("salaire", "salary", "payroll", "راتب", "الرواتب", "اجور", "الاجور"),
    "headcount": _kw("effectif", "headcount", "employe", "employee", "عدد الموظفين", "الموظفين", "العاملين"),
    "orders": _kw("commande", "orders", "order", "طلب", "طلبات", "الطلبات"),
    "quantity": _kw("quantite", "qte", "qty", "quantity", "volume", "كميه", "الكميه", "حجم"),
    "stock": _kw("stock", "inventory", "مخزون", "المخزون"),
    "balance": _kw("solde", "balance", "رصيد", "الرصيد"),
    "price": _kw("prix", "price", "سعر", "الاسعار", "السعر"),
    "rate": _kw("taux", "rate", "pct", "percent", "%", "نسبه", "معدل"),
}


def concept_of(header: str) -> str:
    h = norm(header)
    for key, words in CONCEPTS.items():        # ordered: the most specific concepts first ("on-time delivery %" is a delivery rate, not a plain rate)
        if _has(h, words):
            return key
    return ""


def _fmt(v) -> str:
    from app.core.formatting import fmt_number
    try:
        return fmt_number(float(v), 0 if abs(float(v)) >= 100 else 1)
    except (TypeError, ValueError):
        return str(v)


def rule_meaning(header: str, col: dict, prof: dict, lang: str) -> str:
    """One or two sentences on what the column means and how it will be read, from the business concept in its name and what was measured in its values.
    Never a bare restatement of its type."""
    t = lambda k, **kw: i18n.t(k, lang=lang, **kw)
    role, typ = col.get("role"), prof.get("type")
    if role == "date":
        rng = t("ai.map.m_date_span", lo=prof.get("min"), hi=prof.get("max")) if prof.get("min") and prof.get("max") else ""
        return (t("ai.map.m_date") + " " + rng).strip()
    if role == "dimension":
        ex = "، ".join(str(x) for x in (prof.get("examples") or [])[:3])
        return t("ai.map.m_dim", name=col.get("label") or header, n=prof.get("distinct", 0), ex=ex)
    if role == "measure":
        key = concept_of(header)
        base = t(f"ai.concept.{key}") if key else t("ai.map.m_measure", name=col.get("label") or header)
        span = t("ai.map.m_range", lo=_fmt(prof["min"]), hi=_fmt(prof["max"])) if typ == "number" and prof.get("min") is not None and prof.get("max") is not None else ""
        return (base + " " + span).strip()
    return t("ai.map.m_ignore_" + ("id" if col.get("reason") == "id" else "text" if col.get("reason") == "unique_text" else "other"))


def facts_of(inputs: dict) -> list[float]:
    """Every figure a written explanation may quote: row count and what was measured per column (distinct, min, max, example values, numbers in the headers)."""
    out: list[float] = [float(inputs.get("row_count", 0) or 0), float(len(inputs.get("headers") or []))]
    for p in inputs.get("profile") or []:
        for k in ("rows", "distinct", "min", "max"):
            v = p.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(float(v))
        for e in p.get("examples") or []:
            out.extend(numbers_in(str(e)))
    for h in inputs.get("headers") or []:
        out.extend(numbers_in(str(h)))
    notes = inputs.get("notes") or {}
    out.extend(numbers_in(str(notes.get("file", "")) + " " + " ".join(str(v) for v in (notes.get("columns") or {}).values())))
    return out


def _meaning_ok(text, header: str, role: str) -> bool:
    """A meaning must say something: not empty, not just the column's name, and long enough to be a sentence."""
    s = str(text or "").strip()
    return len(s) >= 24 and norm(s) != norm(header) and role != "ignore" or (role == "ignore" and len(s) >= 12)


def _names_real_columns(text: str, cols: list[dict], need: int = 2) -> bool:
    """A summary is specific when it names the real columns (by label or by the header as written in the file), or, when the model translated the names,
    when it is a real description and not the stock sentence about "dimensions and measures"."""
    nt = norm(text)
    names = {norm(x) for c in cols if c.get("role") in ("date", "measure", "dimension") for x in (c.get("label"), c.get("header")) if x}
    if sum(1 for n in names if n and n in nt) >= min(need, len(names)):
        return True
    generic = any(norm(g) in nt for g in ("يحتوي على أبعاد", "ومقاييس", "ابعاد الفروع"))
    return len(text) >= 120 and not generic


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
            col["meaning"] = privacy.clip(c.get("meaning", ""), 320) if _meaning_ok(c.get("meaning"), header, role) else ""
            if role == "measure" and col["aggregation"] == "none":
                col["aggregation"] = "sum"
            if role != "measure":
                col["aggregation"] = "none"
        if not col.get("meaning"):
            col["meaning"] = rule_meaning(header, col, prof, lang)
        cols.append(col)
        # unsure columns always get a question, so a doubtful guess is never accepted silently
        if col["confidence"] < ASK_BELOW and prof.get("type") != "empty":
            q = qdone.get(idx) or {}
            name = col["label"] or header
            questions.append({"column": idx,
                              "question": privacy.clip(q.get("question"), 200) or i18n.t(f"ai.map.q_{prof.get('type', 'text') if prof.get('type') in ('number', 'date') else 'text'}", lang=lang, col=name),
                              "options": _clean_options(q.get("options"), prof.get("type"), lang)})
    questions.sort(key=lambda q: next(c["confidence"] for c in cols if c["index"] == q["column"]))
    summary = re.sub(r"\s*\n+\s*", " ", str(data.get("table_summary") or "").strip())[:1000]
    if not summary or not _names_real_columns(summary, cols):
        summary = _summary(cols, inputs, lang)             # a generic summary that names nothing is never shown
    span = [str(profs[c["index"]].get(k)) for c in cols if c["role"] == "date" and c["index"] in profs for k in ("min", "max") if profs[c["index"]].get(k)]
    restate = lambda s: any(x and x in s for x in span) or norm(s).startswith(norm("تغطي"))
    highlights = [privacy.clip(x, 240) for x in (data.get("highlights") if isinstance(data.get("highlights"), list) else [])
                  if isinstance(x, str) and len(x.strip()) > 12 and not restate(x)][:4]
    if not highlights:
        highlights = rule_insights(cols, inputs, lang)[0]
    return {"table_summary": summary, "columns": cols, "questions": questions[:8], "highlights": highlights}


def _summary(cols, inputs, lang):
    """A plain description of the table made from the mapping: what one row stands for, the period, how rows are split, what is measured."""
    profs = {p["index"]: p for p in inputs.get("profile") or []}
    rich = [{**c, **{k: profs[c["index"]][k] for k in ("min", "max", "distinct") if c.get("index") in profs and profs[c["index"]].get(k) is not None}} for c in cols]
    return describe(rich, inputs.get("row_count", 0), lang)


def describe(cols, rows, lang):
    """What the table is, in plain sentences: how big, what one row stands for, the period it covers, how the rows are split, what is measured."""
    pick = lambda role: [c.get("label") or c.get("header") or "" for c in cols if c.get("role") == role]
    dates, dims, ms = pick("date"), pick("dimension"), pick("measure")
    first = lambda role: next((c for c in cols if c.get("role") == role), {})
    t = lambda k, **kw: i18n.t(k, lang=lang, **kw)
    parts = [t("ai.map.s_rows", rows=rows)]
    d, dm = first("date"), first("dimension")
    if dates and dims:
        parts.append(t("ai.map.s_grain", dim=dims[0], date=dates[0]))
    elif dates:
        parts.append(t("ai.map.s_date", date=dates[0]))
    elif dims:
        parts.append(t("ai.map.s_dim", dim=dims[0]))
    if dates and d.get("min") and d.get("max"):
        parts.append(t("ai.map.s_period", lo=d["min"], hi=d["max"]))
    if dims and dm.get("distinct"):
        parts.append(t("ai.map.s_dim_count", dim=dims[0], n=dm["distinct"]))
    if ms:
        parts.append(t("ai.map.s_measures", measures="، ".join(ms[:6]) + (" …" if len(ms) > 6 else "")))
    return " ".join(parts)


def _months_between(lo, hi):
    try:
        (y1, m1), (y2, m2) = (int(str(lo)[:4]), int(str(lo)[5:7])), (int(str(hi)[:4]), int(str(hi)[5:7]))
        return (y2 - y1) * 12 + (m2 - m1) + 1
    except (ValueError, TypeError):
        return 0


def rule_insights(cols: list[dict], inputs: dict, lang: str) -> tuple[list[str], list[dict]]:
    """What is worth knowing about the file, and indicators that follow from its columns, from the measured profile alone."""
    t = lambda k, **kw: i18n.t(k, lang=lang, **kw)
    profs = {p["index"]: p for p in inputs.get("profile") or []}
    notes, derived = [], []
    d = next((c for c in cols if c["role"] == "date"), None)
    if d and profs.get(d["index"], {}).get("min") and profs[d["index"]].get("max"):
        months = _months_between(profs[d["index"]]["min"], profs[d["index"]]["max"])
        if 0 < months < 24:
            notes.append(t("ai.map.h_short", months=months))
    for c in cols:
        pr = profs.get(c["index"], {})
        if c["role"] in ("measure", "dimension", "date") and (pr.get("nulls") or 0) >= 0.02:
            notes.append(t("ai.map.h_nulls", col=c["label"], pct=round(pr["nulls"] * 100)))
        if c["role"] == "measure" and c.get("aggregation") == "avg":
            notes.append(t("ai.map.h_avg", col=c["label"]))
    by = {}
    for c in cols:
        if c["role"] == "measure":
            by.setdefault(concept_of(c.get("header") or c["label"]), c["label"])
    rev = by.get("revenue") or by.get("sales")
    cost = by.get("cost") or by.get("expense")
    if rev and cost:
        derived.append({"name": t("ai.map.d_margin"), "how": t("ai.map.d_margin_how", rev=rev, cost=cost)})
    if rev and by.get("orders"):
        derived.append({"name": t("ai.map.d_aov"), "how": t("ai.map.d_aov_how", rev=rev, orders=by["orders"])})
    if rev and by.get("headcount"):
        derived.append({"name": t("ai.map.d_per_head"), "how": t("ai.map.d_per_head_how", rev=rev, hc=by["headcount"])})
    return notes[:4], derived[:3]


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

EXPLAIN LIKE A SENIOR DATA ANALYST. The person reading this does not know the file; your words are what they understand it by.
- `meaning` (every column, 1-2 sentences, max ~45 words): what the column MEANS in this business and how it will be read. Say what it counts or records, what a
  high or low value tells a manager, and any caution the sample shows (a stock rather than a flow, a rate that must not be added up, amounts that look like
  thousands, gaps). Never repeat the column's name or its type as the explanation ("a numeric column", "measures sales" is NOT an explanation).
- `table_summary`: ONE flowing paragraph (4-6 sentences, 70-110 words) that tells the reader what this table MEANS, as if explaining the file to a colleague who has not opened it.
  Say: what business activity it records and what ONE ROW stands for; the period it covers and how the rows are split (the main dimension and how many values it has); what the groups of
  numbers measure and how they relate to each other (for example units sold and the revenue they bring, or a cost against the revenue it serves); and what a manager can learn from it or plan with it.
  Write it as prose: no list, no bullets, no column-by-column inventory, no heading. Refer to columns by their names in the file where it helps, and never open with a stock phrase like
  "a table that contains dimensions and measures". Do not repeat the same words in every sentence.
- `highlights` (0-4 short sentences): WARNINGS and CHECKS only, things a manager must know before planning on this data: missing values, a history too short for seasonality, an id column,
  a measure that is a stock or a rate and must not be added up, amounts that look like thousands, a column that duplicates another. NEVER restate what the summary already says (the period, the
  row count, the branches, the column names, a min-max range). If the profile shows nothing worth a warning, return an empty list.
- FIGURES: quote only numbers present in the profile, the headers or the sample rows (row count, distinct counts, min, max, dates). Do not compute or invent any other.
Write `label`, `table_summary`, `reason`, `meaning`, `highlights`, questions and options in {language}. Keep every `reason` under 10 words and write questions only for columns below 0.6 confidence. Return only the requested JSON."""


class MapColumns(Task):
    name = "map_columns"
    description = "Classify the columns of an uploaded spreadsheet and ask the user about the ones that are unclear."
    schema = {
        "type": "object",
        "properties": {
            "table_summary": {"type": "string"},
            "highlights": {"type": "array", "items": {"type": "string"}},
            "columns": {"type": "array", "items": {"type": "object", "properties": {
                "index": {"type": "integer"}, "label": {"type": "string"},
                "role": {"type": "string", "enum": list(ROLES)}, "unit": {"type": "string"},
                "aggregation": {"type": "string", "enum": list(AGGS)}, "direction": {"type": "string", "enum": list(DIRECTIONS)},
                "confidence": {"type": "number"}, "reason": {"type": "string"}, "meaning": {"type": "string"}},
                "required": ["index", "role", "confidence", "meaning"]}},
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
        facts = facts_of(inputs)
        rules = bool(data.get("_rules"))                # the rules' own sentences are computed from the profile: nothing to check
        strict = inputs.get("_attempt", 0) == 0        # first try: send the model back to fix an invented figure; second try: drop just that text and use the rules' own
        data = {**data, "columns": [dict(c) if isinstance(c, dict) else c for c in data["columns"]]}
        for c in data["columns"]:
            if not rules and isinstance(c, dict) and isinstance(c.get("meaning"), str) and not check_numbers(c["meaning"], facts):
                if strict:
                    raise ValueError(f"the meaning of column {c.get('index')} quotes a figure that is not in the profile or the sample")
                c["meaning"] = ""
        for k in ("table_summary", "highlights"):
            v = data.get(k)
            text = " ".join(v) if isinstance(v, list) else str(v or "")
            if text and not rules and not check_numbers(text, facts):
                if strict:
                    raise ValueError(f"{k} quotes a figure that is not in the profile or the sample")
                data[k] = [] if isinstance(v, list) else ""
        out = reconcile(data, inputs, inputs.get("_lang", "ar"), trust_notes=True)
        return out

    def fallback(self, inputs, lang):
        cols = [heuristic(inputs["headers"][p["index"]] if p["index"] < len(inputs["headers"]) else "", p) for p in inputs["profile"]]
        return {**reconcile({"columns": cols}, {**inputs, "_lang": lang}, lang), "_rules": True}


task = MapColumns()
