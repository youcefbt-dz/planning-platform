"""The path of one key result: what happened (actual), what it takes to arrive (required line) and where it is likely to end (projected range).
Pure geometry, no Flask: the template only draws what is returned here."""
from __future__ import annotations

from datetime import date

W, H, PX, PY = 640, 230, 46, 22


def build(actual: list[tuple[date, float]], *, start_date: date | None, start_value: float, target: float, end_date: date | None, today: date,
          proj: dict | None = None, unit: str = "") -> dict | None:
    pts = sorted(actual)
    if not end_date or (not pts and not start_date):
        return None
    d0 = min([x for x in (start_date, pts[0][0] if pts else None) if x] )
    d1 = max(end_date, today, pts[-1][0] if pts else end_date)
    span = max(1, (d1 - d0).days)
    vals = [v for _, v in pts] + [start_value, target] + ([proj["low"], proj["mid"], proj["high"]] if proj else [])
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = lo - pad, hi + pad
    X = lambda d: round(PX + (d - d0).days / span * (W - 2 * PX), 1)
    Y = lambda v: round(H - PY - (v - lo) / (hi - lo) * (H - 2 * PY), 1)
    out = {"w": W, "h": H, "unit": unit}
    out["actual"] = " ".join(f"{X(d)},{Y(v)}" for d, v in pts)
    out["required"] = [X(max(d0, start_date or d0)), Y(start_value), X(end_date), Y(target)]
    out["today_x"] = X(min(max(today, d0), d1))
    out["target_y"], out["end_x"] = Y(target), X(end_date)
    if pts:
        out["last"] = [X(pts[-1][0]), Y(pts[-1][1])]
    if proj and pts:
        lx, ly = out["last"]
        ex = X(end_date)
        out["proj"] = {"from": [lx, ly], "mid": [ex, Y(proj["mid"])], "band": f"{lx},{ly} {ex},{Y(proj['high'])} {ex},{Y(proj['low'])}"}
    out["ticks"] = [{"y": Y(v), "v": v} for v in (lo + pad, (lo + hi) / 2, hi - pad)]
    out["d0"], out["d1"] = d0, end_date
    return out
