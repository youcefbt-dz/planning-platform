from app.core.models import Membership, OrgUnit, Link
from app.extensions import db
from tests.conftest import register


def _owner(client):
    r = register(client)
    return r.headers["Location"].split("/app/")[1].split("/")[0]


def test_head_of_department_moves_into_it_and_is_cleared_when_removed(client, app):
    slug = _owner(client)
    client.post(f"/app/{slug}/settings/units", data={"name": "المبيعات", "kind": "department", "parent_id": ""})
    client.post(f"/app/{slug}/settings/members", data={"name": "كريم", "email": "k@example.com", "role": "member"})
    with app.app_context():
        u = OrgUnit.query.filter_by(name="المبيعات").first()
        m = Membership.query.join(Membership.user).filter_by(email="k@example.com").first()
        uid, mid, user_id = u.id, m.id, m.user_id
    client.post(f"/app/{slug}/settings/units/{uid}/head", data={"head_id": user_id})
    with app.app_context():
        assert db.session.get(OrgUnit, uid).head_id == user_id
        assert db.session.get(Membership, mid).unit_id == uid                     # a head belongs to the department they head
    page = client.get(f"/app/{slug}/map/units/{uid}").get_data(as_text=True)
    assert "كريم" in page and 'class="dsec"' in page
    client.post(f"/app/{slug}/settings/members/{mid}", data={"action": "remove"})
    with app.app_context():
        assert db.session.get(OrgUnit, uid).head_id is None                       # nobody is left heading it


def test_departments_grid_and_dependency_between_departments(app, demo):
    c = app.test_client()
    page = c.get("/app/demo/map/units").get_data(as_text=True)
    assert 'class="dcard"' in page or "dcard" in page
    with app.app_context():
        from app.modules.goals.models import Objective
        a = next(o for o in Objective.query.order_by(Objective.id).all() if o.unit and o.unit.kind != "company")
        # a dependency is a plain link; the departments' pages derive the relation from it
        other = next(o for o in Objective.query.all() if o.unit and o.unit.kind != "company" and o.unit_id != a.unit_id)
        db.session.add(Link(org_id=a.org_id, source_type="objective", source_id=a.id, target_type="objective", target_id=other.id, kind="depends_on"))
        db.session.commit()
        uid, other_unit = a.unit_id, other.unit.name
    html = c.get(f"/app/demo/map/units/{uid}").get_data(as_text=True)
    assert other_unit in html and "rel__u" in html


def _person(app, org_id, email, unit_id, role="member", head_of=None):
    from app.core.models import User
    with app.app_context():
        u = User(email=email, name=email.split("@")[0], lang="ar")
        u.set_password("correct-horse")
        db.session.add(u)
        db.session.flush()
        db.session.add(Membership(org_id=org_id, user_id=u.id, role=role, unit_id=unit_id))
        if head_of:
            db.session.get(OrgUnit, head_of).head_id = u.id
        db.session.commit()


def _login(app, email):
    c = app.test_client()
    c.post("/login", data={"email": email, "password": "correct-horse"})
    return c


def test_department_head_edits_only_their_own_departments_goals(client, app):
    from app.modules.goals.models import Objective
    slug = _owner(client)
    with app.app_context():
        org_id = OrgUnit.query.first().org_id
        a = OrgUnit(org_id=org_id, name="A", kind="department", parent_id=OrgUnit.query.first().id)
        b = OrgUnit(org_id=org_id, name="B", kind="department", parent_id=OrgUnit.query.first().id)
        db.session.add_all([a, b])
        db.session.flush()
        sub = OrgUnit(org_id=org_id, name="A1", kind="team", parent_id=a.id)
        db.session.add(sub)
        db.session.flush()
        goals = {k: Objective(org_id=org_id, title=f"goal {k}", unit_id=u) for k, u in (("a", a.id), ("b", b.id), ("sub", sub.id), ("org", None))}
        db.session.add_all(goals.values())
        db.session.commit()
        gid = {k: v.id for k, v in goals.items()}
        a_id, b_id = a.id, b.id
    _person(app, org_id, "head@example.com", a_id, head_of=a_id)
    _person(app, org_id, "plain@example.com", a_id)
    head, plain = _login(app, "head@example.com"), _login(app, "plain@example.com")
    base = f"/app/{slug}/goals"
    edit = lambda c, k: c.post(f"{base}/{gid[k]}/edit", data={"title": "changed", "unit_id": ""}).status_code
    assert head.get(f"{base}/{gid['a']}/edit").status_code == 200
    assert head.get(f"{base}/{gid['sub']}/edit").status_code == 200           # the departments under theirs
    assert head.get(f"{base}/{gid['b']}/edit").status_code == 403             # another department
    assert head.get(f"{base}/{gid['org']}/edit").status_code == 403           # the organization's own goals
    assert head.post(f"{base}/{gid['b']}/delete").status_code == 403
    assert head.post(f"{base}/{gid['b']}/kr", data={"title": "x"}).status_code == 403
    # they cannot move their goal out of their scope, nor create one outside it
    head.post(f"{base}/{gid['a']}/edit", data={"title": "moved", "unit_id": b_id, "cycle_id": ""})
    head.post(f"{base}/new?classic=1", data={"title": "outside", "unit_id": b_id})
    with app.app_context():
        assert db.session.get(Objective, gid["a"]).unit_id == a_id
        assert Objective.query.filter_by(title="outside").count() == 0
    head.post(f"{base}/new?classic=1", data={"title": "mine", "unit_id": a_id})
    with app.app_context():
        assert Objective.query.filter_by(title="mine", unit_id=a_id).count() == 1
    # a plain member edits nothing and creates nothing; the owner still edits everything
    assert plain.get(f"{base}/{gid['a']}/edit").status_code == 403
    assert plain.get(f"{base}/new?classic=1").status_code == 403
    assert client.get(f"{base}/{gid['b']}/edit").status_code == 200
    assert client.get(f"{base}/{gid['org']}/edit").status_code == 200
    # buttons follow the locks
    page = head.get(f"{base}/{gid['b']}").get_data(as_text=True)
    assert f"/goals/{gid['b']}/edit" not in page
    assert f"/goals/{gid['a']}/edit" in head.get(f"{base}/{gid['a']}").get_data(as_text=True)


def test_owner_of_a_goal_can_update_it_without_being_a_head(client, app):
    from app.modules.goals.models import Objective
    slug = _owner(client)
    with app.app_context():
        root = OrgUnit.query.first()
        org_id = root.id and root.org_id
        d = OrgUnit(org_id=org_id, name="D", kind="department", parent_id=root.id)
        db.session.add(d)
        db.session.flush()
        d_id = d.id
    _person(app, org_id, "w@example.com", d_id)
    with app.app_context():
        from app.core.models import User
        uid = User.query.filter_by(email="w@example.com").first().id
        mine = Objective(org_id=org_id, title="mine", unit_id=d_id, owner_id=uid)
        other = Objective(org_id=org_id, title="other", unit_id=d_id)
        db.session.add_all([mine, other])
        db.session.commit()
        mine_id, other_id = mine.id, other.id
    w = _login(app, "w@example.com")
    base = f"/app/{slug}/goals"
    assert w.post(f"{base}/{mine_id}/checkin", data={"comment": "going well"}).status_code == 302
    assert w.post(f"{base}/{other_id}/checkin", data={"comment": "nope"}).status_code == 403


def test_invite_link_has_a_qr_code_only_for_who_manages_members(client, app):
    slug = _owner(client)
    client.post(f"/app/{slug}/settings/members/invite", data={"role": "member"})
    with app.app_context():
        from app.core.models import Invite
        iid = Invite.query.first().id
    r = client.get(f"/app/{slug}/settings/members/invite/{iid}/qr.svg")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml" and b"<svg" in r.data
    assert "no-store" in r.headers["Cache-Control"]
    assert f"/invite/{iid}/qr.svg" in client.get(f"/app/{slug}/settings/members").get_data(as_text=True)
    assert app.test_client().get(f"/app/{slug}/settings/members/invite/{iid}/qr.svg").status_code in (302, 401, 403)


def test_compose_page_for_a_head_offers_only_their_departments_and_saves_there(client, app):
    from app.modules.goals.models import Objective
    slug = _owner(client)
    with app.app_context():
        root = OrgUnit.query.first()
        a = OrgUnit(org_id=root.org_id, name="قسمي", kind="department", parent_id=root.id)
        b = OrgUnit(org_id=root.org_id, name="قسم غيري", kind="department", parent_id=root.id)
        db.session.add_all([a, b])
        db.session.commit()
        org_id, aid, bid = root.org_id, a.id, b.id
    _person(app, org_id, "head@example.com", aid, head_of=aid)
    c = _login(app, "head@example.com")
    page = c.get(f"/app/{slug}/goals/compose").get_data(as_text=True)
    assert "قسمي" in page and "قسم غيري" not in page and 'cai' in page
    r = c.post(f"/app/{slug}/goals/compose", data={"source": "manual", "name": "عملاء", "start": "10", "target": "20", "end_date": "2099-01-01",
                                                    "title": "نمو العملاء", "unit_id": str(bid), "do": "save"})
    assert r.status_code == 302
    with app.app_context():
        assert Objective.query.one().unit_id == aid                                # asking for another department falls back to his own


def test_split_a_goal_into_departments_by_a_head_and_by_the_owner(client, app):
    from app.modules.goals.models import Objective
    slug = _owner(client)
    with app.app_context():
        root = OrgUnit.query.first()
        a = OrgUnit(org_id=root.org_id, name="المبيعات", kind="department", parent_id=root.id)
        b = OrgUnit(org_id=root.org_id, name="المالية", kind="department", parent_id=root.id)
        db.session.add_all([a, b])
        db.session.flush()
        top = Objective(org_id=root.org_id, title="نمو الإيراد", progress_driver="key_results", unit_id=root.id)
        db.session.add(top)
        db.session.commit()
        org_id, aid, bid, tid = root.org_id, a.id, b.id, top.id
    page = client.get(f"/app/{slug}/goals/{tid}").get_data(as_text=True)
    assert "cai--split" in page                                                     # the owner sees the proposal box
    frag = client.post(f"/app/{slug}/goals/{tid}/split").get_data(as_text=True)
    assert f'name="title_{aid}"' in frag and f'name="title_{bid}"' in frag
    r = client.post(f"/app/{slug}/goals/{tid}/split/save", data={"unit": [str(aid), str(bid)], f"title_{aid}": "نمو مبيعات القسم", f"title_{bid}": ""})
    assert r.status_code == 302
    with app.app_context():
        kids = Objective.query.filter_by(parent_id=tid).all()
        assert [k.unit_id for k in kids] == [aid]                                   # the empty title was skipped; the child is linked to its parent
    _person(app, org_id, "h2@example.com", bid, head_of=bid)
    c = _login(app, "h2@example.com")
    frag = c.post(f"/app/{slug}/goals/{tid}/split").get_data(as_text=True)
    assert f'name="title_{bid}"' in frag and f'name="title_{aid}"' not in frag     # a head is offered only his own department
    assert c.post(f"/app/{slug}/goals/{tid}/split/save", data={"unit": [str(aid)], f"title_{aid}": "x"}).status_code == 302
    with app.app_context():
        assert Objective.query.filter_by(parent_id=tid, unit_id=aid).count() == 1   # he could not add one for another department
