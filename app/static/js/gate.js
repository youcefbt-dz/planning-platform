/* Gate (sign-in / sign-up / invitation): what is typed in the card is mirrored on the stage, and nothing else.
   - org name  -> the organization node (initials tile turns yellow)
   - name/email -> a small "who" chip under it
   - password focus / typing -> the padlock closes; Caps Lock warning; show/hide
   - register: a four-step strength hint (advice only: the server's rule is eight characters)
   - submit -> the chain lights up (go); a rejected attempt (server error) -> the node shakes (denied)
   Everything works without this file: it is only a mirror. */
(function () {
  'use strict';
  var gate = document.querySelector('[data-gate]');
  if (!gate) return;
  var $ = function (s, r) { return (r || gate).querySelector(s); };
  var orgName = $('[data-org-name]'), tile = $('[data-tile]');
  var tileHTML = tile ? tile.innerHTML : '';
  var userIni = $('[data-user-ini]'), userName = $('[data-user-name]');
  var form = $('[data-gform]');

  // same idea as app/core/profile.initials: skip the Arabic article, first letters of the first two words
  function initials(name) {
    var parts = name.trim().split(/\s+/).filter(Boolean);
    parts = parts.map(function (p) { return (p.indexOf('\u0627\u0644') === 0 && p.length > 3) ? p.slice(2) : p; });
    if (!parts.length) return '';
    return (Array.from(parts[0])[0] + (parts[1] ? Array.from(parts[1])[0] : '')).toUpperCase();
  }
  function setOrg(name) {
    name = (name || '').trim();
    if (!orgName) return;
    orgName.textContent = name || orgName.getAttribute('data-empty');
    orgName.classList.toggle('is-empty', !name);
    tile.classList.toggle('is-set', !!name);
    tile.textContent = name ? initials(name) : '';
    if (!name) tile.innerHTML = tileHTML;
  }
  function setUser(label, ini) {
    label = (label || '').trim();
    if (label) { gate.setAttribute('data-user', ''); userName.textContent = label; userIni.textContent = ini || Array.from(label)[0].toUpperCase(); }
    else { gate.removeAttribute('data-user'); }
  }

  var fixed = gate.getAttribute('data-fixed-org');
  if (fixed) setOrg(fixed);

  Array.prototype.forEach.call(gate.querySelectorAll('[data-live]'), function (inp) {
    var kind = inp.getAttribute('data-live');
    var on = function () {
      if (kind === 'org') setOrg(inp.value);
      else if (kind === 'user') setUser(inp.value);
      else if (kind === 'email') { var local = inp.value.split('@')[0]; setUser(local, local ? local[0].toUpperCase() : ''); }
      else if (kind === 'password') gate.setAttribute('data-lock', inp.value || document.activeElement === inp ? 'closed' : 'open');
    };
    inp.addEventListener('input', on);
    if (kind === 'password') {
      inp.addEventListener('focus', function () { gate.setAttribute('data-lock', 'closed'); });
      inp.addEventListener('blur', function () { gate.setAttribute('data-lock', inp.value ? 'closed' : 'open'); });
    }
    if (inp.value) on();                                  // browser autofill / a form re-shown after an error
  });

  // password: show / hide, Caps Lock, strength
  Array.prototype.forEach.call(gate.querySelectorAll('.gf'), function (gf) {
    var pw = $('input[type=password], input[data-was-password]', gf);
    if (!pw) return;
    var peek = $('[data-peek]', gf), caps = $('[data-caps]', gf);
    if (peek) peek.addEventListener('click', function () {
      var show = pw.type === 'password';
      pw.type = show ? 'text' : 'password'; pw.setAttribute('data-was-password', '');
      peek.setAttribute('aria-pressed', show ? 'true' : 'false');
      peek.setAttribute('aria-label', gate.getAttribute(show ? 'data-hide' : 'data-show'));
    });
    var capsCheck = function (e) { if (caps && e.getModifierState) caps.hidden = !e.getModifierState('CapsLock'); };
    pw.addEventListener('keydown', capsCheck); pw.addEventListener('keyup', capsCheck);
    pw.addEventListener('blur', function () { if (caps) caps.hidden = true; });
  });
  var meter = $('[data-meter]');
  if (meter) {
    var words = JSON.parse(gate.getAttribute('data-strength') || '[]'), hint = $('[data-meter-t]', meter), base = hint.textContent;
    var pwInput = gate.querySelector('input[name=password]');
    pwInput.addEventListener('input', function () {
      var v = pwInput.value, score = 0;
      if (v.length >= 8) score++;
      if (v.length >= 12) score++;
      if (/[a-z\u0600-\u06FF]/i.test(v) && /\d/.test(v)) score++;
      if (/[^\w\s\u0600-\u06FF]/.test(v) || (/[A-Z]/.test(v) && /[a-z]/.test(v) && v.length >= 10)) score++;
      if (!v) { meter.removeAttribute('data-level'); hint.textContent = base; return; }
      score = v.length < 8 ? 1 : Math.max(2, score);
      meter.setAttribute('data-level', String(Math.min(4, score)));
      hint.textContent = words[Math.min(4, score)];
    });
  }

  if (form) form.addEventListener('submit', function (e) {
    var b = e.submitter || form.querySelector('.gbtn');
    if (b) b.setAttribute('aria-busy', 'true');
    gate.setAttribute('data-state', 'go');
  });
  if (gate.hasAttribute('data-error')) {
    setTimeout(function () { gate.setAttribute('data-state', 'denied'); }, 900);
    setTimeout(function () { gate.removeAttribute('data-state'); }, 1700);
  }
})();
