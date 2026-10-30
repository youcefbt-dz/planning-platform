/* Marketing site: sticky header, mobile menu, active section link. No animation libraries. */
(() => {
  const header = document.querySelector('.site-header');
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.getElementById('site-nav');

  const onScroll = () => {
    if (!header || header.classList.contains('site-header--solid')) return;
    header.classList.toggle('is-sticky', window.scrollY > 40);
  };
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  if (toggle && nav) {
    toggle.addEventListener('click', () => {
      const open = nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(open));
      if (open && header) header.classList.add('is-sticky');
      else onScroll();
    });
    nav.addEventListener('click', (e) => {
      if (e.target.closest('a')) { nav.classList.remove('is-open'); toggle.setAttribute('aria-expanded', 'false'); onScroll(); }
    });
  }

  // highlight the nav link of the section in view
  const links = [...document.querySelectorAll('.site-nav a[href*="#"]')];
  const map = links.map((a) => [a, document.getElementById(a.hash.slice(1))]).filter(([, s]) => s);
  if (map.length && 'IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        const link = map.find(([, s]) => s === en.target)?.[0];
        if (link) link.classList.toggle('active', en.isIntersecting);
      });
    }, { rootMargin: '-40% 0px -50% 0px' });
    map.forEach(([, s]) => io.observe(s));
  }

  // close the language menu on outside click
  document.addEventListener('click', (e) => {
    document.querySelectorAll('details.lang-menu[open]').forEach((d) => { if (!d.contains(e.target)) d.removeAttribute('open'); });
  });
})();
