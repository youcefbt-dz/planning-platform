"""The assistant as the person's travel companion: it knows the product and its developer, answers without a model from the built-in guide,
carries the site's name, and offers follow-ups. The model is a scripted fake (see test_agent.py)."""
from app.modules.agent import knowledge as K, loop
from tests.test_agent import Fake, ask, use  # noqa: F401
from tests.test_data_flow import owner  # noqa: F401


def test_the_guide_knows_the_developer_and_how_to_create_a_goal():
    assert K.answer("من مطور هذا الموقع؟")["entry"] == "developer"
    assert K.DEVELOPER in K.answer("من صنع الموقع")["answer"]
    steps = K.answer("كيف أنشئ هدفًا؟")
    assert steps["entry"] == "create_goal" and "هدف جديد" in steps["answer"] and "احفظ الهدف" in steps["answer"] and steps["suggestions"]
    assert K.answer("مرحبا، كيف أنشئ هدفا؟")["entry"] == "create_goal"          # a real question beats small talk
    assert K.answer("مرحبا")["entry"] == "hello"


def test_questions_about_their_own_data_never_get_a_guide_answer():
    for q in ("كيف حالنا؟", "اعرض النتائج الرئيسية خارج المسار", "قارن المستهدفات الحالية بالسجل التاريخي"):
        assert K.answer(q) is None and K.mentions_org_data(q)


def test_a_module_that_is_off_is_not_in_the_guide():
    on = K.guide_text(lambda m: True)
    off = K.guide_text(lambda m: m != "reports")
    assert "التقرير المؤسسي" in on and "التقرير المؤسسي" not in off
    assert K.DEVELOPER in on and "{name}" not in K.guide_text(lambda m: True, name="PlanWise")


def test_follow_up_suggestions_are_split_off_the_answer():
    body, sug = loop.split_suggestions("افتح «الأهداف».\nSUGGEST: كيف أرفع بياناتي؟ | ما هو فحص الواقعية؟ | من المطور؟")
    assert body == "افتح «الأهداف»." and sug == ["كيف أرفع بياناتي؟", "ما هو فحص الواقعية؟", "من المطور؟"]
    assert loop.split_suggestions("لا اقتراحات") == ("لا اقتراحات", [])


def test_small_numbers_in_a_chat_are_not_flagged_but_invented_large_figures_are():
    ok = loop.allowed_figures([])
    assert loop.untraceable("الرابط صالح 70 يومًا", ok, floor=1000) == []
    assert loop.untraceable("مبيعاتك 987654321", ok, floor=1000) == [987654321.0]


def test_without_a_model_the_guide_answers_and_says_so(app, owner):
    c, slug = owner
    code, res = ask(c, slug, "من مطور الموقع؟")
    assert code == 200 and res["mode"] == "guide" and K.DEVELOPER in res["answer"] and res["off_text"]
    code, res = ask(c, slug, "ما عاصمة فرنسا؟")
    assert res["mode"] == "rules" and res["suggestions"]                      # honest: this needs the model; never a made-up answer


def test_the_model_gets_the_guide_the_person_and_the_site_name_and_suggestions_are_returned(app, owner):
    c, slug = owner
    fake = Fake([{"text": "مطوّري هو يوسف بوتمجت.\nSUGGEST: كيف أبدأ؟ | كيف أنشئ هدفًا؟", "tool_calls": []}])
    use(app, fake)
    code, res = ask(c, slug, "من طورك؟")
    system = fake.seen[0]["system"]
    assert "PRODUCT GUIDE" in system and K.DEVELOPER in system and "THE PERSON:" in system and "PlanWise" in system
    assert res["answer"] == "مطوّري هو يوسف بوتمجت." and res["suggestions"] == ["كيف أبدأ؟", "كيف أنشئ هدفًا؟"] and res["unverified"] == []


def test_the_dock_shows_the_site_name_and_starts_with_friendly_questions(app, owner):
    c, slug = owner
    page = c.get(f"/app/{slug}/goals/", follow_redirects=True).get_data(as_text=True)
    assert "data-chat-reset" in page and "data-suggest" in page and "assistant-dock__hello-mark" in page
    assert "<bdi>PlanWise</bdi>" in page and "agent.starter" not in page and "agent.off" not in page      # no raw translation keys on screen
