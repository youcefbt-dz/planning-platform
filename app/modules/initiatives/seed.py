"""Demo initiatives (ar / en / fr). Dates are relative to today so the roadmap always looks alive."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.core.models import CheckIn, Link
from app.extensions import db
from app.modules.initiatives.models import Initiative, Milestone


# key, title, owner, unit, state, priority, start_offset_days, end_offset_days, supports(objective key), milestones[(title, due_offset, done)], note
DATA = [
    ("portal", "إطلاق بوابة طلبات العملاء", "sales", "sales", "active", "high", -75, 70, "promise_q",
     [("تحديد المتطلبات مع 10 عملاء", -50, True),
       ("نموذج أولي قابل للتجربة", -12, True),
       ("تجربة مع 5 عملاء", 20, False),
       ("الإطلاق العام", 70, False)], None),
    ("scan", "تركيب الماسحات الضوئية في المستودع الرئيسي", "ops", "ops", "active", "high", -60, 14, "wh_q",
     [("اختيار المورّد", -45, True),
       ("تسليم الأجهزة", -10, False),
       ("تدريب فريق المستودع", 5, False),
       ("التشغيل الفعلي", 14, False)],
     "تأخر المورّد في التسليم"),
    ("north", "حملة المبيعات في المنطقة الشمالية", "sales", "sales", "active", "high", -17, 74, "rev_q",
     [("قائمة 60 عميلًا مستهدفًا", -5, True),
       ("زيارات الربع الأول من القائمة", 25, False),
       ("عرض تجاري موحّد", 40, False)], None),
    ("collect", "برنامج تحصيل الذمم", "fin", "fin", "active", "medium", -30, 60, "cash_q",
     [("تصنيف الذمم حسب المخاطر", -18, True),
       ("خطة تذكير آلية", 8, False),
       ("اتفاقيات تقسيط مع 5 عملاء", 45, False)], None),
    ("onboard", "برنامج تهيئة الموظفين الجدد", "people", "people", "active", "medium", -40, 50, "onb_q",
     [("دليل التهيئة", -20, True),
       ("تعيين مرافق لكل موظف جديد", 5, False),
       ("استبيان بعد 30 يومًا", 35, False)], None),
    ("suppliers", "توحيد قاعدة الموردين", "ops", "ops", "planned", "medium", 20, 140, "ops",
     [("تحليل المشتريات حسب المورّد", 40, False),
       ("طلب عروض للفئات الرئيسية", 90, False)], None),
    ("routes", "إعادة رسم مسارات التوزيع", "ops", "logistics", "completed", "high", -120, -20, "promise_q",
     [("جمع بيانات التسليم", -100, True),
       ("المسارات الجديدة قيد التجربة", -60, True),
       ("التعميم على كل الأسطول", -20, True)], None),
    ("mentor", "برنامج الإرشاد للمناصب الرئيسية", "people", "people", "on_hold", "low", -30, 100, "team",
     [("تحديد المناصب الرئيسية", -10, True),
       ("اختيار المرشدين", 30, False)],
     "مؤجَّل إلى حين اكتمال ميزانية التكوين"),
]


def seed(org, lang: str, ctx: dict) -> None:
    today, users, units = ctx["today"], ctx["users"], ctx["units"]
    objs = ctx.get("objectives", {})  # present only when the goals module is enabled
    cyc = ctx["cycles"]["quarter"]
    for pos, (key, title, owner, unit, state, prio, so, eo, goal, ms, note) in enumerate(DATA):
        it = Initiative(org_id=org.id, cycle_id=cyc.id, unit_id=units[unit].id, owner_id=users[owner].id, title=title, state=state,
                        priority=prio, start_date=today + timedelta(days=so), end_date=today + timedelta(days=eo), position=pos)
        db.session.add(it)
        db.session.flush()
        for mt, off, done in ms:
            m = Milestone(initiative_id=it.id, title=mt, due_date=today + timedelta(days=off), done=done)
            if done:
                m.done_at = datetime.combine(m.due_date, datetime.min.time()) - timedelta(days=1)
            db.session.add(m)
        if goal in objs:
            db.session.add(Link(org_id=org.id, source_type="initiative", source_id=it.id, target_type="objective", target_id=objs[goal].id, kind="supports"))
        if note:
            db.session.add(CheckIn(org_id=org.id, entity_type="initiative", entity_id=it.id, user_id=users[owner].id, progress=0.25,
                                   status="off_track" if state == "active" else None, comment=note, created_at=datetime.utcnow() - timedelta(days=3)))
