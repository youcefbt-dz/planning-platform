"""Task: turn a typed request ("لماذا ارتفع رقم الأعمال؟") into up to three chart SPECS, or into ONE clarifying question. Never code, never numbers, never SVG.

The renderer (app/modules/data/dashboard.py) draws only specs that pass `validate_spec` against the series the organization owns, so the model chooses
WHAT to show (kind, measure, branch, window) and nothing else; every sentence on screen is computed by code. The names sent are the measure and branch
names (the file's own headers) with their unit and the span of months; no values leave the machine.

Inputs : {"request": str, "catalog": [{"id", "name", "unit", "months", "branches": [str]}]}
Output : {"charts": [{"kind": trend|branches|contribution|heatmap|compare, "measure": id, "measure2": id|null (compare only), "branch": str|null, "months": int|null, "title": str}],
          "ask": str|null, "choices": [str], "missing": [str]}      # `ask` only when the request cannot be answered without a choice; `choices` are names from the catalog
"""
from __future__ import annotations

import json
import re

from app.ai import privacy
from app.ai.base import Task

KINDS = ("trend", "branches", "contribution", "heatmap", "compare", "share", "ranking", "bars", "stacked", "growth", "cumulative", "scatter", "table", "kpi")

SYSTEM = """You are the chart assistant inside a business-planning application used by managers. The request is in Arabic (sometimes mixed with English terms).
Decide what the manager wants to SEE and answer with up to 3 charts, using only the measures and branches listed in `catalog`.

Chart kinds (the manager may ask for ANY of these, in any wording; pick the one that shows what they asked):
- trend: one measure over time as a line, optionally for one branch. "how did X evolve", "show X", "X for branch Y", "last N months".
- bars: columns over time (`by`: month | quarter | year). "monthly/quarterly/yearly X", "bar chart of X", "X per year".
- growth: change versus the same period last year, as columns. "growth of X", "is X growing", "year over year".
- cumulative: running total this year against previous years (sum measures only). "year to date", "cumulative X", "are we ahead of last year".
- share: a donut of each branch's share of the total. "pie / donut / share / proportion of X by branch", "distribution of X among branches".
- ranking: branches as horizontal bars, best first. "rank branches by X", "top branches".
- stacked: columns over time split by branch (sum measures only). "composition of X by branch over time".
- branches: small multiples, one line per branch with its change. "compare branches", "how is each branch doing".
- contribution: which branches moved the total versus last year (a bridge). "why did X rise/fall", "what drove it".
- heatmap: month by year. Seasonality, "which months are strong/weak".
- compare: TWO measures as lines, both indexed to 100 (`measure` + `measure2`). "compare X and Y", "X versus Y".
- scatter: TWO measures against each other, one dot per month, with the trend line and correlation (`measure` on x, `measure2` on y). "relationship between X and Y", "does X depend on Y".
- table: the last 12 periods in a table with the change. "table of X", "give me the numbers".
- kpi: one big number with its change and a small line. "how much is X now", "latest X".
Optional: `by` (month | quarter | year) for bars/growth/stacked/table when the request says monthly/quarterly/yearly, otherwise null.
If the request asks for a drawing the application cannot make (a map, a radar, a box plot ...), draw the CLOSEST kind and say so in `note` (one short Arabic sentence).

Rules:
1. A question about a cause ("لماذا", "ما سبب") -> contribution first, then trend of the same measure.
2. A broad request ("حلّل", "ملخص", "كيف حال X؟", "نظرة على X") -> trend + contribution + branches (only kinds that make sense for that measure).
3. If the request names a branch, use trend (or bars/growth/kpi/table, as asked) with that branch.
4. months: a number of months (3-120) only if the request states a period ("آخر 6 أشهر" -> 6, "سنتين" -> 24), otherwise null.
5. If the request could mean two or more different measures and the text does not decide, do NOT guess: return an empty charts list, put ONE short Arabic question in `ask`,
   and put the candidate measure/branch names, copied exactly from the catalog, in `choices` (2-5 names).
6. Never invent an id, a measure or a branch. The catalog names may be in English while the request is in Arabic (or the reverse): match by meaning
(مبيعات = Sales/Revenue, ربح = Profit, وحدات = Units, تكلفة = Cost). If the request mentions something the catalog does not contain (for example customers when
there is no customers measure), do NOT substitute another measure silently: return empty charts, put the missing thing in `missing`, and ask. If the request is unrelated to the catalog, return empty charts and ask which measure they mean.
7. title: at most 60 characters, Arabic, describing what the chart answers (not just the measure name).

Examples (catalog: id 1 "رقم الأعمال (مليون دج)" with branches الجزائر/وهران/قسنطينة, id 2 "مدة التسليم (يوم)" without branches):
"لماذا تراجعت المبيعات؟" -> charts: contribution(1) then trend(1)
"قارن وهران بالجزائر" -> charts: branches(1)
"مدة التسليم في آخر 6 أشهر" -> charts: trend(2, months 6)
"كيف حالنا؟" -> no charts; ask: "عن أي مؤشر تريد أن تعرف؟"; choices: both names
"ارسم دائرة نسبية للمبيعات حسب كل فرع" -> charts: share(1)   (only if the measure has branches; if its branch list is empty, draw trend(1) and explain in `note` that no branch split exists)
"أعمدة المبيعات سنويا" -> charts: bars(1, by year)
"هل المبيعات تتبع الإعلانات؟" -> charts: scatter(measure=sales, measure2=ads)
Return JSON only."""

# -- Arabic matching used by the fallback --------------------------------------------------------------------------------------------
_DIACRITICS = re.compile("[ً-ٰٟـ]")
_SYN = (("مبيعات", "بيع", "ايرادات", "عائدات", "مداخيل", "رقم", "اعمال", "ايراد", "sales", "sale", "revenue", "turnover", "sold", "income"),
        ("هامش", "ربح", "ربحيه", "ارباح", "profit", "margin", "gross"),
        ("تسليم", "توصيل", "موعد", "تاخير", "delivery", "lead", "ontime"),
        ("مده", "زمن", "وقت", "ايام", "days", "time", "duration"),
        ("موظف", "عمال", "عماله", "توظيف", "employees", "employee", "staff", "headcount"),
        ("مصاريف", "تكاليف", "نفقات", "تكلفه", "cost", "costs", "expenses", "expense"),
        ("وحدات", "كميه", "كميات", "units", "unit", "quantity", "volume"),
        ("زبائن", "زبون", "عملاء", "عميل", "customers", "customer", "clients", "client"))


def norm(s: str) -> str:
    s = _DIACRITICS.sub("", s or "").lower()
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي")):
        s = s.replace(a, b)
    return s


_PREFIXES = ("وبال", "بال", "لل", "وال", "فال", "كال", "ال", "و", "ب", "ل", "ف")
_SUFFIXES = ("ات", "ون", "ين", "ان", "ه", "ي")


def forms(w: str) -> set[str]:
    """The word and the shapes it may have lost a prefix or suffix to: الفروع -> {الفروع, فروع, ...}."""
    out = {w}
    bases = {w}
    for p in _PREFIXES:
        if w.startswith(p) and len(w) - len(p) >= 2:
            bases.add(w[len(p):])
    out |= bases
    for x in list(bases):
        for suf in _SUFFIXES:
            if x.endswith(suf) and len(x) - len(suf) >= 3:
                out.add(x[: -len(suf)])
    return out


def tokens(s: str) -> list[str]:
    s = re.sub(r"\([^)]*\)", " ", norm(s))
    return re.findall(r"[\u0621-\u064a]{2,}|[a-z]{3,}", s)


_SYN_FORMS = tuple(set().union(*(forms(w) for w in g)) for g in _SYN)


def _same(a: str, b: str) -> bool:
    fa, fb = forms(a), forms(b)
    if fa & fb:
        return True
    if any(len(x) >= 4 and len(y) >= 4 and (x.startswith(y) or y.startswith(x)) for x in fa for y in fb):
        return True
    return any((fa & g) and (fb & g) for g in _SYN_FORMS)


def _has(words: list[str], vocab: tuple[str, ...]) -> bool:
    return any(_same(w, v) for w in words for v in vocab)


def _months(text: str) -> int | None:
    t = norm(text).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    if "سنتين" in t or "عامين" in t:
        return 24
    if "نصف سنه" in t or "ستة اشهر" in t or "ست اشهر" in t:
        return 6
    if "ثلاثه اشهر" in t or "ربع سنه" in t:
        return 3
    m = re.search(r"(\d+)\s*(شهر|اشهر|سنه|سنين|سنوات|عام|اعوام)", t)
    if m:
        n = int(m.group(1))
        return max(3, min(120, n * (12 if m.group(2) in ("سنه", "سنين", "سنوات", "عام", "اعوام") else 1)))
    if re.search(r"(آخر|اخر)\s*سنه|السنه الاخيره|عام كامل", t):
        return 12
    return None


_WHY = ("سبب", "ساهم", "مساهم", "حرك", "لماذا", "تغير", "ارتفع", "انخفض", "تراجع", "نزل", "هبط", "زاد", "نقص", "وراء")
_SEASON = ("موسم", "فصل", "حراري", "خريط", "اقوي", "اضعف")
_COMPARE = ("فرع", "فروع", "قارن", "مقارن", "بين", "وكال", "موقع", "ترتيب", "افضل", "اسوا", "اضعف")
_BROAD = ("حلل", "تحليل", "ملخص", "لخص", "نظره", "كيف حال", "حالنا", "وضع", "اشرح")


def _any(n: str, vocab) -> bool:
    return any(v in n for v in vocab)


_SHAPES = (("scatter", ("علاقه بين", "علاقه", "ارتباط", "انتشار", "scatter", "correlation")), ("stacked", ("متراكمه", "مكدس", "stack", "تركيبه", "تركيب ")),
           ("cumulative", ("تراكمي", "تراكم", "cumulative", "ytd", "منذ بداية السنه", "منذ بدايه السنه")), ("share", ("دائره", "دائري", "دايره", "كعكه", "حصه", "نسبه كل", "نسبه ", "توزيع", "pie", "donut", "share")),
           ("ranking", ("ترتيب", "رتب", "rank", "اكبر الفروع", "افضل الفروع")), ("growth", ("نمو", "معدل النمو", "growth", "yoy")), ("table", ("جدول", "table")),
           ("kpi", ("بطاقه", "kpi", "اخر قيمه", "اخر رقم", "كم بلغ", "كم كان", "كم هو", "كم هي")), ("bars", ("اعمده", "عمود", "اعمدة", "bar chart", "columns", "هستوغرام")))


def _by(request: str) -> str | None:
    n = norm(request)
    if _any(n, ("سنوي", "سنويا", "كل سنه", "حسب السنه", "بالسنه", "yearly", "annual")):
        return "year"
    if _any(n, ("فصلي", "فصليا", "ربعي", "ربع سنوي", "كل ربع", "quarter")):
        return "quarter"
    if _any(n, ("شهري", "شهريا", "شهرا بشهر", "كل شهر", "monthly")):
        return "month"
    return None


def _kind(request: str, words: list[str]) -> str:
    n = norm(request)
    for k, vocab in _SHAPES:
        if _any(n, vocab):
            return k
    if _has(words, _BROAD) or "كيف حال" in n:
        return "broad"
    if _has(words, _WHY) or "لماذا" in n:
        return "contribution"
    if _has(words, ("موسم", "فصل", "حراري", "خريط")) or "اي شهر" in n or "اي الاشهر" in n:
        return "heatmap"
    if _has(words, _COMPARE):
        return "branches"
    return "trend"


def _score(m: dict, words: list[str]) -> int:
    score = 0
    for w in set(tokens(m["name"])):
        if any(forms(w) & forms(x) for x in words):
            score += 2                          # the same word
        elif any(_same(w, x) for x in words):
            score += 1                          # a synonym ("المبيعات" for "رقم الأعمال")
    return score


def _branch_in(request: str, m: dict) -> str | None:
    rt = norm(request)
    for b in m.get("branches", []):
        if norm(b) in rt:
            return b
    return None


def parse(request: str, catalog: list[dict]) -> dict:
    """Rule-based reading of the request as ONE spec (the first chart of `interpret`)."""
    words = tokens(request)
    kind = _kind(request, words)
    kind = "contribution" if kind == "broad" else kind
    best, best_score = None, 0
    for m in catalog:
        sc = _score(m, words)
        if sc > best_score:
            best, best_score = m, sc
    if best is None and catalog and kind != "trend":
        best = catalog[0]                           # "قارن الفروع": a chart kind but no measure named, take the first one
    branch = _branch_in(request, best) if best else None
    if branch and kind in ("branches", "contribution"):
        branch = None
    return {"kind": kind, "measure": best["id"] if best else None, "branch": branch, "months": _months(request), "title": ""}


_STOP = {"قارن", "مقارنه", "بين", "لماذا", "كيف", "ما", "ماذا", "هل", "في", "من", "علي", "الي", "مع", "عن", "هذا", "هذه", "حلل", "تحليل", "ملخص", "نظره", "حال", "حالنا", "وضع",
         "اخر", "شهر", "اشهر", "سنه", "سنوات", "عام", "اعوام", "كل", "جميع", "اعرض", "ارسم", "اظهر", "لي", "لنا", "عدد", "تطور", "تغير", "ارتفع", "انخفض", "تراجع", "موسميه", "موسم",
         "فرع", "فروع", "افضل", "اسوا", "اضعف", "اقوي", "سبب", "الان", "الذي", "التي", "حرك", "ساهم", "وراء", "الحالي", "الحاليه", "مقابل", "ضد", "وبين", "حسب", "بالنسبه", "الفرق"}


_STOP |= {"يمكنك", "يمكن", "تقدر", "رسم", "ارسم", "اريد", "اعطني", "اعرض", "وريني", "نسبيه", "نسبي", "دائره", "دائري", "رسما", "بياني", "بيانيا", "مخطط", "شكل", "حسب", "لكل", "كل", "بالنسبه",
          "شهريا", "سنويا", "فصليا", "شهري", "سنوي", "فصلي", "ربعي", "جدول", "اعمده", "عمود", "نمو", "تراكمي", "علاقه", "ارتباط", "ترتيب", "حصه", "توزيع", "بطاقه", "كم", "بلغ", "كان", "يكون", "عن", "او"}
_STOP |= {w for _, vs in _SHAPES for v in vs for w in norm(v).split()}


def _original(word: str, request: str) -> str:
    """The word as the user typed it (the matching works on a normalised form)."""
    for w in re.findall(r"[\u0600-\u06ffA-Za-z]+", request or ""):
        if norm(w) == word:
            return w
    return word


def _unmatched(words: list[str], catalog: list[dict], request: str = "") -> list[str]:
    """Content words of the request that match nothing in the data (no measure, no branch, no synonym): "الزبائن" when there is no customers measure."""
    known = [m["name"] for m in catalog] + [b for m in catalog for b in m.get("branches", [])]
    kw = [tokens(k) for k in known]
    out = []
    for w in words:
        if forms(w) & _STOP:
            continue
        if any(_same(w, x) for toks in kw for x in toks):
            continue
        out.append(w)
    return [_original(w, request) for w in out[:3]]


def _concepts(words: list[str], catalog: list[dict]) -> list[list[dict]]:
    """What the request talks about, as groups of measures: each content word that matches measures gives a set; identical sets are one concept (profit -> {Gross Profit})."""
    seen, out = [], []
    for w in words:
        if forms(w) & _STOP:
            continue
        ms = [m for m in catalog if any(_same(w, x) for x in tokens(m["name"]))]
        key = tuple(m["id"] for m in ms)
        if ms and key not in seen:
            seen.append(key)
            out.append(ms)
    return out


def _compare_words(words: list[str], request: str) -> bool:
    n = norm(request)
    return _any(n, ("علاقه بين", "ارتباط", "انتشار", "scatter", "correlation")) or _has(words, ("قارن", "مقارن", "مقابل")) or "بين" in n.split() or "مقابل" in n or " ضد " in n


def interpret(request: str, catalog: list[dict]) -> dict:
    """Rules for the whole answer: up to three charts; two measures compared; or ONE question when the request is unclear or mentions something the data does not hold."""
    words = tokens(request)
    kind = _kind(request, words)
    if not catalog:
        return {"charts": [], "ask": None, "choices": [], "missing": []}
    rn = norm(request)
    hits = [m for m in catalog if norm(m["name"]) in rn]                         # the full name was typed (also what a clicked choice sends back)
    scored = sorted(((_score(m, words), i, m) for i, m in enumerate(catalog)), key=lambda x: (-x[0], x[1]))
    top = scored[0] if scored else None
    missing = _unmatched(words, catalog, request)
    wants_compare = _compare_words(words, request)
    pair_kind = "scatter" if kind == "scatter" else "compare"
    months = _months(request)

    def pairs():
        ms = hits or [m for sc, _, m in scored if sc > 0] or catalog
        ms = ms[:4]
        return [{"a": x, "b": y} for i, x in enumerate(ms) for y in ms[i + 1:]][:5]

    if wants_compare and len(hits) >= 2:
        a, b = hits[0], hits[1]
        return {"charts": [{"kind": pair_kind, "measure": a["id"], "measure2": b["id"], "branch": None, "months": months, "title": ""}], "ask": None, "choices": [], "missing": []}
    if wants_compare and len(hits) == 1:                                 # one measure typed in full, the other described: "قارن Units Sold بالأرباح"
        h = hits[0]
        own = set().union(*(forms(x) for x in tokens(h["name"])))
        rest = [w for w in words if not (forms(w) & own)]
        others = [[m for m in c if m["id"] != h["id"]] for c in _concepts(rest, catalog)]
        others = [c for c in others if c]
        if others:
            combos = [(h, y) for y in others[0]][:5]
            if len(combos) == 1:
                return {"charts": [{"kind": pair_kind, "measure": h["id"], "measure2": combos[0][1]["id"], "branch": None, "months": months, "title": ""}], "ask": None, "choices": [], "missing": []}
            return {"charts": [], "ask": "pair", "choices": [f"{x['name']} {_AND} {y['name']}" for x, y in combos], "missing": missing}
    if wants_compare and not hits:
        concepts = _concepts(words, catalog)
        if len(concepts) >= 2:
            combos = [(x, y) for x in concepts[0] for y in concepts[1] if x["id"] != y["id"]][:5]
            if len(combos) == 1:
                x, y = combos[0]
                return {"charts": [{"kind": pair_kind, "measure": x["id"], "measure2": y["id"], "branch": None, "months": months, "title": ""}], "ask": None, "choices": [], "missing": []}
            if combos:
                return {"charts": [], "ask": "pair", "choices": [f"{x['name']} {_AND} {y['name']}" for x, y in combos], "missing": missing}
        elif missing:                                                    # "قارن عدد الزبائن والمبيعات": one side exists, the other does not
            pr = pairs()
            if pr:
                return {"charts": [], "ask": "pair", "choices": [f"{p['a']['name']} {_AND} {p['b']['name']}" for p in pr], "missing": missing}
    if hits:
        m = hits[0]
    elif top is None or top[0] == 0:
        if len(catalog) == 1:
            m = catalog[0]
        else:
            return {"charts": [], "ask": "which", "choices": [m["name"] for m in catalog[:5]], "missing": missing}
    else:
        tied = [m for sc, _, m in scored if sc == top[0]]
        if missing and top[0] < 3:                                       # part of the request has no counterpart in the data: say so, do not guess
            return {"charts": [], "ask": "which", "choices": [m["name"] for m in (tied if len(tied) > 1 else [x[2] for x in scored[:4]])[:5]], "missing": missing}
        if len(tied) > 1 and top[0] < 3:
            return {"charts": [], "ask": "which", "choices": [m["name"] for m in tied[:5]], "missing": missing}
        m = top[2]
    has_b = len(m.get("branches", [])) >= 2
    branch = _branch_in(request, m)
    by = _by(request)
    spec = lambda k, **kw: {"kind": k, "measure": m["id"], "branch": kw.get("branch"), "months": months, "title": "", **({"by": by} if by else {})}
    note = None
    if kind in ("share", "ranking", "stacked") and not has_b:
        note = f"لا تتوفر بيانات «{m['name']}» مقسّمة حسب الفرع، فعرضت الإجمالي عبر الزمن."
        charts = [spec("bars" if kind == "stacked" else "trend")]
    elif kind in ("share", "ranking", "stacked") and branch:
        charts = [spec(kind)]
    elif kind in ("bars", "growth", "cumulative", "table", "kpi"):
        charts = [spec(kind, branch=branch)]
    elif kind == "scatter":
        return {"charts": [], "ask": "which", "choices": [x["name"] for x in catalog[:5]], "missing": missing}
    elif branch:
        charts = [spec("trend", branch=branch)]
    elif kind == "broad":
        charts = [spec("trend")] + ([spec("contribution"), spec("branches")] if has_b else [])
    elif kind == "contribution":
        charts = ([spec("contribution")] if has_b else []) + [spec("trend")]
    elif kind == "branches":
        charts = [spec("branches")] if has_b else [spec("trend")]
    elif kind in ("share", "ranking", "stacked"):
        charts = [spec(kind)]
    elif kind == "heatmap":
        charts = [spec("heatmap")]
    else:
        charts = [spec("trend")]
    return {"charts": charts[:3], "ask": None, "choices": [], "missing": [], "note": note}


_AND = "و"


_KIND_ALIAS = {"line": "trend", "linechart": "trend", "timeseries": "trend", "time series": "trend", "evolution": "trend", "bar": "bars",
               "branch": "branches", "regions": "branches", "waterfall": "contribution", "bridge": "contribution", "drivers": "contribution", "why": "contribution",
               "pie": "share", "donut": "share", "doughnut": "share", "proportion": "share", "ranking": "ranking", "rank": "ranking", "column": "bars", "columns": "bars", "barchart": "bars", "stack": "stacked", "stacked bar": "stacked", "stacked area": "stacked", "yoy": "growth", "cumulative": "cumulative", "running total": "cumulative", "ytd": "cumulative", "correlation": "scatter", "relationship": "scatter", "table": "table", "number": "kpi", "card": "kpi", "metric": "kpi", "seasonality": "heatmap", "season": "heatmap", "comparison": "compare", "versus": "compare", "vs": "compare"}


def _norm(x: str) -> str:
    return " ".join(x.lower().replace("_", " ").replace("-", " ").split()) if x else ""


class DrawChart(Task):
    name = "draw_chart"
    description = "Choose up to three chart specs for a typed request, or ask which measure is meant."
    schema = {"type": "object", "properties": {
        "charts": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": list(KINDS)}, "measure": {"type": "string"}, "measure2": {"type": ["string", "null"]}, "branch": {"type": ["string", "null"]},
            "months": {"type": ["integer", "null"]}, "by": {"type": ["string", "null"], "enum": ["month", "quarter", "year", None]}, "title": {"type": "string"}}, "required": ["kind", "measure"]}},
        "note": {"type": ["string", "null"]},
        "ask": {"type": ["string", "null"]}, "choices": {"type": "array", "items": {"type": "string"}}, "missing": {"type": "array", "items": {"type": "string"}}}, "required": ["charts"]}

    def prompt(self, inputs, lang):
        body = {"request": privacy.clip(inputs.get("request"), 200),
                "catalog": [{"id": m["id"], "name": privacy.clip(m["name"], 80), "unit": privacy.clip(m.get("unit", ""), 12), "months": m.get("months"),
                             "branches": [privacy.clip(b, 40) for b in m.get("branches", [])[:12]]} for m in inputs["catalog"][:30]]}
        return SYSTEM, json.dumps(body, ensure_ascii=False)

    def validate(self, data, inputs):
        cat = inputs["catalog"]
        ids = {str(m["id"]): m for m in cat}
        by_name = {}
        for m in cat:
            by_name[_norm(m["name"])] = str(m["id"])
        names = {m["name"] for m in cat} | {b for m in cat for b in m.get("branches", [])}

        def resolve(v):
            """The model may answer with the id, the name, or a near name: accept any that points at exactly one measure."""
            if v is None or isinstance(v, bool):
                return None
            if str(v) in ids:
                return str(v)
            k = _norm(str(v))
            if k in by_name:
                return by_name[k]
            hit = [i for n, i in by_name.items() if k and (k in n or n in k)]
            return hit[0] if len(set(hit)) == 1 else None

        charts, last_err, note = [], None, (data.get("note") if isinstance(data.get("note"), str) and data.get("note").strip() else None)
        for c in (data.get("charts") or [])[:3]:
            if not isinstance(c, dict):
                continue
            kind = _KIND_ALIAS.get(_norm(str(c.get("kind") or "")), _norm(str(c.get("kind") or "")))
            mid = resolve(c.get("measure"))
            if kind not in KINDS or mid is None:
                last_err = f"unknown chart kind {c.get('kind')!r} or measure {c.get('measure')!r}; use kind in {list(KINDS)} and a measure id from the catalog"
                continue
            branch = c.get("branch")
            if branch is not None and branch not in ids[mid].get("branches", []):
                branch = None
            months = c.get("months")
            months = months if isinstance(months, int) and not isinstance(months, bool) and 3 <= months <= 120 else None
            out = {"kind": kind, "measure": mid, "branch": branch, "months": months, "title": privacy.clip(c.get("title"), 90)}
            if kind in ("share", "ranking", "stacked") and len(ids[mid].get("branches", [])) < 2:
                kind = out["kind"] = "bars" if kind == "stacked" else "trend"
                note = f"لا تتوفر بيانات «{ids[mid]['name']}» مقسّمة حسب الفرع، فعرضت الإجمالي."
            if c.get("by") in ("month", "quarter", "year"):
                out["by"] = c["by"]
            if kind in ("compare", "scatter"):
                m2 = resolve(c.get("measure2"))
                if m2 is None or m2 == mid:
                    last_err = "compare needs two different measures from the catalog (measure and measure2)"
                    continue
                out["measure2"] = m2
                out["branch"] = None
            charts.append(out)
        if not charts and (data.get("charts") or []) and not (data.get("ask") or data.get("choices") or data.get("missing")):
            raise ValueError(last_err or "no usable chart")
        ask = data.get("ask") if isinstance(data.get("ask"), str) and data.get("ask").strip() else None
        choices = [c for c in (data.get("choices") or []) if isinstance(c, str) and c in names][:5]
        missing = [privacy.clip(x, 30) for x in (data.get("missing") or []) if isinstance(x, str) and x.strip()][:3]
        if not charts and not choices:
            ask = "which" if (ask or missing) else None
            choices = [m["name"] for m in inputs["catalog"][:5]] if ask else []
        return {"charts": charts, "ask": "which" if (ask and not charts) else None, "choices": choices if not charts else [], "missing": missing if not charts else [], "note": privacy.clip(note, 160) if note and charts else None}

    def fallback(self, inputs, lang):
        return interpret(inputs.get("request", ""), inputs["catalog"])


task = DrawChart()
