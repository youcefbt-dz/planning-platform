"""Demo OKRs and KPIs for a fictional distribution company with two institutional goals
cascading into nine department goals. Values are generated from a target *delta against expected progress*,
so the demo always shows a believable mix of statuses whatever day it is opened.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from app.core import progress as P
from app.core.models import CheckIn
from app.extensions import db
from app.modules.goals.models import Indicator, IndicatorValue, KeyResult, Objective


# Two institutional objectives own the shared outcomes; nine department objectives roll up into them.
# (key, parent_key, level 'year'|'quarter', owner, unit, perspective, title, [KRs], note?)
# KR: (title, unit_label, start, target, delta_points against the progress expected today, metric_type)
# delta: about 0 or above = on track; -15 to -20 = at risk; -30 or worse = off track (the status rules are 10 and 25 points).
OBJECTIVES = [
    # Commercial outcome: progress rolls up from sales, marketing, finance and customer experience.
    ("institution", None, "year", "ceo", "root", "financial",
     "تحقيق نمو تجاري مربح وتعزيز مكانة المؤسسة وتجربة العملاء",
     [], None),

    # Operating outcome: progress rolls up from operations, supply, people, technology and logistics.
    ("operations_institution", None, "year", "ceo", "root", "process",
     "رفع كفاءة التشغيل وموثوقية سلسلة الإمداد والتوزيع",
     [], None),

    # Department goals: every one is explicitly aligned with one institutional objective.
    ("sales", "institution", "year", "sales", "sales", "financial",
     "زيادة المبيعات وتوسيع قاعدة العملاء",
     [("رقم الأعمال السنوي", "مليون دج", 480, 600, 2, "number"),
      ("عملاء جدد نشطون", "عميل", 0, 120, -8, "number")], None),

    ("marketing", "institution", "year", "marketing", "marketing", "customer",
     "توليد طلب مؤهل يدعم نمو المبيعات",
     [("فرص بيع مؤهلة", "فرصة", 90, 300, -10, "number"),
      ("تحويل الفرص إلى عملاء", "%", 11, 18, -12, "percent")], None),

    ("operations", "operations_institution", "year", "ops", "ops", "process",
     "رفع موثوقية تنفيذ الطلبات وتسريع دورة التشغيل",
     [("نسبة التسليم في الموعد", "%", 82, 95, -17, "percent"),
      ("المدة من الطلب إلى التسليم (يوم)", "يوم", 9, 5, -32, "number")], None),

    ("supply", "operations_institution", "year", "supply", "supply", "process",
     "ضمان توفر المنتجات وتحسين أداء الموردين",
     [("التوريد في الموعد", "%", 78, 94, -12, "percent"),
      ("نسبة نفاد المخزون", "%", 8, 2, -18, "percent")],
     "تأخر توريد بعض الأصناف ذات الدوران المرتفع أثر مؤقتًا في توفر المخزون"),

    ("finance", "institution", "year", "fin", "fin", "financial",
     "حماية هامش الربح وتحسين إدارة السيولة",
     [("هامش الربح الإجمالي", "%", 27, 31, -3, "percent"),
      ("تحصيل المستحقات خلال 60 يومًا", "%", 68, 90, -14, "percent")], None),

    ("people", "operations_institution", "year", "people", "people", "learning",
     "رفع جاهزية الكفاءات وتحسين إنتاجية الفريق",
     [("تغطية الوظائف بالتكوين", "%", 35, 90, -15, "percent"),
      ("مدة شغل المناصب الشاغرة", "يوم", 60, 30, -10, "number")], None),

    ("technology", "operations_institution", "year", "tech", "tech", "process",
     "رقمنة الإجراءات ورفع موثوقية الأنظمة",
     [("الطلبات المعالجة رقميًا", "%", 25, 80, -10, "percent"),
      ("جاهزية الأنظمة", "%", 96, 99.5, -4, "percent")], None),

    ("customer", "institution", "year", "customer", "customer", "customer",
     "تحسين تجربة العميل وتسريع معالجة الشكاوى",
     [("رضا العملاء", "%", 72, 90, -16, "percent"),
      ("الشكاوى المعالجة خلال 48 ساعة", "%", 60, 90, -12, "percent")], None),

    ("logistics", "operations_institution", "year", "logistics", "logistics", "process",
     "خفض تكلفة التوزيع وتحسين استغلال الأسطول",
     [("تكلفة التوصيل للطلب", "دج", 1450, 1150, -10, "number"),
      ("معدل استغلال الأسطول", "%", 62, 82, -12, "percent")], None),
]

# Both institutional objectives calculate progress from their aligned department objectives.
INSTITUTION_KEYS = ("institution", "operations_institution")

# Why each institutional and department objective matters
RATIONALE = {
    "institution": "توحيد جهود المبيعات والتسويق والمالية وخدمة العملاء حول نمو تجاري مربح ومستدام.",
    "operations_institution": "توحيد جهود التشغيل والإمداد والموارد البشرية والتقنية والنقل لرفع موثوقية التنفيذ وخفض الهدر.",
    "sales": "زيادة الإيرادات تحتاج إلى نمو قاعدة العملاء مع الحفاظ على قيمة كل صفقة.",
    "marketing": "توفير فرص بيع ذات جودة يمنح فريق المبيعات خطًا مستمرًا من العملاء المحتملين.",
    "operations": "سرعة التنفيذ ودقته هما ما يحوّل الوعد التجاري إلى تجربة موثوقة.",
    "supply": "توفر المخزون في الوقت المناسب يمنع ضياع المبيعات ويحد من تكاليف التخزين الطارئ.",
    "finance": "حماية الهامش والسيولة تجعل النمو قابلًا للاستمرار والتمويل.",
    "people": "النتائج التشغيلية تعتمد على جاهزية الفرق ووضوح المسؤوليات والمهارات.",
    "technology": "رقمنة الإجراءات تقلل العمل اليدوي وتوفر بيانات أدق لاتخاذ القرار.",
    "customer": "معالجة احتياجات العميل بسرعة تحافظ على الثقة وتزيد فرص عودته.",
    "logistics": "تحسين مسارات التوزيع واستغلال الأسطول يخفض التكلفة ويحسن الالتزام بالمواعيد.",
}
ASPIRATIONAL: set[str] = set()

COMMENTS = [
    "تقدّم جيد هذا الأسبوع.",
    "بدأنا نرى أثر الإجراء الأخير.",
    "التقدّم أبطأ من المتوقع، سنراجع الخطة.",
    "",
    "",
]

INDICATORS = [
    # name, unit, type, direction, baseline, target, first, latest, owner, perspective, org unit
    ("رقم الأعمال الشهري", "مليون دج", "number", "higher_better", 40, 50, 41, 47.5, "sales", "financial", "sales"),
    ("نسبة التسليم في الموعد", "%", "percent", "higher_better", 80, 95, 82, 88.5, "ops", "customer", "ops"),
    ("المدة من الطلب إلى التسليم (يوم)", "يوم", "number", "lower_better", 9.5, 5, 9, 6.8, "ops", "process", "ops"),
    ("فرص البيع المؤهلة شهريًا", "فرصة", "number", "higher_better", 14, 35, 16, 29, "marketing", "customer", "marketing"),
    ("التوريد في الموعد", "%", "percent", "higher_better", 78, 94, 80, 88, "supply", "process", "supply"),
    ("هامش الربح الإجمالي", "%", "percent", "higher_better", 27, 31, 27.5, 29.1, "fin", "financial", "fin"),
    ("تغطية الموظفين بالتكوين", "%", "percent", "higher_better", 35, 90, 40, 67, "people", "learning", "people"),
    ("جاهزية الأنظمة الرقمية", "%", "percent", "higher_better", 96, 99.5, 96.2, 98.7, "tech", "process", "tech"),
    ("رضا العملاء", "%", "percent", "higher_better", 72, 90, 74, 84, "customer", "customer", "customer"),
    ("تكلفة التوصيل للطلب", "دج", "number", "lower_better", 1450, 1150, 1420, 1270, "logistics", "financial", "logistics"),
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
                      progress_driver="children" if key in INSTITUTION_KEYS else "key_results",
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

        if kr_rows:
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
    # Neither institutional objective has a standalone metric: each rolls up from its own department goals.
    from app.modules.goals.service import compute_objectives
    views = compute_objectives(org, today=today)
    for institution_key in INSTITUTION_KEYS:
        rollup = views.get(objs[institution_key].id)
        if rollup:
            db.session.add(CheckIn(org_id=org.id, entity_type="objective", entity_id=objs[institution_key].id,
                                   user_id=users["ceo"].id, progress=rollup.progress,
                                   created_at=datetime.combine(today, datetime.min.time()) + timedelta(hours=10),
                                   comment="ملخص تقدم الأهداف الفرعية للأقسام"))

    # Genuine cross-functional dependencies, separate from the parent-child alignment above.
    from app.core.models import Link
    for source, target in (("sales", "marketing"), ("operations", "supply"), ("customer", "logistics"), ("finance", "sales")):
        db.session.add(Link(org_id=org.id, source_type="objective", source_id=objs[source].id,
                            target_type="objective", target_id=objs[target].id, kind="depends_on"))

    # Keep the optional strategy/initiatives seeders compatible without enabling either module.
    # Their older objective keys now point to the closest matching department goal.
    objective_refs = dict(objs)
    objective_refs.update({
        "rev": objs["sales"], "rev_q": objs["sales"],
        "cust": objs["customer"], "promise_q": objs["customer"],
        "ops": objs["operations"], "wh_q": objs["operations"],
        "cash_q": objs["finance"], "onb_q": objs["people"], "team": objs["people"],
    })
    ctx["objectives"] = objective_refs

    for name, ul, mt, direction, base, target, v0, v1, owner, persp, unit_key in INDICATORS:
        ind = Indicator(org_id=org.id, name=name, unit_label=ul, metric_type=mt, direction=direction, frequency="monthly",
                        baseline_value=base, target_value=target, owner_id=users[owner].id, perspective=persp,
                        unit_id=units[unit_key].id)
        db.session.add(ind)
        db.session.flush()
        months = 10
        for k in range(months):
            f = k / (months - 1)
            v = v0 + (v1 - v0) * f + rnd.uniform(-0.02, 0.02) * abs(v1 - v0 or 1)
            if k == months - 1:
                v = v1
            db.session.add(IndicatorValue(indicator_id=ind.id, period_date=_month_start(today, months - 1 - k), value=round(v, 1)))
