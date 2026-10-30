/* Auth experience: a golden plan-path across a living terrain.
   The form stays a plain HTML form; all motion is enhancement. */
(() => {
  'use strict';

  const root = document.querySelector('[data-auth]');
  if (!root) return;

  const form = root.querySelector('[data-auth-form]');
  const fields = form ? Array.from(form.querySelectorAll('[data-auth-field]')) : [];
  const calm = window.matchMedia('(prefers-reduced-motion: reduce)');

  /* ---- field completion fills the golden path ----------------------------- */
  const complete = (field) => {
    const input = field.querySelector('input');
    if (!input || input.disabled) return false;
    const value = input.value.trim();
    if (!value) return false;
    if (input.type === 'email') return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value);
    if (input.type === 'password') {
      const min = Number(input.getAttribute('minlength')) || 1;
      return value.length >= min;
    }
    return true;
  };

  const gold = root.querySelector('[data-journey-progress]');

  const paintProgress = () => {
    let done = 0;
    fields.forEach((field) => {
      const ok = complete(field);
      field.classList.toggle('is-complete', ok);
      if (ok) done += 1;
    });
    const total = fields.length || 1;
    if (gold) gold.style.strokeDashoffset = String(100 - Math.round((done / total) * 100));
    root.classList.toggle('is-filled', done === total && total > 0);
    const marks = root.querySelectorAll('[data-station]');
    marks.forEach((station, index) => {
      station.classList.toggle('is-done', (index + 1) / marks.length <= done / total + 1e-6);
    });
  };

  fields.forEach((field) => {
    const input = field.querySelector('input');
    if (!input) return;
    input.addEventListener('input', paintProgress);
    input.addEventListener('change', paintProgress);
    input.addEventListener('blur', paintProgress);
  });
  paintProgress();

  /* ---- password reveal ---------------------------------------------------- */
  form && form.querySelectorAll('[data-auth-eye]').forEach((button) => {
    button.addEventListener('click', () => {
      const input = document.getElementById(button.getAttribute('aria-controls'));
      if (!input) return;
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      button.classList.toggle('is-on', show);
      button.setAttribute('aria-pressed', String(show));
      const label = show ? button.getAttribute('data-hide-label') : button.getAttribute('data-show-label');
      if (label) button.setAttribute('aria-label', label);
      input.focus({ preventScroll: true });
      if (input.value) paintProgress();
    });
  });

  /* ---- the comet: a light climbing the golden road ------------------------- */
  const journey = root.querySelector('[data-journey]');
  const art = journey && journey.querySelector('.journey__art');
  const stations = journey ? Array.from(journey.querySelectorAll('[data-station]')) : [];
  const comet = journey && journey.querySelector('[data-comet]');
  const trail = journey && journey.querySelector('[data-journey-trail]');
  const parts = comet ? Array.from(comet.querySelectorAll('i')) : [];

  if (journey && art && gold && comet && parts.length) {
    const STEP = 12;
    const TAIL_LEN = STEP * (parts.length - 1);
    let total = 0;
    let at = 0;
    let raf = 0;
    let last = 0;
    let live = [];

    const measure = () => {
      total = gold.getTotalLength();
      live = stations.map((station) => total * (parseFloat(station.dataset.at) || 0));
    };

    const draw = () => {
      const ctm = gold.getScreenCTM();
      if (!ctm) return;
      const box = art.getBoundingClientRect();

      parts.forEach((part, index) => {
        const point = gold.getPointAtLength(((at - index * STEP) % total + total) % total);
        const x = ctm.a * point.x + ctm.c * point.y + ctm.e - box.left;
        const y = ctm.b * point.x + ctm.d * point.y + ctm.f - box.top;
        const scale = Math.max(0.18, 1 - index * 0.062);
        part.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%) scale(${scale})`;
        part.style.opacity = String(Math.max(0.14, 0.95 - index * 0.062));
      });

      if (trail) {
        trail.style.strokeDasharray = `${TAIL_LEN} ${Math.ceil(total)}`;
        trail.style.strokeDashoffset = String(TAIL_LEN - at);
      }

      stations.forEach((station, index) => {
        const half = total / 2;
        const delta = Math.abs((((at - live[index]) % total) + total + half) % total - half);
        station.classList.toggle('is-live', delta < 42);
      });
    };

    const rate = () => {
      if (root.classList.contains('is-launching')) return 0.55;
      if (root.classList.contains('is-engaged')) return 0.085;
      return 0.03;
    };

    const tick = (now) => {
      if (!last) last = now;
      const step = Math.min(now - last, 48);
      last = now;
      at += total * rate() * (step / 1000);
      draw();
      raf = window.requestAnimationFrame(tick);
    };

    const staticFrame = () => {
      at = total * 0.62;
      draw();
      root.classList.add('is-ready');
    };

    const start = () => {
      if (calm.matches || document.hidden) { staticFrame(); return; }
      root.classList.add('is-ready');
      if (!raf) {
        last = 0;
        raf = window.requestAnimationFrame(tick);
      }
    };

    const stop = () => {
      if (raf) window.cancelAnimationFrame(raf);
      raf = 0;
    };

    measure();
    at = total * 0.08;
    draw();
    start();
    if ('ResizeObserver' in window) new ResizeObserver(() => { measure(); draw(); }).observe(journey);
    else window.addEventListener('resize', () => { measure(); draw(); });

    calm.addEventListener && calm.addEventListener('change', () => {
      stop();
      if (calm.matches) staticFrame(); else start();
    });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) stop();
      else if (!calm.matches) start();
    });

    if (form) {
      form.addEventListener('focusin', () => {
        root.classList.add('is-engaged');
        if (calm.matches) staticFrame();
      });
      form.addEventListener('focusout', (event) => {
        if (!form.contains(event.relatedTarget)) root.classList.remove('is-engaged');
      });
    }
  }

  /* ---- submission: a short launch, then the ordinary form post ------------ */
  if (form) {
    form.addEventListener('submit', (event) => {
      if (event.defaultPrevented || form.dataset.launching) {
        event.preventDefault();
        return;
      }
      form.dataset.launching = '1';
      root.classList.add('is-launching');

      const button = form.querySelector('button[type="submit"]');
      if (button) {
        button.setAttribute('aria-busy', 'true');
        button.disabled = true;
        const label = button.querySelector('.auth-submit__label');
        if (label && button.dataset.busyLabel) label.textContent = button.dataset.busyLabel;
      }

      if (!calm.matches) {
        event.preventDefault();
        window.setTimeout(() => {
          HTMLFormElement.prototype.submit.call(form);
        }, 420);
      }
    });
  }
})();
