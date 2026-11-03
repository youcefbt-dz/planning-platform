from datetime import date

from app.core.demo import create_demo
from app.core.models import Link, Membership, OrgUnit
from app.extensions import db
from app.modules.goals.models import Objective
from app.modules.goals.service import compute_objectives


def test_demo_has_one_institution_goal_cascading_to_nine_departments(app):
    today = date(2026, 11, 3)
    with app.app_context():
        org = create_demo("ar", today=today)
        root_unit = OrgUnit.query.filter_by(org_id=org.id, kind="company").one()
        departments = OrgUnit.query.filter_by(org_id=org.id, kind="department").all()
        assert len(departments) == 9
        assert all(u.parent_id == root_unit.id and u.head_id for u in departments)

        objectives = Objective.query.filter_by(org_id=org.id).all()
        institution = next(o for o in objectives if o.parent_id is None)
        children = [o for o in objectives if o.parent_id == institution.id]
        assert institution.progress_driver == "children"
        assert len(children) == 9
        assert {o.unit_id for o in children} == {u.id for u in departments}

        views = compute_objectives(org, today=today)
        assert abs(views[institution.id].progress - sum(views[o.id].progress for o in children) / len(children)) < 1e-9
        assert len(Link.query.filter_by(org_id=org.id, kind="depends_on").all()) == 4
        assert Membership.query.filter_by(org_id=org.id).count() == 19

        # These two product areas stay switched off in the shipped configuration.
        registry = app.extensions["modules"]
        assert not registry.is_enabled("strategy")
        assert not registry.is_enabled("initiatives")
