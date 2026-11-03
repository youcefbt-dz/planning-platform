/* The organization's journey, drawn as an archipelago on an open canvas you can pan and zoom.
   - the capital in the middle: identity, vision, mission (and the organization's own goals around it)
   - every department is an island: its head stands on it, its goals are around the head, sub-departments are islands beside it
   - every goal is a ring: how far it has got, a tick for where it should be today, a hatched gap when it is late
   - routes between goals are the real dependencies (a goal that depends on another); a route whose source is in trouble is marked
   Pan: drag. Zoom: wheel / pinch / buttons / + - keys. Click a goal, a head, a department or the capital for its panel.
   Data: <script data-jx-data> (orgmap/payload.py). Text is always inserted with textContent. */
(function () {
  'use strict';
  var root = document.querySelector('[data-journey]');
  if (!root) return;
  var D;
  try { D = JSON.parse(root.querySelector('[data-jx-data]').textContent); } catch (e) { return; }
  var I = D.i18n, NS = 'http://www.w3.org/2000/svg';
  var RTL = (document.documentElement.getAttribute('dir') || 'ltr') === 'rtl';
  var stage = root.querySelector('[data-stage]'), panel = root.querySelector('[data-panel]'), chipsEl = root.querySelector('[data-chips]'), miniEl = root.querySelector('[data-mini]');
  var calm = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var BAD = { at_risk: 1, off_track: 1 };

  // ---------- helpers ----------
  function el(name, attrs, parent, text) {
    var n = document.createElementNS(NS, name);
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    if (parent) parent.appendChild(n);
    return n;
  }
  function h(tag, cls, text, parent) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; if (parent) parent.appendChild(n); return n; }
  function clip(s, n) { s = String(s || ''); return s.length > n ? s.slice(0, n - 1).trim() + '…' : s; }
  function f1(n) { return Math.round(n * 10) / 10; }
  function rnd(seed) { var s = (seed * 9301 + 49297) % 233280; return function () { s = (s * 9301 + 49297) % 233280; return s / 233280; }; }
  function lines(text, per, max) {                       // wrap a title into at most `max` lines of about `per` characters
    var words = String(text || '').split(/\s+/).filter(Boolean), out = [], cur = '';
    words.forEach(function (w) { if (cur && (cur + ' ' + w).length > per) { out.push(cur); cur = w; } else cur = cur ? cur + ' ' + w : w; });
    if (cur) out.push(cur);
    if (out.length > max) { var rest = out.slice(max - 1).join(' '); out = out.slice(0, max - 1); out.push(clip(rest, per)); }
    return out;
  }

  // ---------- model ----------
  var U = {}, G = {}, capGoals = [], depOut = {}, depIn = {}, kidsG = {}, rootU = null;
  D.units.forEach(function (u) { U[u.id] = u; u.kids = []; u.goals = []; if (u.kind === 'company' && !rootU) rootU = u; });
  D.units.forEach(function (u) { if (u.parent && U[u.parent]) U[u.parent].kids.push(u.id); });
  D.goals.forEach(function (g) {
    G[g.id] = g; var u = g.unit && U[g.unit];
    if (!u || u === rootU) capGoals.push(g.id); else u.goals.push(g.id);
    if (g.parent) (kidsG[g.parent] = kidsG[g.parent] || []).push(g.id);
  });
  D.deps.forEach(function (d) { (depOut[d.from] = depOut[d.from] || []).push(d.to); (depIn[d.to] = depIn[d.to] || []).push(d.from); });
  function subtree(uid) { var out = [], todo = [uid]; while (todo.length) { var x = todo.pop(); out.push(x); U[x].kids.forEach(function (k) { todo.push(k); }); } return out; }
  function goalsOf(uid) { var out = []; subtree(uid).forEach(function (x) { out = out.concat(U[x].goals); }); return out; }
  function standing(ids) {
    var st = ids.map(function (i) { return G[i].status; });
    if (st.indexOf('off_track') > -1) return 'off_track';
    if (st.indexOf('at_risk') > -1) return 'at_risk';
    if (st.length && st.every(function (s) { return s === 'completed'; })) return 'completed';
    return st.length ? 'on_track' : 'not_started';
  }
  function avg(ids) { return ids.length ? Math.round(ids.reduce(function (a, i) { return a + G[i].progress; }, 0) / ids.length) : 0; }
  var attention = D.goals.filter(function (g) { return BAD[g.status]; }).map(function (g) { return g.id; });

  // ---------- layout (world coordinates) ----------
  var islands = [], cap = { x: 0, y: 0, R: 190, goals: [] }, bounds = { x1: -400, y1: -400, x2: 400, y2: 400 };
  function relax(pts, dmin, rc) {
    for (var it = 0; it < 90; it++) {
      for (var i = 0; i < pts.length; i++) for (var j = i + 1; j < pts.length; j++) {
        var dx = pts[j].x - pts[i].x, dy = pts[j].y - pts[i].y, d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        if (d < dmin) { var m = (dmin - d) / 2, ux = dx / d, uy = dy / d; pts[i].x -= ux * m; pts[i].y -= uy * m; pts[j].x += ux * m; pts[j].y += uy * m; }
      }
      pts.forEach(function (p) { var d = Math.sqrt(p.x * p.x + p.y * p.y) || 0.01; if (d < rc) { p.x *= rc / d; p.y *= rc / d; } });
    }
  }
  function localPts(n, seed) {                              // a department's goals sit evenly on a circle around its head, never in a heap
    var pts = [], Rg = n <= 1 ? 120 : Math.max(126, 60 / Math.sin(Math.PI / n)), a0 = n === 2 ? 0 : -Math.PI / 2 + (n === 1 ? 0.6 : 0);
    for (var i = 0; i < n; i++) { var a = a0 + i * 2 * Math.PI / Math.max(n, 1); pts.push({ x: Rg * Math.cos(a), y: Rg * Math.sin(a) }); }
    pts.Rg = Rg;
    return pts;
  }
  function layout() {
    islands = [];
    var map = {};
    D.units.forEach(function (u) {
      if (u === rootU) return;
      var pts = localPts(u.goals.length, u.id), far = u.goals.length ? pts.Rg : 96;
      // Give each department only the room its own goals need; avoid oversized empty discs.
      var isl = { u: u, x: 0, y: 0, R: Math.max(172, far + 104), pts: pts, kids: [] };
      islands.push(isl); map[u.id] = isl;
    });
    var tops = islands.filter(function (i) { return !i.u.parent || i.u.parent === (rootU && rootU.id) || !map[i.u.parent]; });
    islands.forEach(function (i) { if (i.u.parent && map[i.u.parent]) map[i.u.parent].kids.push(i); });

    // Keep the organization's goals close to the centre, with enough breathing room for labels.
    var n = capGoals.length;
    cap.disc = 132;
    var ringR = n ? Math.max(230, 56 / Math.sin(Math.PI / Math.max(n, 2))) : 0;
    cap.ringR = ringR;
    cap.R = n ? ringR + 92 : cap.disc + 42;
    cap.goals = capGoals.map(function (id, i) {
      var a = -Math.PI / 2 + i * 2 * Math.PI / n;
      return { id: id, x: ringR * Math.cos(a), y: ringR * Math.sin(a) };
    });

    // Place top-level departments on one balanced ring. Each sector gets space in proportion
    // to its department size, so the map stays circular instead of stretching into an ellipse.
    var total = 0, gap = 94, xScale = 1.15, yScale = 0.9, cursor = -Math.PI / 2;
    tops.forEach(function (i) { total += 2 * i.R + gap; });
    var sectors = tops.map(function (i) {
      var span = total ? (2 * i.R + gap) / total * 2 * Math.PI : 0;
      var th = cursor + span / 2;
      cursor += span;
      return { island: i, angle: th };
    });
    // The slightly horizontal composition is accounted for in the clearance calculation,
    // so even a department placed at the top or bottom cannot intrude into the central orbit.
    var clearRing = sectors.reduce(function (need, sector) {
      var th = sector.angle, factor = Math.sqrt(Math.pow(xScale * Math.cos(th), 2) + Math.pow(yScale * Math.sin(th), 2));
      return Math.max(need, (cap.R + sector.island.R + 108) / factor);
    }, 0);
    var ring = tops.length ? Math.max(clearRing, total / (2 * Math.PI) * 1.14) : 0;
    sectors.forEach(function (sector) {
      var i = sector.island, th = sector.angle;
      i.x = ring * xScale * Math.cos(th); i.y = ring * yScale * Math.sin(th); i.th = th;
    });

    // Sub-departments sit on the outward side of their parent, with a fan wide enough
    // to keep neighbouring departments apart without arbitrary nudging.
    tops.forEach(function (top) {
      (function placeChildren(parent) {
        var kids = parent.kids;
        if (!kids.length) return;
        var maxChild = Math.max.apply(null, kids.map(function (c) { return c.R; }));
        var distance = parent.R + maxChild + 86;
        var required = kids.reduce(function (sum, c) { return sum + 2 * c.R + 82; }, 0);
        var span = Math.min(Math.PI * 1.8, required / distance);
        var angle = (parent.th == null ? 0 : parent.th) - span / 2;
        kids.forEach(function (c) {
          var part = (2 * c.R + 82) / required * span;
          var th = angle + part / 2;
          angle += part;
          c.x = parent.x + distance * Math.cos(th);
          c.y = parent.y + distance * Math.sin(th);
          c.th = th;
          placeChildren(c);
        });
      })(top);
    });

    var x1 = -cap.R, y1 = -cap.R, x2 = cap.R, y2 = cap.R;
    islands.forEach(function (i) {
      x1 = Math.min(x1, i.x - i.R); y1 = Math.min(y1, i.y - i.R);
      x2 = Math.max(x2, i.x + i.R); y2 = Math.max(y2, i.y + i.R);
    });
    bounds = { x1: x1, y1: y1, x2: x2, y2: y2 };
    islands.forEach(function (i) {
      i.goals = i.u.goals.map(function (id, k) { return { id: id, x: i.x + i.pts[k].x, y: i.y + i.pts[k].y }; });
    });
    pos = {};
    cap.goals.forEach(function (p) { pos[p.id] = p; });
    islands.forEach(function (i) { i.goals.forEach(function (p) { pos[p.id] = p; }); });
    return map;
  }
  var pos = {}, islandOf = {};

  // ---------- geometry ----------
  function blob(R, seed, scale) {
    var r = rnd(seed + 3), n = 18, raw = [], k;
    for (k = 0; k < n; k++) raw.push(r());
    var sm = raw.map(function (v, i) { return (raw[(i + n - 1) % n] + v * 2 + raw[(i + 1) % n]) / 4; });
    var pts = sm.map(function (v, i) { var a = i / n * 2 * Math.PI, rad = R * scale * (0.9 + 0.17 * v); return [rad * Math.cos(a), rad * Math.sin(a)]; });
    var d = 'M' + f1(pts[0][0]) + ' ' + f1(pts[0][1]);
    for (k = 0; k < n; k++) {
      var p0 = pts[(k + n - 1) % n], p1 = pts[k], p2 = pts[(k + 1) % n], p3 = pts[(k + 2) % n];
      d += 'C' + f1(p1[0] + (p2[0] - p0[0]) / 6) + ' ' + f1(p1[1] + (p2[1] - p0[1]) / 6) + ' ' + f1(p2[0] - (p3[0] - p1[0]) / 6) + ' ' + f1(p2[1] - (p3[1] - p1[1]) / 6) + ' ' + f1(p2[0]) + ' ' + f1(p2[1]);
    }
    return d + 'Z';
  }
  function curve(ax, ay, bx, by, bend) {                    // a gentle curve; returns the path and its midpoint
    var dx = bx - ax, dy = by - ay, L = Math.sqrt(dx * dx + dy * dy) || 1, nx = -dy / L, ny = dx / L, c = Math.min(160, L * bend);
    var mx = (ax + bx) / 2 + nx * c, my = (ay + by) / 2 + ny * c;
    return { d: 'M' + f1(ax) + ' ' + f1(ay) + 'Q' + f1(mx) + ' ' + f1(my) + ' ' + f1(bx) + ' ' + f1(by), mx: (ax + bx) / 4 + mx / 2, my: (ay + by) / 4 + my / 2 };
  }
  function arc(r, a0, a1) {                                  // arc from angle a0 to a1 (degrees, 0 = top, clockwise)
    var t0 = (a0 - 90) * Math.PI / 180, t1 = (a1 - 90) * Math.PI / 180, large = (a1 - a0) > 180 ? 1 : 0;
    return 'M' + f1(r * Math.cos(t0)) + ' ' + f1(r * Math.sin(t0)) + 'A' + r + ' ' + r + ' 0 ' + large + ' 1 ' + f1(r * Math.cos(t1)) + ' ' + f1(r * Math.sin(t1));
  }

  // ---------- drawing ----------
  var svg, world, L = {}, nodes = {}, state = { deps: true, align: true, attn: false, sel: null, hover: null, voiceFocus: null }, intro = true;
  function defs() {
    var d = el('defs', null, svg);
    var p = el('pattern', { id: 'jx-hatch', width: 7, height: 7, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, d);
    el('rect', { width: 7, height: 7, class: 'jx-hatch-bg' }, p); el('rect', { width: 3.4, height: 7, class: 'jx-hatch-bar' }, p);
    var q = el('pattern', { id: 'jx-dots', width: 22, height: 22, patternUnits: 'userSpaceOnUse' }, d);
    el('circle', { cx: 11, cy: 11, r: 1.5, class: 'jx-dotp' }, q);
    [['jx-arr', 'jx-arrow'], ['jx-arrw', 'jx-arrow jx-arrow--warn'], ['jx-arra', 'jx-arrow jx-arrow--align']].forEach(function (m) {
      var mk = el('marker', { id: m[0], viewBox: '0 0 10 10', refX: 8.5, refY: 5, markerWidth: 6.5, markerHeight: 6.5, orient: 'auto' }, d);
      el('path', { d: 'M1 1.4L9 5L1 8.6Z', class: m[1] }, mk);
    });
  }

  (function legendColours() {                                // the legend says what the colours mean, in the words of the status labels
    var lg = root.querySelector('.jx__legend'); if (!lg) return;
    ['on_track', 'at_risk', 'off_track', 'completed'].slice().reverse().forEach(function (s) {
      var li = h('li', 'lg-st'); h('i', 'lg-dot', null, li).setAttribute('data-s', s); h('span', null, I.status[s] || s, li); lg.insertBefore(li, lg.firstChild);
    });
  })();

  function render() {
    if (svg) svg.remove();
    svg = el('svg', { class: 'jx-svg', role: 'group', 'aria-label': D.org.name }); stage.appendChild(svg);
    defs();
    world = el('g', { class: 'jx-world' }, svg);
    var gRoads = el('g', { class: 'jx-roads' }, world), gLand = el('g', { class: 'jx-lands' }, world), gAlign = el('g', { class: 'jx-aligns' }, world), gDeps = el('g', { class: 'jx-deps' }, world),
        gCap = el('g', { class: 'jx-capg' }, world), gGoals = el('g', { class: 'jx-goals' }, world), gBloom = el('g', { class: 'jx-bloom' }, world);
    nodes = { bloom: gBloom, goals: {}, aligns: [], deps: [] };

    // roads: capital -> departments, department -> sub-department
    islands.forEach(function (i, k) {
      var par = i.u.parent && islands.filter(function (x) { return x.u.id === i.u.parent; })[0], ax = par ? par.x : 0, ay = par ? par.y : 0, c = curve(ax, ay, i.x, i.y, 0.1);
      el('path', { d: c.d, class: 'jx-road' }, gRoads); el('path', { d: c.d, class: 'jx-roadline' }, gRoads);
    });

    islands.forEach(function (i, k) { island(gLand, gGoals, i, k); });
    capital(gCap, gGoals);

    // alignment: a goal that serves another
    D.goals.forEach(function (g) {
      if (!g.parent || !pos[g.parent] || !pos[g.id]) return;
      var a = pos[g.id], b = pos[g.parent], dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1, ux = dx / d, uy = dy / d;
      var c = curve(a.x + ux * 36, a.y + uy * 36, b.x - ux * 40, b.y - uy * 40, 0.12);
      var p = el('path', { d: c.d, class: 'jx-align', 'data-a': g.id, 'data-b': g.parent, 'marker-end': 'url(#jx-arra)' }, gAlign);
      nodes.aligns.push(p);
    });
    // dependencies: `from` depends on `to`, so the route runs from `to` to `from`
    D.deps.forEach(function (dp) {
      var s = pos[dp.to], t = pos[dp.from]; if (!s || !t) return;
      var dx = t.x - s.x, dy = t.y - s.y, d = Math.sqrt(dx * dx + dy * dy) || 1, ux = dx / d, uy = dy / d, bad = BAD[G[dp.to].status];
      var c = curve(s.x + ux * 38, s.y + uy * 38, t.x - ux * 46, t.y - uy * 46, 0.2);
      var grp = el('g', { class: 'jx-dep' + (bad ? ' is-warn' : ''), 'data-a': dp.from, 'data-b': dp.to }, gDeps);
      el('path', { d: c.d, class: 'jx-depglow' }, grp);
      el('path', { d: c.d, class: 'jx-depline', 'marker-end': 'url(#' + (bad ? 'jx-arrw' : 'jx-arr') + ')' }, grp);
      if (bad) { var w = el('g', { transform: 'translate(' + f1(c.mx) + ' ' + f1(c.my) + ')', class: 'jx-depwarn' }, grp); el('circle', { r: 11 }, w); el('path', { d: 'M0 -5V1.5', class: 'jx-mark' }, w); el('circle', { cy: 5.2, r: 1.3, class: 'jx-markdot' }, w); }
      nodes.deps.push(grp);
    });
    apply();
  }

  function pill(parent, y, text, pct, st) {                 // the department's name on a tag that straddles the top of its disc
    var w = Math.max(164, Math.min(270, text.length * 13 + 96)), g = el('g', { class: 'jx-pill', 'data-s': st, transform: 'translate(0 ' + f1(y) + ')' }, parent);
    el('rect', { x: f1(-w / 2), y: -24, width: f1(w), height: 48, rx: 24, class: 'jx-pillbg' }, g);
    el('circle', { cx: f1(RTL ? w / 2 - 25 : -w / 2 + 25), r: 6.5, class: 'jx-pilldot' }, g);
    el('text', { y: 7, class: 'jx-uname', 'text-anchor': 'middle', x: RTL ? -7 : 7 }, g, text);
    var pc = el('text', { y: 6, class: 'jx-upct', 'text-anchor': RTL ? 'start' : 'end', x: f1(RTL ? -w / 2 + 19 : w / 2 - 19), style: 'direction:ltr' }, g, pct + '%');
    return pc;
  }

  function island(gLand, gGoals, i, k) {
    var u = i.u, ids = goalsOf(u.id), st = standing(ids), pr = avg(ids), g = el('g', { class: 'jx-island', transform: 'translate(' + f1(i.x) + ' ' + f1(i.y) + ')', 'data-unit': u.id, 'data-s': st }, gLand);
    var pop = el('g', { class: 'jx-pop', style: '--i:' + (k + 1) }, g);
    el('circle', { r: i.R + 12, class: 'jx-aura' }, pop);
    var land = el('circle', { r: i.R, class: 'jx-disc' }, pop);
    el('circle', { r: i.R - 24, class: 'jx-inner' }, pop);
    if (u.goals.length) el('circle', { r: i.pts.Rg, class: 'jx-orbit' }, pop);
    var rr = i.R - 8;                                        // the perimeter is the department's progress: filled clockwise from the top
    el('circle', { r: rr, class: 'jx-ptrack' }, pop);
    if (pr > 0) el('circle', { r: rr, class: 'jx-parc', transform: 'rotate(-90)', pathLength: 100, 'stroke-dasharray': pr + ' ' + (100 - pr + 0.01) }, pop);
    pill(pop, -i.R, clip(u.name, 24), pr, st);
    land.addEventListener('click', function (e) { if (drag.moved) return; e.stopPropagation(); selectUnit(u.id); });

    // the head, in the middle of the disc, the goals around them
    var hd = el('g', { class: 'jx-node jx-head' + (u.head ? '' : ' is-empty'), tabindex: 0, role: 'button', 'aria-label': u.name + (u.head ? ' — ' + u.head.name : ' — ' + I.no_head) }, pop);
    el('circle', { r: 50, class: 'jx-hhalo' }, hd);
    el('circle', { r: 38, class: 'jx-hbase' }, hd);
    el('circle', { r: 38, class: 'jx-hring' }, hd);
    if (u.head) el('text', { y: 7, class: 'jx-hini', 'text-anchor': 'middle' }, hd, u.head.initials);
    else el('path', { d: 'M0 -9a6 6 0 1 0 0.01 0M-12 13c1-8 6-12 12-12s11 4 12 12', class: 'jx-hnone' }, hd);
    el('text', { y: 66, class: 'jx-hname', 'text-anchor': 'middle' }, hd, u.head ? clip(u.head.name, 22) : I.no_head);
    if (u.head && u.head.title) el('text', { y: 83, class: 'jx-htitle', 'text-anchor': 'middle' }, hd, clip(u.head.title, 26));
    hd.addEventListener('click', function (e) { if (drag.moved) return; e.stopPropagation(); selectUnit(u.id); });
    hd.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectUnit(u.id); } });
    islandOf[u.id] = i;
    i.goals.forEach(function (p, n) { goal(gGoals, p, k + 2 + n); });
  }

  function capital(gCap, gGoals) {
    var o = D.org, g = el('g', { class: 'jx-node jx-cap', tabindex: 0, role: 'button', 'aria-label': o.name }, gCap), pop = el('g', { class: 'jx-pop', style: '--i:0' }, g), r = cap.disc;
    el('circle', { r: cap.R, class: 'jx-capfield' }, pop);                                   // the whole orbit: a soft field the goals travel in
    if (cap.ringR) el('circle', { r: cap.ringR, class: 'jx-caporbit' }, pop);
    el('circle', { r: r + 22, class: 'jx-caphalo' }, pop);
    el('circle', { r: r, class: 'jx-capland' }, pop);
    el('circle', { r: r - 16, class: 'jx-capshore' }, pop);
    var ident = el('g', { class: 'jx-hs' }, pop);
    el('circle', { cy: -62, r: 50, class: 'jx-ohalo' }, ident);
    el('circle', { cy: -62, r: 43, class: 'jx-oring' }, ident);
    el('circle', { cy: -62, r: 38, class: 'jx-obg' }, ident);
    if (o.logo) { var cp = el('clipPath', { id: 'jx-oclip' }, ident); el('circle', { cy: -62, r: 34 }, cp); el('image', { href: o.logo, x: -34, y: -96, width: 68, height: 68, 'clip-path': 'url(#jx-oclip)', preserveAspectRatio: 'xMidYMid slice' }, ident); }
    else el('text', { y: -53, class: 'jx-oini', 'text-anchor': 'middle' }, ident, o.initials);
    var nm = lines(o.name, 17, 2), y0 = 14;
    nm.forEach(function (ln, n) { el('text', { y: y0 + n * 25, class: 'jx-oname', 'text-anchor': 'middle' }, ident, ln); });
    var y1 = y0 + (nm.length - 1) * 25 + 24;
    el('text', { y: y1, class: 'jx-ocap', 'text-anchor': 'middle' }, ident, I.origin);
    if (D.vision.text) {                                      // the vision: a small star, then its words
      var vy = y1 + 26, vl = lines(D.vision.text, 30, 2);
      var v = el('g', { transform: 'translate(0 ' + f1(vy) + ')', class: 'jx-vis' }, ident);
      el('circle', { r: 10, class: 'jx-vripple' }, v); el('circle', { r: 8, class: 'jx-vcore' }, v);
      el('path', { d: 'M0 -4.6L1.4 -1.5L4.7 -1.1L2.2 1.1L2.9 4.4L0 2.6L-2.9 4.4L-2.2 1.1L-4.7 -1.1L-1.4 -1.5Z', class: 'jx-vstar' }, v);
      vl.forEach(function (ln, n) { el('text', { y: vy + 26 + n * 17, class: 'jx-vtx', 'text-anchor': 'middle' }, ident, ln); });
    }
    g.addEventListener('click', function (e) { if (drag.moved) return; e.stopPropagation(); selectOrg(); });
    g.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectOrg(); } });
    cap.goals.forEach(function (p, n) { goal(gGoals, p, 1 + n); });
  }

  function goal(layer, p, order) {
    var gl = G[p.id], s = gl.status, pr = gl.progress, ex = gl.expected;
    var g = el('g', { class: 'jx-node jx-goal', 'data-id': gl.id, 'data-s': s, 'data-bad': BAD[s] ? 1 : 0, transform: 'translate(' + f1(p.x) + ' ' + f1(p.y) + ')', tabindex: 0, role: 'button',
                      'aria-label': gl.title + ' — ' + pr + '% — ' + (I.status[s] || s) }, layer);
    var pop = el('g', { class: 'jx-pop', style: '--i:' + order }, el('g', { class: 'jx-gs' }, g));
    el('circle', { r: 50, class: 'jx-ghit' }, pop);
    if (BAD[s]) el('circle', { r: 44, class: 'jx-ghalo' }, pop);
    el('circle', { r: 33, class: 'jx-gbase' }, pop);
    el('circle', { r: 24, class: 'jx-gtrack' }, pop);
    if (pr < ex) el('path', { d: arc(24, pr * 3.6, ex * 3.6), class: 'jx-ggap' }, pop);
    if (pr > 0) el('circle', { r: 24, class: 'jx-garc', transform: 'rotate(-90)', pathLength: 100, 'stroke-dasharray': pr + ' ' + (100 - pr + 0.01) }, pop);
    var ea = (ex * 3.6 - 90) * Math.PI / 180;
    el('path', { d: 'M' + f1(18 * Math.cos(ea)) + ' ' + f1(18 * Math.sin(ea)) + 'L' + f1(32 * Math.cos(ea)) + ' ' + f1(32 * Math.sin(ea)), class: 'jx-gexp' }, pop);
    el('text', { y: 5, class: 'jx-gpct', 'text-anchor': 'middle', style: 'direction:ltr' }, pop, pr + '%');
    var bd = el('g', { class: 'jx-gbadge', transform: 'translate(23 -23)' }, pop);
    if (s === 'completed') { el('circle', { r: 10.5, class: 'jx-bcirc' }, bd); el('path', { d: 'M-4.4 .4L-1.3 3.4L4.6 -3', class: 'jx-mark' }, bd); }
    else if (s === 'off_track') { el('circle', { r: 10.5, class: 'jx-bcirc' }, bd); el('path', { d: 'M0 -5V1.2', class: 'jx-mark' }, bd); el('circle', { cy: 4.6, r: 1.4, class: 'jx-markdot' }, bd); }
    else if (s === 'at_risk') { el('circle', { r: 10.5, class: 'jx-bcirc' }, bd); el('path', { d: 'M0 -5V1.2', class: 'jx-mark jx-mark--ink' }, bd); el('circle', { cy: 4.6, r: 1.4, class: 'jx-markdot jx-markdot--ink' }, bd); }
    var lb = el('text', { y: 54, class: 'jx-glabel', 'text-anchor': 'middle' }, pop);
    lines(gl.title, 17, 2).forEach(function (ln, n) { el('tspan', { x: 0, dy: n ? 16 : 0 }, lb, ln); });
    g.addEventListener('mouseenter', function () { state.hover = gl.id; apply(); });
    g.addEventListener('mouseleave', function () { state.hover = null; apply(); });
    g.addEventListener('focus', function () { state.hover = gl.id; apply(); });
    g.addEventListener('blur', function () { state.hover = null; apply(); });
    g.addEventListener('click', function (e) { if (drag.moved) return; e.stopPropagation(); selectGoal(gl.id); });
    g.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectGoal(gl.id); } });
    nodes.goals[gl.id] = g;
  }

  // ---------- focus & highlight ----------
  function related(id) {
    var r = {}; r[id] = 1; var g = G[id];
    if (g.parent) r[g.parent] = 1;
    (kidsG[id] || []).forEach(function (k) { r[k] = 1; });
    (depOut[id] || []).forEach(function (k) { r[k] = 1; }); (depIn[id] || []).forEach(function (k) { r[k] = 1; });
    return r;
  }
  function apply() {
    var vf = state.voiceFocus, focus = vf ? (vf.kind === 'goal' ? vf.id : null) : (state.hover || (state.sel && state.sel.kind === 'goal' ? state.sel.id : null)), rel = focus ? related(focus) : null, unitSet = null;
    if (!focus && vf && vf.kind === 'unit') { unitSet = {}; goalsOf(vf.id).forEach(function (i) { unitSet[i] = 1; }); }
    if (!unitSet && !focus && state.sel && state.sel.kind === 'unit') { unitSet = {}; goalsOf(state.sel.id).forEach(function (i) { unitSet[i] = 1; }); }
    root.classList.toggle('has-focus', !!focus); root.classList.toggle('has-unit', !!unitSet); root.classList.toggle('has-voice-focus', !!vf && vf.kind !== 'org');
    root.classList.toggle('no-deps', !state.deps); root.classList.toggle('no-align', !state.align); root.classList.toggle('only-attn', state.attn);
    Object.keys(nodes.goals).forEach(function (id) {
      var n = nodes.goals[id];
      n.classList.toggle('is-dim', (!!rel && !rel[id]) || (!!unitSet && !unitSet[id]));
      n.classList.toggle('is-focus', id === focus);
      n.classList.toggle('is-sel', !!state.sel && state.sel.kind === 'goal' && state.sel.id === id);
      n.classList.toggle('is-voice-focus', !!vf && vf.kind === 'goal' && vf.id === id);
      n.classList.toggle('is-voice-related', !!vf && (focus ? !!rel[id] : !!unitSet && !!unitSet[id]));
    });
    nodes.deps.concat(nodes.aligns).forEach(function (n) { n.classList.toggle('is-on', !!focus && (n.getAttribute('data-a') === focus || n.getAttribute('data-b') === focus)); });
    Array.prototype.forEach.call(svg.querySelectorAll('.jx-island'), function (n) { n.classList.toggle('is-sel', !!state.sel && state.sel.kind === 'unit' && String(state.sel.id) === n.getAttribute('data-unit')); n.classList.toggle('is-voice-focus', !!vf && vf.kind === 'unit' && String(vf.id) === n.getAttribute('data-unit')); });
    var capNode = svg.querySelector('.jx-cap'); if (capNode) capNode.classList.toggle('is-voice-focus', !!vf && vf.kind === 'org');
    Array.prototype.forEach.call(chipsEl.querySelectorAll('[data-u]'), function (b) { b.setAttribute('aria-pressed', state.sel && state.sel.kind === 'unit' && String(state.sel.id) === b.getAttribute('data-u') ? 'true' : 'false'); });
  }

  // ---------- selection, the panel and the key-result blossom ----------
  function fmtDate(iso) { if (!iso) return ''; try { return new Date(iso).toLocaleDateString(document.documentElement.lang || 'ar', { day: 'numeric', month: 'long', year: 'numeric' }); } catch (e) { return iso; } }
  function closeBtn(parent) { var x = h('button', 'jp-x', '×', parent); x.type = 'button'; x.setAttribute('aria-label', I.close); x.addEventListener('click', deselect); return x; }
  function voiceExplainBtn(parent, kind, id) { var b = h('button', 'jp-voice-btn', I.voice_explain, parent); b.type = 'button'; b.setAttribute('data-voice-target-kind', kind); b.setAttribute('data-voice-target-id', String(id)); return b; }
  function stPill(parent, s) { var p = h('span', 'jp-st', I.status[s] || s, parent); p.setAttribute('data-s', s); return p; }
  function row(parent, label, val) { var r = h('p', 'jp-row', null, parent); h('span', null, label, r); h('b', null, val, r); return r; }
  function goalBtn(parent, id, extra) {
    var b = h('button', 'jp-item', null, parent); b.type = 'button'; b.setAttribute('data-s', G[id].status);
    h('i', 'jp-dot', null, b); h('span', null, G[id].title, b).setAttribute('dir', 'auto'); h('b', 'num', G[id].progress + '%', b);
    if (extra) b.title = extra; b.addEventListener('click', function () { selectGoal(id); }); return b;
  }
  function avatar(parent, head, big) { var a = h('span', 'jp-av' + (big ? ' jp-av--big' : ''), head ? head.initials : '', parent); if (!head) a.classList.add('is-empty'); return a; }
  function openPanel() { panel.hidden = false; panel.classList.remove('is-in'); void panel.offsetWidth; panel.classList.add('is-in'); root.classList.add('has-panel'); }

  function selectGoal(id, keepCam) {
    var g = G[id]; state.sel = { kind: 'goal', id: id }; state.hover = null;
    panel.textContent = ''; var top = h('div', 'jp-top', null, panel); stPill(top, g.status); closeBtn(top);
    h('h2', null, g.title, panel).setAttribute('dir', 'auto');
    voiceExplainBtn(panel, 'goal', id);
    var d = g.progress - g.expected, bar = h('div', 'jp-bar', null, panel); h('i', null, null, bar).style.width = g.progress + '%'; h('u', null, null, bar).style.insetInlineStart = g.expected + '%';
    var line = h('p', 'jp-line', null, panel); h('b', 'num', g.progress + '%', line).setAttribute('dir', 'ltr');
    h('span', null, d === 0 ? I.even : (d < 0 ? I.behind : I.ahead) + ' · ' + Math.abs(d) + ' ' + I.points, line).setAttribute('data-tone', d < 0 ? 'lag' : 'lead');
    var u = g.unit && U[g.unit];
    if (u && u !== rootU) { var r = row(panel, I.unit, u.name); r.classList.add('is-link'); r.addEventListener('click', function () { selectUnit(u.id); }); if (u.head) row(panel, I.head, u.head.name); }
    if (g.owner) row(panel, I.owner, g.owner);
    if (g.end) row(panel, I.ends, fmtDate(g.end));
    var needs = depOut[id] || [], needed = depIn[id] || [];
    if (needs.length) { h('h3', null, I.depends, panel); var l1 = h('div', 'jp-list', null, panel); needs.forEach(function (k) { goalBtn(l1, k); }); if (needs.some(function (k) { return BAD[G[k].status]; })) h('em', 'jp-warn', I.blocked + ' «' + G[needs.filter(function (k) { return BAD[G[k].status]; })[0]].title + '»', panel); }
    if (needed.length) { h('h3', null, I.needed, panel); var l2 = h('div', 'jp-list', null, panel); needed.forEach(function (k) { goalBtn(l2, k); }); }
    if (g.parent && G[g.parent]) { h('h3', null, I.serves, panel); goalBtn(h('div', 'jp-list', null, panel), g.parent); }
    if (kidsG[id]) { h('h3', null, I.served, panel); var l3 = h('div', 'jp-list', null, panel); kidsG[id].forEach(function (k) { goalBtn(l3, k); }); }
    if (g.krs.length) {
      h('h3', null, I.krs + ' · ' + g.krs.length, panel); var ul = h('ul', 'jp-krs', null, panel);
      g.krs.forEach(function (k) {
        var li = h('li', null, null, ul); li.setAttribute('data-s', k.status); h('i', 'jp-dot', null, li);
        var tx = h('span', 'jp-kt', null, li); h('b', null, k.title, tx).setAttribute('dir', 'auto');
        h('small', null, k.now + ' / ' + k.target + (k.gap ? ' · ' + I.gap + ' ' + k.gap : '') + (k.levers.length ? ' · ' + I.levers + ' ' + k.levers.length : ''), tx);
        h('i', null, null, h('span', 'jp-kb', null, li)).style.width = k.progress + '%';
      });
    }
    h('a', 'btn btn-primary btn-sm', I.open_goal, panel).href = g.url;
    openPanel(); bloom(id); apply();
    if (!keepCam) flyToPoint(pos[id].x, pos[id].y, Math.max(cam.k, 1.15));
  }
  function selectUnit(id, keepCam) {
    var u = U[id], i = islandOf[id], ids = goalsOf(id), st = standing(ids); state.sel = { kind: 'unit', id: id }; state.hover = null; clearBloom();
    panel.textContent = ''; var top = h('div', 'jp-top', null, panel); stPill(top, st); closeBtn(top);
    var hd = h('div', 'jp-head', null, panel); avatar(hd, u.head, true);
    var tx = h('div', null, null, hd); h('h2', null, u.name, tx).setAttribute('dir', 'auto');
    voiceExplainBtn(panel, 'unit', id);
    if (u.head) { h('b', null, u.head.name, tx).setAttribute('dir', 'auto'); if (u.head.title) h('small', null, u.head.title, tx); } else h('small', 'is-none', I.no_head, tx);
    var nums = h('div', 'jp-nums', null, panel);
    [[ids.length, I.goals], [avg(ids) + '%', I.avg], [u.people, I.people]].forEach(function (x) { var c = h('div', null, null, nums); h('b', 'num', String(x[0]), c).setAttribute('dir', 'ltr'); h('span', null, x[1], c); });
    if (ids.length) { h('h3', null, I.goals, panel); var l = h('div', 'jp-list', null, panel); ids.forEach(function (k) { goalBtn(l, k); }); } else h('p', 'jp-empty', I.no_goals, panel);
    var subs = u.kids.filter(function (k) { return U[k]; });
    if (subs.length) { h('h3', null, I.unit, panel); var l2 = h('div', 'jp-list', null, panel); subs.forEach(function (k) { var b = h('button', 'jp-item', null, l2); b.type = 'button'; h('i', 'jp-dot', null, b); h('span', null, U[k].name, b); b.addEventListener('click', function () { selectUnit(k); }); }); }
    h('a', 'btn btn-primary btn-sm', I.open_unit, panel).href = u.url;
    openPanel(); apply();
    if (!keepCam && i) flyToRect(i.x - i.R, i.y - i.R, i.x + i.R, i.y + i.R);
  }
  function selectOrg() {
    state.sel = { kind: 'org' }; state.hover = null; clearBloom(); panel.textContent = '';
    var top = h('div', 'jp-top', null, panel); h('span', 'jp-st', I.origin, top); closeBtn(top);
    var hd = h('div', 'jp-head', null, panel); var a = h('span', 'jp-av jp-av--big', D.org.logo ? '' : D.org.initials, hd);
    if (D.org.logo) { var im = h('img', null, null, a); im.src = D.org.logo; im.alt = ''; }
    var tx = h('div', null, null, hd); h('h2', null, D.org.name, tx).setAttribute('dir', 'auto'); if (D.cycle) h('small', null, I.cycle + ': ' + D.cycle, tx);
    voiceExplainBtn(panel, 'org', 'org');
    if (D.vision.text) { h('h3', null, I.vision, panel); h('p', 'jp-text', D.vision.text, panel).setAttribute('dir', 'auto'); }
    if (D.vision.mission) { h('h3', null, I.mission, panel); h('p', 'jp-text', D.vision.mission, panel).setAttribute('dir', 'auto'); }
    var counts = {}; D.goals.forEach(function (g) { counts[g.status] = (counts[g.status] || 0) + 1; });
    h('h3', null, I.goals + ' · ' + D.goals.length, panel); var cl = h('div', 'jp-counts', null, panel);
    Object.keys(I.status).forEach(function (s) { if (counts[s]) { var c = h('span', null, null, cl); c.setAttribute('data-s', s); h('i', 'jp-dot', null, c); h('b', 'num', String(counts[s]), c); h('em', null, I.status[s], c); } });
    if (capGoals.length) { h('h3', null, I.org_goals, panel); var l = h('div', 'jp-list', null, panel); capGoals.forEach(function (k) { goalBtn(l, k); }); }
    openPanel(); apply(); flyToRect(-cap.R, -cap.R, cap.R, cap.R);
  }
  function deselect() { state.sel = null; panel.hidden = true; root.classList.remove('has-panel'); clearBloom(); apply(); }

  function clearBloom() { while (nodes.bloom.firstChild) nodes.bloom.removeChild(nodes.bloom.firstChild); }
  function bloom(id) {                                     // the key results of the selected goal, fanned out around it
    clearBloom();
    var g = G[id], p = pos[id], n = g.krs.length; if (!n) return;
    var grp = el('g', { class: 'jx-gs' }, el('g', { transform: 'translate(' + f1(p.x) + ' ' + f1(p.y) + ')', class: 'jx-bl' }, nodes.bloom)), R = 96 + Math.max(0, n - 6) * 6;
    g.krs.forEach(function (k, i) {
      var a = -Math.PI / 2 + (i + 0.5) * 2 * Math.PI / n, x = R * Math.cos(a), y = R * Math.sin(a);
      var kg = el('g', { class: 'jx-kr', 'data-s': k.status, style: '--j:' + i }, grp);
      el('line', { x1: 0, y1: 0, x2: f1(x), y2: f1(y), class: 'jx-krline' }, kg);
      var c = el('g', { transform: 'translate(' + f1(x) + ' ' + f1(y) + ')' }, kg);
      el('circle', { r: 17, class: 'jx-krbase' }, c); el('circle', { r: 12, class: 'jx-krtrack' }, c);
      if (k.progress > 0) el('circle', { r: 12, class: 'jx-krarc', transform: 'rotate(-90)', pathLength: 100, 'stroke-dasharray': k.progress + ' ' + (100 - k.progress + 0.01) }, c);
      el('title', null, c, k.title + ' — ' + k.progress + '%');
      var right = Math.cos(a) >= 0 ? 1 : -1, tx = el('text', { x: right * 25, y: 4, class: 'jx-krtx', 'text-anchor': (right > 0) === !RTL ? 'start' : 'end' }, c);
      tx.textContent = clip(k.title, 22);
    });
  }

  // ---------- camera ----------
  var cam = { x: 0, y: 0, k: 1 }, fitK = 0.5, tween = null, minK = 0.1, maxK = 3.4;
  function size() { return { w: stage.clientWidth, h: stage.clientHeight }; }
  function freeCenter() {                                  // fit the map into the unobstructed side of the canvas
    var s = size(), hasPanel = root.classList.contains('has-panel') && s.w > 760;
    var hud = root.querySelector('.jx__hud');
    var occupied = hasPanel ? panel.offsetWidth + 28 : (s.w > 900 && hud ? hud.offsetWidth + 34 : 0);
    occupied = Math.min(occupied, s.w * 0.38);
    var freeW = Math.max(320, s.w - occupied);
    var cx = RTL ? freeW / 2 : (s.w + occupied) / 2;
    var topOffset = !hasPanel && s.w > 900 && hud ? Math.min(48, hud.offsetHeight * 0.18) : 0;
    return { cx: cx, cy: s.h / 2 + topOffset - 18, w: freeW, h: s.h - 104 };
  }
  var lastZ = '', mini = null;
  function applyCam() {
    world.setAttribute('transform', 'translate(' + f1(cam.x) + ' ' + f1(cam.y) + ') scale(' + cam.k.toFixed(4) + ')');
    root.style.setProperty('--lab', Math.max(1, Math.min(2.8, 0.95 / cam.k)).toFixed(2));
    root.style.setProperty('--gs', Math.max(1.12, Math.min(2.1, 0.8 / cam.k)).toFixed(2));
    root.style.setProperty('--hs', Math.max(1, Math.min(1.7, 0.7 / cam.k)).toFixed(2));
    var z = cam.k < 0.42 ? 'z-far' : cam.k < 0.95 ? 'z-mid' : 'z-near';
    if (z !== lastZ) { root.classList.remove('z-far', 'z-mid', 'z-near'); root.classList.add(z); lastZ = z; }
    var sz = 34 * cam.k; while (sz < 22) sz *= 2; while (sz > 60) sz /= 2;
    stage.style.backgroundSize = sz + 'px ' + sz + 'px'; stage.style.backgroundPosition = f1(cam.x) + 'px ' + f1(cam.y) + 'px';
    if (mini) mini.update();
  }
  function fitCam(x1, y1, x2, y2, pad) {
    var f = freeCenter(), k = Math.min((f.w - 2 * pad) / (x2 - x1), (f.h - 2 * pad) / (y2 - y1));
    k = Math.max(minK, Math.min(maxK, k));
    return { k: k, x: f.cx - (x1 + x2) / 2 * k, y: f.cy - (y1 + y2) / 2 * k };
  }
  function go(target, ms) {
    if (tween) cancelAnimationFrame(tween);
    if (calm || !ms) { cam = target; applyCam(); return; }
    var from = { x: cam.x, y: cam.y, k: cam.k }, t0 = performance.now();
    (function step(now) {
      var t = Math.min(1, (now - t0) / ms), e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      var k = from.k * Math.pow(target.k / from.k, e);
      cam = { k: k, x: from.x + (target.x - from.x) * e, y: from.y + (target.y - from.y) * e }; applyCam();
      tween = t < 1 ? requestAnimationFrame(step) : null;
    })(performance.now());
  }
  function flyToRect(x1, y1, x2, y2) { go(fitCam(x1, y1, x2, y2, 90), 750); }
  function flyToPoint(x, y, k) { var f = freeCenter(); k = Math.min(maxK, k); go({ k: k, x: f.cx - x * k, y: f.cy - y * k }, 650); }
  function fitAll(ms) { var b = bounds, c = fitCam(b.x1, b.y1, b.x2, b.y2, 40); fitK = c.k; minK = Math.max(0.05, c.k * 0.5); go(c, ms == null ? 800 : ms); }
  function zoomAt(cx, cy, f, ms) {
    var k = Math.max(minK, Math.min(maxK, cam.k * f)), r = k / cam.k;
    go({ k: k, x: cx - (cx - cam.x) * r, y: cy - (cy - cam.y) * r }, ms || 0);
  }

  // ---------- input ----------
  var drag = { moved: false }, ptrs = {}, start = null, pinch0 = null;
  function rectOf() { return stage.getBoundingClientRect(); }
  stage.addEventListener('pointerdown', function (e) {
    if (e.button && e.pointerType === 'mouse') return;
    if (tween) { cancelAnimationFrame(tween); tween = null; }
    ptrs[e.pointerId] = { x: e.clientX, y: e.clientY };
    var ids = Object.keys(ptrs);
    if (ids.length === 1) { start = { x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y }; drag.moved = false; }
    else if (ids.length === 2) { var a = ptrs[ids[0]], b = ptrs[ids[1]]; pinch0 = { d: Math.hypot(a.x - b.x, a.y - b.y), k: cam.k, mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2, cx: cam.x, cy: cam.y }; drag.moved = true; }
  });
  window.addEventListener('pointermove', function (e) {
    if (!ptrs[e.pointerId]) return;
    ptrs[e.pointerId] = { x: e.clientX, y: e.clientY };
    var ids = Object.keys(ptrs);
    if (ids.length >= 2 && pinch0) {
      var a = ptrs[ids[0]], b = ptrs[ids[1]], d = Math.hypot(a.x - b.x, a.y - b.y), r0 = rectOf();
      var k = Math.max(minK, Math.min(maxK, pinch0.k * d / (pinch0.d || 1))), s = k / pinch0.k, mx = (a.x + b.x) / 2 - r0.left, my = (a.y + b.y) / 2 - r0.top, ox = pinch0.mx - r0.left, oy = pinch0.my - r0.top;
      cam = { k: k, x: mx - (ox - pinch0.cx) * s, y: my - (oy - pinch0.cy) * s }; applyCam();
    } else if (start) {
      var dx = e.clientX - start.x, dy = e.clientY - start.y;
      if (!drag.moved && Math.hypot(dx, dy) > 5) { drag.moved = true; stage.classList.add('is-grab'); }
      if (drag.moved) { cam = { k: cam.k, x: start.cx + dx, y: start.cy + dy }; applyCam(); }
    }
  });
  function up(e) {
    if (!ptrs[e.pointerId]) return;
    delete ptrs[e.pointerId]; pinch0 = null; stage.classList.remove('is-grab');
    var ids = Object.keys(ptrs); if (ids.length === 1) { var p = ptrs[ids[0]]; start = { x: p.x, y: p.y, cx: cam.x, cy: cam.y }; } else start = null;
    setTimeout(function () { if (!Object.keys(ptrs).length) drag.moved = false; }, 0);
  }
  window.addEventListener('pointerup', up); window.addEventListener('pointercancel', up);
  stage.addEventListener('wheel', function (e) {
    e.preventDefault(); var r0 = rectOf(), dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
    zoomAt(e.clientX - r0.left, e.clientY - r0.top, Math.exp(-dy * (e.ctrlKey ? 0.012 : 0.0016)), 0);
  }, { passive: false });
  stage.addEventListener('dblclick', function (e) { if (e.target.closest('.jx-node, .jx-land')) return; var r0 = rectOf(); zoomAt(e.clientX - r0.left, e.clientY - r0.top, 1.7, 260); });
  stage.addEventListener('click', function (e) { if (!drag.moved && !e.target.closest('.jx-node, .jx-land')) { if (state.sel) deselect(); } });
  stage.addEventListener('keydown', function (e) {
    var s = size(), step = 90, c = { cx: s.w / 2, cy: s.h / 2 };
    if (e.key === '+' || e.key === '=') zoomAt(c.cx, c.cy, 1.3, 220); else if (e.key === '-' || e.key === '_') zoomAt(c.cx, c.cy, 1 / 1.3, 220);
    else if (e.key === '0') fitAll(600); else if (e.key === 'Escape') deselect();
    else if (e.target === stage && /^Arrow/.test(e.key)) { e.preventDefault(); go({ k: cam.k, x: cam.x + (e.key === 'ArrowLeft' ? step : e.key === 'ArrowRight' ? -step : 0), y: cam.y + (e.key === 'ArrowUp' ? step : e.key === 'ArrowDown' ? -step : 0) }, 160); }
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && state.sel && document.activeElement !== stage) deselect(); });

  // ---------- controls ----------
  Array.prototype.forEach.call(root.querySelectorAll('[data-zoom]'), function (b) {
    b.addEventListener('click', function () {
      var s = size(), a = b.getAttribute('data-zoom'), f = freeCenter();
      if (a === 'in') zoomAt(f.cx, s.h / 2, 1.5, 260); else if (a === 'out') zoomAt(f.cx, s.h / 2, 1 / 1.5, 260);
      else if (a === 'fit') { if (state.sel) deselect(); fitAll(800); }
      else if (a === 'full') { var d = document; if (d.fullscreenElement) d.exitFullscreen(); else if (root.requestFullscreen) root.requestFullscreen(); }
    });
  });
  document.addEventListener('fullscreenchange', function () { root.classList.toggle('is-full', document.fullscreenElement === root); setTimeout(function () { if (!state.sel) fitAll(400); }, 120); });
  Array.prototype.forEach.call(root.querySelectorAll('[data-layer]'), function (b) {
    b.addEventListener('click', function () { var on = b.getAttribute('aria-pressed') !== 'true'; b.setAttribute('aria-pressed', on ? 'true' : 'false'); state[b.getAttribute('data-layer')] = on; apply(); });
  });
  function buildChips() {
    var all = h('button', 'jx-chip', I.all, chipsEl); all.type = 'button'; all.addEventListener('click', function () { if (state.sel) deselect(); fitAll(800); });
    var at = h('button', 'jx-chip jx-chip--attn', null, chipsEl); at.type = 'button'; at.setAttribute('aria-pressed', 'false'); at.disabled = !attention.length;
    h('i', 'jp-dot', null, at).setAttribute('data-s', 'at_risk'); h('span', null, I.attention, at); h('b', 'num', String(attention.length), at);
    at.addEventListener('click', function () { state.attn = !state.attn; at.setAttribute('aria-pressed', state.attn ? 'true' : 'false'); apply(); });
    islands.forEach(function (i) {
      var b = h('button', 'jx-chip', null, chipsEl); b.type = 'button'; b.setAttribute('data-u', i.u.id); avatar(b, i.u.head); h('span', null, i.u.name, b);
      b.addEventListener('click', function () { selectUnit(i.u.id); });
    });
  }
  function buildMini() {
    var W = 190, H = 124, b = bounds, pad = 60, bw = b.x2 - b.x1 + 2 * pad, bh = b.y2 - b.y1 + 2 * pad, s = Math.min(W / bw, H / bh), ox = (W - bw * s) / 2 - (b.x1 - pad) * s, oy = (H - bh * s) / 2 - (b.y1 - pad) * s;
    var m = el('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'jx-mini' }, miniEl);
    el('circle', { cx: f1(ox), cy: f1(oy), r: f1(cap.R * s), class: 'mm-cap' }, m);
    islands.forEach(function (i) { el('circle', { cx: f1(ox + i.x * s), cy: f1(oy + i.y * s), r: f1(i.R * s), class: 'mm-isl' }, m); });
    D.goals.forEach(function (g) { var p = pos[g.id]; if (p) el('circle', { cx: f1(ox + p.x * s), cy: f1(oy + p.y * s), r: 1.8, class: 'mm-g', 'data-s': g.status }, m); });
    var vp = el('rect', { class: 'mm-vp', rx: 3 }, m);
    function toWorld(ev) { var r = m.getBoundingClientRect(), mx = (ev.clientX - r.left) / r.width * W, my = (ev.clientY - r.top) / r.height * H; return { x: (mx - ox) / s, y: (my - oy) / s }; }
    var down = false;
    m.addEventListener('pointerdown', function (ev) { down = true; m.setPointerCapture(ev.pointerId); var w = toWorld(ev); var f = freeCenter(); go({ k: cam.k, x: f.cx - w.x * cam.k, y: f.cy - w.y * cam.k }, 300); });
    m.addEventListener('pointermove', function (ev) { if (!down) return; var w = toWorld(ev), f = freeCenter(); go({ k: cam.k, x: f.cx - w.x * cam.k, y: f.cy - w.y * cam.k }, 0); });
    m.addEventListener('pointerup', function () { down = false; });
    mini = { update: function () {
      var sz = size(), x1 = (0 - cam.x) / cam.k, y1 = (0 - cam.y) / cam.k, x2 = (sz.w - cam.x) / cam.k, y2 = (sz.h - cam.y) / cam.k;
      vp.setAttribute('x', f1(ox + x1 * s)); vp.setAttribute('y', f1(oy + y1 * s)); vp.setAttribute('width', f1((x2 - x1) * s)); vp.setAttribute('height', f1((y2 - y1) * s));
    } };
  }
  var ex = root.querySelector('[data-export]');
  if (ex) ex.addEventListener('click', function () {
    var copy = svg.cloneNode(true), css = '', cs = getComputedStyle(document.documentElement), b = bounds, pad = 70;
    copy.querySelector('.jx-world').removeAttribute('transform');
    Array.prototype.forEach.call(copy.querySelectorAll('.jx-bloom *'), function (n) { n.remove(); });
    copy.setAttribute('viewBox', [b.x1 - pad, b.y1 - pad, b.x2 - b.x1 + 2 * pad, b.y2 - b.y1 + 2 * pad].map(f1).join(' ')); copy.setAttribute('width', 1600); copy.removeAttribute('class'); copy.setAttribute('class', 'jx-svg');
    Array.prototype.forEach.call(document.styleSheets, function (ss) {
      var rules; try { rules = ss.cssRules; } catch (err) { return; }
      Array.prototype.forEach.call(rules || [], function (r) { if (r.selectorText && r.selectorText.indexOf('jx-svg') > -1) css += r.cssText + '\n'; });
    });
    css = css.replace(/var\((--[\w-]+)\)/g, function (m, n) { return cs.getPropertyValue(n).trim() || m; }) + '\n.jx-svg{background:#f3f5ff}.jx-roadline,.jx-depline,.jx-ghalo,.jx-ohalo,.jx-caphalo{animation:none}';
    el('style', null, copy, css); copy.setAttribute('xmlns', NS);
    var a = document.createElement('a'), blob = new Blob(['<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(copy)], { type: 'image/svg+xml' });
    a.href = URL.createObjectURL(blob); a.download = (root.getAttribute('data-slug') || 'org') + '-map.svg'; document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(a.href); }, 1500);
  });
  if (window.ResizeObserver) new ResizeObserver(function () { if (!svg) return; if (!state.sel) { var c = fitCam(bounds.x1, bounds.y1, bounds.x2, bounds.y2, 40); fitK = c.k; minK = Math.max(0.05, c.k * 0.5); } applyCam(); }).observe(stage);

  // ---------- start ----------
  function sizeRoot() {                                    // open space: from just under the page header to the bottom of the screen
    if (document.fullscreenElement === root) { root.style.height = ''; return; }
    var top = root.getBoundingClientRect().top + window.scrollY - window.scrollY, h = window.innerHeight - Math.max(0, root.getBoundingClientRect().top) - 6;
    root.style.height = Math.max(560, h) + 'px';
  }
  sizeRoot(); window.addEventListener('resize', sizeRoot);
  layout(); render(); buildChips(); buildMini();
  window.PlanWiseJourney = {
    focus: function (kind, id) { state.voiceFocus = { kind: String(kind || 'org'), id: String(id || 'org') }; apply(); },
    clearFocus: function () { state.voiceFocus = null; apply(); }
  };
  root.classList.add('is-intro');
  (function begin() {
    var c = fitCam(bounds.x1, bounds.y1, bounds.x2, bounds.y2, 40); fitK = c.k; minK = Math.max(0.05, c.k * 0.5);
    cam = { k: c.k * 0.72, x: c.x + (size().w / 2 - c.x) * 0.28, y: c.y + (size().h / 2 - c.y) * 0.28 }; applyCam();
    go(c, 1500);
    setTimeout(function () { root.classList.remove('is-intro'); }, 2600);
  })();
})();
