"""The voice of the AI: what counts as machine-sounding Arabic, and that the offline wording is complete and consistent."""
import pytest

from app.ai import library, voice
from app.ai.tasks import draft_direction, draft_goal, explain_reality, review_goal, summarize_health


def test_voice_repairs_the_harmless_and_rejects_the_rest():
    assert voice.clean("**المبيعات** ارتفعت ٥٪ ") == "المبيعات ارتفعت 5٪"
    for bad in ("من الجدير بالذكر أن المبيعات ارتفعت.", "افتح الداشبورد لترى.", "ارتفعت المبيعات 好", "ارتفعت المبيعات 🙂"):
        with pytest.raises(ValueError):
            voice.check_style(bad)
    with pytest.raises(ValueError):
        voice.check_style("ارتفع revenue بشكل كبير")                      # an English word the user never typed
    assert voice.check_style("ارتفع Revenue عندنا", source="Revenue")      # the user's own Latin word is fine
    assert voice.check_style("بلغ الإيراد 12 مليون DZD") == "بلغ الإيراد 12 مليون DZD"


def test_a_model_answer_with_filler_or_invented_numbers_is_rejected(app):
    inputs = {"goal": "g", "series": "s", "unit": "", "verdict": {"level": "stretch"}, "facts": [10.0], "_lang": "ar"}
    with app.app_context():
        with pytest.raises(ValueError):
            explain_reality.task.validate({"summary": "بشكل عام هذا المستهدف صعب.", "reasons": [], "suggestion": "", "questions": []}, inputs)
        ok = explain_reality.task.validate({"summary": "المستهدف صعب مقارنة بتاريخك.", "reasons": ["بلغ 10 أقصى ما حققتَه.", "جملة فيها داشبورد."], "suggestion": "", "questions": ["هل ستضيف فرعًا؟"]}, inputs)
    assert ok["reasons"] == ["بلغ 10 أقصى ما حققتَه."]                     # the bad item is dropped, not the whole answer
    assert ok["questions"] == ["هل ستضيف فرعًا؟"]


def test_system_prompt_carries_voice_vocabulary_and_company(app):
    with app.app_context():
        s = voice.system("ROLE", "RULES", "ar", company={"sector_label": "تجارة وتوزيع"}, example="{}")
    assert "ROLE" in s and "VOCABULARY" in s and "تجارة وتوزيع" in s and "NEVER write these forms" in s and "Return only the JSON" in s


def test_offline_health_brief_agrees_in_number_and_names_the_priority(app):
    rows = [{"title": "مبيعات الفرع الشرقي", "status": "off_track", "progress": 32, "projected": {"low": 70, "mid": 80, "high": 92}, "target": 100, "unit": "مليون دج", "data_age_days": 5},
            {"title": "عدد العملاء الجدد", "status": "no_data", "progress": 0, "projected": None, "target": 200, "unit": "", "data_age_days": None}]
    with app.app_context():
        one = summarize_health.task.fallback({"counts": {"off_track": 1, "no_data": 1}, "rows": rows}, "ar")
        allgood = summarize_health.task.fallback({"counts": {"on_track": 3}, "rows": []}, "ar")
    assert "نتيجة واحدة خارج المسار" in one["summary"] and "مبيعات الفرع الشرقي" in one["summary"]
    assert "نتيجة بلا بيانات" not in one["summary"] and "بلا بيانات" in one["summary"]
    assert allgood["summary"].startswith("النتائج الرئيسية الـ3")
    assert one["watch"][1].endswith("حتى الآن.")


def test_offline_goal_review_names_what_to_fix(app):
    with app.app_context():
        out = review_goal.task.fallback({"findings": [{"code": "kr_activity", "level": "warn", "target": "kr:1"}, {"code": "why", "level": "warn", "target": "rationale"}], "krs": [{}, {}]}, "ar")
    assert "النتيجة الرئيسية 2" in out["summary"] and "سبب أهمية الهدف" in out["summary"]


def test_every_template_key_result_is_an_outcome_and_has_no_invented_figure(app):
    from app.modules.goals.coach import starts_with_activity
    for th in library.THEMES:
        assert 2 <= len(th["titles"]) and len(th["why"]) >= 2 and len(th["krs"]) >= 3 and len(th["levers"]) >= 3
        for title, kind, unit in th["krs"]:
            assert kind in draft_goal.KR_TYPES and not starts_with_activity(title) and not library.has_digits(title), title
        for text in [*th["titles"], *th["why"], *th["levers"]]:
            assert not library.has_digits(text), text
            voice.check_style(text)                                            # the templates obey the same voice rules as the model
    for sec in library.FIELD:
        d = library.direction(sec)
        for x in [*d["vision"], *d["mission"]]:
            voice.check_style(x)


def test_matching_ignores_prefixes_and_says_nothing_when_nothing_fits():
    assert library.draft("والمبيعات تحتاج دفعة")[0]["theme"] == "sales"
    assert library.draft("تقليل التكاليف")[0]["theme"] == "profit"
    assert library.draft("شيء غير مفهوم") == []
    assert len(library.levers("شيء غير مفهوم")) == 4


def test_draft_goal_drops_activities_digits_and_bad_types(app):
    raw = {"options": [{"title": "تنمية مبيعاتنا بشكل منتظم", "rationale": "لأن المبيعات تموّل بقية الأهداف.",
                        "krs": [{"title": "الإيراد الشهري", "type": "increase", "unit": "دج"}, {"title": "إطلاق حملة تسويقية", "type": "increase", "unit": ""},
                                {"title": "رفع الإيراد إلى 500", "type": "weird", "unit": ""}, {"title": "عدد العملاء النشطين", "type": "weird", "unit": "عميل"}]},
                       {"title": "هدف بلا نتائج", "rationale": "", "krs": []}]}
    with app.app_context():
        out = draft_goal.task.validate(raw, {"intent": "رفع المبيعات", "_lang": "ar"})
    assert len(out["options"]) == 1
    krs = out["options"][0]["krs"]
    assert [k["title"] for k in krs] == ["الإيراد الشهري", "عدد العملاء النشطين"] and krs[1]["type"] == "increase"


def test_draft_direction_has_values_even_when_the_model_gives_none(app):
    with app.app_context():
        out = draft_direction.task.validate({"vision": ["أن نكون الخيار الأول في منطقتنا", "أن نبلغ 50 فرعًا"], "mission": ["نقدّم منتجات موثوقة لعملائنا."], "values": []}, {"sector": "trade", "_lang": "ar"})
    assert out["vision"] == ["أن نكون الخيار الأول في منطقتنا"] and len(out["values"]) == 6
