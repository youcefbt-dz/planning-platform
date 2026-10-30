/* Assist — "click instead of type". Three tiny behaviours, all by event delegation, all optional (every form still works without this file):
     [data-fill="text" data-target="#sel" data-mode="set|append|list|empty"]   a chip that puts its text into a field
     [data-assist="URL" data-assist-from="#a,#b"] … [data-assist-run] … [data-assist-out]   fetch an HTML fragment of suggestions
     Enter inside an assist block's input runs the suggestion instead of submitting the surrounding form.                          */
(function () {
  'use strict';
  var token = (document.querySelector('meta[name=csrf-token]') || {}).content || '';
  function fire(el, type) { el.dispatchEvent(new Event(type, { bubbles: true })); }

  function fill(chip) {
    var text = chip.getAttribute('data-fill') || '', mode = chip.getAttribute('data-mode') || 'set';
    var all = [].slice.call(document.querySelectorAll(chip.getAttribute('data-target') || ''));
    var el = mode === 'empty' ? (all.filter(function (x) { return !x.value.trim(); })[0]) : all[0];
    if (!el) { chip.disabled = true; return; }
    var cur = el.value.trim();
    if (mode === 'append') el.value = cur ? cur + (/[.:؟!،]$/.test(cur) ? ' ' : '، ') + text : text;
    else if (mode === 'list') {
      var items = cur ? cur.split(/[،,]\s*/) : [];
      if (items.indexOf(text) === -1) items.push(text);
      el.value = items.join('، ');
    } else el.value = text;
    chip.setAttribute('aria-pressed', 'true');
    fire(el, 'input'); fire(el, 'change');
    if (mode !== 'list') el.focus();
  }

  function run(btn) {
    var box = btn.closest('[data-assist]'); if (!box) return;
    var out = box.querySelector('[data-assist-out]'), fd = new FormData();
    (box.getAttribute('data-assist-from') || '').split(',').forEach(function (sel) {
      var el = sel.trim() && document.querySelector(sel.trim()); if (el && el.name) fd.set(el.name, el.value);
    });
    btn.setAttribute('aria-busy', 'true'); out.classList.add('panel-loading');
    fetch(box.getAttribute('data-assist'), { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRFToken': token, 'X-Requested-With': 'fetch' } })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(r); })
      .then(function (html) { out.innerHTML = html; })
      .catch(function () { out.textContent = box.getAttribute('data-assist-failed') || ''; })
      .then(function () { btn.removeAttribute('aria-busy'); out.classList.remove('panel-loading'); });
  }

  document.addEventListener('click', function (e) {
    var chip = e.target.closest('[data-fill]'); if (chip) { e.preventDefault(); fill(chip); return; }
    var go = e.target.closest('[data-assist-run]'); if (go) { e.preventDefault(); run(go); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' || !e.target.matches('input')) return;
    var box = e.target.closest('[data-assist]'); if (!box) return;
    e.preventDefault(); var go = box.querySelector('[data-assist-run]'); if (go) run(go);
  });
})();
