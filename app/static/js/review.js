/* The file review page. Every change is a plain form post that also works without this script; with it:
   - a column row saves the moment a field changes (role, name, unit, how a month is built, what "better" means)
   - an answered question folds into a "done" line, the counters and the confirm button follow
   - notes are saved while typing, the spreadsheet preview shows a cell's value */
(function () {
  'use strict';
  var root = document.querySelector('[data-review]');
  if (!root) return;
  var token = (root.querySelector('input[name=csrf_token]') || {}).value || '';
  var $ = function (s, r) { return (r || root).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || root).querySelectorAll(s)); };
  var H = { 'X-Requested-With': 'fetch', 'Accept': 'application/json' };

  function send(url, fd) {
    fd.append('csrf_token', token);
    return fetch(url, { method: 'POST', body: fd, credentials: 'same-origin', headers: H }).then(function (r) { return r.ok ? r.json() : Promise.reject(r); });
  }
  function flash(el) {
    if (!el) return;
    el.hidden = false; clearTimeout(el._t);
    el._t = setTimeout(function () { el.hidden = true; }, 1600);
  }

  // ---- counters, confirm button ----------------------------------------------------------------------------------
  function paintRole(col) {
    var row = $('.rrow[data-col="' + col.index + '"]');
    if (row) {
      row.setAttribute('data-role', col.role);
      var set = function (n, v) { var el = $('[name=' + n + ']', row); if (el && v !== undefined && v !== null) el.value = v; };
      set('role', col.role); set('label', col.label); set('unit', col.unit || '');
      if (col.aggregation && col.aggregation !== 'none') set('aggregation', col.aggregation);
      set('direction', col.direction);
    }
    $$('.grid [data-colh="' + col.index + '"]').forEach(function (n) { n.setAttribute('data-role', col.role); });
    var counts = {};
    $$('.rrow').forEach(function (r) { var k = r.getAttribute('data-role'); counts[k] = (counts[k] || 0) + 1; });
    $$('[data-count]').forEach(function (b) { b.textContent = counts[b.getAttribute('data-count')] || 0; });
  }
  function refreshState(data) {
    var left = $$('.q:not(.is-done)').length;
    var qc = $('[data-f=qcount]'); if (qc) qc.textContent = left;
    var ask = $('[data-ask]');
    if (ask && left === 0) setTimeout(function () { ask.hidden = true; }, 900);
    var st = $('[data-f=remaining]');
    if (st) {
      st.setAttribute('data-done', left === 0 ? 'true' : 'false');
      var tx = $('[data-f=remaining_text]', st);
      if (tx && data.remaining_label) tx.textContent = data.remaining_label;
    }
    var go = $('[data-confirm-btn]'); if (go) go.disabled = !data.ready;
    var warn = $('[data-ready-error]'); if (warn && data.ready) warn.remove();
  }

  // ---- the questions ---------------------------------------------------------------------------------------------
  root.addEventListener('submit', function (e) {
    var f = e.target.closest('form[data-answer]');
    if (!f || !window.fetch) return;
    e.preventDefault();
    var block = f.closest('.q'), btn = f.querySelector('button');
    var label = btn.textContent.trim();
    $$('button', block).forEach(function (b) { b.disabled = true; });
    send(f.action, new FormData(f)).then(function (data) {
      paintRole(data.column);
      block.classList.add('is-done');
      var done = $('.q__done', block);
      $('[data-answer-text]', block).textContent = root.getAttribute('data-t-answered').replace('%s', label);
      done.hidden = false;
      refreshState(data);
    }).catch(function () { f.submit(); });
  });

  // ---- editing a column in place -----------------------------------------------------------------------------------
  function saveRow(row, onlyLabelChanged) {
    var fd = new FormData();
    ['role', 'label', 'unit', 'aggregation', 'direction'].forEach(function (n) {
      var el = $('[name=' + n + ']', row);
      if (el) fd.append(n, el.value);
    });
    row.classList.add('is-saving');
    send(row.getAttribute('data-url'), fd).then(function (data) {
      row.classList.remove('is-saving');
      paintRole(data.column);
      flash($('[data-rowsaved]', row));
      refreshState(data);
    }).catch(function () { row.classList.remove('is-saving'); });
  }
  $$('.rrow').forEach(function (row) {
    row.addEventListener('change', function (e) {
      if (e.target.matches('[data-note]')) return;
      saveRow(row);
    });
    var label = $('[name=label]', row);
    if (label) label.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); label.blur(); } });
  });

  // ---- notes: saved while typing -----------------------------------------------------------------------------------
  var nf = document.getElementById('notes-form');
  $$('[data-note]').forEach(function (ta) {
    ta.addEventListener('change', function () {
      if (!nf || !window.fetch) return;
      var fd = new FormData(); fd.append('save_only', '1'); fd.append(ta.name, ta.value);
      send(nf.action, fd).then(function () {
        flash($('[data-saved]', nf)); var r = ta.closest('.rrow'); if (r) flash($('[data-rowsaved]', r));
      }).catch(function () {});
    });
  });
  $$('.chip-btn[data-fill]').forEach(function (b) {
    b.addEventListener('click', function () {
      var t = $(b.getAttribute('data-target')); if (!t) return;
      t.value = (t.value ? t.value.replace(/\s+$/, '') + ' ' : '') + b.getAttribute('data-fill');
      t.dispatchEvent(new Event('change', { bubbles: true })); t.focus();
    });
  });

  // ---- the preview: click a cell to see its value, a column header to jump to its row --------------------------------
  var sheet = $('[data-sheet]');
  if (sheet) {
    var ref = $('[data-ref]', sheet), val = $('[data-refval]', sheet), cur = null;
    sheet.addEventListener('click', function (e) {
      var td = e.target.closest('td[data-ref]');
      if (td) {
        if (cur) cur.classList.remove('is-cell');
        cur = td; td.classList.add('is-cell');
        ref.textContent = td.getAttribute('data-ref'); val.textContent = td.textContent;
        return;
      }
      var h = e.target.closest('[data-colh]');
      if (h && h.getAttribute('data-colh') !== '') {
        var row = $('.rrow[data-col="' + h.getAttribute('data-colh') + '"]');
        if (row) { row.scrollIntoView({ block: 'center', behavior: 'smooth' }); row.classList.add('is-flash'); setTimeout(function () { row.classList.remove('is-flash'); }, 1500); }
      }
    });
  }
  var hr = document.getElementById('f-hr');
  if (hr) hr.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); hr.form.submit(); } });
})();
