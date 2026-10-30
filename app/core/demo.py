"""Demo organization builder. Core people/units/cycles live here; each module seeds its own data
through its manifest `seed(org, lang, ctx)` hook, and may read what earlier modules put in ctx."""
from __future__ import annotations

import secrets
from datetime import date, timedelta

from flask import current_app

from app.core.models import Cycle, Membership, Organization, OrgUnit, User
from app.extensions import db

SLUGS = {"ar": "demo"}

ORG_NAME = "مؤسسة الأفق للتجهيزات"
PEOPLE = {  # key: (name, title, role)
    "ceo": ("سمير بن عيسى", "المدير العام", "owner"),
    "fin": ("نادية حداد", "مديرة المالية", "admin"),
    "sales": ("كريم مزياني", "مدير المبيعات", "admin"),
    "ops": ("ليلى بوزيد", "مديرة العمليات", "admin"),
    "people": ("أمين شرفي", "مسؤول الموارد البشرية", "member"),
}
UNITS = [  # key, parent, kind, name
    ("root", None, "company", ORG_NAME),
    ("sales", "root", "department", "المبيعات"),
    ("ops", "root", "department", "العمليات"),
    ("logistics", "ops", "team", "اللوجستيك"),
    ("fin", "root", "department", "المالية"),
    ("people", "root", "department", "الموارد البشرية"),
]


def delete_demo(slug: str) -> None:
    org = Organization.query.filter_by(slug=slug).first()
    if not org:
        return
    org_id = org.id
    # delete tenant rows of every table that carries org_id, children first
    from sqlalchemy import text

    tables = [t.name for t in db.metadata.sorted_tables if "org_id" in t.c and t.name not in ("organization", "membership")]
    ids_obj = "SELECT id FROM objective WHERE org_id=:o"
    with db.engine.begin() as conn:
        for stmt in (
            "DELETE FROM indicator_value WHERE indicator_id IN (SELECT id FROM indicator WHERE org_id=:o)",
            "DELETE FROM milestone WHERE initiative_id IN (SELECT id FROM initiative WHERE org_id=:o)",
        ):
            try:
                conn.execute(text(stmt), {"o": org.id})
            except Exception:  # module tables may not exist if a module was removed
                pass
        conn.execute(text("UPDATE membership SET unit_id=NULL WHERE org_id=:o"), {"o": org.id})
        for name in reversed(tables):
            conn.execute(text(f'DELETE FROM "{name}" WHERE org_id=:o'), {"o": org.id})
        conn.execute(text("DELETE FROM membership WHERE org_id=:o"), {"o": org.id})
        user_ids = [r[0] for r in conn.execute(text("SELECT id FROM user WHERE email LIKE :e"), {"e": f"%@{slug}.demo.invalid"})]
        for uid in user_ids:
            conn.execute(text("DELETE FROM user WHERE id=:u"), {"u": uid})
        conn.execute(text("DELETE FROM organization WHERE id=:o"), {"o": org.id})
    db.session.expire_all()
    # uploaded demo files live outside the database
    import shutil
    from pathlib import Path

    shutil.rmtree(Path(current_app.instance_path) / "uploads" / str(org_id), ignore_errors=True)


PROFILE = {
    "sector": "trade", "size": "medium", "currency": "DZD", "fiscal_start": 1,
    "vision": "أن نكون الخيار الأول للتوزيع الموثوق في شمال الجزائر.",
    "mission": "نوصل البضاعة في موعدها وبجودة ثابتة، ونبني علاقة طويلة مع كل عميل.",
    "values": "الأمانة، الالتزام بالمواعيد، الجودة",
}


def create_demo(lang: str, today: date | None = None) -> Organization:
    today = today or date.today()
    slug = SLUGS[lang]
    delete_demo(slug)
    org = Organization(name=ORG_NAME, slug=slug, is_demo=True, settings={})
    db.session.add(org)
    db.session.flush()
    from app.core import profile as _profile

    _profile.save_profile(org, **PROFILE)

    units = {}
    for key, parent, kind, names in UNITS:
        u = OrgUnit(org_id=org.id, parent_id=units[parent].id if parent else None, name=names, kind=kind, position=len(units))
        db.session.add(u)
        db.session.flush()
        units[key] = u

    users = {}
    for key, (names, titles, role) in PEOPLE.items():
        u = User(email=f"{key}@{slug}.demo.invalid", name=names, lang=lang)
        u.set_password(secrets.token_urlsafe(24))  # nobody signs in as a demo person
        db.session.add(u)
        db.session.flush()
        users[key] = u
        unit = {"ceo": "root", "fin": "fin", "sales": "sales", "ops": "ops", "people": "people"}[key]
        db.session.add(Membership(org_id=org.id, user_id=u.id, role=role, unit_id=units[unit].id, title=titles))
        units[unit].head_id = u.id

    y = today.year
    year = Cycle(org_id=org.id, name=str(y), kind="year", start_date=date(y, 1, 1), end_date=date(y, 12, 31), status="active")
    db.session.add(year)
    db.session.flush()
    q = (today.month - 1) // 3
    qs = date(y, q * 3 + 1, 1)
    qe = (date(y + 1, 1, 1) if q == 3 else date(y, q * 3 + 4, 1)) - timedelta(days=1)
    quarter = Cycle(org_id=org.id, parent_id=year.id, name=f"Q{q + 1} {y}", kind="quarter", start_date=qs, end_date=qe, status="active")
    db.session.add(quarter)
    db.session.flush()

    ctx = {"today": today, "users": users, "units": units, "cycles": {"year": year, "quarter": quarter}}
    for mid, fn in current_app.extensions["modules"].seeders():
        fn(org, lang, ctx)
    db.session.commit()
    return org
