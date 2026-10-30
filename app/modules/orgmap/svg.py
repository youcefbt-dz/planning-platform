"""The map as one standalone SVG (organization → goals → indicators → levers). Text is escaped; status is always a word as well as a colour."""
from __future__ import annotations

from xml.sax.saxutils import escape

from app.core.formatting import fmt_value
from app.core.i18n import t

COL = {"on_track": "#1f9d5b", "completed": "#1f9d5b", "at_risk": "#d99a00", "off_track": "#d6453d", "not_started": "#8a93a8"}
NW, NH, GAP = 210, 56, 16


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _node(x, y, w, h, title, sub, status=None, bad=False):
    col = COL.get(status, "#c9cfe0")
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="#fff" stroke="{"#d6453d" if bad else "#d7dcec"}" stroke-width="{2 if bad else 1}"/>',
           f'<rect x="{x + w - 6}" y="{y + 8}" width="4" height="{h - 16}" rx="2" fill="{col}"/>',
           f'<text x="{x + w - 16}" y="{y + 22}" text-anchor="end" font-size="13" font-weight="700" fill="#1b2140">{escape(_clip(title, 30))}</text>']
    if sub:
        out.append(f'<text x="{x + w - 16}" y="{y + 42}" text-anchor="end" font-size="11" fill="#5a6280">{escape(_clip(sub, 36))}</text>')
    return "".join(out)


def render(m: dict) -> str:
    goals = m["goals"]
    ys = [20, 130, 250, 400]
    # each goal gets a column group as wide as its widest layer
    groups, x = [], 20
    for gl in goals:
        w = max(1, len(gl["krs"])) * (NW + GAP)
        groups.append((gl, x, w))
        x += w + 30
    width = max(x, 2 * NW + 60)
    body = []
    cx = width / 2
    prof = m["profile"]
    body.append(_node(cx - NW / 2, ys[0], NW, NH, m["org"].name, prof.get("vision") or ""))
    for gl, gx, gw in groups:
        mid = gx + gw / 2
        o = gl["obj"]
        body.append(f'<path d="M{cx} {ys[0] + NH} V{ys[0] + NH + 24} H{mid} V{ys[1]}" fill="none" stroke="#c9cfe0"/>')
        body.append(_node(mid - NW / 2, ys[1], NW, NH, o.title, t("status." + gl["status"]), gl["status"], gl["attention"]))
        for i, k in enumerate(gl["krs"]):
            kx = gx + i * (NW + GAP) + GAP / 2
            kc = kx + (NW) / 2
            kr = k["kr"]
            body.append(f'<path d="M{mid} {ys[1] + NH} V{ys[1] + NH + 24} H{kc} V{ys[2]}" fill="none" stroke="#c9cfe0"/>')
            sub = f'{fmt_value(kr.current_value, kr.unit_label)} / {fmt_value(kr.target_value, kr.unit_label)} · {t("status." + k["status"])}'
            body.append(_node(kx, ys[2], NW, NH + 8, kr.title, sub, k["status"], k["status"] in ("off_track", "at_risk")))
            for j, lv in enumerate(k["levers"][:3]):
                ly = ys[3] + j * (NH - 8)
                body.append(f'<path d="M{kc} {ys[2] + NH + 8} V{ly + 22}" fill="none" stroke="#e2e6f2"/>')
                body.append(_node(kx + 14, ly, NW - 14, NH - 16, lv["title"], t("goals.factors.state." + lv["status"]), None))
    height = ys[3] + 3 * (NH - 8) + 30
    return (f'<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {int(width)} {height}" width="{int(width)}" height="{height}" '
            f'direction="rtl" font-family="Noto Sans Arabic, Tahoma, sans-serif"><rect width="100%" height="100%" fill="#f6f7fc"/>{"".join(body)}</svg>')
