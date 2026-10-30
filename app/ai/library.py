"""Starter wording that works with no model at all: the offline half of the "draft it for me" features.

What this is for: a manager who stares at an empty "Objective" box will type nothing or type something vague. These templates are the
well-known shapes of the common business goals (the same ground Perdoo, Profit.co and Cascade cover with their template galleries),
written once in plain Arabic, ranked against what the person typed, and offered as ONE-CLICK starting points that are then edited.

Rules that keep it honest:
  * no figure is ever invented — a key result comes with a type and a unit, never a start or a target (those come from the user's data);
  * every key result is an outcome, never an activity (tests/test_ai_assist.py checks all of them with the goal coach's own rule);
  * a template that does not match what was typed is not offered: with no match we say so and keep the user's own words.
Pure Python, no Flask.
"""
from __future__ import annotations

import re

from app.ai.voice import normalise

# kind: increase | decrease | stay_above | stay_below | binary | milestone   (same vocabulary as the goals module)
THEMES: list[dict] = [
    {"id": "sales", "kw": ["مبيع", "ايراد", "رقم الاعمال", "رقم اعمال", "دخل", "بيع", "نمو"],
     "titles": ["تنمية مبيعاتنا نموًّا منتظمًا ومستدامًا", "رفع إيراداتنا من عملائنا الحاليين ومن عملاء جدد"],
     "why": ["المبيعات هي ما يموّل بقية أهدافنا، ونموّها المنتظم يمنحنا قدرة على الاستثمار والتوظيف.",
             "إيراد ينمو من قاعدة عملاء أوسع أقل خطرًا من إيراد يعتمد على عدد قليل من العملاء."],
     "krs": [("الإيراد الشهري", "increase", "دج"), ("عدد العملاء النشطين", "increase", "عميل"), ("متوسط قيمة الطلب", "increase", "دج"),
             ("نسبة العروض التي تتحول إلى طلبات", "increase", "%")],
     "levers": ["فتح نقطة بيع أو فرع جديد", "حملة تسويقية موجَّهة", "تعديل الأسعار", "التعاقد مع موزّع جديد"]},
    {"id": "profit", "kw": ["ربح", "تكلف", "تكالي", "مصاريف", "مصروف", "هامش", "ميزاني", "ترشيد", "نفقات", "هدر"],
     "titles": ["تحسين ربحيتنا بضبط التكاليف دون المساس بالجودة", "رفع هامشنا الربحي بإنفاق أذكى"],
     "why": ["الربح الذي يبقى بعد التكاليف هو ما يحمي المؤسسة في السنوات الصعبة ويموّل نموّها.",
             "خفض الهدر يحسّن الربح دون الحاجة إلى بيع أكثر."],
     "krs": [("هامش الربح الصافي", "increase", "%"), ("التكاليف التشغيلية الشهرية", "decrease", "دج"), ("تكلفة الوحدة المنتجة", "decrease", "دج"),
             ("نسبة المصاريف إلى الإيراد", "decrease", "%")],
     "levers": ["إعادة التفاوض مع كبار الموردين", "تقليص الهدر في الإنتاج أو التخزين", "تعديل الأسعار", "التخلي عن نفقات قليلة الجدوى"]},
    {"id": "cash", "kw": ["سيول", "نقد", "تحصيل", "ديون", "دين", "مستحقات", "خزين", "فواتير", "فاتور"],
     "titles": ["تعزيز سيولتنا وتسريع تحصيل مستحقاتنا", "ضمان سيولة تكفي لتشغيلنا دون اللجوء إلى الاقتراض العاجل"],
     "why": ["قد تربح المؤسسة على الورق وتعجز عن دفع أجورها لأن الأموال عالقة عند العملاء.",
             "تحصيل أسرع يعني تمويلًا لعملياتنا من أموالنا نحن."],
     "krs": [("متوسط مدة تحصيل الفواتير", "decrease", "يوم"), ("قيمة الديون المتأخرة", "decrease", "دج"), ("رصيد الخزينة", "stay_above", "دج"),
             ("نسبة الفواتير المحصَّلة في أجلها", "increase", "%")],
     "levers": ["تذكير العملاء بالفواتير قبل موعدها", "خصم للدفع المعجَّل", "تشديد شروط الائتمان", "متابعة الفواتير المتأخرة أسبوعيًا"]},
    {"id": "customers", "kw": ["عميل", "عملاء", "زبون", "زبائن", "رضا", "ولاء", "شكاو", "شكوى", "خدمه", "خدمة"],
     "titles": ["أن يصبح عملاؤنا أوفياء لنا ويوصون بنا", "تقديم خدمة تجعل العميل يعود إلينا"],
     "why": ["عميل راضٍ يكرّر الشراء ويجلب غيره، وهذا أرخص من البحث الدائم عن عملاء جدد.",
             "الشكاوى المتكررة تكشف أين تضيع مبيعاتنا قبل أن تظهر في الأرقام."],
     "krs": [("نسبة رضا العملاء", "increase", "%"), ("نسبة العملاء الذين يكررون الشراء", "increase", "%"), ("عدد الشكاوى الشهرية", "decrease", "شكوى"),
             ("متوسط زمن الرد على العميل", "decrease", "ساعة")],
     "levers": ["استبيان قصير بعد كل خدمة", "تعيين مسؤول مخصَّص للشكاوى", "برنامج ولاء للعملاء الدائمين"]},
    {"id": "quality", "kw": ["جود", "عيوب", "عيب", "مرتجع", "خطا", "اخطاء", "معيب", "مطابق", "اعطال", "عطل"],
     "titles": ["رفع جودة منتجاتنا حتى تتراجع العيوب والمرتجعات", "تقديم منتج مطابق للمواصفات من أول مرة"],
     "why": ["كل منتج معيب يكلّفنا مرتين: إعادة العمل وخسارة ثقة العميل.", "الجودة الثابتة هي ما يبرّر سعرنا أمام المنافسين."],
     "krs": [("نسبة المرتجعات", "decrease", "%"), ("نسبة المنتجات المعيبة", "decrease", "%"), ("نسبة المطابقة عند الفحص الأول", "increase", "%"),
             ("عدد حوادث الجودة الشهرية", "decrease", "حادثة")],
     "levers": ["فحص إضافي قبل الشحن", "تدريب الفريق على معايير الجودة", "استبدال المورّد الذي تتكرر عيوب موادّه"]},
    {"id": "operations", "kw": ["تسليم", "توصيل", "انتاج", "مخزون", "تاخر", "اجال", "طاقه", "طاقة", "تشغيل", "عمليات", "كفاءه", "كفاءة"],
     "titles": ["تسليم طلباتنا في موعدها وبكفاءة أعلى", "تشغيل أسلس يختصر الوقت بين الطلب والتسليم"],
     "why": ["التأخر في التسليم يُفقدنا العملاء أسرع من أي سبب آخر.", "عمليات منظَّمة تتيح لنا النمو دون أن نزيد التكاليف بالقدر نفسه."],
     "krs": [("نسبة الطلبات المسلَّمة في موعدها", "increase", "%"), ("متوسط زمن التسليم", "decrease", "يوم"), ("معدل استغلال الطاقة الإنتاجية", "increase", "%"),
             ("قيمة المخزون الراكد", "decrease", "دج")],
     "levers": ["إعادة تنظيم المخزون", "إضافة وردية عمل", "الاستعانة بشركة توصيل", "صيانة وقائية للآلات"]},
    {"id": "people", "kw": ["موظف", "عمال", "عامل", "فريق", "توظيف", "دوران", "تدريب", "غياب", "كفاءات", "سلامه", "سلامة", "اجور", "اجر", "رواتب"],
     "titles": ["بناء فريق مستقر ومؤهَّل يبقى معنا", "رفع كفاءة فريقنا وتقليل مغادرة أفضل عناصره"],
     "why": ["فريق يغادر باستمرار يكلّفنا التوظيف والتدريب من جديد ويُضعف الخدمة.", "المهارات التي نبنيها اليوم هي ما سيحقق أهدافنا القادمة."],
     "krs": [("نسبة دوران العاملين", "decrease", "%"), ("ساعات التدريب لكل عامل", "increase", "ساعة"), ("نسبة الغياب", "decrease", "%"),
             ("نسبة رضا العاملين", "increase", "%")],
     "levers": ["برنامج تدريب سنوي", "مراجعة سلّم الأجور", "تحسين ظروف العمل", "تعيين مشرف مباشر لكل فريق"]},
    {"id": "market", "kw": ["سوق", "اسواق", "توسع", "فرع", "تصدير", "حصه", "حصة", "منطقه", "منطقة", "ولايه", "ولاية", "منافس"],
     "titles": ["دخول سوق جديدة بقاعدة عملاء ثابتة", "زيادة حصتنا في السوق التي نعمل فيها"],
     "why": ["التوسع المدروس يقلّل اعتمادنا على سوق واحدة ويفتح لنا نموًّا لا نجده في مكاننا الحالي.", "حصة أكبر في السوق تمنحنا قدرة أفضل على التفاوض مع الموردين."],
     "krs": [("عدد العملاء في السوق الجديدة", "increase", "عميل"), ("حصتنا من السوق المستهدفة", "increase", "%"), ("الإيراد القادم من السوق الجديدة", "increase", "دج"),
             ("نسبة بلوغ العملاء المستهدفين", "increase", "%")],
     "levers": ["افتتاح فرع أو نقطة بيع", "شريك محلي يعرف السوق", "حملة تعريفية في المنطقة المستهدفة"]},
    {"id": "digital", "kw": ["رقمن", "برنامج", "نظام", "موقع", "الكتروني", "إلكتروني", "تحول", "اتمته", "أتمتة", "تطبيق"],
     "titles": ["رقمنة عملياتنا لنوفّر الوقت ونقلّل الأخطاء", "الانتقال من الأعمال الورقية إلى نظام واحد موثوق"],
     "why": ["الأعمال اليدوية المتكررة تستهلك وقت أفضل عناصرنا وتُنتج أخطاء يصعب تتبّعها.", "بيانات منظَّمة في مكان واحد تتيح لنا قرارات أسرع."],
     "krs": [("نسبة العمليات المنجزة عبر النظام", "increase", "%"), ("الوقت اللازم لإقفال الحساب الشهري", "decrease", "يوم"), ("نسبة الطلبات الواردة عبر الموقع", "increase", "%"),
             ("عدد الأخطاء في إدخال البيانات", "decrease", "خطأ")],
     "levers": ["شراء برنامج لإدارة الأعمال", "تدريب الفريق على النظام الجديد", "إطلاق متجر إلكتروني"]},
]

GENERIC_LEVERS = ["إضافة طاقة جديدة (فرع، وردية عمل، معدات)", "تغيير الأسعار أو إطلاق عرض جديد", "عميل كبير أو سوق جديدة لم تكن في تاريخنا", "تحسين الكفاءة وتقليل الهدر"]

_KR_TYPES = ("increase", "decrease", "stay_above", "stay_below", "binary", "milestone")


def _score(text: str, theme: dict) -> int:
    """How many of the theme's keywords start a word of `text` (a leading و/ب/ل/ال is ignored: «والمبيعات» still matches «مبيع»)."""
    n = normalise(text)
    words = n.split()
    forms = {w[i:] for w in words for i in (0, 1, 2, 3) if len(w) - i >= 2}
    hits = 0
    for k in theme["kw"]:
        nk = normalise(k)
        if " " in nk:
            hits += nk in n
        else:
            hits += any(f.startswith(nk) for f in forms)
    return hits


def _kr(t):
    return {"title": t[0], "type": t[1], "unit": t[2]}


def match(text: str, limit: int = 3) -> list[dict]:
    """Themes that fit `text`, best first. Empty when nothing fits (the caller then keeps the user's own words)."""
    ranked = sorted(((_score(text, th), i, th) for i, th in enumerate(THEMES)), key=lambda x: (-x[0], x[1]))
    return [th for s, _, th in ranked if s > 0][:limit]


def draft(intent: str, limit: int = 3) -> list[dict]:
    """Up to `limit` complete options {title, rationale, krs:[{title,type,unit}], theme} for what the person typed."""
    found = match(intent, limit)
    out: list[dict] = []
    if len(found) == 1:  # one clear theme: offer two different angles on it
        th = found[0]
        out.append({"theme": th["id"], "title": th["titles"][0], "rationale": th["why"][0], "krs": [_kr(k) for k in th["krs"][:3]]})
        out.append({"theme": th["id"], "title": th["titles"][1], "rationale": th["why"][1], "krs": [_kr(k) for k in th["krs"][1:4]]})
    else:
        for th in found:
            out.append({"theme": th["id"], "title": th["titles"][0], "rationale": th["why"][0], "krs": [_kr(k) for k in th["krs"][:3]]})
    return out[:limit]


def levers(*texts: str, limit: int = 4) -> list[str]:
    """Typical outside factors for a goal about `texts` (goal title, measure name): from the matching themes, else the generic four."""
    joined = " ".join(t for t in texts if t)
    out: list[str] = []
    for th in match(joined, 2):
        for x in th["levers"]:
            if x not in out:
                out.append(x)
    for x in GENERIC_LEVERS:
        if len(out) >= limit:
            break
        if x not in out:
            out.append(x)
    return out[:limit]


# -- organization direction (vision / mission / values) -----------------------------------------------------------------------------
FIELD = {"trade": "التجارة والتوزيع", "manufacturing": "الصناعة", "services": "الخدمات", "construction": "البناء والأشغال", "agri": "الفلاحة والصناعات الغذائية",
         "transport": "النقل واللوجستيات", "health": "الرعاية الصحية", "education": "التعليم والتكوين", "tech": "التكنولوجيا والمعلوماتية", "other": "مجال عملنا"}
OFFER = {"trade": "منتجات موثوقة بأسعار عادلة", "manufacturing": "منتجات مصنَّعة بإتقان", "services": "خدمات يعتمد عليها عملاؤنا", "construction": "مشاريع تُسلَّم بجودتها وفي موعدها",
         "agri": "منتجات غذائية طازجة وآمنة", "transport": "نقلًا آمنًا وفي الموعد", "health": "رعاية صحية قريبة وموثوقة", "education": "تكوينًا يفتح لمتعلّمينا فرص العمل",
         "tech": "حلولًا تقنية تبسّط عمل عملائنا", "other": "منتجات وخدمات تلبّي حاجة عملائنا"}
VALUES = ["الجودة", "النزاهة", "الالتزام بالمواعيد", "خدمة العميل", "التعلّم المستمر", "العمل الجماعي", "الشفافية", "المسؤولية", "الابتكار", "الاحترام"]


def direction(sector: str = "") -> dict:
    f, o = FIELD.get(sector, FIELD["other"]), OFFER.get(sector, OFFER["other"])
    return {
        "vision": [f"أن نكون الشريك الأول الموثوق لعملائنا في {f}", f"أن نصبح مرجعًا في {f} بجودة يعرفها السوق", f"أن ننمو في {f} نموًّا مستدامًا يخدم عملاءنا وفريقنا"],
        "mission": [f"نقدّم لعملائنا {o} بجودة ثابتة وفي الموعد، ونبني معهم علاقة طويلة.", f"نعمل كل يوم لنقدّم {o}، ونحرص على أن يجد فريقنا بيئة يتطوّر فيها.",
                    f"نخدم عملاءنا بتقديم {o} بأمانة، ونعيد استثمار نجاحنا في تحسين ما نقدّمه."],
        "values": VALUES,
    }


def has_digits(text: str) -> bool:
    return bool(re.search(r"[0-9٠-٩]", text or ""))
