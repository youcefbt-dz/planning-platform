"""Demo data for the goals module — a small fictional distribution company; kept simple on purpose.

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


# A deliberately small demo: three company goals, two department goals that serve them, and three indicators. Each one reads at a glance:
#   تنمية رقم الأعمال ... على المسار      إرضاء عملائنا ... معرَّض للخطر      تشغيل أسرع ... خارج المسار
# (key, parent_key, level 'year'|'quarter', owner, unit, perspective, title, [KRs], note?)
# KR: (title, unit_label, start, target, delta_points against the progress expected today, metric_type)
# delta: about 0 or above = on track; -15 to -20 = at risk; -30 or worse = off track (the status rules are 10 and 25 points).
OBJECTIVES = [
    ("rev", None, "year", "ceo", "root", "financial",
     "تنمية رقم الأعمال بربحية",
     [("رقم الأعمال السنوي", "مليون دج", 480, 600, 2, "number"),
      ("هامش الربح الإجمالي", "%", 27, 31, -3, "percent")],
     None),
    ("cust", None, "year", "sales", "root", "customer",
     "إرضاء عملائنا",
     [("نسبة العملاء الراضين", "%", 70, 85, -16, "percent"),
      ("نسبة التسليم في الموعد", "%", 82, 95, -17, "percent")],
     None),
    ("ops", None, "year", "ops", "root", "process",
     "تشغيل أسرع وأكثر موثوقية",
     [("المدة من الطلب إلى التسليم (يوم)", "يوم", 9, 5, -32, "number"),
      ("الطلبيات التي فيها خطأ", "%", 3.2, 1, -30, "percent")],
     None),
    ("rev_q", "rev", "quarter", "sales", "sales", "financial",
     "كسب 25 عميلًا جديدًا هذا الربع",
     [("عملاء جدد", "", 0, 25, 3, "number"),
      ("زيارات العملاء المحتملين", "", 0, 60, 0, "number")],
     None),
    ("wh_q", "ops", "quarter", "ops", "ops", "process",
     "تجهيز الطلبيات في المستودع بسرعة أكبر",
     [("مدة تجهيز الطلبية (ساعة)", "ساعة", 36, 12, -30, "number"),
      ("أخطاء التحضير لكل 1000 سطر", "", 32, 10, -12, "number")],
     "تأخر وصول الماسحات الضوئية من المورّد"),
]

# Why each company goal matters
RATIONALE = {
    "rev": "نمو مربح يمكّننا من تمويل المخزون والفريق.",
    "cust": "العميل الراضي يعود ويوصي بنا، ويقلّل كلفة اكتساب عملاء جدد.",
    "ops": "كل يوم تأخير في التسليم يتحول إلى شكوى وإلى مال متأخر.",
}
ASPIRATIONAL: set[str] = set()

COMMENTS = [
    "تقدّم جيد هذا الأسبوع.",
    "بدأنا نرى أثر الإجراء الأخير.",
    "التقدّم أبطأ من المتوقع، سنراجع الخطة.",
    "",
    "",
]

# (name, unit_label, metric_type, direction, baseline, target, start_value, end_value, owner, perspective)
INDICATORS = [
    ("رقم الأعمال الشهري", "مليون دج", "number", "higher_better", 40, 50, 41, 47.5, "ceo", "financial"),
    ("نسبة التسليم في الموعد", "%", "percent", "higher_better", 80, 95, 82, 88.5, "ops", "customer"),
    ("المدة من الطلب إلى التسليم (يوم)", "يوم", "number", "lower_better", 9.5, 5, 9, 6.8, "ops", "process"),
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
                      progress_driver="key_results",
                      start_date=cyc.start_date, end_date=cyc.end_date,
                      rationale=RATIONALE[key] if key in RATIONALE else None, commitment="aspirational" if key in ASPIRATIONAL else "committed",
                      created_at=datetime.combine(cyc.start_date, datetime.min.time()) + timedelta(days=2))
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
                                   comment=note, status="off_track"))
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
