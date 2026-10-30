"""The user explains the file and its columns to the model: saved, sent with the data, never lost, never allowed to override the data."""
from app.ai.hub import Hub
from app.ai.tasks.map_columns import reconcile
from app.extensions import db
from app.modules.data import service
from app.modules.data.models import Dataset
from tests.test_data_flow import owner, upload  # noqa: F401  (fixtures / helpers)


def _offline(inputs):
    return Hub().run("map_columns", inputs, lang="ar", consent=False)


def _new_dataset(app, owner):
    c, slug = owner
    r = upload(c, slug, "المبيعات_والموظفون.xlsx")
    return c, slug, int(r.headers["Location"].split("/")[-2])


def test_notes_are_autosaved_and_sent_with_the_data(app, owner):
    c, slug, ds_id = _new_dataset(app, owner)
    r = c.post(f"/app/{slug}/data/{ds_id}/explain", data={"save_only": "1", "file_note": "مبيعات الفروع", "note_2": "عدد الطلبات"})
    assert r.get_json() == {"ok": True}
    seen = {}
    with app.app_context():
        ds = db.session.get(Dataset, ds_id)
        assert ds.meta["file_note"] == "مبيعات الفروع" and ds.meta["col_notes"]["2"]["t"] == "عدد الطلبات"
        service.analyze(ds, runner=lambda i: (seen.update(i), _offline(i))[1])
        assert seen["notes"] == {"file": "مبيعات الفروع", "columns": {2: "عدد الطلبات"}}
        assert ds.meta["col_notes"]["2"]["t"] == "عدد الطلبات" and ds.meta["file_note"] == "مبيعات الفروع"   # survives re-reading
        assert next(col for col in ds.columns if col["index"] == 2).get("explained") is True


def test_a_note_does_not_follow_its_position_to_another_column(app, owner):
    c, slug, ds_id = _new_dataset(app, owner)
    c.post(f"/app/{slug}/data/{ds_id}/explain", data={"save_only": "1", "note_2": "عدد الطلبات"})
    seen = {}
    with app.app_context():
        ds = db.session.get(Dataset, ds_id)
        meta = dict(ds.meta); notes = {k: dict(v) for k, v in meta["col_notes"].items()}
        notes["2"]["h"] = "some other header"            # the table changed: column 2 is not the one the note was written for
        meta["col_notes"] = notes; ds.meta = meta
        service.analyze(ds, runner=lambda i: (seen.update(i), _offline(i))[1])
    assert "notes" not in seen


def test_empty_note_removes_it_and_html_is_not_executed(app, owner):
    c, slug, ds_id = _new_dataset(app, owner)
    c.post(f"/app/{slug}/data/{ds_id}/explain", data={"save_only": "1", "note_2": "<script>alert(1)</script>"})
    page = c.get(f"/app/{slug}/data/{ds_id}/map").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    c.post(f"/app/{slug}/data/{ds_id}/explain", data={"save_only": "1", "note_2": "  "})
    with app.app_context():
        assert "2" not in db.session.get(Dataset, ds_id).meta["col_notes"]


def test_reread_keeps_what_the_user_decided_by_hand(app, owner):
    c, slug, ds_id = _new_dataset(app, owner)
    with app.app_context():
        ds = db.session.get(Dataset, ds_id)
        service.edit_column(ds, 3, role="dimension", label="My own name")
        db.session.commit()
    r = c.post(f"/app/{slug}/data/{ds_id}/explain", data={"reread": "1", "file_note": "x"})
    assert r.status_code == 302
    with app.app_context():
        col = next(col for col in db.session.get(Dataset, ds_id).columns if col["index"] == 3)
        assert col["label"] == "My own name" and col["role"] == "dimension" and col["state"] == "user"
        assert all(q["column"] != 3 for q in db.session.get(Dataset, ds_id).questions)


def _inputs(typ):
    return {"headers": ["a"], "row_count": 5, "profile": [{"index": 0, "type": typ, "examples": [], "distinct": 3}],
            "notes": {"file": "", "columns": {"0": "explained"}}}


def test_an_explanation_settles_a_doubt_but_never_beats_the_data(app):
    data = {"columns": [{"index": 0, "role": "measure", "label": "Orders", "confidence": 0.3}]}
    with app.app_context():
        col = reconcile(data, _inputs("number"), "ar", trust_notes=True)["columns"][0]
        assert col["role"] == "measure" and col["confidence"] >= 0.75                      # the owner explained it, the data agrees
        assert reconcile(data, _inputs("number"), "ar", trust_notes=False)["columns"][0]["confidence"] == 0.3   # the rules never read notes
        text = reconcile(data, _inputs("text"), "ar", trust_notes=True)["columns"][0]
        assert text["role"] == "ignore" and text["confidence"] <= 0.3                      # "measure" over text cells stays rejected
        codes = {"columns": [{"index": 0, "role": "dimension", "label": "Code", "confidence": 0.9}]}
        assert reconcile(codes, _inputs("number"), "ar", trust_notes=True)["columns"][0]["confidence"] >= 0.75   # "these numbers are codes"


def test_notes_page_renders_for_the_owner(app, owner):
    c, slug, ds_id = _new_dataset(app, owner)
    page = c.get(f"/app/{slug}/data/{ds_id}/map?lang=ar").get_data(as_text=True)
    for hook in ('data-panel="columns"', 'id="notes-form"', 'name="note_2"', "data-confirm-btn", 'class="grid"'):
        assert hook in page
