"""Demo data: two years of monthly operations figures for three branches, written as a real .xlsx so the demo shows the whole flow."""
from __future__ import annotations

import io
import math
import random
from datetime import date
from types import SimpleNamespace

from openpyxl import Workbook

from app.extensions import db
from app.modules.data import service
from app.modules.data.models import Dataset

NAMES = ("بيانات التشغيل الشهرية", "التاريخ", "الفرع", "رقم الأعمال (مليون دج)", "هامش الربح الإجمالي %", "التسليم في الموعد %", "مدة التسليم (يوم)", ("الجزائر", "وهران", "قسنطينة"))

def _months(today: date, n: int = 24):
    y, m = today.year, today.month - 1               # up to last month
    if m == 0:
        y, m = y - 1, 12
    out = []
    for _ in range(n):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def seed(org, lang: str, ctx: dict) -> None:
    title, c_date, c_branch, c_rev, c_margin, c_ontime, c_days, branches = NAMES
    rnd = random.Random(7)
    today = ctx["today"]
    months = _months(today)
    wb = Workbook()
    ws = wb.active
    ws.title = title[:30]
    ws.append([c_date, c_branch, c_rev, c_margin, c_ontime, c_days])
    weights = (1.0, 0.7, 0.55)
    for k, mo in enumerate(months):
        season = 1 + 0.12 * math.sin((mo.month - 3) / 12 * 2 * math.pi) + (0.08 if mo.month in (11, 12) else 0)
        for b, name in enumerate(branches):
            outage = 0.58 if (b == 2 and k == len(months) - 8) else 1.0     # one branch lost a month (a stock-out): the dashboard marks it
            rev = outage * 14.5 * weights[b] * (1 + 0.009 * k) * season * (1 + rnd.gauss(0, 0.025))
            margin = 26.2 + 0.07 * k + rnd.gauss(0, 0.5) + (0.4 if b == 0 else -0.2 * b)
            ontime = 80.5 + 0.2 * k + rnd.gauss(0, 1.2) - 0.8 * b
            days = 9.4 - 0.05 * k + rnd.gauss(0, 0.25) + 0.3 * b
            ws.append([mo, name, round(rev, 2), round(margin, 1), round(min(ontime, 99), 1), round(days, 1)])
    for row in ws.iter_rows(min_row=2, max_col=1):
        row[0].number_format = "yyyy-mm"
    buf = io.BytesIO()
    wb.save(buf)
    fname = f"{title}.xlsx"
    ds = Dataset(org_id=org.id, name=title, filename=fname, status="draft", stored_as=service.store_file(org.id, buf.getvalue(), fname))
    db.session.add(ds)
    db.session.flush()

    from app.ai.tasks import map_columns

    def offline(inputs):
        return SimpleNamespace(data=map_columns.task.fallback(inputs, lang), provider="offline", model="", external=False, fell_back=False, errors=[], ms=0)

    service.analyze(ds, runner=offline)
    # the demo is "already confirmed by a person": the unit and direction a manager would give
    service.edit_column(ds, 2, role="measure", unit="M DZD", aggregation="sum", direction="higher_better")
    service.edit_column(ds, 3, role="measure", unit="%", aggregation="avg", direction="higher_better")
    service.edit_column(ds, 4, role="measure", unit="%", aggregation="avg", direction="higher_better")
    service.edit_column(ds, 5, role="measure", unit="", aggregation="avg", direction="lower_better")
    ds.questions = []
    service.refresh_summary(ds, lang)
    service.confirm(ds)
    db.session.flush()

    # measure the demo goals with the demo series (matched by the goals demo's own titles)
    try:
        from app.modules.goals.models import KeyResult
    except Exception:  # goals module absent: nothing to link
        return
    wanted = {"margin": 3, "ontime": 4, "days": 5}
    keys = {"margin": "هامش الربح الإجمالي", "ontime": "نسبة التسليم في الموعد", "days": "المدة من الطلب إلى التسليم (يوم)"}
    from app.modules.data.models import Series

    total = {s.name: s for s in Series.query.filter_by(dataset_id=ds.id, dimension=None)}
    cols_by_idx = {c["index"]: c["label"] for c in ds.columns}
    for key, col_idx in wanted.items():
        kr = KeyResult.query.filter_by(org_id=org.id, title=keys[key]).first()
        s = total.get(cols_by_idx.get(col_idx))
        if kr and s:
            service.set_kr_series(org.id, kr.id, s.id)

    # one goal that goes beyond what history supports, with the outside factors that justify it (shows the factors and the justification in reports)
    try:
        from app.modules.goals.models import KRFactor
    except Exception:
        return
    kr = KeyResult.query.filter_by(org_id=org.id, title=keys["ontime"]).first()
    if kr is None:
        return
    FACTORS = (("عقد جديد مع شركة نقل بتتبّع مباشر", "contract", 2.5, "confirmed", "عقد موقَّع"), ("افتتاح مركز توزيع جهوي ثانٍ", "capacity", 1.5, "probable", "قرار المجلس، التسليم في الربع القادم"))
    for n, kind, eff, cert, ev in FACTORS:
        db.session.add(KRFactor(org_id=org.id, key_result_id=kr.id, title=n, kind=kind, effect=eff, certainty=cert, evidence=ev))
    kr.justification = "المستهدف يتجاوز ما حققناه تاريخيًا. العقد الموقَّع مع شركة النقل يضيف نحو 2.5 نقطة، ومركز التوزيع الثاني يُرجَّح أن يضيف نحو 1.5 نقطة إن سُلِّم في موعده."
    kr.confidence = 6
