/* Goals — the form (live quality review, key-result types, levels from history, suggestions), the justification draft on the
   goal page, and the health brief. Plain fetch; every action also works as a normal form post without this script. */
(function () {
  'use strict';
  var token = (document.querySelector('meta[name=csrf-token]') || {}).content || '';
  var lang = document.documentElement.lang || 'en';
  var nf = new Intl.NumberFormat(lang === 'ar' ? 'ar-u-nu-latn' : lang, { maximumFractionDigits: 2 });

  function post(url, fd) {
    return fetch(url, { method: 'POST', body: fd || new FormData(), credentials: 'same-origin', headers: { 'X-CSRFToken': token, 'X-Requested-With': 'fetch' } });
  }
  function text(r) { return r.ok ? r.text() : Promise.reject(r); }
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return [].slice.call((root || document).querySelectorAll(sel)); }
  function fire(el, type) { el.dispatchEvent(new Event(type, { bubbles: true })); }
  function json(attr, el) { try { return JSON.parse(el.getAttribute(attr) || '{}'); } catch (e) { return {}; } }

  /* ---------- the goal form ---------- */
  function initForm(form) {
    var review = $('[data-review]', form), suggest = $('#suggest', form);
    var hints = json('data-hints', form), tlabels = json('data-tlabels', form), lnames = json('data-lnames', form);
    var rows = $$('.krrow', form);
    var timer = null, seq = 0, wantAI = false;

    /* quality review: rules live as you type; the model only when asked */
    function runReview(ai) {
      if (!review) return;
      var fd = new FormData(form); if (ai) fd.set('ai', '1');
      var my = ++seq; review.classList.add('panel-loading');
      post(form.dataset.reviewUrl, fd).then(text).then(function (html) { if (my === seq) review.innerHTML = html; })
        .catch(function () {}).then(function () { review.classList.remove('panel-loading'); });
    }
    function schedule() { clearTimeout(timer); timer = setTimeout(function () { runReview(false); }, 700); }
    form.addEventListener('input', schedule);
    form.addEventListener('change', schedule);
    var aiBtn = $('[data-review-ai]', form);
    if (aiBtn) aiBtn.addEventListener('click', function () { aiBtn.setAttribute('aria-busy', 'true'); wantAI = true; runReview(true); setTimeout(function () { aiBtn.removeAttribute('aria-busy'); }, 1500); });
    if (review) {
      review.addEventListener('click', function (e) {
        var b = e.target.closest('[data-use-title],[data-use-kr]'); if (!b) return;
        var el = b.hasAttribute('data-use-title') ? $('#f-title') : $('#kt' + b.getAttribute('data-use-kr'));
        if (el) { el.value = b.getAttribute('data-use-title') || b.getAttribute('data-text'); fire(el, 'input'); }
        b.disabled = true;
      });
      if ($('#f-title').value.trim()) runReview(false);
    }

    /* key-result types: the fields a type needs */
    function endDate() {
      var d = $('#f-end_date'); if (d && d.value) return d.value;
      var c = $('#f-cycle_id'); var o = c && c.options[c.selectedIndex];
      return (o && o.getAttribute('data-end')) || '';
    }
    function adapt(row) {
      var type = $('[data-f=type]', row).value;
      var show = { start: type === 'increase' || type === 'decrease', target: type !== 'binary', unit: type !== 'binary' && type !== 'milestone' };
      Object.keys(show).forEach(function (k) { var f = $('[data-for=' + k + ']', row); if (f) f.hidden = !show[k]; });
      var lab = $('[data-label-target]', row); if (lab && tlabels[type]) lab.textContent = tlabels[type];
      var h = $('[data-kind-hint]', row); if (h) h.textContent = hints[type] || '';
      var m = $('.kr-measure', row); if (m) m.hidden = !(type === 'increase' || type === 'decrease' || type === 'stay_above' || type === 'stay_below');
      fetchLevels(row);
    }

    /* levels from the organization's own history */
    function setLevel(row, key) {
      $('[data-f=level]', row).value = key || '';
      $$('.level', row).forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-level') === key ? 'true' : 'false'); });
    }
    function fetchLevels(row) {
      var url = form.dataset.levelsUrl, box = $('[data-levels]', row); if (!url || !box) return;
      var sel = $('[data-r=series]', row), type = $('[data-f=type]', row).value;
      if (!sel || !sel.value || (type !== 'increase' && type !== 'decrease')) { box.hidden = true; return; }
      var strip = $('.levelrow', box), note = $('.levels__note', box), end = endDate();
      box.hidden = false; strip.innerHTML = ''; note.textContent = '';
      if (!end) { note.textContent = form.dataset.tNeedEnd; return; }
      var q = new URLSearchParams({ series: sel.value, end: end, direction: type === 'decrease' ? 'lower_better' : 'higher_better' });
      var st = $('[data-f=start]', row).value.replace(',', '.'); if (st && !isNaN(parseFloat(st))) q.set('start', st);
      fetch(url + '?' + q.toString(), { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (d) {
        strip.innerHTML = '';
        if (!d.ok) { box.hidden = true; return; }
        if (!d.levels) { note.textContent = form.dataset.tShort; return; }
        ['conservative', 'ambitious', 'stretch'].forEach(function (k) {
          var b = document.createElement('button'); b.type = 'button'; b.className = 'level'; b.setAttribute('data-level', k); b.setAttribute('data-value', d.levels[k]); b.setAttribute('aria-pressed', 'false');
          var a = document.createElement('span'); a.textContent = lnames[k];
          var v = document.createElement('b'); v.className = 'num'; var bd = document.createElement('bdi'); bd.dir = 'ltr'; bd.textContent = nf.format(d.levels[k]) + (d.unit ? ' ' + d.unit : ''); v.appendChild(bd);
          b.appendChild(a); b.appendChild(v); strip.appendChild(b);
        });
        note.textContent = form.dataset.tBasis.replace('{n}', d.levels.windows);
        setLevel(row, $('[data-f=level]', row).value);
      }).catch(function () { box.hidden = true; });
    }

    rows.forEach(function (row) {
      $('[data-f=type]', row).addEventListener('change', function () { adapt(row); });
      var sel = $('[data-r=series]', row); if (sel) sel.addEventListener('change', function () { setLevel(row, ''); setTimeout(function () { fetchLevels(row); }, 0); });
      $('[data-f=start]', row).addEventListener('change', function () { fetchLevels(row); });
      $('[data-f=target]', row).addEventListener('input', function () { setLevel(row, ''); });
      row.addEventListener('click', function (e) {
        var b = e.target.closest('.level'); if (!b) return;
        var t = $('[data-f=target]', row); t.value = b.getAttribute('data-value'); fire(t, 'input'); fire(t, 'change');
        setLevel(row, b.getAttribute('data-level'));
      });
      adapt(row);
    });
    ['#f-end_date', '#f-cycle_id'].forEach(function (s) { var el = $(s); if (el) el.addEventListener('change', function () { rows.forEach(fetchLevels); }); });

    var more = $('[data-add-kr]', form);
    if (more) more.addEventListener('click', function () {
      var h = rows.filter(function (r) { return r.hidden; })[0];
      if (h) { h.hidden = false; $('[data-f=title]', h).focus(); }
      if (!rows.some(function (r) { return r.hidden; })) more.hidden = true;
    });

    /* a proposed goal (from one typed line): title, why and key results go into the form; numbers stay for the person (or their data) */
    form.addEventListener('click', function (e) {
      var b = e.target.closest('[data-pick-goal]'); if (!b) return;
      var setv = function (el, v) { if (el) { el.value = v; fire(el, 'input'); } };
      setv($('#f-title'), b.getAttribute('data-title') || '');
      setv($('#f-rationale'), b.getAttribute('data-rationale') || '');
      var krs = []; try { krs = JSON.parse(b.getAttribute('data-krs') || '[]'); } catch (x) { krs = []; }
      var free = rows.filter(function (r) { return !$('[data-f=title]', r).value.trim() || r.getAttribute('data-draft') === '1'; });
      krs.slice(0, free.length).forEach(function (k, i) {
        var row = free[i]; row.hidden = false; row.setAttribute('data-draft', '1');
        var ty = $('[data-f=type]', row); ty.value = k.type || 'increase'; adapt(row);
        setv($('[data-f=title]', row), k.title || ''); setv($('[data-f=unit]', row), k.unit || '');
      });
      free.slice(krs.length).forEach(function (row) { if (row.getAttribute('data-draft') === '1') { setv($('[data-f=title]', row), ''); setv($('[data-f=unit]', row), ''); } });
      var more = $('[data-add-kr]', form); if (more && !rows.some(function (r) { return r.hidden; })) more.hidden = true;
      $$('[data-pick-goal]', form).forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      var first = free[0] && ($('[data-f=target]', free[0]) || $('[data-f=title]', free[0])); if (first) first.focus();
      schedule();
    });

    /* suggestions from the organization's own data */
    var sbtn = $('[data-suggest]', form);
    if (sbtn && suggest) {
      sbtn.addEventListener('click', function () {
        var fd = new FormData(); ['title', 'rationale', 'end_date', 'cycle_id'].forEach(function (n) { var el = form.elements[n]; if (el) fd.set(n, el.value); });
        sbtn.setAttribute('aria-busy', 'true'); suggest.classList.add('panel-loading');
        post(form.dataset.suggestUrl, fd).then(text).then(function (html) { suggest.innerHTML = html; })
          .catch(function () {}).then(function () { sbtn.removeAttribute('aria-busy'); suggest.classList.remove('panel-loading'); });
      });
      suggest.addEventListener('click', function (e) {
        var lv = e.target.closest('.level');
        if (lv) { var card = lv.closest('[data-sug]'); $$('.level', card).forEach(function (b) { b.setAttribute('aria-pressed', b === lv ? 'true' : 'false'); }); return; }
        var add = e.target.closest('[data-sug-add]'); if (!add) return;
        var c = add.closest('[data-sug]');
        var row = rows.filter(function (r) { return !$('[data-f=title]', r).value.trim(); })[0];
        if (!row) { add.disabled = true; return; }
        row.hidden = false;
        var set = function (f, v) { var el = $('[data-f=' + f + ']', row); if (el && v !== '' && v != null) { el.value = v; fire(el, 'input'); } };
        var ty = $('[data-f=type]', row); ty.value = c.getAttribute('data-type'); adapt(row);
        set('title', c.getAttribute('data-title')); set('unit', c.getAttribute('data-unit'));
        var s0 = c.getAttribute('data-start'); if (s0 !== '') set('start', String(Math.round(parseFloat(s0) * 100) / 100));
        var sel = $('[data-r=series]', row); if (sel) { sel.value = c.getAttribute('data-series'); fire(sel, 'change'); }
        var picked = $('.level[aria-pressed=true]', c);
        if (picked) { set('target', picked.getAttribute('data-value')); setLevel(row, picked.getAttribute('data-level')); }
        add.disabled = true; add.textContent = '✓';
        schedule();
      });
    }
  }
  var gf = $('[data-goal-form]'); if (gf) initForm(gf);

  /* ---------- the goal page: draft a justification ---------- */
  $$('form[data-just]').forEach(function (f) {
    var btn = $('[data-just-draft]', f), by = $('[data-just-by]', f), ta = $('textarea', f);
    if (!btn) return;
    btn.addEventListener('click', function () {
      btn.setAttribute('aria-busy', 'true'); by.textContent = '';
      post(f.dataset.just).then(function (r) { return r.ok ? r.json() : Promise.reject(r); }).then(function (d) {
        ta.value = d.text;
        by.textContent = d.rules ? f.dataset.byRules : f.dataset.byModel.replace('{p}', d.label || d.provider);
      }).catch(function () { by.textContent = f.dataset.failed; }).then(function () { btn.removeAttribute('aria-busy'); });
    });
  });

  /* ---------- goal health: the brief ---------- */
  var bb = $('[data-brief]');
  if (bb) bb.addEventListener('click', function () {
    var out = $('#brief'), fd = new FormData(); fd.set('cycle', bb.getAttribute('data-cycle') || '');
    bb.setAttribute('aria-busy', 'true'); out.classList.add('panel-loading');
    post(bb.getAttribute('data-brief'), fd).then(text).then(function (html) { out.innerHTML = html; })
      .catch(function () {}).then(function () { bb.removeAttribute('aria-busy'); out.classList.remove('panel-loading'); });
  });
})();
