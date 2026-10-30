"""The two promises of the architecture: the brand is swappable, modules are removable."""
import yaml

from app import create_app
from app.core.brand import Brand


def test_brand_swap_changes_every_surface(tmp_path):
    data = yaml.safe_load(open("config/brand.yaml", encoding="utf-8"))
    data["name"] = {"ar": "نَسَق"}
    data["colors"]["primary"] = "#0A7F5A"
    data["placeholder"] = False
    b = Brand(data)
    assert b.name_for("ar") == "نَسَق"
    assert "#0A7F5A" in b.css_vars()


def test_missing_logo_falls_back_to_text(app):
    with app.test_request_context("/"):
        from app.core.brand import logo_html
        app.extensions["brand"].data["logos"]["full"]["on_light"] = "does-not-exist.svg"
        app.extensions["brand"].data["logos"]["full"].pop("ar", None)
        html = str(logo_html("full", "on_light", "ar"))
        assert "logo-lockup" in html and "Plan" in html


def test_all_modules_discovered_and_toggleable(app):
    reg = app.extensions["modules"]
    assert {"goals", "initiatives", "strategy", "reports"} <= set(reg.discovered)


import pytest


@pytest.mark.parametrize("off", [["strategy", "reports"], ["initiatives"], ["goals"], ["data"], ["data", "goals"], ["goals", "initiatives", "strategy", "reports", "data"]])
def test_disabling_modules_never_breaks_the_rest(tmp_path, monkeypatch, off):
    """The 'delete freely' promise: any module can be switched off and every remaining page still renders."""
    import re
    import app.core.modules as M
    cfg = yaml.safe_load(open("config/modules.yaml", encoding="utf-8"))
    for m in off:
        cfg["modules"][m]["enabled"] = False
    p = tmp_path / "modules.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(M, "MODULES_CONFIG", p)
    a = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path/'x.db'}"})
    from app.extensions import db
    with a.app_context():
        db.create_all()
        from app.core.demo import create_demo
        create_demo("ar")
    c = a.test_client()
    seen, queue = set(), ["/app/demo/"]
    while queue and len(seen) < 80:
        url = queue.pop(0)
        path = url.split("?")[0]
        if path in seen:
            continue
        seen.add(path)
        r = c.get(url)
        assert r.status_code == 200, (off, url, r.status_code)
        html = r.get_data(as_text=True)
        for m in off:
            assert f"/{m}/" not in html, (off, url, f"link to disabled module {m}")
        for href in re.findall(r'href="(/app/demo/[^"#]*)"', html):
            if ".csv" not in href:
                queue.append(href)
    for m in off:
        assert c.get(f"/app/demo/{m}/").status_code == 404
