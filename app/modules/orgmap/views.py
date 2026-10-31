from __future__ import annotations

from flask import Response, abort, current_app, flash, g, redirect, render_template, request, url_for

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
