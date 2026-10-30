"""Invitation links: valid 7 days, single use, joins with the chosen role."""
from datetime import datetime, timedelta

from app.core.models import Invite, Membership, User
from app.extensions import db
from tests.conftest import register


def test_invite_link_flow(app, client):
    r = register(client)
    slug = r.headers["Location"].split("/app/")[1].split("/")[0]
    assert client.post(f"/app/{slug}/settings/members/invite", data={"role": "viewer"}).status_code == 302
    with app.app_context():
        inv = Invite.query.one()
        token = inv.token
        assert inv.role == "viewer" and timedelta(days=6) < inv.expires_at - datetime.utcnow() <= timedelta(days=7)
    assert token in client.get(f"/app/{slug}/settings/members").get_data(as_text=True)
    guest = app.test_client()
    assert guest.get(f"/join/{token}").status_code == 200
    r = guest.post(f"/join/{token}", data={"name": "Sara", "email": "sara@example.com", "password": "longenough1"})
    assert r.status_code == 302
    with app.app_context():
        u = User.query.filter_by(email="sara@example.com").one()
        assert Membership.query.filter_by(user_id=u.id).one().role == "viewer"
    assert app.test_client().get(f"/join/{token}").status_code == 404          # single use


def test_expired_invite_is_refused(app, client):
    r = register(client)
    slug = r.headers["Location"].split("/app/")[1].split("/")[0]
    client.post(f"/app/{slug}/settings/members/invite", data={"role": "member"})
    with app.app_context():
        inv = Invite.query.one()
        inv.expires_at = datetime.utcnow() - timedelta(minutes=1)
        token = inv.token
        db.session.commit()
    assert app.test_client().get(f"/join/{token}").status_code == 404
