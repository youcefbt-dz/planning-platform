"""The assistant: tools read the organization, the loop checks the model's figures, drafts need approval. The model is a scripted fake
(no network in tests): what is under test is everything AROUND the model — which is where an assistant is made trustworthy."""
import json
from datetime import date, timedelta

from app.ai.base import Provider
from app.extensions import db
from app.modules.agent import loop
from app.modules.data.models import Series
from app.modules.goals.models import KeyResult, Objective
from tests.test_data_flow import owner, upload  # noqa: F401

END = (date.today() + timedelta(days=300)).isoformat()


class Fake(Provider):
    """Plays a script: each item is a dict {"text", "tool_calls"} or a function(convo) -> that dict. Records every conversation it saw."""
    name = "fake"
    supports_chat = True

    def __init__(self, script):
        self.script, self.seen = list(script), []

    def available(self, cfg):
        return True

    def chat(self, messages, tools, system, cfg, **kw):
        self.seen.append({"messages": json.loads(json.dumps(messages, default=str)), "tools": [t["name"] for t in tools], "system": system})
        step = self.script.pop(0)
        return {**(step(messages) if callable(step) else step), "model": "fake-1"}


def use(app, fake):
    app.extensions["ai"].chat_providers = lambda org, **kw: ([("fake", fake, {}, True)], "")


def call(name, **args):
    return {"id": f"c_{name}", "name": name, "args": args}


def ask(c, slug, text, history=None):
    r = c.post(f"/app/{slug}/assistant/chat", json={"messages": [*(history or []), {"role": "user", "content": text}]})
    return r.status_code, r.get_json()


def _series(app, c, slug):
    r = upload(c, slug, "sales_by_branch.xlsx")
    ds_id = int(r.headers["Location"].split("/")[-2])
    c.post(f"/app/{slug}/data/{ds_id}/confirm")
    with app.app_context():
        return Series.query.filter_by(dimension=None).first().id


def _goal(c, slug, sid):
    c.post(f"/app/{slug}/goals/compose", data={"series": sid, "target": "999999999", "end_date": END, "title": "رفع المبيعات", "commitment": "committed", "do": "save"})


# -- figures ------------------------------------------------------------------------------------------------------------------------------
def test_a_figure_is_traceable_when_a_tool_returned_it_or_arithmetic_on_them():
    ok = loop.allowed_figures([8637815.0, 7388644.0, 17.4])
    assert loop.untraceable("المبيعات 8637815 وكانت قبل سنة 7388644", ok) == []
    assert loop.untraceable("بزيادة 17% عن العام الماضي", ok) == []                          # 17.4 written as 17
    assert loop.untraceable("نحو 8.6 مليون", ok) == []                                    # millions
    assert loop.untraceable("الفرق 1249171", ok) == []                                     # a difference of two returned figures
    assert loop.untraceable("المبيعات 9100000", ok) == [9100000.0]                         # invented
    assert loop.untraceable("في 2026 وفي 3 أقسام و12 شهرًا", ok) == []                    # years and small counts are plain language


# -- the loop -----------------------------------------------------------------------------------------------------------------------------
def test_agent_reads_with_tools_then_answers_with_a_verified_figure(app, owner):
    c, slug = owner
    sid = _series(app, c, slug)
    _goal(c, slug, sid)
    fake = Fake([{"text": "", "tool_calls": [call("goal_health"), call("list_series")]},
                 lambda convo: {"text": "سلسلتك الأولى فيها %d قراءة." % json.loads(next(m for m in convo if m["role"] == "tool" and m["name"] == "list_series")["content"])["series"][0]["points"], "tool_calls": []}])
    use(app, fake)
    code, res = ask(c, slug, "أين نتعثر؟")
    assert code == 200 and res["mode"] == "model" and res["unverified"] == []
    assert [s["tool"] for s in res["steps"]] == ["goal_health", "list_series"]
    first = fake.seen[0]
    assert "propose_goal" in first["tools"] and "get_goal" in first["tools"]
    tool_msgs = [m for m in fake.seen[1]["messages"] if m["role"] == "tool"]
    assert {m["name"] for m in tool_msgs} == {"goal_health", "list_series"} and "needing_attention" in tool_msgs[0]["content"] + tool_msgs[1]["content"]


def test_an_invented_figure_is_sent_back_once_and_fixed(app, owner):
    c, slug = owner
    sid = _series(app, c, slug)
    fake = Fake([{"text": "", "tool_calls": [call("series_history", series_id=sid)]},
                 {"text": "مبيعاتك بلغت 987654321 دج.", "tool_calls": []},
                 {"text": "لم أجد هذا الرقم في بياناتك.", "tool_calls": []}])
    use(app, fake)
    code, res = ask(c, slug, "كم مبيعاتنا؟")
    assert res["answer"].startswith("لم أجد") and res["unverified"] == []
    repair = fake.seen[2]["messages"][-1]
    assert repair["role"] == "user" and "987654321" in repair["content"]


def test_an_invented_figure_that_persists_is_flagged_not_hidden(app, owner):
    c, slug = owner
    fake = Fake([{"text": "نمونا 987654321 دج.", "tool_calls": []}, {"text": "نمونا 987654321 دج فعلًا.", "tool_calls": []}])
    use(app, fake)
    code, res = ask(c, slug, "كم نمونا؟")
    assert res["unverified"] == [987654321.0]


def test_a_bad_tool_call_is_an_error_the_model_can_read(app, owner):
    c, slug = owner
    fake = Fake([{"text": "", "tool_calls": [call("get_goal", goal_id=99999)]}, {"text": "هذا الهدف غير موجود.", "tool_calls": []}])
    use(app, fake)
    ask(c, slug, "حدّثني عن الهدف 99999")
    tool = next(m for m in fake.seen[1]["messages"] if m["role"] == "tool")
    assert "does not exist" in tool["content"]


def test_get_goal_shows_what_came_before_the_target(app, owner):
    c, slug = owner
    sid = _series(app, c, slug)
    _goal(c, slug, sid)
    with app.app_context():
        gid = Objective.query.one().id
    fake = Fake([{"text": "", "tool_calls": [call("get_goal", goal_id=gid)]}, {"text": "تم.", "tool_calls": []}])
    use(app, fake)
    ask(c, slug, "تفاصيل الهدف")
    kr = json.loads(next(m for m in fake.seen[1]["messages"] if m["role"] == "tool")["content"])["key_results"][0]
    assert kr["target"] == 999999999 and kr["needs_change"] and kr["value_a_year_ago"] is not None and kr["best_ever"] is not None


# -- drafts -----------------------------------------------------------------------------------------------------------------------------------
def test_a_draft_takes_its_figures_from_code_and_nothing_is_created_until_approved(app, owner):
    c, slug = owner
    sid = _series(app, c, slug)
    fake = Fake([{"text": "", "tool_calls": [call("target_levels", series_id=sid, end_date=END)]},
                 {"text": "", "tool_calls": [call("propose_goal", title="رفع مبيعاتنا نموًّا منتظمًا", rationale="لأنها تموّل بقية أهدافنا",
                                                  end_date=END, key_results=[{"title": "مبيعات الفروع", "series_id": sid, "target_level": "ambitious", "target": 1}])]},
                 {"text": "صغت مسودة واحدة بانتظار اعتمادك.", "tool_calls": []}])
    use(app, fake)
    code, res = ask(c, slug, "اقترح هدفًا للمبيعات")
    assert len(res["proposals"]) == 1 and "apr" in res["proposals_html"] and "data-apply" in res["proposals_html"]
    lv = json.loads(next(m for m in fake.seen[1]["messages"] if m["role"] == "tool")["content"])
    p = res["proposals"][0]["key_results"][0]
    assert p["target"] == lv["ambitious"] and p["level"] == "ambitious"           # the ambitious level, not the "1" the model typed
    with app.app_context():
        assert Objective.query.count() == 0                                        # a draft writes nothing
    r = c.post(f"/app/{slug}/assistant/apply", json={"proposal": res["proposals"][0]})
    assert r.status_code == 200 and "/goals/" in r.get_json()["url"]
    with app.app_context():
        o = Objective.query.one()
        kr = KeyResult.query.filter_by(objective_id=o.id).one()
        assert kr.target_value == lv["ambitious"] and o.title == "رفع مبيعاتنا نموًّا منتظمًا"
        from app.modules.data import service
        assert service.linked_series_id(kr.org_id, kr.id) == sid                   # linked to its data, like a goal made on the compose page


def test_a_key_result_without_data_needs_figures_from_the_person(app, owner):
    c, slug = owner
    fake = Fake([{"text": "", "tool_calls": [call("propose_goal", title="رفع رضا الزبائن", end_date=END, key_results=[{"title": "رضا الزبائن", "unit": "%"}])]},
                 {"text": "ما قيمة رضا الزبائن اليوم وما المستهدف؟", "tool_calls": []}])
    use(app, fake)
    code, res = ask(c, slug, "اقترح هدفًا لرضا الزبائن")
    assert res["proposals"] == []
    assert "do not invent" in next(m for m in fake.seen[1]["messages"] if m["role"] == "tool")["content"]


def test_a_draft_cannot_be_forged_beyond_what_the_user_may_do(app, owner):
    c, slug = owner
    r = c.post(f"/app/{slug}/assistant/apply", json={"proposal": {"title": "هدف", "unit_id": 99999, "end_date": END,
                                                                   "key_results": [{"title": "س", "start": 1, "target": 2}]}})
    assert r.status_code == 400
    with app.app_context():
        assert Objective.query.count() == 0


# -- no model --------------------------------------------------------------------------------------------------------------------------------------
def test_without_a_model_the_person_gets_a_computed_briefing_and_the_truth(app, owner):
    c, slug = owner
    sid = _series(app, c, slug)
    _goal(c, slug, sid)
    code, res = ask(c, slug, "كيف حالنا؟")
    assert code == 200 and res["mode"] == "rules" and "نتيجة رئيسية" in res["answer"] and res["off_text"]
    legacy = c.get(f"/app/{slug}/assistant/")
    assert legacy.status_code == 302 and legacy.headers["Location"].endswith(f"/app/{slug}/")
    page = c.get(f"/app/{slug}/", follow_redirects=True).get_data(as_text=True)
    assert 'data-agent' in page and 'data-dock-open' in page and 'data-preference-key' in page
    assert 'assistant-dock__panel' in page


def test_personal_assistant_preference_is_available_to_non_admin_members(app, owner):
    from app.core.models import Membership, Organization, OrgUnit, User

    _, slug = owner
    email = "member-preferences@example.com"
    with app.app_context():
        org = Organization.query.filter_by(slug=slug).one()
        root = OrgUnit.query.filter_by(org_id=org.id, kind="company").first()
        user = User(email=email, name="Member", lang="ar")
        user.set_password("correct-horse")
        db.session.add(user)
        db.session.flush()
        db.session.add(Membership(org_id=org.id, user_id=user.id, role="member", unit_id=root.id))
        db.session.commit()

    member = app.test_client()
    member.post("/login", data={"email": email, "password": "correct-horse"})
    page = member.get(f"/app/{slug}/settings/preferences")
    assert page.status_code == 200 and 'data-assistant-visibility' in page.get_data(as_text=True)
    assert member.get(f"/app/{slug}/settings/ai").status_code == 403


def test_the_assistant_is_a_floating_control_not_a_navigation_section(app, owner):
    c, slug = owner
    page = c.get(f"/app/{slug}/goals/", follow_redirects=True).get_data(as_text=True)
    assert 'data-dock-open' in page
    assert f'href="/app/{slug}/assistant/"' not in page
    assert 'data-dock-close' in page and 'data-dock-hide' not in page
    preferences = c.get(f"/app/{slug}/settings/preferences", follow_redirects=True).get_data(as_text=True)
    assert 'data-assistant-visibility' in preferences
