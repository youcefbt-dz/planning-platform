"""The route map: a trunk from the organization, one coloured LINE per goal, a STATION per key result, a pin where the goal stands today.

Reading order is right to left. Along each line: a solid colour up to where the goal is today ("أنت هنا"), a dotted continuation to the target flag, a small
tick for where the clock says it should be. Stations carry a progress ring and the status as an icon and a word; under a station hang its data source and
the branches that move it; over it, the levers outside the data that its target depends on. A data series that feeds two goals is an interchange.
"""
from __future__ import annotations

from flask import current_app

from app.core.i18n import t
from app.modules.orgmap import scene as S
from app.modules.orgmap.scene import Canvas, clip, icon, lines_block, pill, ring, text, wrap

SP, CARD_W, TRUNK_PAD = 214, 268, 112


def _logo(cx, cy, r, org, step, cv: Canvas):
    clip_id = "logo-clip"
    src = org.get("logo")
    cv.add(step, f'<circle cx="{cx}" cy="{cy}" r="{r + 9}" fill="#fff" stroke="{S.PRIMARY}" stroke-width="5"/>'
                 f'<circle cx="{cx}" cy="{cy}" r="{r + 9}" fill="none" stroke="#fff" stroke-width="2" opacity=".0"/>', ox=cx, oy=cy)
    if src:
        cv.add(step, f'<defs><clipPath id="{clip_id}"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath></defs>'
                     f'<image href="{S.esc(src)}" x="{cx - r}" y="{cy - r}" width="{2 * r}" height="{2 * r}" preserveAspectRatio="xMidYMid slice" clip-path="url(#{clip_id})"/>', ox=cx, oy=cy)
    else:
        init = "".join(w[0] for w in (org["label"] or "؟").split()[:2])
        cv.add(step, f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{S.TINT}"/>' + text(cx, cy + 14, init, size=40, weight=800, fill=S.PRIMARY), ox=cx, oy=cy)


class Route:
    name = "route"
    label = "خريطة المترو"

    def layout(self, facts: dict, spec: dict, rv: dict) -> Canvas:
        n, st = facts["nodes"], facts["stats"]
        goals = facts["goals"]
        maxk = max([len(n[g]["kr"]) for g in goals] + [1])
        W = max(1240, TRUNK_PAD + CARD_W + 120 + (maxk - 1) * SP + 220 + 60)
        lane_h, pad = {}, {}
        for g in goals:
            br = max([len(n[k]["branches"]) for k in n[g]["kr"]] + [0])
            lv = max([len(n[k]['levers']) for k in n[g]['kr']] + [0])
            pad[g] = 26 * min(lv, 2)
            lane_h[g] = 262 + 26 * (min(br, 3) + 1) + pad[g]
        HZ = 230
        H = HZ + sum(lane_h.values()) + 110
        cv = Canvas(W, H)
        xt = W - TRUNK_PAD + 12                                  # the trunk
        cy0, r0 = 112, 56
        org = n["org"]

        # ---- origin: logo, name, a line about the cycle, and the vision --------------------------------------------------------------
        s0 = rv["org"]
        _logo(xt, cy0, r0, org, s0, cv)
        cv.add(s0, text(xt - 96, cy0 - 6, S.clip(org["label"], 34), size=30, weight=800, fill=S.INK, anchor="end")
               + text(xt - 96, cy0 + 26, t("orgmap.j.sub", goals=len(goals), stations=st["stations"], cycle=st["cycle"] or "—"), size=14, weight=500, fill=S.BODY, anchor="end"), kind="fade")
        if "vision" in n:
            sv = rv["vision"]
            v = n["vision"]
            vt = wrap(v["vision"] or v["mission"], 64, 2)
            vw = 560
            cv.add(sv, f'<rect x="{xt - 96 - vw}" y="{cy0 + 50}" width="{vw}" height="58" rx="14" fill="{S.TINT}"/>'
                       f'<rect x="{xt - 96 - 5}" y="{cy0 + 60}" width="4" height="38" rx="2" fill="{S.PRIMARY}"/>'
                       + lines_block(xt - 96 - 18, cy0 + 76, vt, size=13, weight=500, fill=S.INK, anchor="end", lh=20), kind="fade")
        last_y = HZ
        # ---- lanes ------------------------------------------------------------------------------------------------------------------------
        y = HZ + 60
        lane_y = {}
        for gi, gid in enumerate(goals):
            lane_y[gid] = y + pad[gid]
            y += lane_h[gid]
        trunk_end = lane_y[goals[-1]] if goals else cy0 + r0
        trunk_start = cy0 + r0 + 9
        cv.add(rv["org"] if not goals else min(rv[g] for g in goals),
               f'<path class="j-draw" pathLength="1" d="M{xt} {trunk_start} V{trunk_end - 26}" fill="none" stroke="{S.LINE}" stroke-width="10" stroke-linecap="round"/>', kind="draw")
        pos: dict[str, tuple[float, float]] = {}
        for gi, gid in enumerate(goals):
            g = n[gid]
            color = S.LINE_COLORS[spec["lines"].get(gid, gi) % 6]
            y = lane_y[gid]
            step = rv[gid]
            krs = g["kr"]
            x_card_l = xt - 34 - CARD_W
            x_card_r = xt - 34
            x0 = x_card_l                                         # the line starts at the card's far edge
            xs = [x0 - 112 - i * SP for i in range(len(krs))]
            x_end = (xs[-1] - 150) if xs else x0 - 260
            span = x0 - x_end
            x_here = x0 - span * g["progress"] / 100
            x_exp = x0 - span * g["expected"] / 100
            # elbow from the trunk into the card, then the line itself
            cv.add(step, f'<path class="j-draw" pathLength="1" d="M{xt} {y - 40} Q{xt} {y} {xt - 36} {y}" fill="none" stroke="{S.LINE}" stroke-width="10" stroke-linecap="round"/>', kind="draw")
            cv.add(step, f'<path class="j-draw" pathLength="1" d="M{x0} {y} H{x_here:g}" fill="none" stroke="{color}" stroke-width="11" stroke-linecap="round"/>', kind="draw")
            cv.add(step, f'<path class="j-fade" d="M{x_here:g} {y} H{x_end:g}" fill="none" stroke="{color}" stroke-width="7" stroke-linecap="round" stroke-dasharray="1 13" opacity=".75"/>', kind="fade")
            # the goal card
            title = wrap(g["label"], 19, 2)
            sfg, sbg = S.STATUS.get(g["status"], S.STATUS["not_started"])[1:]
            chip, _ = pill(x_card_r - 14, y + 30, t("status." + g["status"]), fg=sfg, bg=sbg, size=11, h=20, anchor="end")
            card = (f'<rect x="{x_card_l}" y="{y - 46}" width="{CARD_W}" height="92" rx="18" fill="#fff" stroke="{color}" stroke-width="3"/>'
                    f'<rect x="{x_card_r - 78}" y="{y - 46}" width="78" height="92" rx="18" fill="{color}"/>'
                    f'<rect x="{x_card_r - 78}" y="{y - 46}" width="18" height="92" fill="{color}"/>'
                    + text(x_card_r - 39, y + 8, f"{g['progress']}%", size=26, weight=800, fill="#fff")
                    + text(x_card_r - 39, y + 30, t("orgmap.j.done"), size=11, weight=500, fill="#ffffffcc")
                    + lines_block(x_card_r - 90, y - 18, title, size=14, weight=700, anchor="end", lh=20)
                    + chip)
            cv.add(step, card, ox=x_card_r, oy=y)
            # pace tick and the pin
            cv.add(rv["here"], f'<path d="M{x_exp:g} {y + 14} l-7 12 h14 z" fill="{S.INK}"/>' + text(x_exp, y + 44, t("orgmap.j.expected", n=g["expected"]), size=10.5, weight=600, fill=S.BODY), kind="fade")
            pin = (f'<circle class="j-pulse" cx="{x_here:g}" cy="{y}" r="15" fill="none" stroke="{color}" stroke-width="3" opacity=".5"/>'
                   f'<circle cx="{x_here:g}" cy="{y}" r="11" fill="#fff" stroke="{color}" stroke-width="5"/>')
            tag, tw = pill(x_here, y - 42, t("orgmap.j.here_tag", n=g["progress"]), fg="#fff", bg=S.INK, size=11.5, h=24)
            cv.add(rv["here"], pin + tag + f'<path d="M{x_here - 5:g} {y - 30} h10 l-5 7 z" fill="{S.INK}"/>', ox=x_here, oy=y)
            # the target flag
            fy = y
            end_txt = g["end"].strftime("%d/%m/%Y") if g.get("end") else ""
            cv.add(step, f'<circle cx="{x_end:g}" cy="{fy}" r="24" fill="#fff" stroke="{color}" stroke-width="5"/>' + icon("flag", x_end, fy, 22, color, 2.2)
                   + text(x_end, fy + 48, t("orgmap.j.target"), size=12, weight=700) + (text(x_end, fy + 66, end_txt, size=11, weight=500, fill=S.BODY) if end_txt else ""), ox=x_end, oy=fy)
            # stations
            for i, kid in enumerate(krs):
                k = n[kid]
                x = xs[i]
                pos[kid] = (x, y)
                ks = rv[kid]
                icn, fg, bg = S.STATUS.get(k["status"], S.STATUS["not_started"])
                ringcol = color
                emph = kid in spec["emphasis"]
                body = (f'<circle cx="{x:g}" cy="{y}" r="{35 if emph else 0}" fill="{fg}" opacity=".10"/>' if emph else "")
                body += f'<circle cx="{x:g}" cy="{y}" r="22" fill="#fff"/>' + ring(x, y, 28, k["progress"], ringcol, width=6)
                body += icon(icn, x, y, 22, fg, 2.4)
                lab = wrap(k["label"], 24, 2)
                body += lines_block(x, y + 58, lab, size=13, weight=700, anchor="middle", lh=18)
                body += text(x, y + 98, f"{k['now']} / {k['target']}", size=12, weight=600, fill=S.BODY)
                chip, _ = pill(x, y + 122, t("status." + k["status"]) + (f" · {k['progress']}%"), fg=fg, bg=bg, size=11, h=22)
                body += chip
                row = y + 150
                if k["gap"]:
                    gp, _ = pill(x, row, t("orgmap.j.gap", gap=k["gap"]), fg="#b4231f", bg="#fde7e6", size=10.5, h=20, ic="alert-triangle")
                    body += gp
                    row += 24
                for bid in k["branches"][:3]:
                    b = n[bid]
                    fgb, bgb = S.TONE.get(b["tone"], S.TONE["flat"])
                    bp, _ = pill(x, row, clip(f"{b['label']} {b['text']}", 30), fg=fgb, bg=bgb, size=10.5, weight=600, h=20)
                    body += bp
                    row += 24
                cv.add(ks, body, ox=x, oy=y)
                for j, lid in enumerate(k["levers"][:3]):
                    lv = n[lid]
                    lp, _ = pill(x, y - 82 - j * 26, clip(lv["label"], 24), fg="#fff", bg=S.PRIMARY if lv["status"] != "dropped" else S.MUTED, size=10.5, h=21, ic="rocket")
                    cv.add(rv[lid], lp, ox=x, oy=y - 82)
            last_y = max(last_y, y)
        # ---- data shared by two goals: an interchange ------------------------------------------------------------------------------------------
        for sid in st["shared"]:
            users = [u for u in n[sid]["users"] if u in pos]
            if len(users) < 2:
                continue
            (xa, ya), (xb, yb) = pos[users[0]], pos[users[1]]
            if ya > yb:
                (xa, ya), (xb, yb) = (xb, yb), (xa, ya)
            midx, midy = (xa + xb) / 2 + 60, (ya + yb) / 2
            d = f"M{xa + 44:g} {ya + 20} C{xa + 120:g} {ya + 110:g} {xb + 120:g} {yb - 110:g} {xb + 44:g} {yb - 20}"
            lab, _ = pill(midx + 60, midy, clip(n[sid]["label"], 24), fg=S.PRIMARY, bg="#fff", size=11, h=24, ic="link", stroke=S.PRIMARY)
            cv.add(rv["links"], f'<path d="{d}" fill="none" stroke="{S.PRIMARY}" stroke-width="2.5" stroke-dasharray="6 7" opacity=".7"/>' + lab, kind="fade")
        # ---- legend ----------------------------------------------------------------------------------------------------------------------------
        ly = H - 52
        cv.add(rv["here"], f'<rect x="{W - 40 - 780}" y="{ly - 22}" width="780" height="44" rx="22" fill="#fff" stroke="{S.LINE}"/>'
               + "".join(icon(S.STATUS[s][0], W - 70 - i * 150, ly, 18, S.STATUS[s][1], 2.4) + text(W - 86 - i * 150, ly + 4, t("status." + s), size=12, weight=600, fill=S.BODY, anchor="end")
                         for i, s in enumerate(("completed", "at_risk", "off_track", "not_started")))
               + f'<path d="M{W - 700} {ly - 8} l-6 11 h12 z" fill="{S.INK}"/>' + text(W - 712, ly + 4, t("orgmap.j.legend_expected"), size=12, weight=600, fill=S.BODY, anchor="end"), kind="fade")
        return cv


family = Route()
