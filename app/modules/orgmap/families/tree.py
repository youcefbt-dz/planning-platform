"""The tree: the organization at the top, a column per goal, key results as boxes down the column, tributaries and levers inside each box.

The classic org-chart shape (the diagram the owner sketched), drawn with progress bars, status icons and orthogonal connectors.
"""
from __future__ import annotations

from app.core.i18n import t
from app.modules.orgmap import scene as S
from app.modules.orgmap.families.route import _logo
from app.modules.orgmap.scene import Canvas, clip, icon, lines_block, pill, text, wrap

COLW, BOXW = 350, 304


class Tree:
    name = "tree"
    label = "الشجرة"

    def layout(self, facts: dict, spec: dict, rv: dict) -> Canvas:
        n, st = facts["nodes"], facts["stats"]
        goals = facts["goals"]
        W = max(1100, len(goals) * COLW + 80)
        cx = W / 2
        has_v = "vision" in n
        top = 300 if has_v else 230
        # heights of the columns decide the canvas height
        def kr_h(k):
            rows = (len(k["branches"][:3]) + 1) // 2 + (1 if k["levers"] else 0)
            return 104 + 26 * rows + (24 if k["gap"] else 0)
        col_h = {g: 110 + sum(kr_h(n[k]) + 22 for k in n[g]["kr"]) for g in goals}
        H = top + 70 + max(col_h.values() or [0]) + 70
        cv = Canvas(W, H)
        org = n["org"]
        _logo(cx, 86, 46, org, rv["org"], cv)
        cv.add(rv["org"], text(cx, 176, clip(org["label"], 40), size=26, weight=800) + text(cx, 202, t("orgmap.j.sub", goals=len(goals), stations=st["stations"], cycle=st["cycle"] or "—"), size=13.5, weight=500, fill=S.BODY), kind="fade")
        if has_v:
            v = n["vision"]
            vt = wrap(v["vision"] or v["mission"], 90, 2)
            cv.add(rv["vision"], f'<rect x="{cx - 380}" y="222" width="760" height="56" rx="14" fill="{S.TINT}"/>' + lines_block(cx, 246, vt, size=13, weight=500, lh=20), kind="fade")
        bus = top + 8
        xs = {g: W - 40 - COLW / 2 - i * COLW for i, g in enumerate(goals)}
        if goals:
            first = min(rv[g] for g in goals)
            cv.add(first, f'<path class="j-draw" pathLength="1" d="M{cx} {278 if has_v else 214} V{bus}" fill="none" stroke="{S.LINE}" stroke-width="6" stroke-linecap="round"/>', kind="draw")
        for gi, gid in enumerate(goals):
            g = n[gid]
            color = S.LINE_COLORS[spec["lines"].get(gid, gi) % 6]
            gx, step = xs[gid], rv[gid]
            cv.add(step, f'<path class="j-draw" pathLength="1" d="M{cx} {bus} H{gx} V{top + 36}" fill="none" stroke="{S.LINE}" stroke-width="6" stroke-linejoin="round"/>', kind="draw")
            sfg, sbg = S.STATUS.get(g["status"], S.STATUS["not_started"])[1:]
            chip, _ = pill(gx + BOXW / 2 - 14, top + 98, t("status." + g["status"]), fg=sfg, bg=sbg, size=11, h=20, anchor="end")
            card = (f'<rect x="{gx - BOXW / 2}" y="{top + 36}" width="{BOXW}" height="92" rx="16" fill="#fff" stroke="{color}" stroke-width="3"/>'
                    f'<rect x="{gx - BOXW / 2}" y="{top + 36}" width="8" height="92" rx="4" fill="{color}"/>'
                    + lines_block(gx + BOXW / 2 - 16, top + 62, wrap(g["label"], 22, 2), size=14.5, weight=700, anchor="end", lh=20)
                    + chip + text(gx - BOXW / 2 + 54, top + 94, f"{g['progress']}%", size=22, weight=800, fill=color))
            cv.add(step, card, ox=gx, oy=top + 80)
            y = top + 128 + 26
            spine_x = gx + BOXW / 2 - 18
            ends = []
            for kid in g["kr"]:
                k = n[kid]
                h = kr_h(k)
                icn, fg, bg = S.STATUS.get(k["status"], S.STATUS["not_started"])
                x0 = gx - BOXW / 2 + 10
                bw = BOXW - 20
                body = (f'<rect x="{x0}" y="{y}" width="{bw}" height="{h}" rx="14" fill="#fff" stroke="{S.LINE}" stroke-width="1.5"/>'
                        f'<rect x="{x0}" y="{y + 14}" width="5" height="{h - 28}" rx="2.5" fill="{fg}"/>'
                        + icon(icn, x0 + bw - 24, y + 24, 20, fg, 2.4)
                        + lines_block(x0 + bw - 46, y + 28, wrap(k["label"], 25, 2), size=13, weight=700, anchor="end", lh=18)
                        + text(x0 + bw - 14, y + 68, f"{k['now']} / {k['target']}", size=12, weight=600, fill=S.BODY, anchor="end")
                        + f'<rect x="{x0 + 16}" y="{y + 60}" width="{bw - 190}" height="8" rx="4" fill="#E3E7F5"/><rect x="{x0 + 16}" y="{y + 60}" width="{(bw - 190) * k["progress"] / 100:g}" height="8" rx="4" fill="{color}"/>'
                        + text(x0 + 16, y + 88, f"{k['progress']}%", size=11.5, weight=700, fill=S.INK, anchor="start"))
                ry = y + 98
                if k["gap"]:
                    gp, _ = pill(x0 + bw - 14, ry, t("orgmap.j.gap", gap=k["gap"]), fg="#b4231f", bg="#fde7e6", size=10.5, h=20, ic="alert-triangle", anchor="end")
                    body += gp
                    ry += 24
                brs = k["branches"][:3]
                for bi, bid in enumerate(brs):
                    b = n[bid]
                    fgb, bgb = S.TONE.get(b["tone"], S.TONE["flat"])
                    bp, _ = pill(x0 + bw - 14 - (bi % 2) * 150, ry + (bi // 2) * 26, clip(f"{b['label']} {b['text']}", 17), fg=fgb, bg=bgb, size=10, h=20, anchor="end")
                    body += bp
                if brs:
                    ry += 26 * ((len(brs) + 1) // 2)
                if k["levers"]:
                    lp, _ = pill(x0 + bw - 14, ry, clip(n[k["levers"][0]]["label"], 28), fg="#fff", bg=S.PRIMARY, size=10, h=20, ic="rocket", anchor="end")
                    body += lp
                cv.add(rv[kid], f'<path class="j-draw" pathLength="1" d="M{spine_x} {top + 128} V{y + 24} H{x0 + bw}" fill="none" stroke="{S.LINE}" stroke-width="3.5" stroke-linejoin="round"/>', kind="draw")
                cv.add(rv[kid], body, ox=gx, oy=y + h / 2)
                ends.append(y + h)
                y += h + 22
        cv.add(rv["here"], text(W / 2, H - 28, t("orgmap.j.cap.here", journey=st["journey"]), size=14, weight=700, fill=S.BODY), kind="fade")
        return cv


family = Tree()
