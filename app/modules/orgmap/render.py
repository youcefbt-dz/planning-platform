"""From facts + spec to the finished picture: pick the family, lay it out, number the steps."""
from __future__ import annotations

from app.modules.orgmap import spec as SP
from app.modules.orgmap import story


def compose(facts: dict, spec: dict) -> dict:
    """{"svg": str, "steps": [{"title","text"}], "spec": spec}. The same SVG serves the page (animated by CSS/JS) and the downloadable file (all visible)."""
    fams = SP.families()
    fam = fams.get(spec["family"]) or next(iter(fams.values()))
    rv = SP.reveal(facts, spec)
    cv = fam.layout(facts, spec, rv)
    steps = story.captions(facts, spec)
    return {"cv": cv, "steps": steps, "spec": spec, "rv": rv, "family": fam.name, "title": spec["title"]}


def svg(composed: dict, *, standalone: bool = False) -> str:
    return composed["cv"].render(title=composed["title"], steps_total=len(composed["steps"]), standalone=standalone)
