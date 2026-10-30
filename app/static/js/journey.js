/* The journey (رحلة المؤسسة): one living picture of the whole organization.
   The identity is the source, the vision is the horizon, every goal is a strand that flows between them as far as it has really got
   (solid) and onward (dotted). A bright line marks today: the strand's head behind it is late (hatched gap), ahead of it is leading.
   Two real kinds of dependency are drawn between strands: a goal that serves another goal, and goals measured by the same data.
   There is no timeline to play: the picture is always whole and always moving (flow, pulses); pointing at a goal reveals what it touches.
   Data: <script data-jr-data> (orgmap/payload.py). All text is inserted with textContent. */
(function () {
  'use strict';
  var root = document.querySelector('[data-journey]');
  if (!root) return;
  var D;
  try { D = JSON.parse(root.querySelector('[data-jr-data]').textContent); } catch (e) { return; }
  var I = D.i18n, NS = 'http://www.w3.org/2000/svg';
  var RTL = (document.documentElement.getAttribute('dir') || 'ltr') === 'rtl';
  var stage = root.querySelector('[data-stage]'), card = root.querySelector('[data-card]');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- geometry: logical u runs from the identity to the vision; X() mirrors it for right-to-left reading ----
  var W = 1200, OX = 80, VX = W - 80, U0 = 215, U1 = W - 215, TOP = 100;
  var FWD = RTL ? -1 : 1;
  function X(u) { return RTL ? W - u : u; }
  function UP(p) { return U0 + (U1 - U0) * Math.max(0, Math.min(100, p)) / 100; }
  function f1(n) { return Math.round(n * 10) / 10; }

  var state = { order: 'plan', links: true, gaps: true, pinned: null, focus: null };
  var byId = {}, kids = {}, shareMap = {};
  D.goals.forEach(function (g) { byId[g.id] = g; if (g.parent) { (kids[g.parent] = kids[g.parent] || []).push(g.id); } });
  D.shares.forEach(function (s) { s.users.forEach(function (a) { s.users.forEach(function (b) { if (a.goal !== b.goal) { (shareMap[a.goal] = shareMap[a.goal] || {})[b.goal] = s.label; } }); }); });

  function el(name, attrs, parent, text) {
    var n = document.createElementNS(NS, name);
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    if (parent) parent.appendChild(n);
    return n;
  }
  function h(tag, cls, text, parent) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; if (parent) parent.appendChild(n); return n; }
  function clip(s, n) { s = String(s || ''); return s.length > n ? s.slice(0, n - 1).trim() + '…' : s; }

  // ---- layout ----
  var svg, L = {};                                   // L[goalId] = {rank, yi, wig(u), headU, expU, <krId>: {x,y,u}}
  function layout(order) {
    var n = D.goals.length, LS = n <= 4 ? 84 : n <= 8 ? 68 : 58, H = TOP + n * LS + 78, yc = TOP + n * LS / 2;
    var list = D.goals.slice();
    if (order === 'late') list.sort(function (a, b) { return (b.expected - b.progress) - (a.expected - a.progress); });
    L = {};
    list.forEach(function (g, rank) {
      var yi = TOP + LS * (rank + 0.5), A = Math.min(5, LS / 11), ph = rank * 1.9 + 0.7;
      L[g.id] = { rank: rank, yi: yi, wig: (function (yi0, A0, ph0) { return function (u) { return yi0 + A0 * Math.sin(u / 92 + ph0); }; })(yi, A, ph), headU: UP(g.progress), expU: UP(g.expected) };
    });
    return { n: n, LS: LS, H: H, yc: yc, list: list };
  }
  function body(id, u1, u2) {                         // polyline along a strand's body between two logical positions
    var l = L[id], d = '', step = 8, u;
    for (u = u1; u < u2; u += step) d += (d ? 'L' : 'M') + f1(X(u)) + ' ' + f1(l.wig(u));
    return d + (d ? 'L' : 'M') + f1(X(u2)) + ' ' + f1(l.wig(u2));
  }
  function fanOut(id, yc) {
    var l = L[id], a = OX + 44, b = U0, k = (b - a) * 0.55;
    return 'M' + f1(X(a)) + ' ' + f1(yc) + 'C' + f1(X(a + k)) + ' ' + f1(yc) + ' ' + f1(X(b - k)) + ' ' + f1(l.wig(U0)) + ' ' + f1(X(b)) + ' ' + f1(l.wig(U0));
  }
  function fanIn(id, yc) {
    var l = L[id], a = U1, b = VX - 40, k = (b - a) * 0.55;
    return 'M' + f1(X(a)) + ' ' + f1(l.wig(U1)) + 'C' + f1(X(a + k)) + ' ' + f1(l.wig(U1)) + ' ' + f1(X(b - k)) + ' ' + f1(yc) + ' ' + f1(X(b)) + ' ' + f1(yc);
  }
  function seg(d) { return d.replace(/^M/, 'L'); }

  // ---- drawing ----
  function render(first) {
    var geo = layout(state.order), yc = geo.yc;
    Array.prototype.forEach.call(stage.querySelectorAll('.jr-svg'), function (n) { n.remove(); });
    svg = el('svg', { viewBox: '0 0 ' + W + ' ' + geo.H, class: 'jr-svg', role: 'group', 'aria-label': D.org.name });
    stage.insertBefore(svg, card);
    defs();

    var gBg = el('g', { class: 'jr-bg' }, svg);
    ruler(gBg, geo);
    var gToday = el('g', { class: 'jr-today' }, svg);
    var gLanes = el('g', { class: 'jr-lanes' }, svg);
    var gLinks = el('g', { class: 'jr-links' }, svg);
    var gNodes = el('g', { class: 'jr-nodes' }, svg);

    geo.list.forEach(function (g, i) { lane(gLanes, g, yc, i, first); });
    today(gToday, geo);
    links(gLinks);
    origin(gNodes, yc);
    vision(gNodes, yc);

    if (first && !reduce) {                           // drawn in once; afterwards the picture only lives (flow, pulses)
      root.classList.add('is-intro');
      setTimeout(function () { root.classList.remove('is-intro'); }, 2800);
    }
    apply();
  }

  function defs() {
    var d = el('defs', null, svg);
    var p = el('pattern', { id: 'jr-hatch', width: 7, height: 7, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, d);
    el('rect', { width: 7, height: 7, class: 'jr-hatch-bg' }, p);
    el('rect', { width: 3, height: 7, class: 'jr-hatch-bar' }, p);
    var m = el('marker', { id: 'jr-arrow', viewBox: '0 0 10 10', refX: 8, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' }, d);
    el('path', { d: 'M1 1.5L8.5 5L1 8.5Z', class: 'jr-arrow' }, m);
  }

  function ruler(g, geo) {
    var y = 62;
    el('line', { x1: X(U0), x2: X(U1), y1: y, y2: y, class: 'jr-rule' }, g);
    for (var p = 0; p <= 100; p += 10) {
      var big = p % 25 === 0;
      el('line', { x1: X(UP(p)), x2: X(UP(p)), y1: y - (big ? 7 : 4), y2: y, class: 'jr-tick' }, g);
      if (big) el('text', { x: X(UP(p)), y: y - 13, class: 'jr-tl', 'text-anchor': 'middle', style: 'direction:ltr' }, g, p + '%');
    }
    el('text', { x: X(U0), y: 22, class: 'jr-axis', 'text-anchor': 'start' }, g, I.axis);
    geo.list.forEach(function (g2, i) { var yy = TOP + geo.LS * (i + 0.5); el('line', { x1: X(U0), x2: X(U1), y1: yy, y2: yy, class: 'jr-rail' }, g); });
  }

  function today(g, geo) {
    // each goal knows where it should be today (its own cycle); goals of the same cycle line up in one column
    var groups = {};
    D.goals.forEach(function (gl) { var k = Math.round(gl.expected / 2) * 2; groups[k] = (groups[k] || 0) + 1; });
    var keys = Object.keys(groups).map(Number).sort(function (a, b) { return groups[b] - groups[a]; });
    if (keys.length > 3) return;                                                // too many different todays: the per-goal ticks say it
    var y1 = 72, y2 = geo.H - 40;
    keys.forEach(function (k, i) {
      var x = X(UP(k));
      el('line', { x1: x, x2: x, y1: y1, y2: y2, class: 'jr-todayline' }, g);
      el('path', { d: 'M' + (x - 6) + ' ' + (y1 - 4) + 'L' + (x + 6) + ' ' + (y1 - 4) + 'L' + x + ' ' + (y1 + 6) + 'Z', class: 'jr-todaytri' }, g);
      var label = I.today + ' \u2066' + k + '%\u2069', w = 28 + (I.today.length + String(k).length + 2) * 6.6;
      var pill = el('g', { class: 'jr-todaypill', transform: 'translate(' + x + ' ' + (y2 + 4 + (i % 2) * 0) + ')' }, g);
      el('rect', { x: -w / 2, y: 0, width: w, height: 24, rx: 12, class: 'jr-pillbg' }, pill);
      el('text', { x: 0, y: 16, 'text-anchor': 'middle', class: 'jr-pilltx' }, pill, label);
    });
  }

  function lane(g, goal, yc, idx, first) {
    var l = L[goal.id], s = goal.status, p = goal.progress, e = goal.expected, hu = l.headU, eu = l.expU;
    var grp = el('g', { class: 'jr-lane', 'data-id': goal.id, 'data-s': s, tabindex: 0, role: 'button', style: '--d:' + (idx * 90) + 'ms',
                        'aria-label': goal.title + ' — ' + p + '% — ' + (I.status[s] || s) }, g);
    var fo = fanOut(goal.id, yc), bs = p > 0 ? body(goal.id, U0, hu) : '', ba = body(goal.id, hu, U1), fi = fanIn(goal.id, yc);
    var solid = fo + (bs ? seg(bs) : '');

    el('path', { d: body(goal.id, U0, U1), class: 'jr-hit' }, grp);                              // wide invisible target
    if (p > 0) el('path', { d: solid, class: 'jr-glow' }, grp);
    el('path', { d: fo, class: 'jr-pre' }, grp);
    el('path', { d: ba + seg(fi), class: 'jr-ahead' }, grp);
    var sp = el('path', { d: solid, class: 'jr-solid' }, grp);
    if (p > 0) el('path', { d: solid, class: 'jr-flow' }, grp);
    if (p > 0 && !reduce) {                                                                   // droplets travelling from the source to the head
      var n = s === 'off_track' ? 1 : 2;
      for (var i = 0; i < n; i++) {
        el('circle', { r: 3.4, class: 'jr-dot', style: 'offset-path:path("' + solid + '");--dur:' + (5.5 + idx * 0.37 + i * 1.3).toFixed(2) + 's;--dl:' + (-(i * 2.6 + idx * 0.8)).toFixed(2) + 's' }, grp);
      }
    }
    // the gap (behind the day's line) or the lead
    var yH = l.wig(hu), yE = l.wig(eu), d = p - e;
    if (d !== 0) {
      el('rect', { x: Math.min(X(hu), X(eu)), y: f1((yH + yE) / 2 - 9), width: Math.abs(X(eu) - X(hu)), height: 18, rx: 9, class: d < 0 ? 'jr-gap' : 'jr-lead' }, grp);
      if (d < 0 && -d >= 6) el('text', { x: (X(hu) + X(eu)) / 2, y: f1((yH + yE) / 2 - 14), 'text-anchor': 'middle', class: 'jr-gaptx' }, grp, '−' + (-d));
    }
    el('rect', { x: f1(X(eu) - 3), y: f1(yE - 12), width: 6, height: 24, rx: 3, class: 'jr-exp' }, grp);

    // key results: beads at their own progress
    goal.krs.forEach(function (k) {
      var u = UP(k.progress), b = el('circle', { cx: f1(X(u)), cy: f1(l.wig(u)), r: 5.4, class: 'jr-bead', 'data-s': k.status }, grp);
      el('title', null, b, k.title + ' — ' + k.progress + '%');
      l[k.id] = { x: X(u), y: l.wig(u), u: u };
    });

    // head
    var hx = X(hu), head = el('g', { class: 'jr-headg', transform: 'translate(' + f1(hx) + ' ' + f1(yH) + ')' }, grp);
    if (s !== 'not_started' && s !== 'completed') el('circle', { r: 11, class: 'jr-pulse' }, head);
    if (s === 'at_risk') el('circle', { r: 17, class: 'jr-ring' }, head);
    el('circle', { r: 11, class: 'jr-head' }, head);
    if (s === 'completed') el('path', { d: 'M-4.5 0.5L-1.3 3.7L5 -3.2', class: 'jr-mark' }, head);
    else if (s === 'off_track') { el('path', { d: 'M0 -5.5V1', class: 'jr-mark' }, head); el('circle', { cy: 5, r: 1.3, class: 'jr-markdot' }, head); }
    else if (s === 'on_track') el('circle', { r: 3.6, class: 'jr-markdot' }, head);
    el('text', { x: 0, y: 29, class: 'jr-pct', 'text-anchor': 'middle', style: 'direction:ltr' }, head, p + '%');

    // the title above the strand's start
    el('text', { x: X(U0 + 4), y: f1(l.wig(U0 + 4) - 17), class: 'jr-title', 'text-anchor': 'start' }, grp, clip(goal.title, 52));

    if (first && !reduce) { try { sp.style.setProperty('--len', Math.ceil(sp.getTotalLength())); } catch (err) { /* not laid out */ } }
    bind(grp, goal);
  }

  function links(g) {
    // alignment: a goal that serves another one (from its head to the parent's strand at the same position)
    D.goals.forEach(function (c) {
      if (!c.parent || !L[c.parent]) return;
      var lc = L[c.id], lp = L[c.parent], u = Math.max(U0 + 18, Math.min(U1 - 18, lc.headU));
      var x = X(u), ya = lc.wig(u), yb = lp.wig(u), bulge = FWD * (34 + Math.min(40, Math.abs(ya - yb) * 0.16));
      var path = el('path', { d: 'M' + f1(x) + ' ' + f1(ya) + 'C' + f1(x + bulge) + ' ' + f1(ya) + ' ' + f1(x + bulge) + ' ' + f1(yb) + ' ' + f1(x) + ' ' + f1(yb), class: 'jr-align', 'data-a': c.id, 'data-b': c.parent, 'marker-end': 'url(#jr-arrow)' }, g);
      if (c.status === 'off_track' || c.status === 'at_risk') path.setAttribute('data-bad', '1');
    });
    // shared data: key results of different goals measured by the same series
    D.shares.forEach(function (sh) {
      var pts = sh.users.filter(function (u) { return L[u.goal] && L[u.goal][u.kr]; }).map(function (u) { return { goal: u.goal, p: L[u.goal][u.kr], rank: L[u.goal].rank }; });
      pts.sort(function (a, b) { return a.rank - b.rank; });
      for (var i = 0; i < pts.length - 1; i++) {
        var a = pts[i], b = pts[i + 1];
        if (a.goal === b.goal) continue;
        var bulge = -FWD * (26 + (i % 3) * 10), mx = (a.p.x + b.p.x) / 2 + bulge * 0.75, my = (a.p.y + b.p.y) / 2;
        el('path', { d: 'M' + f1(a.p.x) + ' ' + f1(a.p.y) + 'C' + f1(a.p.x + bulge) + ' ' + f1(a.p.y) + ' ' + f1(b.p.x + bulge) + ' ' + f1(b.p.y) + ' ' + f1(b.p.x) + ' ' + f1(b.p.y), class: 'jr-share', 'data-a': a.goal, 'data-b': b.goal }, g);
        var gl = el('g', { class: 'jr-shareglyph', transform: 'translate(' + f1(mx) + ' ' + f1(my) + ')', 'data-a': a.goal, 'data-b': b.goal }, g);
        el('circle', { r: 8, class: 'jr-sgbg' }, gl);
        el('path', { d: 'M-3.6 -2.2C-3.6 -4 3.6 -4 3.6 -2.2S-3.6 0 -3.6 -2.2M-3.6 -2.2V2.2C-3.6 4 3.6 4 3.6 2.2V-2.2', class: 'jr-sgmark' }, gl);
        el('title', null, gl, sh.label);
      }
    });
  }

  function origin(g, yc) {
    var o = el('g', { class: 'jr-origin', transform: 'translate(' + X(OX) + ' ' + yc + ')', tabindex: 0, role: 'button', 'aria-label': D.org.name }, g);
    el('circle', { r: 64, class: 'jr-ohalo' }, o);
    el('circle', { r: 42, class: 'jr-oring' }, o);
    el('circle', { r: 36, class: 'jr-obg' }, o);
    if (D.org.logo) {
      var cp = el('clipPath', { id: 'jr-oclip' }, o); el('circle', { r: 31 }, cp);
      el('image', { href: D.org.logo, x: -31, y: -31, width: 62, height: 62, 'clip-path': 'url(#jr-oclip)', preserveAspectRatio: 'xMidYMid slice' }, o);
    } else el('text', { y: 8, class: 'jr-oini', 'text-anchor': 'middle' }, o, D.org.initials);
    el('text', { y: 72, class: 'jr-oname', 'text-anchor': 'middle' }, o, clip(D.org.name, 18));
    el('text', { y: 91, class: 'jr-ocap', 'text-anchor': 'middle' }, o, I.origin);
    o.addEventListener('mouseenter', function () { if (!state.pinned) showCard({ kind: 'origin' }, false); });
    o.addEventListener('mouseleave', function () { if (!state.pinned) hideCard(); });
  }

  function vision(g, yc) {
    var v = el('g', { class: 'jr-vision', transform: 'translate(' + X(VX) + ' ' + yc + ')', tabindex: 0, role: 'button', 'aria-label': I.vision }, g);
    el('circle', { r: 92, class: 'jr-vhalo' }, v);
    [50, 68, 86].forEach(function (r, i) { el('circle', { r: r, class: 'jr-vripple', style: '--i:' + i }, v); });
    el('circle', { r: 36, class: 'jr-vcore' }, v);
    el('path', { d: 'M0 -17L5.2 -5.4L17.8 -4.3L8.3 4L11.1 16.4L0 9.9L-11.1 16.4L-8.3 4L-17.8 -4.3L-5.2 -5.4Z', class: 'jr-vstar' }, v);
    el('text', { y: 68, class: 'jr-vname', 'text-anchor': 'middle' }, v, D.vision.text ? I.vision : I.horizon);
    if (D.vision.text) {
      var words = clip(D.vision.text, 54).split(/\s+/), lines = [''], k = 0;
      words.forEach(function (w) { if ((lines[k] + ' ' + w).trim().length > 20 && lines[k]) { lines[++k] = w; } else lines[k] = (lines[k] + ' ' + w).trim(); });
      lines.slice(0, 3).forEach(function (ln, i) { el('text', { y: 87 + i * 15, class: 'jr-vtx', 'text-anchor': 'middle' }, v, ln); });
    }
    v.addEventListener('mouseenter', function () { if (!state.pinned) showCard({ kind: 'vision' }, false); });
    v.addEventListener('mouseleave', function () { if (!state.pinned) hideCard(); });
    v.addEventListener('click', function (e) { e.stopPropagation(); pin({ kind: 'vision' }); });
    v.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pin({ kind: 'vision' }); } });
  }

  // ---- relations, focus ----
  function related(id) {
    var r = {}; r[id] = 1;
    var g = byId[id];
    if (g && g.parent) r[g.parent] = 1;
    (kids[id] || []).forEach(function (k) { r[k] = 1; });
    var sh = shareMap[id] || {}; for (var k in sh) r[k] = 1;
    return r;
  }
  function apply() {
    var id = state.focus, rel = id ? related(id) : null;
    root.classList.toggle('has-focus', !!id);
    root.classList.toggle('no-links', !state.links);
    root.classList.toggle('no-gaps', !state.gaps);
    var bad = id && byId[id] && (byId[id].status === 'off_track' || byId[id].status === 'at_risk');
    Array.prototype.forEach.call(svg.querySelectorAll('.jr-lane'), function (n) {
      var i = n.getAttribute('data-id');
      n.classList.toggle('is-dim', !!id && !rel[i]);
      n.classList.toggle('is-focus', i === id);
      n.classList.toggle('is-hit', !!bad && byId[id].parent === i);
    });
    Array.prototype.forEach.call(svg.querySelectorAll('.jr-align, .jr-share, .jr-shareglyph'), function (n) {
      n.classList.toggle('is-on', !!id && (n.getAttribute('data-a') === id || n.getAttribute('data-b') === id));
    });
  }
  function setFocus(id) { state.focus = id; apply(); }

  // ---- the card ----
  function fmtDate(iso) { if (!iso) return ''; try { return new Date(iso).toLocaleDateString(document.documentElement.lang || 'ar', { day: 'numeric', month: 'long', year: 'numeric' }); } catch (e) { return iso; } }
  function placeCard(x, y) {
    var sw = stage.clientWidth, sh = stage.clientHeight, k = sw / (svg.viewBox.baseVal.width || W);
    var px = x * k, py = y * k, cw = card.offsetWidth, ch = card.offsetHeight, gap = 26;
    var left = px > sw / 2 ? px - cw - gap : px + gap;
    left = Math.max(10, Math.min(sw - cw - 10, left));
    card.style.left = left + 'px'; card.style.top = Math.max(10, Math.min(sh - ch - 10, py - 30)) + 'px';
  }
  function row(parent, label, val) { var r = h('p', 'jc-row', null, parent); h('span', null, label, r); h('b', null, val, r); return r; }
  function closeBtn(top) { var x = h('button', 'jc-x', '×', top); x.type = 'button'; x.setAttribute('aria-label', I.close); x.addEventListener('click', unpin); }
  function goalCard(g, pinned) {
    card.textContent = '';
    var top = h('div', 'jc-top', null, card);
    h('span', 'jc-st', I.status[g.status] || g.status, top).setAttribute('data-s', g.status);
    if (pinned) closeBtn(top);
    h('h4', null, g.title, card).setAttribute('dir', 'auto');
    var d = g.progress - g.expected, bar = h('div', 'jc-bar', null, card);
    h('i', null, null, bar).style.width = g.progress + '%';
    h('u', null, null, bar).style.insetInlineStart = g.expected + '%';
    var line = h('p', 'jc-line', null, card);
    h('b', 'num', g.progress + '%', line).setAttribute('dir', 'ltr');
    h('span', null, d === 0 ? I.even : (d < 0 ? I.behind : I.ahead) + ' · ' + Math.abs(d) + ' ' + I.points, line).setAttribute('data-tone', d < 0 ? 'lag' : 'lead');
    if (g.owner) row(card, I.owner, g.owner);
    if (g.end) row(card, I.ends, fmtDate(g.end));
    var p = g.parent && byId[g.parent];
    if (p) { row(card, I.serves, p.title); if (g.status === 'off_track' || g.status === 'at_risk') h('em', 'jc-warn', I.blocks + ' «' + p.title + '»', card); }
    var ch = (kids[g.id] || []).map(function (k) { return byId[k].title; });
    if (ch.length) row(card, I.served_by, ch.join('، '));
    var sh = shareMap[g.id]; if (sh) { var names = []; for (var k in sh) names.push(byId[k].title + ' (' + sh[k] + ')'); row(card, I.shares, names.join('، ')); }
    if (pinned) {
      h('h5', null, I.krs + ' · ' + g.krs.length, card);
      var ul = h('ul', 'jc-krs', null, card);
      g.krs.forEach(function (k) {
        var li = h('li', null, null, ul); li.setAttribute('data-s', k.status);
        h('span', 'jc-kd', null, li);
        var tx = h('span', 'jc-kt', null, li); h('b', null, k.title, tx).setAttribute('dir', 'auto');
        h('small', null, k.now + ' / ' + k.target + (k.gap ? ' · ' + I.gap + ' ' + k.gap : '') + (k.levers.length ? ' · ' + I.levers + ' ' + k.levers.length : ''), tx);
        h('i', null, null, h('span', 'jc-kb', null, li)).style.width = k.progress + '%';
      });
      h('a', 'btn btn-primary btn-sm', I.open, card).href = g.url;
    }
  }
  function textCard(title, lines, label, pinned) {
    card.textContent = '';
    var top = h('div', 'jc-top', null, card);
    h('span', 'jc-st', label, top);
    if (pinned) closeBtn(top);
    h('h4', null, title, card).setAttribute('dir', 'auto');
    lines.forEach(function (t) { if (t[1]) { var r = h('p', 'jc-text', null, card); h('b', null, t[0], r); h('span', null, t[1], r).setAttribute('dir', 'auto'); } });
  }
  function svgH() { return svg.viewBox.baseVal.height; }
  function showCard(what, pinned) {
    card.hidden = false; card.classList.toggle('is-pinned', !!pinned);
    var pos;
    if (what.kind === 'goal') { var g = byId[what.id], l = L[g.id]; goalCard(g, pinned); pos = [X(l.headU), l.wig(l.headU)]; }
    else if (what.kind === 'vision') { textCard(D.vision.text ? I.vision : I.horizon, [[I.vision, D.vision.text], [I.mission, D.vision.mission]], D.org.name, pinned); pos = [X(VX), svgH() / 2]; }
    else { textCard(D.org.name, [[I.origin, D.cycle]], I.origin, pinned); pos = [X(OX), svgH() / 2]; }
    placeCard(pos[0], pos[1]);
  }
  function hideCard() { card.hidden = true; }
  function pin(what) {
    if (state.pinned && state.pinned.kind === what.kind && state.pinned.id === what.id) { unpin(); return; }
    state.pinned = what; showCard(what, true);
    setFocus(what.kind === 'goal' ? what.id : null);
    root.classList.add('has-pin');
  }
  function unpin() { state.pinned = null; root.classList.remove('has-pin'); hideCard(); setFocus(null); }

  function bind(grp, goal) {
    var what = { kind: 'goal', id: goal.id };
    grp.addEventListener('mouseenter', function () { if (state.pinned) return; setFocus(goal.id); showCard(what, false); });
    grp.addEventListener('mouseleave', function () { if (state.pinned) return; setFocus(null); hideCard(); });
    grp.addEventListener('focus', function () { if (!state.pinned) { setFocus(goal.id); showCard(what, false); } });
    grp.addEventListener('blur', function () { if (!state.pinned) { setFocus(null); hideCard(); } });
    grp.addEventListener('click', function (e) { e.stopPropagation(); pin(what); });
    grp.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pin(what); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        var all = Array.prototype.slice.call(svg.querySelectorAll('.jr-lane')).sort(function (a, b) { return L[a.getAttribute('data-id')].rank - L[b.getAttribute('data-id')].rank; });
        var nx = all[all.indexOf(grp) + (e.key === 'ArrowDown' ? 1 : -1)];
        if (nx) nx.focus();
      }
    });
  }
  stage.addEventListener('click', function (e) { if (state.pinned && !e.target.closest('.jr-lane, .jr-vision, .jr__card')) unpin(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && state.pinned) unpin(); });

  // ---- controls ----
  Array.prototype.forEach.call(root.querySelectorAll('[data-layer]'), function (b) {
    b.addEventListener('click', function () {
      var on = b.getAttribute('aria-pressed') !== 'true';
      b.setAttribute('aria-pressed', on ? 'true' : 'false'); state[b.getAttribute('data-layer')] = on; apply();
    });
  });
  Array.prototype.forEach.call(root.querySelectorAll('[data-order]'), function (b) {
    b.addEventListener('click', function () {
      state.order = b.getAttribute('data-order');
      Array.prototype.forEach.call(root.querySelectorAll('[data-order]'), function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      unpin(); render(false);
    });
  });
  var ex = root.querySelector('[data-export]');
  if (ex) ex.addEventListener('click', function () {
    var copy = svg.cloneNode(true), css = '', cs = getComputedStyle(document.documentElement);
    Array.prototype.forEach.call(document.styleSheets, function (ss) {
      var rules; try { rules = ss.cssRules; } catch (e) { return; }
      Array.prototype.forEach.call(rules || [], function (r) { if (r.selectorText && r.selectorText.indexOf('jr-svg') > -1) css += r.cssText + '\n'; });
    });
    css = css.replace(/var\((--[\w-]+)\)/g, function (m, n) { return cs.getPropertyValue(n).trim() || m; }) + '\n.jr-dot,.jr-pulse,.jr-vripple,.jr-flow{display:none}';
    el('style', null, copy, css); copy.setAttribute('xmlns', NS);
    var a = document.createElement('a'), blob = new Blob(['<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(copy)], { type: 'image/svg+xml' });
    a.href = URL.createObjectURL(blob); a.download = (root.getAttribute('data-slug') || 'org') + '-journey.svg'; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1500);
  });
  window.addEventListener('resize', function () { if (state.pinned && !card.hidden) showCard(state.pinned, true); });

  render(true);
})();
