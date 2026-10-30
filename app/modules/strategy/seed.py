"""Demo strategy content (ar / en / fr)."""
from __future__ import annotations

from app.core.models import Link
from app.extensions import db
from app.modules.strategy.models import FoundationItem, Priority, SwotItem


VISION = "أن نكون المورّد المرجعي لتجهيزات المهنيين في شمال إفريقيا."
MISSION = "نضمن للمهنيين تجهيزات موثوقة في الموعد الذي وعدناهم به، بسعر عادل وخدمة قريبة."
VALUES = [
    ("الوفاء بالوعد", "ما نعد به نلتزم به، وإن تعذّر نخبر العميل قبل أن يسأل."),
    ("القرب من العميل", "نقرّر انطلاقًا من احتياجات العملاء لا من راحة الداخل."),
    ("الشفافية", "الأرقام مشتركة بين الفرق، والأخبار السيئة تُقال مبكرًا."),
    ("التعلّم المستمر", "نراجع ما نجح وما أخفق كل ربع سنة."),
]
SWOT = {
    "strength": ["شبكة توزيع تغطي 38 ولاية", "علاقات طويلة مع الموردين الرئيسيين", "فريق مبيعات متمرّس"],
    "weakness": ["تتبّع المخزون يدوي في معظمه", "بطء تحصيل الذمم", "اعتماد كبير على عدد قليل من العملاء"],
    "opportunity": ["طلب متزايد من المؤسسات الصغيرة والمتوسطة", "إمكانية الطلب عبر الإنترنت", "بدائل محلية للاستيراد"],
    "threat": ["تقلّب أسعار الصرف وتكاليف الاستيراد", "دخول منافسين رقميين", "تأخر الشحن الدولي"],
}
PRIORITIES = [
    ("growth", "نمو مربح", "توسيع قاعدة العملاء مع الحفاظ على الهامش.", ["rev", "rev_q", "cash_q"]),
    ("trust", "ثقة العملاء", "تسليم في الموعد وخدمة تُوصى بها.", ["cust", "promise_q"]),
    ("excellence", "تميّز العمليات والفريق", "عمليات أسرع وفريق يتطوّر.", ["ops", "wh_q", "team", "onb_q"]),
]
# cause -> effect links on the strategy map
MAP_LINKS = [("team", "ops"), ("ops", "cust"), ("cust", "rev"), ("team", "cust")]


def seed(org, lang: str, ctx: dict) -> None:
    db.session.add(FoundationItem(org_id=org.id, kind="vision", text=VISION))
    db.session.add(FoundationItem(org_id=org.id, kind="mission", text=MISSION))
    for pos, (name, text) in enumerate(VALUES):
        db.session.add(FoundationItem(org_id=org.id, kind="value", title=name, text=text, position=pos))
    for kind, items in SWOT.items():
        for pos, item in enumerate(items):
            db.session.add(SwotItem(org_id=org.id, kind=kind, text=item, position=pos))
    objs = ctx.get("objectives", {})
    for pos, (_, title, desc, keys) in enumerate(PRIORITIES):
        p = Priority(org_id=org.id, title=title, description=desc, position=pos)
        db.session.add(p)
        db.session.flush()
        for k in keys:
            if k in objs:
                db.session.add(Link(org_id=org.id, source_type="objective", source_id=objs[k].id, target_type="priority", target_id=p.id, kind="supports"))
    for a, b in MAP_LINKS:
        if a in objs and b in objs:
            db.session.add(Link(org_id=org.id, source_type="objective", source_id=objs[a].id, target_type="objective", target_id=objs[b].id, kind="supports"))
