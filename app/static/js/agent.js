/* The assistant's chat (PlanWise: the person's travel companion). The server is stateless: each turn sends the (short) conversation and gets back the answer,
   the tools it used, follow-up suggestions, and any drafted goals (rendered by the server). Nothing is written until the person presses "approve" on a draft card. */
(function () {
  'use strict';
  var root = document.querySelector('[data-dock-root]') || document.querySelector('[data-agent]');
  if (!root) return;
  var thread = root.querySelector('[data-thread]'), form = root.querySelector('[data-form]'), input = root.querySelector('[data-input]'), send = root.querySelector('[data-send]');
  var hello = root.querySelector('[data-hello]');
  var helloHTML = hello ? hello.outerHTML : '';
  var panel = root.querySelector('[data-dock-panel]');
  var launcher = root.querySelector('[data-dock-open]');
  var suggestBox = root.querySelector('[data-suggest]');
  var teaser = root.querySelector('[data-teaser]');
  var markSvg = root.querySelector('.assistant-dock__mark svg');
  var AVATAR = '<span class="ag__avatar" aria-hidden="true">' + (markSvg ? markSvg.outerHTML : '') + '</span>';
  var token = (document.querySelector('meta[name=csrf-token]') || {}).content || '';
  var floating = root.classList.contains('ag--floating');
  var KEY = root.dataset.historyKey || ('planwise.agent.' + location.pathname);
  var HIDDEN_KEY = root.dataset.preferenceKey || '';
  var history = [], busy = false;
  var L = root.dataset;
  var visibilityToggle = document.querySelector('[data-assistant-visibility]');
  var voiceToggle = root.querySelector('[data-voice-toggle]');
  var VOICE_KEY = root.dataset.voiceKey || ('planwise.agent.voice.' + location.pathname);
  var speechSupported = !!(window.speechSynthesis && window.SpeechSynthesisUtterance);
  var autoVoice = true, activeSpeakButton = null, speechGeneration = 0;

  function readVoicePreference() {
    try {
      var saved = localStorage.getItem(VOICE_KEY);
      return saved === null ? true : saved === '1';
    } catch (_) { return true; }
  }
  function updateVoiceToggle() {
    if (!voiceToggle) return;
    var on = voiceToggle.querySelector('[data-voice-icon-on]');
    var off = voiceToggle.querySelector('[data-voice-icon-off]');
    if (!speechSupported) {
      voiceToggle.disabled = true;
      voiceToggle.title = L.lNoVoice || 'الصوت غير متاح في هذا المتصفح';
      voiceToggle.setAttribute('aria-label', voiceToggle.title);
      voiceToggle.setAttribute('aria-pressed', 'false');
      if (on) on.hidden = true;
      if (off) off.hidden = false;
      return;
    }
    voiceToggle.setAttribute('aria-pressed', autoVoice ? 'true' : 'false');
    voiceToggle.title = autoVoice ? (L.lVoiceOn || 'إيقاف القراءة التلقائية') : (L.lVoiceOff || 'تشغيل القراءة التلقائية');
    voiceToggle.setAttribute('aria-label', voiceToggle.title);
    if (on) on.hidden = !autoVoice;
    if (off) off.hidden = autoVoice;
  }
  function setAutoVoice(enabled) {
    autoVoice = !!enabled;
    try { localStorage.setItem(VOICE_KEY, autoVoice ? '1' : '0'); } catch (_) {}
    updateVoiceToggle();
    if (!autoVoice) stopSpeech();
  }
  function speechText(value) {
    return String(value || '')
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/\*\*(.*?)\*\*/g, '$1')
      .replace(/^\s*[-•*]\s+/gm, '')
      .replace(/[#*_`>|]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }
  function findSpeechVoice(arabic) {
    var voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : [];
    var langPrefix = arabic ? 'ar' : ((document.documentElement.lang || navigator.language || 'en').split('-')[0].toLowerCase());
    var matching = voices.filter(function (v) { return String(v.lang || '').toLowerCase().indexOf(langPrefix) === 0; });
    matching.sort(function (a, b) {
      function score(v) {
        var n = String(v.name || '').toLowerCase(), pts = 0;
        if (/natural|neural|online/.test(n)) pts += 5;
        if (/google|microsoft/.test(n)) pts += 4;
        if (/arabic|العربية|hoda|naayf|salma/.test(n) && arabic) pts += 2;
        if (v.localService === false) pts += 1;
        return pts;
      }
      return score(b) - score(a);
    });
    return matching[0] || null;
  }
  function speechChunks(value) {
    var textValue = speechText(value), sentences = textValue.match(/[^.!؟?؛]+[.!؟?؛]?/g) || [textValue], out = [], current = '';
    sentences.forEach(function (part) {
      part = part.trim();
      while (part.length > 230) {
        var cut = part.lastIndexOf(' ', 230);
        if (cut < 100) cut = 230;
        if (current) { out.push(current); current = ''; }
        out.push(part.slice(0, cut).trim());
        part = part.slice(cut).trim();
      }
      if (!part) return;
      if ((current + ' ' + part).trim().length > 230) { out.push(current); current = part; }
      else current = (current + ' ' + part).trim();
    });
    if (current) out.push(current);
    return out.filter(Boolean);
  }
  function finishSpeech(button) {
    root.classList.remove('is-speaking');
    if (button) {
      button.classList.remove('is-playing');
      button.setAttribute('aria-label', L.lListen || 'استمع إلى الإجابة');
      var label = button.querySelector('span');
      if (label) label.textContent = L.lListen || 'استمع';
    }
    if (activeSpeakButton === button) activeSpeakButton = null;
  }
  function stopSpeech() {
    speechGeneration += 1;
    if (speechSupported) window.speechSynthesis.cancel();
    finishSpeech(activeSpeakButton);
    activeSpeakButton = null;
  }
  function speakAnswer(value, button) {
    if (!speechSupported) {
      if (button) { var noVoice = button.querySelector('span'); if (noVoice) noVoice.textContent = L.lNoVoice || 'الصوت غير متاح'; }
      return;
    }
    var chunks = speechChunks(value);
    if (!chunks.length) return;
    stopSpeech();
    var generation = speechGeneration;
    var arabic = /[\u0600-\u06FF]/.test(value);
    var voice = findSpeechVoice(arabic);
    activeSpeakButton = button || null;
    if (button) {
      button.classList.add('is-playing');
      button.setAttribute('aria-label', L.lStop || 'إيقاف الصوت');
      var label = button.querySelector('span');
      if (label) label.textContent = L.lStop || 'إيقاف';
    }
    var index = 0;
    function nextChunk() {
      if (generation !== speechGeneration) return;
      if (index >= chunks.length) { finishSpeech(button || null); return; }
      var utterance = new SpeechSynthesisUtterance(chunks[index++]);
      utterance.lang = voice ? voice.lang : (arabic ? 'ar-SA' : (document.documentElement.lang || 'en-US'));
      if (voice) utterance.voice = voice;
      utterance.rate = arabic ? 0.94 : 0.97;
      utterance.pitch = 1.02;
      utterance.volume = 1;
      utterance.onstart = function () { if (generation === speechGeneration) root.classList.add('is-speaking'); };
      utterance.onend = nextChunk;
      utterance.onerror = function () { if (generation === speechGeneration) finishSpeech(button || null); };
      try { window.speechSynthesis.speak(utterance); }
      catch (_) { if (generation === speechGeneration) finishSpeech(button || null); }
    }
    root.classList.remove('is-thinking');
    root.classList.add('is-speaking');
    nextChunk();
  }
  function replyTools(value) {
    value = String(value || '');
    if (!value.trim()) return '';
    var copy = '<button class="assistant-dock__reply-audio" type="button" data-copy data-text="' + esc(value) + '" aria-label="' + esc(L.lCopy || 'نسخ الإجابة') + '"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></svg><span>' + esc(L.lCopy || 'نسخ') + '</span></button>';
    var listen = speechSupported ? '<button class="assistant-dock__reply-audio" type="button" data-speak data-speech="' + esc(value) + '" aria-label="' + esc(L.lListen || 'استمع إلى الإجابة') + '"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></svg><span>' + esc(L.lListen || 'استمع') + '</span></button>' : '';
    return '<div class="assistant-dock__reply-tools">' + listen + copy + '</div>';
  }
  function copyText(text, btn) {
    var label = btn.querySelector('span'), old = label ? label.textContent : '';
    function done() { if (label) { label.textContent = L.lCopied || 'نُسخت'; setTimeout(function () { label.textContent = old; }, 1600); } }
    function fallback() {
      var ta = document.createElement('textarea'); ta.value = text; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
      document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); done(); } catch (_) {} ta.remove();
    }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, fallback); else fallback();
  }
  autoVoice = speechSupported ? readVoicePreference() : false;
  if (voiceToggle && !speechSupported) {
    voiceToggle.disabled = true;
    voiceToggle.title = L.lNoVoice || 'الصوت غير متاح في هذا المتصفح';
    voiceToggle.setAttribute('aria-label', voiceToggle.title);
  }
  updateVoiceToggle();


  function readHidden() {
    try { return HIDDEN_KEY && localStorage.getItem(HIDDEN_KEY) === '1'; } catch (_) { return false; }
  }
  function writeHidden(hidden) {
    try {
      if (!HIDDEN_KEY) return;
      if (hidden) localStorage.setItem(HIDDEN_KEY, '1');
      else localStorage.removeItem(HIDDEN_KEY);
    } catch (_) {}
  }

  function setPanelOpen(open) {
    if (!panel) return;
    panel.hidden = !open;
    if (launcher) launcher.setAttribute('aria-expanded', open ? 'true' : 'false');
    root.classList.toggle('is-open', !!open);
    if (open && teaser) teaser.hidden = true;
    if (open && input) input.focus();
    if (open) bottom();
  }

  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function md(text) {                       // paragraphs, "- " lists, "1. " lists and **bold**: nothing else, always escaped first
    var out = [], list = null;
    function close() { if (list) { out.push('</' + list + '>'); list = null; } }
    function inline(x) { return esc(x).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>'); }
    String(text || '').split(/\n/).forEach(function (line) {
      var ul = /^\s*[-•*]\s+(.*)$/.exec(line), ol = /^\s*\d+[.)]\s+(.*)$/.exec(line), m = ul || ol;
      if (m) {
        var kind = ul ? 'ul' : 'ol';
        if (list !== kind) { close(); out.push('<' + kind + '>'); list = kind; }
        out.push('<li>' + inline(m[1]) + '</li>');
        return;
      }
      close();
      if (line.trim()) out.push('<p>' + inline(line) + '</p>');
    });
    close();
    return out.join('');
  }
  function save() { try { sessionStorage.setItem(KEY, JSON.stringify(history.slice(-14))); } catch (_) {} }
  function bottom() { thread.scrollTop = thread.scrollHeight; if (!floating) window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' }); }
  function hideHello() { if (hello) { hello.remove(); hello = null; } }
  function add(role, html, cls) {
    hideHello();
    var el = document.createElement('div'); el.className = 'ag__msg ag__msg--' + role + (cls ? ' ' + cls : '');
    el.innerHTML = role === 'bot' ? AVATAR + '<div class="ag__bubble" data-body>' + html + '</div>' : html;
    thread.appendChild(el); bottom(); return el;
  }
  function body(el) { return el.querySelector('[data-body]') || el; }
  function chips(steps) {
    if (!steps || !steps.length) return '';
    return '<div class="ag__steps">' + steps.map(function (s) { return '<span class="ag__step' + (s.ok ? '' : ' is-bad') + '">' + esc(s.label) + '</span>'; }).join('') + '</div>';
  }
  function showSuggest(list) {
    if (!suggestBox) return;
    list = (list || []).filter(Boolean).slice(0, 3);
    suggestBox.innerHTML = list.map(function (q) { return '<button class="chip-btn" type="button" data-ask="' + esc(q) + '">' + esc(q) + '</button>'; }).join('');
    suggestBox.hidden = !list.length;
  }
  function render(res) {
    var badge = res.mode === 'model'
      ? '<span class="ag__by">' + esc(res.provider || '') + (res.model ? ' · ' + esc(res.model) : '') + '</span>' : '';
    var warn = res.unverified && res.unverified.length ? '<p class="ag__warn">' + esc(L.lUnverified) + ': <bdi dir="ltr">' + res.unverified.map(function (n) { return esc(n); }).join(', ') + '</bdi></p>' : '';
    var off = res.mode !== 'model' && res.offText ? '<p class="ag__rules">' + esc(res.offText) + '</p>' : '';
    return chips(res.steps) + '<div class="ag__text">' + md(res.answer) + '</div>' + replyTools(res.answer) + warn + (res.proposals_html || '') + off + badge;
  }
  function typing() { return '<span class="ag__dots" role="status" aria-label="..."><i></i><i></i><i></i></span>'; }
  function ask(text) {
    text = (text || '').trim(); if (!text || busy) return;
    stopSpeech();
    busy = true; send.disabled = true; input.value = ''; grow(); showSuggest([]);
    history.push({ role: 'user', content: text });
    add('user', '<div class="ag__text"><p>' + esc(text) + '</p></div>');
    root.classList.remove('is-speaking');
    root.classList.add('is-thinking');
    var wait = add('bot', typing(), 'is-wait');
    fetch(root.dataset.endpoint, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token, 'X-Requested-With': 'fetch' },
      body: JSON.stringify({ messages: history.slice(-14) }) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || 'x'); return j; }); })
      .then(function (res) {
        res.offText = res.off_text || '';
        wait.classList.remove('is-wait'); body(wait).innerHTML = render(res);
        root.classList.remove('is-thinking');
        history.push({ role: 'assistant', content: res.answer || '' }); save();
        showSuggest(res.suggestions);
        if (autoVoice && res.answer) speakAnswer(res.answer, wait.querySelector('[data-speak]'));
      })
      .catch(function (e) { root.classList.remove('is-thinking'); wait.classList.remove('is-wait'); body(wait).innerHTML = '<div class="ag__text"><p class="ag__warn">' + esc(e && e.message && e.message !== 'x' && e.message !== 'Failed to fetch' ? e.message : L.lError) + '</p></div>'; history.pop(); })
      .then(function () { busy = false; send.disabled = false; bottom(); if (!floating || (panel && !panel.hidden)) input.focus(); });
  }
  function grow() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 160) + 'px'; }
  function reset() {                          // a fresh conversation: forget this chat (only in this tab), bring the welcome back
    stopSpeech(); history = []; save(); showSuggest([]);
    thread.innerHTML = helloHTML; hello = thread.querySelector('[data-hello]');
    if (input) { input.value = ''; grow(); input.focus(); }
  }
  function maybeTeaser() {                    // once per browser tab, only when the chat is empty: a friendly hello above the launcher
    if (!teaser || history.length || root.hidden || (panel && !panel.hidden)) return;
    var key = root.dataset.teaserKey || '';
    try { if (key && sessionStorage.getItem(key)) return; sessionStorage.setItem(key, '1'); } catch (_) {}
    setTimeout(function () {
      if (root.hidden || (panel && !panel.hidden)) return;
      teaser.hidden = false;
      setTimeout(function () { teaser.hidden = true; }, 9000);
    }, 1800);
  }

  form.addEventListener('submit', function (e) { e.preventDefault(); ask(input.value); });
  input.addEventListener('input', grow);
  input.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); } });
  root.addEventListener('click', function (e) {
    var open = e.target.closest('[data-dock-open]');
    if (open) { setPanelOpen(true); return; }
    var close = e.target.closest('[data-dock-close]');
    if (close) { setPanelOpen(false); return; }
    var tclose = e.target.closest('[data-teaser-close]');
    if (tclose) { if (teaser) teaser.hidden = true; return; }
    var again = e.target.closest('[data-chat-reset]');
    if (again) { reset(); return; }
    var voiceSwitch = e.target.closest('[data-voice-toggle]');
    if (voiceSwitch) { setAutoVoice(!autoVoice); return; }
    var copyButton = e.target.closest('[data-copy]');
    if (copyButton) { copyText(copyButton.getAttribute('data-text') || '', copyButton); return; }
    var speakButton = e.target.closest('[data-speak]');
    if (speakButton) {
      if (activeSpeakButton === speakButton && root.classList.contains('is-speaking')) stopSpeech();
      else speakAnswer(speakButton.getAttribute('data-speech') || '', speakButton);
      return;
    }
    var a = e.target.closest('[data-ask]'); if (a) { ask(a.getAttribute('data-ask')); return; }
    var b = e.target.closest('[data-apply]'); if (!b) return;
    var card = b.closest('[data-proposal]'), p; try { p = JSON.parse(card.getAttribute('data-proposal')); } catch (_) { return; }
    b.disabled = true; b.textContent = L.lApproving;
    fetch(root.dataset.applyUrl, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token }, body: JSON.stringify({ proposal: p }) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok || !j.ok) throw new Error(j.error || L.lError); return j; }); })
      .then(function (j) { card.classList.add('is-done'); card.querySelector('.apr__foot').innerHTML = '<a class="btn btn-primary" href="' + esc(j.url) + '">' + esc(L.lOpen) + '</a>'; })
      .catch(function (err) { b.disabled = false; b.textContent = '↻'; var w = document.createElement('p'); w.className = 'ag__warn'; w.textContent = err.message; card.appendChild(w); });
  });
  if (floating) {
    document.addEventListener('pointerdown', function (e) {
      if (panel && !panel.hidden && !root.contains(e.target)) setPanelOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && panel && !panel.hidden) setPanelOpen(false);
    });
  }

  if (visibilityToggle) {
    visibilityToggle.addEventListener('change', function () {
      var hidden = !visibilityToggle.checked;
      writeHidden(hidden);
      if (hidden) { setPanelOpen(false); stopSpeech(); }
      root.hidden = hidden;
    });
  }

  var hidden = readHidden();
  root.hidden = hidden;
  if (visibilityToggle) visibilityToggle.checked = !hidden;
  try {
    var prev = JSON.parse(sessionStorage.getItem(KEY) || '[]');
    if (prev.length) {
      history = prev; hideHello();
      prev.forEach(function (m) { add(m.role === 'user' ? 'user' : 'bot', '<div class="ag__text">' + md(m.content) + '</div>' + (m.role === 'assistant' ? replyTools(m.content) : '')); });
    }
  } catch (_) {}
  if (!floating) input.focus();
  maybeTeaser();
})();
