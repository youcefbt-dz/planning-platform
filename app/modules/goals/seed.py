"""Demo data for the goals module — a fictional mid-size distribution company, in ar / en / fr.

Values are generated from a target *delta against expected progress*, so the demo always shows
a believable mix of statuses whatever day it is opened.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from app.core import progress as P
from app.core.models import CheckIn
from app.extensions import db
from app.modules.goals.models import Indicator, IndicatorValue, KeyResult, Objective


# (key, parent_key, level 'year'|'quarter', owner, unit, perspective, title(ar,en,fr), [KRs], note?)
# KR: (title(ar,en,fr), unit_label, start, target, delta_points, metric_type)
OBJECTIVES = [
    ("rev", None, "year", "ceo", "root", "financial",
     "تنمية رقم الأعمال بربحية",
     [("رقم الأعمال السنوي", "M DZD", 480, 600, -26, "number"),
      ("هامش الربح الإجمالي", "%", 27, 31, -8, "percent"),
      ("حصة رقم الأعمال من العملاء المتكررين", "%", 52, 65, 6, "percent")],
     "في انتظار توقيع عقد التوزيع الجديد في الشرق"),
    ("cust", None, "year", "sales", "root", "customer",
     "أن نكون المورّد الذي يوصي به عملاؤنا",
     [("مؤشر صافي نقاط الترويج (NPS)", "", 31, 50, 4, "number"),
      ("نسبة التسليم في الموعد", "%", 82, 95, -4, "percent"),
      ("الشكاوى المعالجة خلال 48 ساعة", "%", 60, 90, -12, "percent")],
     None),
    ("ops", None, "year", "ops", "root", "process",
     "تشغيل أسرع وأكثر موثوقية",
     [("المدة من الطلب إلى التسليم (يوم)", "days", 9, 5, -9, "number"),
      ("حالات نفاد المخزون شهريًا", "", 14, 4, -3, "number"),
      ("أخطاء تحضير الطلبيات", "%", 3.2, 1, 5, "percent")],
     None),
    ("team", None, "year", "people", "people", "learning",
     "بناء فريق قادر على النمو",
     [("معدل ترك العمل الطوعي", "%", 18, 10, 2, "percent"),
      ("ساعات التكوين لكل موظف", "h", 12, 30, -14, "number"),
      ("المناصب الرئيسية التي لها خلف جاهز", "", 2, 8, -6, "number")],
     None),
    ("rev_q", "rev", "quarter", "sales", "sales", "financial",
     "كسب 25 عميلًا جديدًا في المنطقة الشمالية",
     [("عملاء جدد", "", 0, 25, 4, "number"),
      ("قيمة الفرص التجارية المفتوحة", "M DZD", 40, 90, 8, "number")],
     None),
    ("cash_q", "rev", "quarter", "fin", "fin", "financial",
     "تحرير السيولة المجمّدة في الذمم",
     [("متوسط فترة تحصيل الذمم (يوم)", "days", 74, 55, 3, "number"),
      ("الذمم المتأخرة أكثر من 90 يومًا", "M DZD", 38, 15, -22, "number")],
     "لم تُحصَّل بعد الدفعة الكبرى لأحد العملاء"),
    ("promise_q", "cust", "quarter", "ops", "logistics", "customer",
     "الوفاء بوعد التسليم",
     [("الطلبيات المسلّمة في التاريخ المتفق عليه", "%", 82, 95, 5, "percent"),
      ("الطلبيات المزوّدة بتتبّع مباشر", "%", 0, 100, -3, "percent")],
     None),
    ("wh_q", "ops", "quarter", "ops", "ops", "process",
     "تقليص زمن الدورة داخل المستودع",
     [("المدة من الاستلام إلى التخزين (ساعة)", "h", 36, 12, -30, "number"),
      ("أخطاء التحضير لكل 1000 سطر", "", 32, 10, -4, "number")],
     "تأخر وصول الماسحات الضوئية من المورّد"),
    ("onb_q", "team", "quarter", "people", "people", "learning",
     "إنجاح تهيئة الموظفين الجدد في أول 90 يومًا",
     [("الموظفون الجدد الذين أكملوا خطة التهيئة", "%", 40, 90, 3, "percent"),
      ("استمرار الموظفين الجدد بعد 90 يومًا", "%", 78, 92, 7, "percent")],
     None),
]

# Why each top-level goal matters (ar, en, fr) and which ones are deliberate stretches (aspirational ~70% = success)
RATIONALE = {
    "rev": "بدون نمو مربح لا نستطيع تمويل المخزون ولا الفريق. هذا الهدف يحدد قدرتنا على الاستثمار هذه السنة.",
    "cust": "العميل الذي يوصي بنا يخفّض كلفة اكتساب العملاء ويثبّت الإيراد المتكرر.",
    "ops": "كل يوم تأخير في التسليم يتحول إلى شكوى وإلى ذمم متأخرة.",
    "team": "النمو يتوقف عند أول منصب رئيسي يشغر دون خلف جاهز.",
}
ASPIRATIONAL = {"cust", "team"}

COMMENTS = [
    "تقدّم جيد هذا الأسبوع.",
    "بدأنا نرى أثر الإجراء الأخير.",
    "التقدّم أبطأ من المتوقع، سنراجع الخطة.",
    "تم تحديث الرقم بعد إقفال الشهر.",
    "",
    "",
]

# (name, unit_label, metric_type, direction, baseline, target, start_value, end_value, owner, perspective)
INDICATORS = [
    ("رقم الأعمال الشهري", "M DZD", "number", "higher_better", 40, 50, 41, 47.5, "fin", "financial"),
    ("هامش الربح الإجمالي", "%", "percent", "higher_better", 26, 31, 27.2, 29.1, "fin", "financial"),
    ("نسبة التسليم في الموعد", "%", "percent", "higher_better", 80, 95, 82, 88.5, "ops", "customer"),
    ("مؤشر صافي نقاط الترويج (NPS)", "", "number", "higher_better", 28, 50, 31, 41, "sales", "customer"),
    ("المدة من الطلب إلى التسليم (يوم)", "days", "number", "lower_better", 9.5, 5, 9, 6.8, "ops", "process"),
    ("متوسط فترة تحصيل الذمم (يوم)", "days", "number", "lower_better", 78, 55, 74, 63, "fin", "financial"),
    ("معدل ترك العمل الطوعي (سنوي)", "%", "percent", "lower_better", 19, 10, 18, 13.5, "people", "learning"),
]


def _round(v: float, span: float) -> float:
    return round(v, 0 if abs(span) >= 60 else 1)


def _month_start(d: date, back: int) -> date:
    y, m = d.year, d.month - back
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def seed(org, lang: str, ctx: dict) -> None:
    rnd = random.Random(42)
    today, users, units, cycles = ctx["today"], ctx["users"], ctx["units"], ctx["cycles"]
    objs: dict[str, Objective] = {}
    for key, parent, level, owner, unit, persp, title, krs, note in OBJECTIVES:
        cyc = cycles["year"] if level == "year" else cycles["quarter"]
        o = Objective(org_id=org.id, cycle_id=cyc.id, unit_id=units[unit].id, owner_id=users[owner].id,
                      parent_id=objs[parent].id if parent else None, title=title, perspective=persp,
                      progress_driver="key_results" if not parent or level == "quarter" else "both",
                      start_date=cyc.start_date, end_date=cyc.end_date,
                      rationale=RATIONALE[key] if key in RATIONALE else None, commitment="aspirational" if key in ASPIRATIONAL else "committed",
                      created_at=datetime.combine(cyc.start_date, datetime.min.time()) + timedelta(days=2))
        if level == "year":
            o.progress_driver = "both" if key in ("rev", "cust", "ops", "team") else "key_results"
        db.session.add(o)
        db.session.flush()
        objs[key] = o
        exp = P.expected_progress(o.start_date, o.end_date, today)
        elapsed_days = max((today - o.start_date).days, 1)
        dates = sorted({o.start_date + timedelta(days=int(elapsed_days * k / 6)) for k in range(1, 7)})
        dates = [d for d in dates if d < today] + [today - timedelta(days=rnd.randint(0, 3))]

        kr_rows = []
        for pos, (kt, ul, start, target, delta, mt) in enumerate(krs):
            prog = max(0.03, min(0.97, exp + delta / 100.0))
            cur = _round(start + (target - start) * prog, target - start)
            kr = KeyResult(org_id=org.id, objective_id=o.id, title=kt, metric_type=mt, unit_label=ul, start_value=start, kr_type="decrease" if target < start else "increase",
                           target_value=target, current_value=cur, position=pos, owner_id=users[owner].id)
            db.session.add(kr)
            kr_rows.append((kr, prog))
        db.session.flush()

        for n, d in enumerate(dates):
            frac = ((d - o.start_date).days / elapsed_days) ** 0.9
            when = datetime.combine(d, datetime.min.time()) + timedelta(hours=9 + rnd.randint(0, 6))
            sum_p = 0.0
            for kr, prog in kr_rows:
                wobble = rnd.uniform(-0.02, 0.02)
                p = max(0.0, min(prog, prog * frac + wobble)) if d != dates[-1] else prog
                v = _round(kr.start_value + (kr.target_value - kr.start_value) * p, kr.target_value - kr.start_value) if d != dates[-1] else kr.current_value
                sum_p += P.kr_progress(kr.start_value, kr.target_value, v)
                db.session.add(CheckIn(org_id=org.id, entity_type="key_result", entity_id=kr.id, user_id=users[owner].id, value=v,
                                       progress=P.kr_progress(kr.start_value, kr.target_value, v), created_at=when,
                                       comment=COMMENTS[rnd.randrange(len(COMMENTS))] if n else ""))
            db.session.add(CheckIn(org_id=org.id, entity_type="objective", entity_id=o.id, user_id=users[owner].id,
                                   progress=sum_p / len(kr_rows), created_at=when + timedelta(minutes=5), comment=""))
        if note:
            db.session.add(CheckIn(org_id=org.id, entity_type="objective", entity_id=o.id, user_id=users[owner].id,
                                   progress=sum(p for _, p in kr_rows) / len(kr_rows), created_at=datetime.utcnow() - timedelta(days=2),
                                   comment=note, status="off_track" if key in ("rev", "wh_q") else "at_risk"))
    ctx["objectives"] = objs

    for name, ul, mt, direction, base, target, v0, v1, owner, persp in INDICATORS:
        ind = Indicator(org_id=org.id, name=name, unit_label=ul, metric_type=mt, direction=direction, frequency="monthly",
                        baseline_value=base, target_value=target, owner_id=users[owner].id, perspective=persp,
                        unit_id=units["root"].id)
        db.session.add(ind)
        db.session.flush()
        months = 10
        for k in range(months):
            f = k / (months - 1)
            v = v0 + (v1 - v0) * f + rnd.uniform(-0.02, 0.02) * abs(v1 - v0 or 1)
            if k == months - 1:
                v = v1
            db.session.add(IndicatorValue(indicator_id=ind.id, period_date=_month_start(today, months - 1 - k), value=round(v, 1)))
