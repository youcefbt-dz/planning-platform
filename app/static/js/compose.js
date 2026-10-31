/* Compose — three small helpers on top of a form that works without them:
   - a suggestion from the assistant (data path) fills the measure, the target (the chosen level) and the title, then asks for the check;
   - a drafted goal (no-data path) fills the title, the why, and the first key result's name, unit and direction;
   - choosing a department shows who heads it. */
(function () {
  'use strict';
  var form = document.querySelector('[data-compose]');
  if (!form) return;
  function $(sel) { return form.querySelector(sel); }
  function fire(el) { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }
  function set(sel, v, onlyEmpty) { var el = $(sel); if (!el || v === undefined || v === null) return; if (onlyEmpty && el.value.trim()) return; el.value = v; fire(el); }
  function check() { var b = form.querySelector('button[name=do][value=check]'); if (b && form.requestSubmit) form.requestSubmit(b); else form.submit(); }

  form.addEventListener('click', function (e) {
    var lv = e.target.closest('.level');
    if (lv && form.contains(lv)) {
      var group = lv.parentNode; [].forEach.call(group.querySelectorAll('.level'), function (x) { x.setAttribute('aria-pressed', 'false'); });
      lv.setAttribute('aria-pressed', 'true'); return;
    }
    var add = e.target.closest('[data-sug-add]');
    if (add) {
      e.preventDefault();
      var card = add.closest('[data-sug]'), pressed = card.querySelector('.level[aria-pressed=true]') || card.querySelector('.level[data-level=ambitious]') || card.querySelector('.level');
      set('#c-series', card.getAttribute('data-series'));
      if (pressed) set('#c-target', String(parseFloat(pressed.getAttribute('data-value'))));
      set('#c-title', card.getAttribute('data-title'), true);
      check(); return;
    }
    var pick = e.target.closest('[data-pick-goal]');
    if (pick) {
      e.preventDefault();
      var krs = []; try { krs = JSON.parse(pick.getAttribute('data-krs') || '[]'); } catch (_) {}
      set('#c-title', pick.getAttribute('data-title')); set('#c-why', pick.getAttribute('data-rationale'));
      var k = krs[0];
      if (k) {
        set('#c-name', k.title); set('#c-unit', k.unit || '');
        var dir = /decrease|stay_below/.test(k.type || '') ? 'lower_better' : 'higher_better', r = $('input[name=direction][value=' + dir + ']'); if (r) r.checked = true;
      }
      var s = $('#c-start') || $('#c-series'); if (s) { s.scrollIntoView({ behavior: 'smooth', block: 'center' }); s.focus({ preventScroll: true }); }
    }
  });

  var unit = $('#c-unit-sel'), line = $('[data-head-line] span');
  if (unit && line) {
    var heads = {}; try { heads = JSON.parse(unit.getAttribute('data-heads') || '{}'); } catch (_) {}
    var holder = $('[data-head-line]'), yes = holder.getAttribute('data-yes'), no = holder.getAttribute('data-no'), org = line.textContent;
    var orgText = unit.value ? '' : line.textContent;
    unit.addEventListener('change', function () {
      var h = heads[unit.value];
      line.textContent = !unit.value ? (orgText || org) : h ? yes.replace('{name}', h) : no;
    });
  }

  // the measure's own history beside the target, live: now, a year ago, the one before, the best — and what the typed target asks for
  var sel = $('#c-series'), box = $('[data-ctx]'), tgt = $('#c-target'), need = $('[data-need]');
  if (sel && box && tgt) {
    var ctx = {}; try { ctx = JSON.parse(sel.getAttribute('data-ctx-json') || '{}'); } catch (_) {}
    var nf = function (v, u) { return Number(v).toLocaleString('en', { maximumFractionDigits: 2 }) + (u ? ' ' + u : ''); };
    var d = box.dataset;
    var paint = function () {
      var c = ctx[sel.value];
      if (!sel.value) { box.hidden = true; if (need) need.textContent = ''; return; }
      box.hidden = false;
      if (!c) { box.innerHTML = '<p class="cnow">' + d.lNone + '</p>'; return; }
      var li = function (lab, v, cls) { return v === null || v === undefined ? '' : '<li' + (cls ? ' class="' + cls + '"' : '') + '><small></small><b class="num">' + nf(v, c.unit) + '</b></li>'; };
      var items = [[d.lYear, c.year_ago, ''], [d.lPrior, c.prior, ''], [d.lNow + ' · ' + c.date, c.now, 'is-now'], [d.lBest, c.best, '']];
      box.innerHTML = '<ol class="cctx__row">' + items.map(function (x) { return li(x[0], x[1], x[2]); }).join('') + '</ol>';
      [].forEach.call(box.querySelectorAll('li'), function (el, i) { el.querySelector('small').textContent = items.filter(function (x) { return x[1] !== null && x[1] !== undefined; })[i][0]; });
      needLine();
    };
    var needLine = function () {
      var c = ctx[sel.value]; if (!need) return;
      var raw = tgt.value.replace(/[\s,]/g, '').replace('،', '.'), v = parseFloat(raw);
      if (!c || isNaN(v)) { need.textContent = ''; return; }
      var diff = v - c.now, pct = c.now ? Math.abs(diff / c.now) * 100 : null;
      if (diff === 0) { need.textContent = d.nHit; return; }
      var tpl = diff > 0 ? d.nUp : d.nDown;
      need.textContent = tpl.replace('{n}', nf(Math.abs(diff), c.unit)).replace('{pct}', pct === null ? '' : pct.toFixed(1) + '%');
    };
    sel.addEventListener('change', paint); tgt.addEventListener('input', needLine);
    if (sel.value && !box.querySelector('li')) paint(); else needLine();
  }
})();
