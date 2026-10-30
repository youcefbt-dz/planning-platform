"""Outside factors: does what the plan depends on cover what history cannot?  Pure numbers, no Flask, no database.

A target above what the organization's own history supports leaves a GAP. The user lists the factors the plan relies on (a price rise, a new branch,
a signed contract), each with an effect in the key result's own units and how certain it is. Coverage is reported in three honest tiers instead of one
flattering sum — and it NEVER changes the history-based verdict, so typing a number cannot turn red into green:

    covered   confirmed factors alone close the gap
    likely    confirmed + probable close it
    hoped     only with hoped-for factors
    partial   even all claimed factors fall short       none   no factor recorded       none_needed   history already supports the target
"""
from __future__ import annotations

CERTAINTIES = ("confirmed", "probable", "hoped")


def gap_to_target(target: float, supported: float | None, direction: str = "higher_better") -> float:
    """How far the target is beyond what history supports, in the key result's units (0 when it is within reach)."""
    if supported is None:
        return 0.0
    d = 1 if direction == "higher_better" else -1
    return max(0.0, d * (target - supported))


def coverage(gap: float, factors: list[dict]) -> dict:
    """factors: [{effect, certainty}] — effect is signed toward the goal (a headwind is negative)."""
    sums = {c: 0.0 for c in CERTAINTIES}
    headwind = 0.0                                       # a factor against the goal always counts, whatever its certainty: a risk is not optional
    for f in factors:
        e = float(f.get("effect") or 0)
        if e < 0:
            headwind += e
        else:
            sums[f.get("certainty") if f.get("certainty") in sums else "hoped"] += e
    confirmed, probable, hoped = sums["confirmed"], sums["probable"], sums["hoped"]
    net_confirmed, net_likely, total = confirmed + headwind, confirmed + probable + headwind, confirmed + probable + hoped + headwind
    if gap <= 0:
        status = "none_needed"
    elif not factors:
        status = "none"
    elif net_confirmed >= gap:
        status = "covered"
    elif net_likely >= gap:
        status = "likely"
    elif total >= gap:
        status = "hoped"
    else:
        status = "partial"
    share = lambda x: (max(0.0, min(1.0, x / gap)) if gap > 0 else 1.0)
    return {"gap": gap, "confirmed": net_confirmed, "probable": probable, "hoped": hoped, "headwind": headwind, "total": total, "status": status,
            "share_confirmed": share(net_confirmed), "share_likely": share(net_likely), "share_all": share(total),
            "unproven": (total - net_confirmed) / total if total > 0 else 0.0}
