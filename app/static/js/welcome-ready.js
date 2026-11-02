(function () {
  'use strict';
  var page = document.querySelector('[data-ready]');
  if (!page) return;

  var steps = Array.prototype.slice.call(page.querySelectorAll('[data-ready-step]'));
  var progress = page.querySelector('[data-ready-progress]');
  var title = page.querySelector('[data-ready-title]');
  var description = page.querySelector('[data-ready-description]');
  var auto = page.querySelector('[data-ready-auto]');
  var overview = page.getAttribute('data-overview');
  var doneText = page.getAttribute('data-done');
  var activeText = page.getAttribute('data-active');
  var pendingText = page.getAttribute('data-pending');
  var openingText = page.getAttribute('data-opening');

  function setStep(index, state) {
    var item = steps[index];
    if (!item) return;
    item.classList.remove('is-done', 'is-active', 'is-pending');
    item.classList.add('is-' + state);
    if (state === 'active') item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
    var label = item.querySelector('[data-ready-status]');
    if (label) label.textContent = state === 'done' ? doneText : state === 'active' ? activeText : pendingText;
  }

  function finish() {
    if (title) title.textContent = page.getAttribute('data-complete-title');
    if (description) description.textContent = page.getAttribute('data-complete-sub');
    if (auto) auto.textContent = openingText || '';
    if (overview) window.setTimeout(function () { window.location.replace(overview); }, 650);
  }

  // The first two rows reflect the settings already saved by the previous steps.
  // Only the final visual hand-off is animated here; the page does not simulate backend work.
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var pace = reduced ? 320 : 680;
  window.setTimeout(function () {
    setStep(2, 'done');
    setStep(3, 'active');
    if (progress) progress.style.width = '82%';
  }, pace);
  window.setTimeout(function () {
    setStep(3, 'done');
    if (progress) progress.style.width = '100%';
    if (page.getAttribute('data-complete-title')) finish();
  }, pace * 2 + 220);
})();
