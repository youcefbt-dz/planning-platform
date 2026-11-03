from __future__ import annotations

import io
import json
import os
import re
import time
import urllib.error
import urllib.request

from flask import Response, abort, current_app, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import ai
from app.core.i18n import t
from app.core.permissions import require
from app.extensions import db
from app.modules.orgmap import bp
from app.modules.orgmap.build import BAD, build as build_map
from app.modules.orgmap.svg import render as render_svg


def reading(m: dict) -> str:
    """Two or three sentences about where the organization stands, composed by code from the map's own numbers (no model involved)."""
    c, total = m["counts"], m["total"]
    if not m["goals"]:
        return t("orgmap.read.empty")
    parts = [t("orgmap.read.counts", total=total, ok=c.get("on_track", 0) + c.get("completed", 0), risk=c.get("at_risk", 0), off=c.get("off_track", 0))]
    worst = None
    for gl in m["goals"]:
        for k in gl["krs"]:
            if k["status"] in BAD and k["gap"] is not None and k["gap"] > 0:
                if worst is None or k["gap"] > worst[1]["gap"]:
                    worst = (gl, k)
    if worst:
        gl, k = worst
        from app.core.formatting import fmt_value

        parts.append(t("orgmap.read.worst", goal=gl["obj"].title, kr=k["kr"].title, gap=fmt_value(round(k["gap"]), k["kr"].unit_label)))
        if k["branches"]:
            low = [b for b in k["branches"] if b["tone"] == "bad"]
            if low:
                parts.append(t("orgmap.read.branch", name=low[0]["name"]))
    elif total and not c.get("at_risk") and not c.get("off_track"):
        parts.append(t("orgmap.read.fine"))
    return " ".join(parts)


# -- the journey -------------------------------------------------------------------------------------------------------------------
def _need_goals():
    if not current_app.extensions["modules"].is_enabled("goals"):
        abort(404)


def _stored():
    return (g.org.settings or {}).get("journey") or {}


def _current(facts):
    """The spec to draw: the saved one when it is still true to the facts, else the rule-based story. Returns (spec, who)."""
    from app.modules.orgmap import spec as SP

    st = _stored()
    if st.get("spec"):
        try:
            return SP.validate(st["spec"], facts), st.get("by", "rules")
        except ValueError:
            pass                                    # the organization changed (a goal was deleted…): tell the story again from the facts
    return SP.default(facts, "route" if len(facts["goals"]) >= 2 else "tree"), "rules"


def _save(spec, by, request_text=""):
    settings = dict(g.org.settings or {})
    settings["journey"] = {"spec": spec, "by": by, "request": request_text}
    g.org.settings = settings
    db.session.commit()


def numbers(f: dict) -> list[dict]:
    """The figures that tell where the organization stands, each one computed from the facts (nothing a model wrote)."""
    s, n = f["stats"], f["nodes"]
    out = []
    if s["time"] is not None:
        gap = s["journey"] - s["time"]
        out.append({"key": "pace", "icon": "progress", "value": ("+" if gap > 0 else "−" if gap < 0 else "") + str(abs(gap)), "unit": t("orgmap.n.points"), "tone": "good" if gap >= 0 else "bad",
                    "label": t("orgmap.n.pace"), "note": t("orgmap.n.pace_note", journey=s["journey"], time=s["time"])})
    out.append({"key": "journey", "icon": "target-arrow", "value": str(s["journey"]), "unit": "%", "tone": "flat", "label": t("orgmap.n.journey"), "ring": s["journey"],
                "note": t("orgmap.n.journey_note", n=len(f["goals"]))})
    if s["days_left"] is not None:
        out.append({"key": "days", "icon": "calendar", "value": str(s["days_left"]), "unit": t("orgmap.n.days"), "tone": "flat", "label": t("orgmap.n.left"), "note": s["cycle"]})
    out.append({"key": "stations", "icon": "flag", "value": str(s["stations"]), "unit": "", "tone": "flat", "label": t("orgmap.n.stations"),
                "bar": [("completed", s["reached"]), ("on_track", s["on_track"]), ("at_risk", s["at_risk"]), ("off_track", s["off_track"])], "note": t("orgmap.n.stations_note", ok=s["reached"] + s["on_track"], risk=s["at_risk"], off=s["off_track"])})
    if s["biggest"]:
        k = n[s["biggest"]]
        out.append({"key": "gap", "icon": "alert-triangle", "value": k["gap"], "unit": "", "tone": "bad", "label": t("orgmap.n.gap"), "note": k["label"], "small": True})
    if s["krs"]:
        out.append({"key": "fed", "icon": "table", "value": f"{s['fed']}/{s['krs']}", "unit": "", "tone": "flat", "label": t("orgmap.n.fed"),
                    "note": t("orgmap.n.fed_note", shared=len(s["shared"]))})
    return out


@bp.get("/")
def index():
    """The journey page: the facts as one JSON document; js/journey.js draws it (and keeps it alive)."""
    _need_goals()
    from app.modules.orgmap import facts as FA
    from app.modules.orgmap import payload as PL

    facts = FA.collect(g.org)
    m = build_map(g.org)
    prof = m["profile"]
    payload = PL.build(g.org, facts, prof.get("vision") or "", prof.get("mission") or "")
    return render_template("orgmap/index.html", facts=facts, payload=payload, nums=numbers(facts), reading=reading(m), can_edit=_can_edit())


def _can_edit() -> bool:
    from app.core.permissions import can

    return bool(can("goals.edit"))


@bp.post("/compose")
@require("goals.edit")
def compose():
    """Ask the model to (re)compose the journey, optionally with an instruction; or just switch the drawing style."""
    _need_goals()
    from app.modules.orgmap import facts as FA
    from app.modules.orgmap import spec as SP

    facts = FA.collect(g.org)
    cur, _ = _current(facts)
    req = (request.form.get("request") or "").strip()[:200]
    fam = request.form.get("family")
    if fam in SP.families() and not req and not request.form.get("redraw"):
        _save({**cur, "family": fam}, _stored().get("by", "rules"), _stored().get("request", ""))
        return redirect(url_for("orgmap.index"))
    res = ai.run("draw_map", {"digest": FA.digest(facts), "facts": facts, "request": req, "families": list(SP.families()), "current": cur})
    spec = res.data
    if fam in SP.families() and not req:
        spec = {**spec, "family": fam}
    _save(spec, "model" if res.is_model and not res.fell_back else "rules", req)
    if not res.is_model:
        flash(t("orgmap.j.by_rules"), "info")
    return redirect(url_for("orgmap.index"))


@bp.get("/export.svg")
def export_svg():
    _need_goals()
    from app.modules.orgmap import facts as FA
    from app.modules.orgmap import render as R

    facts = FA.collect(g.org)
    spec, _ = _current(facts)
    return Response(R.svg(R.compose(facts, spec), standalone=True), mimetype="image/svg+xml", headers={"Content-Disposition": f'attachment; filename="{g.org.slug}-journey.svg"'})


# -- spoken explanation of the map -----------------------------------------------------------------------------------------------
def _speech_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="planwise-orgmap-speech-v1")


def _speech_chunks(text: str, limit: int = 175) -> list[str]:
    """Split Arabic narration into TTS-sized chunks without cutting words or sentence flow."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!؟])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > limit:
            words = sentence.split()
            sentence_parts, part = [], ""
            for word in words:
                candidate = (part + " " + word).strip()
                if len(candidate) > limit and part:
                    sentence_parts.append(part)
                    part = word
                else:
                    part = candidate
            if part:
                sentence_parts.append(part)
        else:
            sentence_parts = [sentence]
        for part in sentence_parts:
            candidate = (current + " " + part).strip()
            if len(candidate) > limit and current:
                chunks.append(current)
                current = part
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


def _map_explanation_inputs(facts: dict, payload: dict, focus: dict | None = None) -> tuple[dict, dict]:
    """Pass only concise, relevant facts to the narrator; never send names of staff or raw spreadsheet rows."""
    units_by_id = {str(u["id"]): u for u in payload.get("units", [])}
    goals_by_id = {str(gl["id"]): gl for gl in payload.get("goals", [])}
    goals_per_unit: dict[str, list[dict]] = {key: [] for key in units_by_id}
    for gl in payload.get("goals", []):
        if gl.get("unit") is not None and str(gl["unit"]) in goals_per_unit:
            goals_per_unit[str(gl["unit"])].append(gl)

    units = []
    for uid, unit in units_by_id.items():
        group = goals_per_unit.get(uid, [])
        units.append({
            "id": uid,
            "name": unit.get("name", "")[:90],
            "parent_name": units_by_id.get(str(unit.get("parent")), {}).get("name", ""),
            "goals_count": len(group),
            "average_progress": round(sum(int(x.get("progress") or 0) for x in group) / len(group)) if group else 0,
            "at_risk": sum(x.get("status") == "at_risk" for x in group),
            "off_track": sum(x.get("status") == "off_track" for x in group),
            "need_attention": sum(x.get("status") in ("at_risk", "off_track") for x in group),
        })

    # Prioritize goals requiring attention while retaining a broad view for the model.
    all_goals = list(payload.get("goals", []))
    if focus and focus.get("kind") == "goal":
        all_goals.sort(key=lambda x: 0 if str(x.get("id")) == str(focus.get("id")) else 1)
    priority_goals = sorted(
        all_goals,
        key=lambda x: (
            0 if x.get("status") == "off_track" else 1 if x.get("status") == "at_risk" else 2,
            int(x.get("progress") or 0) - int(x.get("expected") or 0),
        ),
    )
    if focus and focus.get("kind") == "goal":
        focus_goal = next((x for x in all_goals if str(x.get("id")) == str(focus.get("id"))), None)
        if focus_goal:
            ordered_goals = [focus_goal] + [x for x in priority_goals if x is not focus_goal][:17]
        else:
            ordered_goals = priority_goals[:18]
    elif focus and focus.get("kind") == "unit":
        focus_goals = [x for x in priority_goals if str(x.get("unit")) == str(focus.get("id"))]
        other_goals = [x for x in priority_goals if str(x.get("unit")) != str(focus.get("id"))]
        ordered_goals = (focus_goals + other_goals)[:18]
    else:
        ordered_goals = priority_goals[:18]
    goals = []
    for gl in ordered_goals:
        unit = units_by_id.get(str(gl.get("unit"))) or {}
        key_results = []
        for kr in (gl.get("krs") or [])[:5]:
            key_results.append({
                "title": str(kr.get("title") or "")[:100],
                "status": kr.get("status"),
                "status_label": payload.get("i18n", {}).get("status", {}).get(kr.get("status"), kr.get("status")),
                "progress": kr.get("progress"),
                "gap_exists": bool(kr.get("gap")),
            })
        goals.append({
            "id": str(gl["id"]),
            "title": str(gl.get("title") or "")[:110],
            "status": gl.get("status"),
            "status_label": payload.get("i18n", {}).get("status", {}).get(gl.get("status"), gl.get("status")),
            "progress": gl.get("progress"),
            "expected": gl.get("expected"),
            "unit_id": str(gl.get("unit")) if gl.get("unit") is not None else "",
            "unit_name": str(unit.get("name") or "")[:90],
            "key_results": key_results,
        })

    stats = facts["stats"]
    goal_rows = payload.get("goals", [])
    counts = {
        "journey": stats.get("journey", 0),
        "time": stats.get("time"),
        "pace_gap": (stats.get("journey", 0) - stats.get("time")) if stats.get("time") is not None else None,
        "days_left": stats.get("days_left"),
        "goals_count": len(goal_rows),
        "goals_completed": sum(x.get("status") == "completed" for x in goal_rows),
        "goals_on_track": sum(x.get("status") == "on_track" for x in goal_rows),
        "goals_at_risk": sum(x.get("status") == "at_risk" for x in goal_rows),
        "goals_off_track": sum(x.get("status") == "off_track" for x in goal_rows),
        "goals_need_attention": sum(x.get("status") in ("at_risk", "off_track") for x in goal_rows),
        "key_results_count": stats.get("stations", 0),
        "key_results_fed": stats.get("fed", 0),
        "total_results": stats.get("krs", 0),
    }
    dependencies = []
    for dep in payload.get("deps", [])[:24]:
        source, target = goals_by_id.get(str(dep.get("from"))), goals_by_id.get(str(dep.get("to")))
        if source and target:
            dependencies.append({"goal": source.get("title", ""), "depends_on": target.get("title", "")})

    focus_target = None
    if focus:
        kind, entity_id = focus.get("kind"), str(focus.get("id", ""))
        if kind == "goal" and entity_id in goals_by_id:
            focus_target = {"kind": "goal", "id": entity_id, "title": goals_by_id[entity_id].get("title", "")}
        elif kind == "unit" and entity_id in units_by_id:
            focus_target = {"kind": "unit", "id": entity_id, "title": units_by_id[entity_id].get("name", "")}
        elif kind == "org" and entity_id == "org":
            focus_target = {"kind": "org", "id": "org", "title": payload.get("org", {}).get("name", "")}

    inputs = {
        "org": {"name": str(payload.get("org", {}).get("name") or "المؤسسة")[:100]},
        "stats": counts,
        "units": units,
        "goals": goals,
        "dependencies": dependencies,
        "focus_target": focus_target,
    }
    title_map = {("org", "org"): inputs["org"]["name"]}
    title_map.update({("unit", x["id"]): x["name"] for x in units})
    title_map.update({("goal", x["id"]): x["title"] for x in goals})
    # A focus goal can be outside the top 18: add its identity so validation can still name it.
    for gl in payload.get("goals", []):
        title_map.setdefault(("goal", str(gl["id"])), str(gl.get("title") or "الهدف")[:110])
    for unit in payload.get("units", []):
        title_map.setdefault(("unit", str(unit["id"])), str(unit.get("name") or "القسم")[:90])
    return inputs, title_map


@bp.post("/explain")
def explain():
    """Generate an evidence-grounded spoken story for the current map."""
    _need_goals()
    from app.modules.orgmap import facts as FA
    from app.modules.orgmap import payload as PL

    raw = request.get_json(silent=True) or {}
    focus = raw.get("focus") if isinstance(raw.get("focus"), dict) else None
    facts = FA.collect(g.org)
    payload = PL.build(g.org, facts, "", "")
    inputs, titles = _map_explanation_inputs(facts, payload, focus)
    result = ai.run("explain_journey", inputs)

    segments, parts = [], []
    serializer = _speech_serializer()
    for index, item in enumerate(result.data.get("segments", [])):
        kind, entity_id = item["kind"], str(item["id"])
        segment = {"index": index, "kind": kind, "id": entity_id, "title": titles.get((kind, entity_id), "المؤسسة"), "text": item["text"]}
        segments.append(segment)
        for chunk in _speech_chunks(item["text"]):
            token = serializer.dumps({"org_id": g.org.id, "text": chunk})
            parts.append({"segment": index, "token": token})

    tts_available = bool(os.environ.get("GROQ_API_KEY", "").strip()) and ai.org_consent(g.org) and not bool(g.get("read_only"))
    return jsonify({
        "segments": segments,
        "parts": parts,
        "tts_available": tts_available,
        "provider": "model" if result.is_model else "rules",
        "message": "تم إعداد قراءة المخطط." if segments else "لا توجد بيانات كافية لشرح المخطط.",
    })


@bp.post("/ask")
def ask():
    """Answer a focused question about the map and prepare the answer for speech."""
    _need_goals()
    from app.modules.orgmap import facts as FA
    from app.modules.orgmap import payload as PL

    body = request.get_json(silent=True) or {}
    question = str(body.get("question") or "").strip()
    if not question or len(question) > 220:
        return jsonify({"error": "question_required", "message": "اكتب سؤالًا قصيرًا لا يتجاوز 220 حرفًا."}), 400

    facts = FA.collect(g.org)
    payload = PL.build(g.org, facts, "", "")
    focus = next(({"kind": "goal", "id": gl["id"]} for gl in payload.get("goals", [])
                  if gl.get("title") and gl["title"].casefold() in question.casefold()), None)
    if focus is None:
        focus = next(({"kind": "unit", "id": unit["id"]} for unit in payload.get("units", [])
                      if unit.get("name") and unit["name"].casefold() in question.casefold()), None)
    inputs, titles = _map_explanation_inputs(facts, payload, focus)
    inputs["question"] = question
    result = ai.run("ask_journey", inputs)
    item = result.data
    kind, entity_id = item["kind"], str(item["id"])
    segment = {"index": 0, "kind": kind, "id": entity_id, "title": titles.get((kind, entity_id), "المؤسسة"), "text": item["text"]}
    parts = [{"segment": 0, "token": _speech_serializer().dumps({"org_id": g.org.id, "text": chunk})}
             for chunk in _speech_chunks(item["text"])]
    tts_available = bool(os.environ.get("GROQ_API_KEY", "").strip()) and ai.org_consent(g.org) and not bool(g.get("read_only"))
    return jsonify({"segment": segment, "parts": parts, "tts_available": tts_available, "provider": "model" if result.is_model else "rules"})


def _audit_speech(text: str, model: str, elapsed_ms: int, *, ok: bool, error: str = "") -> None:
    """Count speech synthesis against the same per-organization external AI budget."""
    try:
        from app.ai.models import AICall

        user_id = current_user.id if current_user.is_authenticated else None
        db.session.add(AICall(
            org_id=g.org.id if g.org else None, user_id=user_id, task="explain_voice", provider="groq", model=model,
            external=True, ok=ok, error=(error or "")[:300], ms=max(0, int(elapsed_ms)),
            sent_chars=len(text), sent_preview=text[:8000],
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("could not record spoken map briefing call")


@bp.post("/speech")
def speech():
    """Turn one signed narration chunk into audio; the API key never reaches the browser."""
    _need_goals()
    consent = ai.org_consent(g.org)
    if g.get("read_only") or not consent:
        return jsonify({"error": "consent_required"}), 403
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return jsonify({"error": "speech_unavailable"}), 503

    body = request.get_json(silent=True) or {}
    token = str(body.get("token") or "")
    if len(token) > 4096:
        return jsonify({"error": "invalid_audio_request"}), 400
    try:
        signed = _speech_serializer().loads(token, max_age=900)
    except (BadSignature, SignatureExpired):
        return jsonify({"error": "expired_audio_request"}), 400
    if signed.get("org_id") != g.org.id:
        abort(403)
    spoken = str(signed.get("text") or "").strip()
    if not spoken or len(spoken) > 180:
        return jsonify({"error": "invalid_text"}), 400

    allowed, reason = current_app.extensions["ai"].external_allowed(g.org, consent=consent, read_only=bool(g.get("read_only")))
    if not allowed:
        status = 429 if reason == "quota" else 403
        return jsonify({"error": "external_ai_limit" if reason == "quota" else "consent_required"}), status

    voice_id = str(body.get("voice") or "fahad")
    if voice_id not in {"fahad", "sultan", "abdullah", "noura", "lulwa", "aisha"}:
        voice_id = "fahad"
    model = "canopylabs/orpheus-arabic-saudi"

    request_body = json.dumps({"model": model, "input": spoken, "voice": voice_id, "response_format": "wav"}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/audio/speech",
        data=request_body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "audio/wav"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=50) as response:
            audio_bytes = response.read(12 * 1024 * 1024 + 1)
        elapsed = int((time.monotonic() - started) * 1000)
        if len(audio_bytes) > 12 * 1024 * 1024:
            _audit_speech(spoken, model, elapsed, ok=False, error="audio_too_large")
            return jsonify({"error": "audio_too_large"}), 502
    except urllib.error.HTTPError as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        _audit_speech(spoken, model, elapsed, ok=False, error=f"HTTP {exc.code}")
        current_app.logger.warning("Groq speech request failed: HTTP %s", exc.code)
        return jsonify({"error": "speech_generation_failed"}), 502
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        _audit_speech(spoken, model, elapsed, ok=False, error=type(exc).__name__)
        current_app.logger.warning("Groq speech request failed: %s", type(exc).__name__)
        return jsonify({"error": "speech_service_unavailable"}), 502

    _audit_speech(spoken, model, elapsed, ok=True)
    return send_file(io.BytesIO(audio_bytes), mimetype="audio/wav", as_attachment=False, download_name="planwise-narration.wav", max_age=0)
