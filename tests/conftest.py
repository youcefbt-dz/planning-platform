import pytest

from app import create_app
from app.extensions import db


@pytest.fixture()
def app(tmp_path):
    app = create_app({
        "TESTING": True, "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
    })
    # No app context is held open for the whole test: a long-lived context would share `g`
    # (and Flask-Login's cached user) between requests and hide authorization bugs.
    with app.app_context():
        db.create_all()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def demo(app):
    from app.core.demo import create_demo
    with app.app_context():
        create_demo("ar")
    return app


def register(client, email="a@example.com", org="Acme Ltd"):
    return client.post("/register", data={"name": "Ada", "email": email, "password": "correct-horse", "org_name": org}, follow_redirects=False)


@pytest.fixture()
def full_modules(tmp_path, monkeypatch):
    """Config with EVERY module on (1.1 ships with strategy/initiatives off; their code must keep working)."""
    import yaml
    import app.core.modules as M
    cfg = yaml.safe_load(open(M.MODULES_CONFIG, encoding="utf-8"))
    for m in cfg["modules"].values():
        m["enabled"] = True
    p = tmp_path / "modules_all.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(M, "MODULES_CONFIG", p)
