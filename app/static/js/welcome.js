/* Welcome (first sign-in). Step 1: the chosen radio drives the picture (data-choice: allow opens the gate and packets flow, deny closes it).
   Step 2: a chosen or dropped logo replaces the initials tile in the preview header at once. Both steps work without this file (plain forms). */
(function () {
  'use strict';
  var wm = document.querySelector('[data-wm]');
  if (wm) {
    var form = wm.querySelector('[data-wm-form]');
    Array.prototype.forEach.call(wm.querySelectorAll('input[name=choice]'), function (r) {
      r.addEventListener('change', function () { wm.setAttribute('data-choice', r.value); });
    });
    var checked = wm.querySelector('input[name=choice]:checked');
    if (checked) wm.setAttribute('data-choice', checked.value);
    form.addEventListener('submit', function (e) { var b = e.submitter || form.querySelector('.wbtn'); if (b) b.setAttribute('aria-busy', 'true'); });
  }

  // step 3: suggestions rise one after another, and a field that was just filled flashes yellow once
  var wd = document.querySelector('[data-wd]');
  if (wd) {
    var out = wd.querySelector('[data-assist-out]');
    new MutationObserver(function () {
      Array.prototype.forEach.call(out.querySelectorAll('.pick, .chip-btn'), function (el, i) { el.style.setProperty('--k', i); });
    }).observe(out, { childList: true });
    wd.addEventListener('input', function (e) {
      if (!e.target.matches('.wf__in') || e.isTrusted) return;                 // only programmatic fills (assist.js dispatches synthetic events)
      e.target.classList.remove('is-filled'); void e.target.offsetWidth; e.target.classList.add('is-filled');
    });
  }

  var wl = document.querySelector('[data-wl]');
  if (!wl) return;
  var input = wl.querySelector('#logo-file'), drop = wl.querySelector('[data-drop]');
  var title = wl.querySelector('[data-drop-t]'), sub = wl.querySelector('[data-drop-s]');
  var err = wl.querySelector('[data-err]'), tile = wl.querySelector('[data-tile]');
  var maxBytes = (parseInt(wl.getAttribute('data-max'), 10) || 1400) * 1024;
  var OK = ['image/png', 'image/jpeg', 'image/webp'];

  function fail(msg) { err.textContent = msg; err.hidden = !msg; }
  function take(file) {
    if (!file) return;
    if (OK.indexOf(file.type) < 0 || file.size > maxBytes) { input.value = ''; drop.classList.remove('has-file'); fail(wl.getAttribute('data-err-type')); return; }
    fail('');
    var rd = new FileReader();
    rd.onload = function () {
      var t = tile.querySelector('.org-tile');
      t.innerHTML = ''; var img = document.createElement('img'); img.alt = ''; img.src = rd.result; t.appendChild(img);
      tile.classList.remove('is-pop'); void tile.offsetWidth; tile.classList.add('is-pop');
    };
    rd.readAsDataURL(file);
    title.textContent = file.name;
    sub.textContent = '\u200E' + Math.max(1, Math.round(file.size / 1024)) + ' KB';
    drop.classList.remove('has-file'); void drop.offsetWidth; drop.classList.add('has-file');
  }
  drop.addEventListener('click', function () { input.click(); });
  input.addEventListener('change', function () { take(input.files && input.files[0]); });
  var depth = 0;
  wl.addEventListener('dragenter', function (e) { if (e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') > -1) { e.preventDefault(); depth++; wl.classList.add('is-drag'); } });
  wl.addEventListener('dragover', function (e) { if (wl.classList.contains('is-drag')) e.preventDefault(); });
  wl.addEventListener('dragleave', function () { depth = Math.max(0, depth - 1); if (!depth) wl.classList.remove('is-drag'); });
  wl.addEventListener('drop', function (e) {
    if (!wl.classList.contains('is-drag')) return;
    e.preventDefault(); depth = 0; wl.classList.remove('is-drag');
    var f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (!f) return;
    try { input.files = e.dataTransfer.files; } catch (_) {}
    take(f);
  });
})();
