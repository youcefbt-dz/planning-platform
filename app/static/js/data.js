/* Data module — upload form and the mapping page. Progressive enhancement: every action also works as a plain form post.
   - tabs: columns / file preview / quality / reading (the hash keeps the tab: #quality, #col-3 …)
   - answering a question or editing a column is sent with fetch; the card updates and moves, nothing reloads
   - what the user writes to explain a column is saved while typing; "re-read" sends it to the model again */
(function () {
  'use strict';

  // intake cards (the upload card of the data pages): choose a kind of file -> the card plays and opens its drop area.
  // One file input serves both file cards; a file of the other kind switches the card by itself; dropping anywhere on the card works.
  var root = document.querySelector('[data-intake]');
  if (root) {
    var form = root.querySelector('form');
    var input = root.querySelector('.intake__input');
    var grid = root.querySelector('[data-grid]');
    var picks = Array.prototype.slice.call(root.querySelectorAll('.pick'));
    var errBox = root.querySelector('[data-intake-error]');
    var maxBytes = (parseInt(root.getAttribute('data-max'), 10) || 8) * 1024 * 1024;
    var KINDS = { excel: ['xlsx', 'xlsm'], csv: ['csv', 'tsv', 'txt'] };
    var wide = window.matchMedia('(min-width: 761px)');
    var current = null;

    var kindOf = function (name) {
      var ext = (String(name).split('.').pop() || '').toLowerCase();
      for (var k in KINDS) if (KINDS[k].indexOf(ext) > -1) return k;
      return null;
    };
    var byKind = function (k) { return picks.filter(function (p) { return p.getAttribute('data-kind') === k; })[0]; };
    var fmtSize = function (b) { return b < 1048576 ? Math.max(1, Math.round(b / 1024)) + ' ' + root.getAttribute('data-kb') : (b / 1048576).toFixed(1) + ' ' + root.getAttribute('data-mb'); };

    function showError(msg) {
      if (!msg) { errBox.hidden = true; return; }
      errBox.textContent = msg; errBox.hidden = false;
      errBox.classList.remove('is-shake'); void errBox.offsetWidth; errBox.classList.add('is-shake');
    }
    function layout() {                                   // the open card grows, the others make room (desktop only)
      if (!grid) return;
      if (!wide.matches) { grid.style.gridTemplateColumns = ''; return; }
      grid.style.gridTemplateColumns = picks.map(function (p) { return p.classList.contains('is-open') ? 'minmax(0,1.7fr)' : 'minmax(0,1fr)'; }).join(' ');
    }
    function reset(p) {
      p.classList.remove('has-file');
      var d = p.querySelector('.pick__drop'), go = p.querySelector('.pick__go');
      if (d) { d.querySelector('.pick__t').textContent = d.getAttribute('data-idle-t'); d.querySelector('.pick__s').textContent = d.getAttribute('data-idle-s'); }
      if (go) go.setAttribute('inert', '');
    }
    function open(kind, keepFile) {
      current = kind;
      picks.forEach(function (p) {
        var on = p.getAttribute('data-kind') === kind;
        p.classList.toggle('is-open', on);
        p.querySelector('.pick__top').setAttribute('aria-expanded', on ? 'true' : 'false');
        var body = p.querySelector('.pick__body');
        if (on) body.removeAttribute('inert'); else body.setAttribute('inert', '');
        if (!on || !keepFile) reset(p);
      });
      if (!keepFile) input.value = '';
      if (KINDS[kind]) input.setAttribute('accept', KINDS[kind].map(function (e) { return '.' + e; }).join(','));
      showError('');
      layout();
      // the drop area grows under the card: bring it into view once the card has opened
      var card = byKind(kind), calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (card) setTimeout(function () { if (current === kind) card.scrollIntoView({ block: 'nearest', behavior: calm ? 'auto' : 'smooth' }); }, 520);
    }
    function close() { current = null; picks.forEach(function (p) { p.classList.remove('is-open'); p.querySelector('.pick__top').setAttribute('aria-expanded', 'false'); p.querySelector('.pick__body').setAttribute('inert', ''); reset(p); }); input.value = ''; layout(); }

    function take(file) {
      if (!file) return;
      var k = kindOf(file.name);
      if (!k) { input.value = ''; if (current) reset(byKind(current)); showError(root.getAttribute('data-err-type')); return; }
      if (file.size > maxBytes) { input.value = ''; if (current) reset(byKind(current)); showError(root.getAttribute('data-err-size')); return; }
      if (k !== current) open(k, true);
      var p = byKind(k), d = p.querySelector('.pick__drop');
      p.classList.remove('has-file'); void p.offsetWidth;   // replay the "file landed" bounce when a second file replaces the first
      d.querySelector('.pick__t').textContent = file.name;
      d.querySelector('.pick__s').textContent = fmtSize(file.size) + ' \u00b7 ' + d.getAttribute('data-change');
      p.querySelector('.pick__go').removeAttribute('inert');
      p.classList.add('has-file');
      showError('');
    }

    picks.forEach(function (p) {
      p.querySelector('.pick__top').addEventListener('click', function () {
        var kind = p.getAttribute('data-kind');
        if (p.classList.contains('is-open')) close(); else open(kind, false);
      });
      var pickBtn = p.querySelector('[data-pick-file]');
      if (pickBtn) pickBtn.addEventListener('click', function () { input.click(); });
    });
    input.addEventListener('change', function () { take(input.files && input.files[0]); });

    // drag & drop on the whole card; the kind is read from the dropped file's name
    var depth = 0;
    root.addEventListener('dragenter', function (e) { if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') < 0) return; e.preventDefault(); depth++; root.classList.add('is-drag'); });
    root.addEventListener('dragover', function (e) { if (root.classList.contains('is-drag')) e.preventDefault(); });
    root.addEventListener('dragleave', function () { depth = Math.max(0, depth - 1); if (!depth) root.classList.remove('is-drag'); });
    root.addEventListener('drop', function (e) {
      if (!root.classList.contains('is-drag')) return;
      e.preventDefault(); depth = 0; root.classList.remove('is-drag');
      var f = e.dataTransfer.files && e.dataTransfer.files[0];
      if (!f) return;
      try { input.files = e.dataTransfer.files; } catch (_) { /* old browsers: the name is still shown, the picker stays the way in */ }
      take(f);
    });
    root.addEventListener('keydown', function (e) { if (e.key === 'Escape' && current) { close(); } });
    if (wide.addEventListener) wide.addEventListener('change', layout);

    // a sending card shows it is busy (the global spinner on the button)
    form.addEventListener('submit', function (e) { if (e.submitter) e.submitter.setAttribute('aria-busy', 'true'); });
  }
})();

(function () {
  'use strict';

  // upload: show the chosen file name, accept drag & drop
  document.querySelectorAll('[data-upload]').forEach(function (form) {
    var input = form.querySelector('input[type=file]');
    var out = form.querySelector('[data-filename]');
    var drop = form.querySelector('.upload__drop');
    if (!input) return;
    input.addEventListener('change', function () { if (out) out.textContent = input.files[0] ? input.files[0].name : ''; });
    ['dragenter', 'dragover'].forEach(function (ev) { drop.addEventListener(ev, function () { drop.classList.add('is-over'); }); });
    ['dragleave', 'drop'].forEach(function (ev) { drop.addEventListener(ev, function () { drop.classList.remove('is-over'); }); });
  });

  var page = document.querySelector('[data-mapview]');
  if (!page) return;
  var $ = function (sel, root) { return (root || page).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || page).querySelectorAll(sel)); };

  // ---- the sheet (preview tab) -----------------------------------------------------------------------------------
  var sheet = $('[data-sheet]');
  var refEl = sheet && $('[data-ref]', sheet);
  var valEl = sheet && $('[data-refval]', sheet);
  var annRow = sheet && $('.grid__ann', sheet);
  var scroller = sheet && $('.sheet__scroll', sheet);

  // the letters row sticks right under the annotation row, whatever its height (only measurable while the tab is visible)
  function fitHeader() {
    if (annRow && scroller && annRow.offsetHeight) scroller.style.setProperty('--ann-h', annRow.getBoundingClientRect().height + 'px');
  }
  window.addEventListener('resize', fitHeader);

  // ---- tabs --------------------------------------------------------------------------------------------------------
  var tabs = $$('[data-tab]');
  var panels = $$('[data-panel]');
  function showTab(name, keepHash) {
    if (!panels.some(function (p) { return p.getAttribute('data-panel') === name; })) name = 'columns';
    tabs.forEach(function (t) { t.setAttribute('aria-selected', t.getAttribute('data-tab') === name ? 'true' : 'false'); });
    panels.forEach(function (p) { p.hidden = p.getAttribute('data-panel') !== name; });
    if (name === 'columns') fitHeader();
    if (!keepHash && window.history && history.replaceState) history.replaceState(null, '', '#' + name);
  }
  tabs.forEach(function (t) { t.addEventListener('click', function () { showTab(t.getAttribute('data-tab')); }); });

  function openCard(idx, flash) {
    var card = document.getElementById('col-' + idx);
    if (!card) return;
    showTab('columns', true);
    card.open = true;
    focusColumn(idx);
    card.scrollIntoView({ block: 'center', behavior: 'smooth' });
    if (flash) { card.classList.add('is-flash'); setTimeout(function () { card.classList.remove('is-flash'); }, 1500); }
  }
  // the column of an opened card is outlined in the table above it, and the table scrolls sideways to it
  function focusColumn(idx) {
    $$('.grid .is-focus').forEach(function (n) { n.classList.remove('is-focus'); });
    var cells = $$('.grid [data-colh="' + idx + '"]');
    cells.forEach(function (n) { n.classList.add('is-focus'); });
    var sc = $('.sheet__scroll'), first = cells[0];
    if (sc && first) { var r = first.getBoundingClientRect(), b = sc.getBoundingClientRect(); sc.scrollLeft += (r.left < b.left ? r.left - b.left - 20 : r.right > b.right ? r.right - b.right + 20 : 0); }
  }
  $$('.ccard').forEach(function (c) { c.addEventListener('toggle', function () { if (c.open) focusColumn(c.getAttribute('data-idx')); }); });
  function fromHash() {
    var h = (location.hash || '').replace('#', '');
    if (/^col-\d+$/.test(h)) { openCard(h.slice(4), true); return; }
    showTab(h || 'columns', true);
  }
  fromHash();
  window.addEventListener('hashchange', fromHash);

  // ---- sheet interaction -----------------------------------------------------------------------------------------
  var cellSel = null;
  if (sheet) {
    sheet.addEventListener('click', function (e) {
      var td = e.target.closest('td[data-ref]');
      if (td) {
        if (cellSel) cellSel.classList.remove('is-cell');
        cellSel = td;
        td.classList.add('is-cell');
        refEl.textContent = td.getAttribute('data-ref');
        valEl.textContent = td.textContent;
        return;
      }
      var h = e.target.closest('[data-colh]');
      if (h && h.getAttribute('data-colh') !== '') openCard(h.getAttribute('data-colh'), true);
    });
    sheet.addEventListener('keydown', function (e) {
      if ((e.key === 'Enter' || e.key === ' ') && e.target.classList.contains('ann')) {
        e.preventDefault();
        openCard(e.target.getAttribute('data-col'), true);
      }
    });
  }

  // ---- live updates after a column is answered / edited ------------------------------------------------------------
  function paint(col, roles, aggLabel) {
    var idx = String(col.index);
    $$('[data-colh="' + idx + '"],[data-col="' + idx + '"]').forEach(function (n) {
      n.setAttribute('data-role', col.role);
      n.setAttribute('data-unsure', 'false');
    });
    var card = $('[data-colrow="' + idx + '"]');
    if (card) {
      card.setAttribute('data-role', col.role);
      var chip = $('[data-f=chip]', card);
      if (chip) { chip.setAttribute('data-role', col.role); var rn = $('[data-f=rolename]', chip); if (rn) rn.textContent = roles[col.role]; }
      var nm = $('[data-f=label2]', card); if (nm) nm.textContent = col.label;
      var meta = $('[data-f=meta]', card);
      if (meta) meta.textContent = col.role === 'measure' ? ((col.unit ? col.unit + ' · ' : '') + (aggLabel || '')) : '';
      var qm = $('[data-f=qmark]', card); if (qm) qm.hidden = true;
    }
    $$('[data-col="' + idx + '"]').forEach(function (a) {
      var r = $('[data-f=role]', a); if (r) r.textContent = roles[col.role];
      var rc = $('.role-chip', a); if (rc) rc.setAttribute('data-role', col.role);
      var l = $('[data-f=label]', a); if (l) l.textContent = col.label;
      var conf = $('[data-f=conf]', a); if (conf) conf.textContent = '✓';
      var m = $('[data-f=meta]', a);
      if (m) m.textContent = col.role === 'measure' ? ((col.unit || '—') + ' · ' + (aggLabel || '')) : '';
    });
    // cells that no longer fit are only known to the server; they refresh on the next load
    $$('td.bad[data-colh="' + idx + '"]').forEach(function (n) { n.classList.remove('bad'); });
    fitHeader();
  }

  // an answered card leaves the "needs you" group and takes its place among the understood ones
  function settle(idx) {
    var card = $('[data-colrow="' + idx + '"]');
    if (!card) return;
    var ask = $('[data-q]', card); if (ask) ask.remove();
    card.setAttribute('data-state', 'ok');
    card.open = false;
    var ok = $('[data-group=ok]');
    if (ok && card.parentNode !== ok) {
      var next = $$('[data-colrow]', ok).filter(function (c) { return +c.getAttribute('data-idx') > +idx; })[0];
      ok.insertBefore(card, next || null);
    }
  }

  function refreshState(data) {
    var left = $$('[data-group=ask] [data-colrow]').length;
    var head = $('[data-grouphead=ask]'); if (head) head.hidden = left === 0;
    var cnt = $('[data-f=qcount]'); if (cnt) cnt.textContent = left;
    var tq = $('[data-f=tabq]'); if (tq) { tq.textContent = left; tq.hidden = left === 0; }
    var st = $('[data-f=remaining]');
    if (st) { st.setAttribute('data-done', left === 0 ? 'true' : 'false'); var tx = $('[data-f=remaining_text]', st); if (tx && data.remaining_label) tx.textContent = data.remaining_label; }
    var confirmBtn = $('[data-confirm-btn]'); if (confirmBtn) confirmBtn.disabled = !data.ready;
    var warn = $('[data-ready-error]'); if (warn && data.ready) warn.remove();
  }

  document.addEventListener('submit', function (e) {
    var form = e.target.closest('form[data-ajax]');
    if (!form || !window.fetch) return;
    e.preventDefault();
    var btn = form.querySelector('button[type=submit]');
    if (btn) btn.disabled = true;
    fetch(form.action, {
      method: 'POST', body: new FormData(form), credentials: 'same-origin',
      headers: { 'X-Requested-With': 'fetch', 'Accept': 'application/json' }
    }).then(function (r) { return r.ok ? r.json() : Promise.reject(r); }).then(function (data) {
      paint(data.column, data.roles, data.aggregation_label);
      settle(data.column.index);
      refreshState(data);
      if (btn) btn.disabled = false;
      var man = form.closest('.ccard__manual'); if (man) man.open = false;
    }).catch(function () { form.submit(); });
  });

  // ---- explaining columns to the model: saved while typing --------------------------------------------------------
  var notesForm = document.getElementById('notes-form');
  var tokenEl = notesForm && notesForm.querySelector('input[name=csrf_token]');
  var rereadBtn = $('[data-reread]');
  var unsent = $('[data-unsent]');
  var changed = false;

  function flashSaved(field) {
    var wrap = field.closest('.ccard__explain') || field.closest('.explain');
    var tag = wrap && wrap.querySelector('[data-saved]');
    if (!tag) return;
    tag.hidden = false;
    clearTimeout(tag._t);
    tag._t = setTimeout(function () { tag.hidden = true; }, 1800);
  }
  function markChanged() {
    changed = true;
    if (rereadBtn) rereadBtn.hidden = false;
    if (unsent) unsent.hidden = false;
  }
  $$('[data-note]').forEach(function (ta) {
    ta.addEventListener('input', markChanged);
    ta.addEventListener('change', function () {
      if (!window.fetch || !tokenEl) return;
      var fd = new FormData();
      fd.append('csrf_token', tokenEl.value);
      fd.append('save_only', '1');
      fd.append(ta.name, ta.value);
      fetch(notesForm.action, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch', 'Accept': 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
        .then(function () {
          flashSaved(ta);
          var m = /^note_(\d+)$/.exec(ta.name);
          var flag = m && $('[data-colrow="' + m[1] + '"] [data-f=noteflag]');
          if (flag) flag.hidden = !ta.value.trim();
        })
        .catch(function () { /* the text is still in the field; "re-read" will send it with the form */ });
    });
  });

  // the header-row input sits in the same form as the row-number buttons: Enter applies it
  var hr = document.getElementById('f-hr');
  if (hr) hr.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); hr.form.submit(); } });
})();
