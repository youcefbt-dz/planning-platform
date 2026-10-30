/* App shell behaviours. Progressive enhancement only: every page works without this file. */
(() => {
  // "/" focuses the search box (GitHub convention)
  document.addEventListener('keydown', (e) => {
    if (e.key !== '/' || e.target.closest('input,textarea,select,[contenteditable]')) return;
    const s = document.querySelector('.topsearch input');
    if (s) { e.preventDefault(); s.focus(); }
  });

  // close <details> menus on outside click / Escape
  const menus = () => document.querySelectorAll('details.menu[open]');
  document.addEventListener('click', (e) => menus().forEach((d) => { if (!d.contains(e.target)) d.removeAttribute('open'); }));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') menus().forEach((d) => d.removeAttribute('open')); });

  // forms that submit when a filter changes
  document.querySelectorAll('form[data-autosubmit]').forEach((f) => {
    f.querySelectorAll('select').forEach((s) => s.addEventListener('change', () => f.submit()));
  });

  // confirmation for destructive actions (form[data-confirm] or button[data-confirm])
  document.addEventListener('submit', (e) => {
    const f = e.target;
    const msg = (e.submitter && e.submitter.dataset.confirm) || f.dataset.confirm;
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // print button
  document.querySelectorAll('[data-print]').forEach((b) => b.addEventListener('click', () => window.print()));

  // chart tooltips: any element with data-tip inside [data-chart]. Re-run on HTML fetched later: window.initCharts(root)
  window.initCharts = (root) => (root || document).querySelectorAll('[data-chart]').forEach((wrap) => {
    if (wrap.dataset.tipReady) return;
    wrap.dataset.tipReady = '1';
    const tip = document.createElement('div');
    tip.className = 'tip';
    tip.hidden = true;
    wrap.appendChild(tip);
    wrap.addEventListener('pointerover', (e) => {
      const el = e.target.closest('[data-tip]');
      if (!el) return;
      const r = el.getBoundingClientRect(), w = wrap.getBoundingClientRect();
      tip.textContent = el.dataset.tip;
      tip.style.left = `${r.left - w.left + r.width / 2}px`;
      tip.style.top = `${r.top - w.top}px`;
      tip.hidden = false;
    });
    wrap.addEventListener('pointerout', (e) => { if (e.target.closest('[data-tip]')) tip.hidden = true; });
  });
  window.initCharts();
})();
