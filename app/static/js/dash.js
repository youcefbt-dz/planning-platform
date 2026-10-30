/* Dashboard: range tabs and the hover read-out on the main chart. Reads data-* written by the server; no chart maths here. */
(function () {
  function initRange(box) {
    var tabs = box.querySelector('[data-range]');
    if (!tabs) return;
    tabs.addEventListener('click', function (e) {
      var b = e.target.closest('[data-i]');
      if (!b) return;
      tabs.querySelectorAll('[data-i]').forEach(function (x) { x.setAttribute('aria-selected', x === b ? 'true' : 'false'); });
      box.querySelectorAll('.dview').forEach(function (v) { v.hidden = v.getAttribute('data-view') !== b.getAttribute('data-i'); });
    });
  }
  function initHover(wrap) {
    var pts;
    try { pts = JSON.parse(wrap.getAttribute('data-hover') || '[]'); } catch (e) { return; }
    if (!pts.length) return;
    var svg = wrap.querySelector('svg'), tip = wrap.querySelector('.dtip'), xh = svg.querySelector('.xh'), xd = svg.querySelector('.xd'), area = svg.querySelector('.hitarea');
    var W = parseFloat(wrap.getAttribute('data-w'));
    function show(clientX) {
      var r = svg.getBoundingClientRect(), x = (clientX - r.left) / r.width * W, best = 0, d = Infinity;
      for (var i = 0; i < pts.length; i++) { var dd = Math.abs(pts[i][0] - x); if (dd < d) { d = dd; best = i; } }
      var p = pts[best];
      xh.setAttribute('x1', p[0]); xh.setAttribute('x2', p[0]); xh.hidden = false;
      xd.setAttribute('cx', p[0]); xd.setAttribute('cy', p[1]); xd.hidden = false;
      tip.replaceChildren();
      var h = document.createElement('b'); h.textContent = p[2]; tip.appendChild(h);
      var v = document.createElement('span'); v.className = 'dtip__v'; v.textContent = p[3]; tip.appendChild(v);
      if (p[4]) {
        var pr = document.createElement('span'); pr.className = 'dtip__p'; pr.textContent = (wrap.getAttribute('data-prior') || '') + ' ' + p[4] + (p[5] ? '  (' + p[5] + ')' : ''); tip.appendChild(pr);
      }
      tip.hidden = false;
      var left = p[0] / W * r.width, tw = tip.offsetWidth;
      tip.style.left = Math.max(4, Math.min(r.width - tw - 4, left - tw / 2)) + 'px';
      tip.style.top = Math.max(0, p[1] / parseFloat(svg.viewBox.baseVal.height) * r.height - tip.offsetHeight - 14) + 'px';
    }
    function hide() { xh.hidden = true; xd.hidden = true; tip.hidden = true; }
    area.addEventListener('pointermove', function (e) { show(e.clientX); });
    area.addEventListener('pointerleave', hide);
    area.addEventListener('pointerdown', function (e) { show(e.clientX); });
  }
  function init() {
    document.querySelectorAll('.chartbox[data-kind="trend"]').forEach(initRange);
    document.querySelectorAll('.dchart').forEach(initHover);
  }
  /* the AI is reading: show the "thinking" card at once, the page is about to reload with the answer */
  function initThink() {
    var form = document.querySelector('form.ask'), tpl = document.getElementById('think-tpl');
    if (!form || !tpl) return;
    function show() {
      document.querySelectorAll('.answer').forEach(function (a) { a.remove(); });
      if (document.querySelector('.think')) return;
      var host = document.createElement('section'); host.className = 'answer';
      host.appendChild(tpl.content.firstElementChild.cloneNode(true));
      var after = document.querySelector('.ask__hint') || form;
      after.insertAdjacentElement('afterend', host);
      var b = form.querySelector('button[type=submit]'); if (b) b.setAttribute('aria-busy', 'true');
    }
    form.addEventListener('submit', show);
    document.addEventListener('click', function (e) { var a = e.target.closest('.ask__hint a, .answer__ask a'); if (a && !e.defaultPrevented) show(); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { init(); initThink(); }); else { init(); initThink(); }
})();
