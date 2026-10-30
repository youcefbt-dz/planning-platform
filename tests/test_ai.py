"""The AI layer: rules that always work, validation that never trusts a model, providers against fake servers, privacy gate."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.ai.base import ProviderError, extract_json
from app.ai.hub import Hub
from app.ai.tasks import explain_reality, map_columns
from app.extensions import db

PROFILE = [
    {"index": 0, "rows": 24, "nulls": 0, "distinct": 24, "type": "date", "examples": ["2025-01-01"], "percent_sign": False},
    {"index": 1, "rows": 24, "nulls": 0, "distinct": 3, "type": "text", "examples": ["Alger", "Oran"], "percent_sign": False},
    {"index": 2, "rows": 24, "nulls": 0, "distinct": 24, "type": "number", "examples": ["120"], "min": 1, "max": 9, "percent_sign": False},
    {"index": 3, "rows": 24, "nulls": 0, "distinct": 24, "type": "number", "examples": ["155"], "min": 1, "max": 9, "percent_sign": False},
]
INPUTS = {"sheet": "S", "layout": "long", "headers": ["Mois", "Agence", "Chiffre d'affaires", "مب"], "profile": PROFILE, "row_count": 24,
          "rows": [["2025-01-01", "Alger", "120", "155"]] * 3}


def test_extract_json_is_tolerant():
    assert extract_json('```json\n{"a": 1,}\n```') == {"a": 1}
    assert extract_json('Sure! {"a": {"b": 2}} hope that helps') == {"a": {"b": 2}}
    with pytest.raises(ProviderError):
        extract_json("no json here")


def test_rules_read_headers_in_three_languages_and_ask_about_the_cryptic_one(app):
    with app.app_context():
        out = map_columns.task.fallback(INPUTS, "ar")
    roles = {c["index"]: c["role"] for c in out["columns"]}
    assert roles[0] == "date" and roles[1] == "dimension" and roles[2] == "measure"
    asked = [q["column"] for q in out["questions"]]
    assert 3 in asked and 2 not in asked                          # "مب" is cryptic -> a question; "Chiffre d'affaires" is clear


def test_a_model_claim_the_data_contradicts_is_rejected(app):
    bad = {"columns": [{"index": 0, "role": "measure", "confidence": 0.99}, {"index": 1, "role": "date", "confidence": 0.99},
                       {"index": 2, "role": "dimension", "confidence": 0.95}, {"index": 3, "role": "measure", "confidence": 0.95}]}
    with app.app_context():
        out = map_columns.task.validate(bad, {**INPUTS, "_lang": "ar"})
    roles = {c["index"]: c for c in out["columns"]}
    assert roles[0]["role"] != "measure"                          # the data parses as dates, not as numbers
    assert roles[1]["role"] != "date"                             # text that is not a date
    assert roles[2]["confidence"] < 0.6 and any(q["column"] == 2 for q in out["questions"])   # numeric "category" -> ask


def test_explanation_may_only_use_numbers_it_was_given():
    facts = [27.3, 31, 3.7, 22]
    assert explain_reality.check_numbers("The target asks for 3.7 points; 22 periods were compared.", facts)
    assert not explain_reality.check_numbers("You will gain 45% more.", facts)


def test_invented_number_makes_the_task_reject_the_model(app):
    inputs = {"goal": "g", "series": "s", "unit": "", "verdict": {"level": "realistic"}, "facts": [10.0]}
    with app.app_context(), pytest.raises(ValueError):
        explain_reality.task.validate({"summary": "Growth of 77% is easy.", "reasons": [], "suggestion": "", "questions": []}, inputs)


# -- providers against fake servers -----------------------------------------------------------------------------------
class Fake(BaseHTTPRequestHandler):
    seen = []
    mode = "ok"
    reject_json_mode = False

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        Fake.seen.append({"path": self.path, "body": body, "headers": {k.lower(): v for k, v in self.headers.items()}})
        if Fake.reject_json_mode and "response_format" in body:
            self.send_response(400); self.end_headers(); self.wfile.write(b"response_format not supported"); return
        if Fake.mode == "fail":
            self.send_response(500); self.end_headers(); self.wfile.write(b"boom"); return
        answer = {"table_summary": "ok", "columns": [{"index": 0, "role": "date", "confidence": 0.9}, {"index": 2, "role": "measure", "confidence": 0.9}]}
        if self.path.endswith("/v1/messages"):
            out = {"model": body["model"], "content": [{"type": "tool_use", "name": "respond", "input": answer}]}
        else:
            out = {"model": body["model"], "choices": [{"message": {"content": "```json\n" + json.dumps(answer) + "\n```"}}]}
        data = json.dumps(out).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(data)


@pytest.fixture()
def fake():
    Fake.seen, Fake.mode = [], "ok"
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def hub_with(app, chain, fake_url, monkeypatch):
    h = Hub()
    h.cfg["chain"] = chain
    h.cfg["providers"]["anthropic"]["base_url"] = fake_url
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("AI_LOCAL_BASE_URL", fake_url)
    monkeypatch.setenv("AI_LOCAL_MODEL", "qwen-test")
    return h


def test_local_model_needs_no_consent_and_is_not_logged_as_external(app, fake, monkeypatch):
    h = hub_with(app, ["openai_compat", "offline"], fake, monkeypatch)
    with app.app_context():
        r = h.run("map_columns", INPUTS, lang="ar", consent=False)
    assert r.provider == "openai_compat" and r.external is False and r.model == "qwen-test"
    assert Fake.seen[0]["path"].endswith("/chat/completions") and "JSON schema" in Fake.seen[0]["body"]["messages"][0]["content"]


def test_cloud_model_is_skipped_without_consent_and_used_with_it(app, fake, monkeypatch):
    h = hub_with(app, ["anthropic", "offline"], fake, monkeypatch)
    with app.app_context():
        r = h.run("map_columns", INPUTS, lang="ar", consent=False)
        assert r.provider == "offline" and r.fell_back and "consent" in " ".join(r.errors) and not Fake.seen
        r = h.run("map_columns", INPUTS, lang="ar", consent=True)
    assert r.provider == "anthropic" and r.external is True
    assert Fake.seen[0]["headers"]["x-api-key"] == "sk-test" and Fake.seen[0]["body"]["tool_choice"]["name"] == "respond"


def test_demo_workspaces_never_spend_the_owners_api_budget(app, fake, monkeypatch):
    h = hub_with(app, ["anthropic", "offline"], fake, monkeypatch)
    with app.app_context():
        r = h.run("map_columns", INPUTS, lang="ar", consent=True, read_only=True)
    assert r.provider == "offline" and not Fake.seen


def test_failing_provider_falls_back_to_the_next_one(app, fake, monkeypatch):
    h = hub_with(app, ["openai_compat", "anthropic", "offline"], fake, monkeypatch)
    Fake.mode = "fail"
    with app.app_context():
        r = h.run("map_columns", INPUTS, lang="ar", consent=True)
    assert r.provider == "offline" and r.fell_back and len(r.errors) == 2


def test_cloud_calls_are_audited_with_exactly_what_was_sent(app, fake, monkeypatch):
    from app.ai.models import AICall
    from app.core.models import Organization
    h = hub_with(app, ["anthropic", "offline"], fake, monkeypatch)
    with app.app_context():
        org = Organization(name="X", slug="x")
        db.session.add(org); db.session.commit()
        h.run("map_columns", INPUTS, lang="ar", org=org, consent=True)
        call = AICall.query.filter_by(org_id=org.id).one()
        assert call.external and call.ok and "Chiffre d'affaires" in call.sent_preview


def test_daily_quota_stops_cloud_calls(app, fake, monkeypatch):
    from app.core.models import Organization
    from app.ai.models import AICall
    h = hub_with(app, ["anthropic", "offline"], fake, monkeypatch)
    h.cfg.setdefault("privacy", {})["external_calls_per_org_per_day"] = 1
    with app.app_context():
        org = Organization(name="X", slug="x")
        db.session.add(org); db.session.commit()
        assert h.run("map_columns", INPUTS, lang="ar", org=org, consent=True).provider == "anthropic"
        r = h.run("map_columns", INPUTS, lang="ar", org=org, consent=True)
        assert r.provider == "offline" and "quota" in " ".join(r.errors)


def test_only_a_sample_of_rows_is_ever_sent(app, fake, monkeypatch):
    h = hub_with(app, ["anthropic", "offline"], fake, monkeypatch)
    big = {**INPUTS, "rows": [[f"2025-01-{i % 28 + 1:02d}", "Alger", str(i), "1"] for i in range(500)]}
    with app.app_context():
        h.run("map_columns", big, lang="ar", consent=True)
    sent = json.loads(Fake.seen[0]["body"]["messages"][0]["content"])
    assert len(sent["sample_rows"]) <= 8


def test_a_new_provider_or_task_is_just_a_file(app):
    h = Hub()
    assert {"anthropic", "openai_compat", "offline"} <= set(h.providers) and {"map_columns", "explain_reality"} <= set(h.tasks)


def test_grok_is_a_cloud_provider_with_its_own_key_and_needs_consent(app, fake, monkeypatch):
    h = Hub()
    h.cfg["chain"] = ["xai", "offline"]
    h.cfg["providers"]["xai"]["base_url"] = fake
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    with app.app_context():
        assert h.run("map_columns", INPUTS, lang="ar", consent=True).provider == "offline"   # no key → not available
        monkeypatch.setenv("XAI_API_KEY", "xai-test")
        assert h.run("map_columns", INPUTS, lang="ar", consent=False).provider == "offline"  # no consent → skipped
        assert not Fake.seen
        r = h.run("map_columns", INPUTS, lang="ar", consent=True)
    assert r.provider == "xai" and r.external is True and r.model == "grok-test"
    assert Fake.seen[0]["headers"]["authorization"] == "Bearer xai-test" and Fake.seen[0]["path"].endswith("/chat/completions")


def test_groq_is_a_cloud_provider_and_retries_without_json_mode_when_rejected(app, fake, monkeypatch):
    h = Hub()
    h.cfg["chain"] = ["groq", "offline"]
    h.cfg["providers"]["groq"]["base_url"] = fake
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("GROQ_MODEL", "some-model")
    Fake.reject_json_mode = True
    try:
        with app.app_context():
            assert h.run("map_columns", INPUTS, lang="ar", consent=False).provider == "offline"
            r = h.run("map_columns", INPUTS, lang="ar", consent=True)
    finally:
        Fake.reject_json_mode = False
    assert r.provider == "groq" and r.external is True and r.model == "some-model"
    assert "response_format" in Fake.seen[0]["body"] and "response_format" not in Fake.seen[1]["body"]
    assert Fake.seen[1]["headers"]["authorization"] == "Bearer gsk-test"
