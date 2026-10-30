/* Reality check — live verdict. An element marked [data-reality] collects its fields, asks the fragment endpoint, and puts the
   returned HTML into its target panel. Plain GET submit keeps working without this script.
   Fields: inside the element, [data-r=series|start|target|end|direction]. Fields that live elsewhere on the page are named with
   data-<field>-from="#selector"; a fixed value can be given as data-<field>="…".
   Convenience: data-start-to / data-unit-to="#selector" fill those inputs from the chosen series when they are empty. */
(function () {
  'use strict';
  var timers = new WeakMap();
  var KEYS = ['series', 'start', 'target', 'end', 'direction'];

  function valueOf(root, key) {
    var own = root.querySelector('[data-r=' + key + ']');
    if (own && own.value !== '') return own.value;
    var from = root.getAttribute('data-' + key + '-from');
    if (from) { var el = document.querySelector(from); if (el && el.value !== '') return el.value; }
    return root.getAttribute('data-' + key) || '';
  }

  function run(root, ai) {
    var target = document.querySelector(root.getAttribute('data-target'));
    var endpoint = root.getAttribute('data-endpoint');
    if (!target || !endpoint || !window.fetch) return;
    var q = new URLSearchParams();
    KEYS.forEach(function (k) { var v = valueOf(root, k); if (v !== '') q.set(k, v); });
    if (ai) q.set('ai', '1');
    var goal = root.getAttribute('data-goal'); if (goal) q.set('goal', goal);
    if (!q.get('series') || !q.get('target') || !q.get('end')) { target.innerHTML = ''; return; }
    target.classList.add('panel-loading');
    fetch(endpoint + '?' + q.toString(), { credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(r); })
      .then(function (html) { target.innerHTML = html; wire(target, root); })
      .catch(function () { /* the plain form still works */ })
      .then(function () { target.classList.remove('panel-loading'); });
  }

  function schedule(root) {
    clearTimeout(timers.get(root));
    timers.set(root, setTimeout(function () { run(root, false); }, 350));
  }

  function wire(panel, root) {
    var a = panel.querySelector('[data-explain]');
    if (a) a.addEventListener('click', function (e) { e.preventDefault(); a.setAttribute('aria-busy', 'true'); run(root, true); });
    if (window.initCharts) window.initCharts(panel);
  }

  document.querySelectorAll('[data-reality]').forEach(function (root) {
    var series = root.querySelector('[data-r=series]');
    var start = root.querySelector('[data-r=start]');
    if (series) series.addEventListener('change', function () {
      var o = series.options[series.selectedIndex];
      if (!o) return;
      if (start && o.dataset.latest && (!start.value || start.dataset.auto === '1')) { start.value = o.dataset.latest; start.dataset.auto = '1'; }
      [['data-start-to', o.dataset.latest ? String(Math.round(parseFloat(o.dataset.latest) * 100) / 100) : ''], ['data-unit-to', o.dataset.unit || '']].forEach(function (p) {
        var sel = root.getAttribute(p[0]); var el = sel && document.querySelector(sel);
        if (el && !el.value && p[1]) el.value = p[1];
      });
    });
    if (start) start.addEventListener('input', function () { start.dataset.auto = '0'; });
    root.addEventListener('input', function () { schedule(root); });
    root.addEventListener('change', function () { schedule(root); });
    KEYS.forEach(function (k) {
      var sel = root.getAttribute('data-' + k + '-from'); var el = sel && document.querySelector(sel);
      if (el) { el.addEventListener('input', function () { schedule(root); }); el.addEventListener('change', function () { schedule(root); }); }
    });
    if (root.tagName === 'FORM') root.addEventListener('submit', function (e) { if (window.fetch) { e.preventDefault(); run(root, false); } });
    var panel = document.querySelector(root.getAttribute('data-target'));
    if (panel) wire(panel, root);
    if (series && series.value) run(root, false);            // a key result that is already measured shows its verdict at once
  });
})();
