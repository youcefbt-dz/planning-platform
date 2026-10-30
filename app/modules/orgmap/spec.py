"""The language the journey is written in, and the checks that keep it honest.

A SPEC is a small dict a model (or the built-in rules) writes:

    {"family": "route" | "tree" | ...,                 which drawing style (one file in families/ each)
     "title":  "رحلة المؤسسة",                          a short heading, no digits
     "steps":  [{"show": ["org"], "title": "من نحن"},   the order of the story; `show` lists ids from the facts (a goal brings its stations along),
                {"show": ["goal:3"], "title": "..."},   plus the pseudo ids "here" (the you-are-here pins) and "links" (data shared between goals)
                {"show": ["here", "links"]}],
     "lines":  {"goal:3": 2},                          colour index (0-5) of a goal's line
     "emphasis": ["kr:7"]}                             things to ring

`validate` rejects any id that is not in the facts, any title with a digit (numbers come from code, never from a model), and anything over the limits;
what is left unmentioned is appended as a last step, so the picture is always complete and always true.
"""
from __future__ import annotations

import importlib
import pkgutil
import re

from app.core.i18n import t

MAX_STEPS, MAX_SHOW, MAX_EMPH = 12, 24, 8
PSEUDO = ("here", "links")
_DIGIT = re.compile(r"[0-9٠-٩]")


def families() -> dict:
    """Every drawing style found in app/modules/orgmap/families/ (drop a file with a `family` object to add one)."""
    import app.modules.orgmap.families as pkg

    out = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("_"):
            continue
        fam = getattr(importlib.import_module(f"{pkg.__name__}.{info.name}"), "family", None)
        if fam is not None:
            out[fam.name] = fam
    return out


def _title(s, fallback: str) -> str:
    s = (s or "").strip() if isinstance(s, str) else ""
    if not s or _DIGIT.search(s):
        return fallback
    return s[:60]


def default(facts: dict, family: str = "route") -> dict:
    """The story the rules tell with no model: who we are, where we are heading, one step per goal, then where we stand now."""
    n = facts["nodes"]
    steps = [{"show": ["org"], "title": t("orgmap.j.t.org")}]
    if "vision" in n:
        steps.append({"show": ["vision"], "title": t("orgmap.j.t.vision")})
    for gid in facts["goals"]:
        steps.append({"show": [gid], "title": n[gid]["label"][:60]})
    steps.append({"show": ["here", "links"], "title": t("orgmap.j.t.here")})
    bad = [k for k, v in n.items() if v["type"] == "kr" and v["status"] in ("at_risk", "off_track")]
    return {"family": family, "title": t("orgmap.j.title"), "steps": steps, "lines": {g: i % 6 for i, g in enumerate(facts["goals"])}, "emphasis": bad[:MAX_EMPH]}


def validate(raw, facts: dict) -> dict:
    """A clean spec, or ValueError saying exactly what was wrong (the AI hub shows that to the model and asks once more)."""
    if not isinstance(raw, dict):
        raise ValueError("the spec must be an object")
    n = facts["nodes"]
    fams = families()
    family = raw.get("family") if raw.get("family") in fams else None
    if family is None:
        raise ValueError(f"family must be one of {sorted(fams)}")
    steps_in = raw.get("steps")
    if not isinstance(steps_in, list) or not steps_in or len(steps_in) > MAX_STEPS:
        raise ValueError(f"steps must be a list of 1 to {MAX_STEPS}")
    steps, seen = [], set()
    for i, st in enumerate(steps_in):
        show = st.get("show") if isinstance(st, dict) else None
        if not isinstance(show, list) or not show or len(show) > MAX_SHOW:
            raise ValueError(f"step {i}: show must list 1 to {MAX_SHOW} ids")
        for x in show:
            if x not in n and x not in PSEUDO:
                raise ValueError(f"step {i}: unknown id {x!r}; use only ids from the facts, or 'here' / 'links'")
        show = [x for x in dict.fromkeys(show)]
        seen.update(show)
        steps.append({"show": show, "title": _title(st.get("title"), "")})
    if "org" not in seen:
        steps[0]["show"].insert(0, "org")
        seen.add("org")
    tops = [x for x in (["vision"] if "vision" in n else []) + facts["goals"] if x not in seen]
    if tops:
        steps.append({"show": tops, "title": ""})
    if not any("here" in s["show"] for s in steps):
        steps.append({"show": ["here", "links"], "title": t("orgmap.j.t.here")})
    elif not any("links" in s["show"] for s in steps):
        [s for s in steps if "here" in s["show"]][0]["show"].append("links")
    lines_in = raw.get("lines") if isinstance(raw.get("lines"), dict) else {}
    lines = {g: (lines_in.get(g) if isinstance(lines_in.get(g), int) and 0 <= lines_in.get(g) <= 5 else i % 6) for i, g in enumerate(facts["goals"])}
    emph = [x for x in (raw.get("emphasis") or []) if x in n][:MAX_EMPH] if isinstance(raw.get("emphasis"), list) else []
    return {"family": family, "title": _title(raw.get("title"), t("orgmap.j.title")), "steps": steps, "lines": lines, "emphasis": emph}


def reveal(facts: dict, spec: dict) -> dict[str, int]:
    """The step at which each thing first appears. Mentioned = that step; a station, tributary or lever comes with its goal unless mentioned earlier."""
    n = facts["nodes"]
    rv: dict[str, int] = {}
    for i, st in enumerate(spec["steps"]):
        for x in st["show"]:
            rv.setdefault(x, i)
    rv.setdefault("org", 0)
    last = len(spec["steps"]) - 1
    if "vision" in n:
        rv.setdefault("vision", rv["org"])
    for gid in facts["goals"]:
        g = n[gid]
        early = min([rv[k] for k in g["kr"] if k in rv] + [rv.get(gid, last)])
        rv[gid] = early
        for kid in g["kr"]:
            rv.setdefault(kid, rv[gid])
            k = n[kid]
            for c in k["branches"] + k["levers"]:
                rv.setdefault(c, rv[kid])
    for sid, s in n.items():
        if s["type"] == "series":
            rv.setdefault(sid, min(rv.get(u, last) for u in s["users"]))
    rv.setdefault("here", last)
    rv.setdefault("links", last)
    return rv
