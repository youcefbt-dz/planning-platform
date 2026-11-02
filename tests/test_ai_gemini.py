"""Gemini as the first cloud provider: structured answers, tool calls for the agent, per-model and per-provider fail-over, and honest explanations."""
import io
import json
import urllib.error

import pytest

from app.ai.base import AIRequest, ProviderError, RateLimited
from app.ai.hub import Hub
from app.ai.providers import gemini as G
from app.ai.tasks import map_columns
from tests.test_ai import INPUTS, PROFILE

MAPPING = {"table_summary": "x", "columns": [
    {"index": 0, "label": "Mois", "role": "date", "confidence": 0.99, "meaning": "المحور الزمني: كل صف ينتمي إلى شهر محدد من هذا العمود."},
    {"index": 1, "label": "Agence", "role": "dimension", "confidence": 0.95, "meaning": "الفرع الذي سُجّلت فيه القراءة، ويقسّم الأرقام بين الوكالات."},
    {"index": 2, "label": "Chiffre d'affaires", "role": "measure", "unit": "DZD", "aggregation": "sum", "confidence": 0.97,
     "meaning": "قيمة ما باعته الوكالة في الشهر؛ ارتفاعها تحسّن في النشاط التجاري."},
    {"index": 3, "label": "مب", "role": "measure", "aggregation": "sum", "confidence": 0.9, "meaning": "رقم غير واضح الاسم يُقرأ مع بقية الأعمدة قبل الاعتماد عليه."}]}


def reply(obj):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj, ensure_ascii=False)}]}, "finishReason": "STOP"}]}


def http_error(code, retry_after="30"):
    return urllib.error.HTTPError("https://x", code, "err", {"retry-after": retry_after}, io.BytesIO(b'{"error":{}}'))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    G._PARK.clear()
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setenv("GEMINI_MODEL", "flash-a, flash-b")
    yield
    G._PARK.clear()


def script(monkeypatch, handler):
    calls = []

    def post(url, body, key, timeout):
        calls.append({"url": url, "body": body, "key": key})
        return handler(url, body, len(calls))

    monkeypatch.setattr(G.GeminiProvider, "_post", staticmethod(post))
    return calls


def test_gemini_returns_structured_json_with_the_key_in_a_header(app, monkeypatch):
    calls = script(monkeypatch, lambda u, b, n: reply({"ok": True}))
    h = Hub()
    cfg = h.provider_cfg("gemini")
    req = AIRequest(task=map_columns.task, inputs={}, lang="ar", system="sys", user="usr", schema={"type": "object"}, max_tokens=900)
    data, model = G.provider.complete(req, cfg)
    assert data == {"ok": True} and model == "flash-a"
    assert calls[0]["url"].endswith("/models/flash-a:generateContent") and calls[0]["key"] == "g-test"
    assert calls[0]["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert calls[0]["body"]["generationConfig"]["maxOutputTokens"] >= 2048           # room for the model's own reasoning


def test_a_limited_model_is_skipped_for_the_next_model_of_the_same_provider(app, monkeypatch):
    def handler(url, body, n):
        if "flash-a" in url:
            raise http_error(429)
        return reply({"ok": 1})

    calls = script(monkeypatch, handler)
    req = AIRequest(task=map_columns.task, inputs={}, lang="ar", system="s", user="u", schema={})
    data, model = G.provider.complete(req, Hub().provider_cfg("gemini"))
    assert model == "flash-b" and len(calls) == 2
    G.provider.complete(req, Hub().provider_cfg("gemini"))
    assert len(calls) == 3 and "flash-b" in calls[2]["url"]                          # flash-a is parked: not asked again


def test_all_models_limited_raises_rate_limited_with_the_wait(app, monkeypatch):
    script(monkeypatch, lambda u, b, n: (_ for _ in ()).throw(http_error(429, "42")))
    req = AIRequest(task=map_columns.task, inputs={}, lang="ar", system="s", user="u", schema={})
    with pytest.raises(RateLimited) as e:
        G.provider.complete(req, Hub().provider_cfg("gemini"))
    assert e.value.retry_after == 42


def test_a_bad_key_is_not_a_rate_limit(app, monkeypatch):
    script(monkeypatch, lambda u, b, n: (_ for _ in ()).throw(http_error(403)))
    req = AIRequest(task=map_columns.task, inputs={}, lang="ar", system="s", user="u", schema={})
    with pytest.raises(ProviderError) as e:
        G.provider.complete(req, Hub().provider_cfg("gemini"))
    assert not isinstance(e.value, RateLimited)


def test_gemini_limited_goes_to_grok_at_once_and_is_not_asked_again(app, monkeypatch):
    """The site never stalls on a limit: Gemini answers 429 once, Grok answers, and the next request skips Gemini without calling it."""
    gem = script(monkeypatch, lambda u, b, n: (_ for _ in ()).throw(http_error(429)))
    from app.ai.providers import xai as X

    grok = []

    def grok_complete(self, req, cfg):
        grok.append(1)
        return json.loads(json.dumps(MAPPING)), "grok-test"

    monkeypatch.setattr(X.XAIProvider, "complete", grok_complete)
    monkeypatch.setenv("XAI_API_KEY", "x")
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    h = Hub()
    h.cfg["chain"] = ["gemini", "xai", "offline"]
    with app.app_context():
        r1 = h.run("map_columns", INPUTS, lang="ar", consent=True)
        calls_after_first = len(gem)
        r2 = h.run("map_columns", INPUTS, lang="ar", consent=True)
    assert r1.provider == "xai" and r2.provider == "xai" and len(grok) == 2
    assert len(gem) == calls_after_first                                              # parked: the second request did not wait for Gemini again
    assert h.cooling("gemini")


def test_gemini_is_chosen_first_when_available(app, monkeypatch):
    script(monkeypatch, lambda u, b, n: reply(MAPPING))
    h = Hub()
    assert h.chain().index("gemini") < h.chain().index("xai") < h.chain().index("offline")
    with app.app_context():
        r = h.run("map_columns", INPUTS, lang="ar", consent=True)
    assert r.provider == "gemini" and r.model == "flash-a" and r.external is True
    assert all(c["meaning"] for c in r.data["columns"])


def test_gemini_chat_sends_tools_signatures_and_merges_results(app, monkeypatch):
    seen = {}

    def handler(url, body, n):
        seen["body"] = body
        return {"candidates": [{"content": {"parts": [
            {"functionCall": {"name": "goal_health", "args": {"limit": 3}}, "thoughtSignature": "SIG1"},
            {"functionCall": {"name": "org_units", "args": {}}}]}}]}

    script(monkeypatch, handler)
    tools = [{"name": "goal_health", "description": "d", "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
             {"name": "org_units", "description": "d", "parameters": {"type": "object", "properties": {}}}]
    msgs = [{"role": "user", "content": "كيف حالنا؟"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "name": "goal_health", "args": {}, "sig": "S0"}, {"id": "b", "name": "org_units", "args": {}}]},
            {"role": "tool", "tool_call_id": "a", "name": "goal_health", "content": json.dumps({"total": 4})},
            {"role": "tool", "tool_call_id": "b", "name": "org_units", "content": json.dumps([{"name": "x"}])}]
    turn = G.provider.chat(msgs, tools, "system", Hub().provider_cfg("gemini"))
    assert [c["name"] for c in turn["tool_calls"]] == ["goal_health", "org_units"] and turn["tool_calls"][0]["sig"] == "SIG1" and "sig" not in turn["tool_calls"][1]
    body = seen["body"]
    decls = body["tools"][0]["functionDeclarations"]
    assert "parametersJsonSchema" in decls[0] and "parametersJsonSchema" not in decls[1]  # no empty schema for a tool without arguments
    roles = [c["role"] for c in body["contents"]]
    assert roles == ["user", "model", "user"]                                         # both results of the round travel in ONE user turn
    assert body["contents"][1]["parts"][0]["thoughtSignature"] == "S0"
    assert len(body["contents"][2]["parts"]) == 2 and body["contents"][2]["parts"][1]["functionResponse"]["response"] == {"result": [{"name": "x"}]}


# -- explanations that say something ----------------------------------------------------------------------------------
def test_a_model_figure_that_is_not_in_the_data_is_sent_back_then_dropped(app):
    bad = json.loads(json.dumps(MAPPING))
    bad["columns"][2]["meaning"] = "قيمة المبيعات الشهرية، وقد نمت 77% خلال العام الماضي بحسب الملف."
    with app.app_context():
        with pytest.raises(ValueError):
            map_columns.task.validate(bad, {**INPUTS, "_lang": "ar", "_attempt": 0})
        out = map_columns.task.validate(json.loads(json.dumps(bad)), {**INPUTS, "_lang": "ar", "_attempt": 1})
    m = out["columns"][2]["meaning"]
    assert "77" not in m and len(m) > 40                                              # replaced by the rules' own sentence about sales


def test_a_generic_summary_is_replaced_by_one_that_names_the_columns(app):
    data = json.loads(json.dumps(MAPPING))
    data["table_summary"] = "جدول مبيعات شهري يحتوي على أبعاد الفروع ومقاييس المبيعات والإيرادات والتكاليف."
    with app.app_context():
        out = map_columns.task.validate(data, {**INPUTS, "_lang": "ar"})
    s = out["table_summary"]
    assert "Agence" in s or "Mois" in s or "Chiffre" in s
    assert "يحتوي على أبعاد" not in s


def test_every_column_gets_a_meaning_even_without_a_model(app):
    with app.app_context():
        out = map_columns.task.fallback(INPUTS, "ar")
    for c in out["columns"]:
        assert len(c["meaning"]) > 30 and c["meaning"].strip() != c["label"]
    sales = next(c for c in out["columns"] if c["index"] == 2)["meaning"]
    assert "مبيعات" in sales or "إيراد" in sales or "حصّلته" in sales


def test_rules_know_what_a_delivery_rate_is(app):
    assert map_columns.concept_of("On-time delivery %") == "delivery"
    assert map_columns.concept_of("Net sales") == "sales"
    assert map_columns.concept_of("Coût") == "cost"
    assert map_columns.concept_of("الإيرادات") == "revenue"


def test_the_table_summary_is_one_paragraph_and_no_indicators_are_returned(app):
    data = json.loads(json.dumps(MAPPING))
    data["table_summary"] = "سجلّ شهري لأداء الوكالات.\nيمثل كل صف وكالة في شهر واحد، ويقيس المبلغ المحصَّل وما يتصل به لقراءة نمو النشاط ومقارنة الوكالات بعضها ببعض."
    data["derived"] = [{"name": "متوسط سلة العميل", "how": "المبيعات ÷ عدد العملاء", "uses": [9]}]
    with app.app_context():
        out = map_columns.task.validate(data, {**INPUTS, "_lang": "ar"})
    assert "\n" not in out["table_summary"] and out["table_summary"].startswith("سجلّ شهري")
    assert "derived" not in out


def test_a_highlight_that_only_restates_the_period_is_dropped(app):
    data = json.loads(json.dumps(MAPPING))
    data["highlights"] = ["تغطي السجلات فترة ممتدة من 2025-01-01 إلى 2025-12-01 عبر 3 فروع رئيسية.", "العمود «مب» لا يوضح اسمه ما يقيس؛ تأكد من معناه قبل اعتماده."]
    with app.app_context():
        out = map_columns.task.validate(data, {**INPUTS, "_lang": "ar"})
    assert out["highlights"] == ["العمود «مب» لا يوضح اسمه ما يقيس؛ تأكد من معناه قبل اعتماده."]


def test_a_summary_with_translated_names_is_kept_but_the_stock_sentence_is_not(app):
    data = json.loads(json.dumps(MAPPING))
    data["table_summary"] = "سجلّ شهري لأداء الوكالات: يمثل كل صف وكالة في شهر واحد، ويقيس المبلغ المحصَّل وما يتصل به لقراءة نمو النشاط ومقارنة الوكالات بعضها ببعض."
    with app.app_context():
        kept = map_columns.task.validate(json.loads(json.dumps(data)), {**INPUTS, "_lang": "ar"})["table_summary"]
        data["table_summary"] = "جدول مبيعات شهري يحتوي على أبعاد الفروع ومقاييس المبيعات والإيرادات والتكاليف وغيرها من القيم المسجلة في الملف."
        dropped = map_columns.task.validate(data, {**INPUTS, "_lang": "ar"})["table_summary"]
    assert kept.startswith("سجلّ شهري") and "يحتوي على أبعاد" not in dropped
