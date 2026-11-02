from __future__ import annotations

from datetime import date

from flask import abort, g, jsonify, redirect, render_template, request, url_for

from app.core import scope as SC
from app.core.formatting import fmt_date
from app.core.i18n import t
from app.core.permissions import require
from app.modules.agent import bp, loop
from app.modules.agent import tools as T


@bp.get("/")
def index():
    # The assistant now lives in the floating dock on every workspace page.
    # Redirect old bookmarks here rather than maintaining a second, full-page chat UI.
    return redirect(url_for("shell.overview"))


@bp.post("/chat")
def chat():
    body = request.get_json(silent=True) or {}
    history = body.get("messages") if isinstance(body.get("messages"), list) else []
    if not history or len(str(history[-1].get("content", ""))) < 2:
        return jsonify(ok=False, error=t("agent.err.empty")), 400
    res = loop.run_agent(history, lang=g.get("lang", "ar"))
    for p in res.get("proposals", []):
        p["end_label"] = fmt_date(date.fromisoformat(p["end_date"]))
    html = "".join(render_template("agent/_proposal.html", p=p, can_apply=SC.can_add_goal()) for p in res.get("proposals", []))
    return jsonify(ok=True, answer=res["answer"], steps=res["steps"], mode=res["mode"], why=res.get("why", ""), provider=res.get("provider"), model=res.get("model"),
                   unverified=res.get("unverified", []), off_text=(t("agent.off." + (res.get("why") or "none")) if res["mode"] == "rules" else ""), proposals=res.get("proposals", []), proposals_html=html)


@bp.post("/apply")
@require("agent.apply")
def apply():
    body = request.get_json(silent=True) or {}
    p = body.get("proposal")
    if not isinstance(p, dict) or not SC.can_add_goal():
        abort(403)
    try:
        gid = loop.apply_proposal(p)
    except T.ToolError as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, url=url_for("goals.detail", id=gid))
