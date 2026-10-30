"""One caption per step of the journey, written by code from the facts (a model only chooses the titles). Every number here is computed."""
from __future__ import annotations

from app.core.i18n import t, tn
from app.modules.orgmap.scene import clip

BAD = ("at_risk", "off_track")


def _goal_line(n: dict, g: dict) -> str:
    krs = [n[k] for k in g["kr"]]
    bad = sum(1 for k in krs if k["status"] in BAD)
    base = t("orgmap.j.cap.goal", title=clip(g["label"], 60), progress=g["progress"], expected=g["expected"], status=t("status." + g["status"]))
    stations = tn("orgmap.j.cap.stations", len(krs)) if krs else t("orgmap.j.cap.no_stations")
    tail = t("orgmap.j.cap.bad", n=bad) if bad else ""
    return " ".join(x for x in (base, stations + ("،" if tail else "."), tail) if x)


def captions(facts: dict, spec: dict) -> list[dict]:
    n, s = facts["nodes"], facts["stats"]
    out = []
    for st in spec["steps"]:
        show = st["show"]
        goals = [x for x in show if x in n and n[x]["type"] == "goal"]
        krs = [x for x in show if x in n and n[x]["type"] == "kr"]
        if "org" in show:
            org = n["org"]
            text = t("orgmap.j.cap.org", name=org["label"], goals=tn("orgmap.j.cap.goals", len(facts["goals"])), cycle=s["cycle"] or t("orgmap.j.cap.no_cycle"))
            title = st["title"] or t("orgmap.j.t.org")
        elif "vision" in show:
            v = n["vision"]
            text = clip(v["vision"] or v["mission"], 170)
            title = st["title"] or t("orgmap.j.t.vision")
        elif goals:
            text = " ".join(_goal_line(n, n[g]) for g in goals[:2]) if len(goals) <= 2 else t("orgmap.j.cap.many", n=len(goals))
            title = st["title"] or (n[goals[0]]["label"] if len(goals) == 1 else t("orgmap.j.t.goals"))
        elif krs:
            k = n[krs[0]]
            text = t("orgmap.j.cap.kr", title=clip(k["label"], 60), now=k["now"], target=k["target"], status=t("status." + k["status"]))
            title = st["title"] or clip(k["label"], 60)
        else:                                                       # the "where are we now" step
            parts = [t("orgmap.j.cap.here", journey=s["journey"])]
            if s["time"] is not None:
                parts.append(t("orgmap.j.cap.time", time=s["time"]))
            if s["biggest"]:
                k = n[s["biggest"]]
                parts.append(t("orgmap.j.cap.biggest", title=clip(k["label"], 50), gap=k["gap"]))
            elif s["stations"] and not (s["at_risk"] or s["off_track"]):
                parts.append(t("orgmap.j.cap.fine"))
            if s["shared"]:
                parts.append(tn("orgmap.j.cap.shared", len(s["shared"])))
            text = " ".join(parts)
            title = st["title"] or t("orgmap.j.t.here")
        out.append({"title": title, "text": text})
    return out
