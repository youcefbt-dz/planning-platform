"""Task: compose the organization's journey map. The model chooses a drawing style, the order of the story, which goals get which line colour and what to ring.
It never draws, never positions, never writes a number: the code lays everything out and every figure comes from the facts.

Inputs : {"digest": facts digest (ids, types, labels, statuses, whole-number progress), "request": str|None, "families": [name], "current": spec|None}
Output : a spec (see app/modules/orgmap/spec.py)
"""
from __future__ import annotations

import json

from app.ai import privacy
from app.ai.base import Task

SYSTEM = """You compose the "journey" of an organization: a map that is drawn on screen step by step, like a story the manager watches. You do not draw. You choose.
You receive `digest`: the things that exist (ids with types: org, vision, goal, kr = key result/station, branch, series, lever), their statuses and whole-number progress.
Return a spec with:
- family: one of `families`. "route" is a metro map (one coloured line per goal, a station per key result, a pin where each goal stands today): the best choice when there are
  2+ goals. "tree" is a top-down org chart: better for 1 goal or when the manager asked for a hierarchy.
- title: short Arabic heading for the whole journey (no digits).
- steps: 3 to 10 steps, in the order the story should be told. Each step: show = ids to reveal now (a goal id brings its stations, tributaries and levers with it; you may also
  name a single kr id to give one station its own step), title = a short Arabic phrase (no digits) saying why this step matters.
  Start with "org" (and "vision" if it exists). Tell the story, do not just list: for example start with the goal that is furthest along, or with the one at risk, or group two
  goals that share data. End with a step that shows ["here", "links"] (the you-are-here pins and the data shared between goals).
- lines: {goal id: colour index 0-5}. Give goals that belong together neighbouring colours; never reuse an index if there are 6 or fewer goals.
- emphasis: up to 6 ids to ring (key results with status at_risk or off_track first, unless the request says otherwise).
Rules: use only ids from `digest`. Never write numbers or percentages in titles. If `request` is present (the manager asked to change the picture, for example "focus on the
struggling goal"), obey it by reordering steps and emphasis; if `current` is present, start from it. Return JSON only."""


class DrawMap(Task):
    name = "draw_map"
    description = "Compose the journey map: style, story order, line colours, emphasis."
    schema = {"type": "object", "properties": {
        "family": {"type": "string"}, "title": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "object", "properties": {"show": {"type": "array", "items": {"type": "string"}}, "title": {"type": "string"}}, "required": ["show"]}},
        "lines": {"type": "object"}, "emphasis": {"type": "array", "items": {"type": "string"}}}, "required": ["family", "steps"]}

    def prompt(self, inputs, lang):
        body = {"digest": inputs["digest"], "families": inputs.get("families") or ["route", "tree"], "request": privacy.clip(inputs.get("request"), 200) or None, "current": inputs.get("current")}
        return SYSTEM, json.dumps(body, ensure_ascii=False)

    def validate(self, data, inputs):
        from app.modules.orgmap import spec as SP

        return SP.validate(data, inputs["facts"])

    def fallback(self, inputs, lang):
        from app.modules.orgmap import spec as SP

        facts, req = inputs["facts"], (inputs.get("request") or "")
        fam = "tree" if ("شجر" in req or "هرم" in req or "هيكل" in req) else ("route" if len(facts["goals"]) >= 2 else "tree")
        sp = SP.default(facts, fam)
        n = facts["nodes"]
        if any(w in req for w in ("تعثر", "خطر", "مشكل", "متأخر", "ركز", "ركّز")):          # "focus on what is struggling": tell the hardest goals first
            rank = {"off_track": 0, "at_risk": 1}
            gs = sorted(facts["goals"], key=lambda g: (rank.get(n[g]["status"], 2), -n[g]["progress"]))
            head = [s for s in sp["steps"] if not any(x in n and n[x]["type"] == "goal" for x in s["show"]) and "here" not in s["show"]]
            tail = [s for s in sp["steps"] if "here" in s["show"]]
            sp["steps"] = head + [{"show": [g], "title": n[g]["label"][:60]} for g in gs] + tail
        return sp


task = DrawMap()
