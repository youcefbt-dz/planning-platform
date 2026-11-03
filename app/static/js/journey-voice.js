/* The spoken guide for the organization map. Uses signed, short audio chunks from the server
   when Groq speech is allowed; otherwise it falls back to the device's Arabic speech voice. */
(function () {
  'use strict';
  var player = document.querySelector('[data-voice-player]');
  var mapRoot = document.querySelector('[data-journey]');
  if (!player || !mapRoot) return;

  var openBtn = mapRoot.querySelector('[data-voice-open]');
  var closeBtn = player.querySelector('[data-voice-close]');
  var playBtn = player.querySelector('[data-voice-play]');
  var playLabel = player.querySelector('[data-voice-play-label]');
  var stopBtn = player.querySelector('[data-voice-stop]');
  var nextBtn = player.querySelector('[data-voice-next]');
  var prevBtn = player.querySelector('[data-voice-prev]');
  var voiceSelect = player.querySelector('[data-voice-voice]');
  var questionForm = player.querySelector('[data-voice-question-form]');
  var questionInput = player.querySelector('[data-voice-question]');
  var titleEl = player.querySelector('[data-voice-title]');
  var textEl = player.querySelector('[data-voice-text]');
  var counterEl = player.querySelector('[data-voice-counter]');
  var statusEl = player.querySelector('[data-voice-status]');
  var engineEl = player.querySelector('[data-voice-engine]');
  var progressEl = player.querySelector('[data-voice-progress]');
  var progressFill = player.querySelector('[data-voice-progress-fill]');
  var labels = player.dataset;
  var segments = [], parts = [], mode = 'browser', currentSegment = 0, currentPart = 0;
  var preparedBlob = null, preparedPart = -1, audio = null, objectUrl = null, utterance = null;
  var playing = false, busy = false, runSerial = 0;

  function token() {
    var el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.content : '';
  }
  function setStatus(text, tone) {
    statusEl.textContent = text || '';
    statusEl.dataset.tone = tone || '';
  }
  function setPlayLabel(paused) {
    playLabel.textContent = paused ? labels.labelPause : labels.labelPlay;
    var icon = playBtn.querySelector('svg');
    if (icon) {
      var path = icon.querySelector('path');
      if (path) path.setAttribute('d', paused ? 'M8 5v14M16 5v14' : 'm7 4 13 8-13 8z');
    }
  }
  function currentFocus(segment) {
    if (window.PlanWiseJourney && segment) window.PlanWiseJourney.focus(segment.kind, segment.id);
  }
  function showSegment(index) {
    if (!segments.length) return;
    currentSegment = Math.max(0, Math.min(index, segments.length - 1));
    var segment = segments[currentSegment];
    titleEl.textContent = segment.title || labels.labelPart;
    textEl.textContent = segment.text || '';
    counterEl.textContent = labels.labelPart + ' ' + (currentSegment + 1) + ' / ' + segments.length;
    var pct = Math.round((currentSegment / Math.max(segments.length, 1)) * 100);
    progressFill.style.width = pct + '%';
    progressEl.setAttribute('aria-valuenow', String(pct));
    prevBtn.disabled = currentSegment <= 0 || busy;
    nextBtn.disabled = currentSegment >= segments.length - 1 || busy;
    currentFocus(segment);
  }
  function releaseAudio() {
    if (audio) {
      audio.pause();
      audio.onended = audio.onerror = audio.onpause = null;
      audio = null;
    }
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = null;
    }
  }
  function stopPlayback(resetLabel) {
    runSerial++;
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    releaseAudio();
    playing = false;
    busy = false;
    if (resetLabel !== false) setPlayLabel(false);
  }
  function jsonPost(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token(), 'X-Requested-With': 'fetch' },
      body: JSON.stringify(body || {})
    }).then(function (response) {
      if (!response.ok) throw new Error('request_failed_' + response.status);
      return response.json();
    });
  }
  function fetchPart(index, serial) {
    var part = parts[index];
    if (!part) return Promise.reject(new Error('audio_part_missing'));
    setStatus(labels.labelPreparing);
    return fetch(player.dataset.speechUrl, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token(), 'X-Requested-With': 'fetch' },
      body: JSON.stringify({ token: part.token, voice: voiceSelect.value })
    }).then(function (response) {
      if (!response.ok) throw new Error('speech_unavailable');
      return response.blob();
    }).then(function (blob) {
      if (serial !== runSerial) return null;
      preparedBlob = blob;
      preparedPart = index;
      setStatus(labels.labelReady);
      return blob;
    });
  }
  function prepareFirst(serial) {
    if (mode !== 'groq' || !parts.length) {
      setStatus(labels.labelReady);
      playBtn.disabled = !('speechSynthesis' in window);
      return Promise.resolve();
    }
    return fetchPart(0, serial).then(function () {
      if (serial !== runSerial) return;
      currentPart = 0;
      playBtn.disabled = false;
    }).catch(function () {
      if (serial !== runSerial) return;
      mode = 'browser';
      engineEl.textContent = labels.labelBrowser;
      setStatus(labels.labelReady);
      playBtn.disabled = !('speechSynthesis' in window);
    });
  }
  function start(focus) {
    stopPlayback();
    var serial = ++runSerial;
    segments = []; parts = []; currentSegment = 0; currentPart = 0;
    preparedBlob = null; preparedPart = -1; mode = 'browser';
    player.hidden = false;
    if (openBtn) openBtn.setAttribute('aria-expanded', 'true');
    mapRoot.classList.add('has-voice');
    titleEl.textContent = labels.labelIntro || 'قراءة ذكية للمخطط';
    textEl.textContent = labels.labelWait;
    counterEl.textContent = labels.labelPart + ' —';
    progressFill.style.width = '0%'; progressEl.setAttribute('aria-valuenow', '0');
    playBtn.disabled = true; stopBtn.disabled = true; nextBtn.disabled = true; prevBtn.disabled = true;
    setStatus(labels.labelWait);
    engineEl.textContent = labels.labelWait;
    jsonPost(player.dataset.explainUrl, focus ? { focus: focus } : {}).then(function (data) {
      if (serial !== runSerial) return;
      segments = Array.isArray(data.segments) ? data.segments : [];
      parts = Array.isArray(data.parts) ? data.parts : [];
      if (!segments.length) throw new Error('empty_narration');
      mode = data.tts_available && parts.length ? 'groq' : 'browser';
      engineEl.textContent = (data.provider === 'model' ? labels.labelModel : labels.labelRules) + (mode === 'browser' ? ' · ' + labels.labelBrowser : ' · Groq');
      showSegment(0);
      stopBtn.disabled = false;
      nextBtn.disabled = segments.length < 2;
      return prepareFirst(serial);
    }).then(function () {
      if (serial === runSerial) {
        // The first audio clip is ready before the user presses play, avoiding browser autoplay blocks.
        playBtn.disabled = mode === 'browser' && !('speechSynthesis' in window);
      }
    }).catch(function () {
      if (serial !== runSerial) return;
      setStatus(labels.labelError, 'error');
      textEl.textContent = labels.labelError;
      playBtn.disabled = true;
    });
  }
  function setPlaying(value) {
    playing = value;
    setPlayLabel(value);
    if (value) setStatus(labels.labelReady);
  }
  function playGroqPart(index, serial) {
    if (serial !== runSerial) return Promise.resolve();
    currentPart = index;
    var part = parts[index];
    if (!part) {
      setPlaying(false);
      progressFill.style.width = '100%'; progressEl.setAttribute('aria-valuenow', '100');
      setStatus(labels.labelReady);
      return Promise.resolve();
    }
    if (currentSegment !== part.segment) showSegment(part.segment);
    var blobPromise = (preparedPart === index && preparedBlob) ? Promise.resolve(preparedBlob) : fetchPart(index, serial);
    return blobPromise.then(function (blob) {
      if (serial !== runSerial || !blob) return;
      releaseAudio();
      objectUrl = URL.createObjectURL(blob);
      audio = new Audio(objectUrl);
      audio.onended = function () {
        if (serial !== runSerial) return;
        var next = index + 1;
        if (next < parts.length) {
          currentPart = next;
          var nextPart = parts[next];
          if (nextPart.segment !== currentSegment) showSegment(nextPart.segment);
          preparedBlob = null; preparedPart = -1;
          playGroqPart(next, serial).catch(function () { fallbackToBrowser(true); });
        } else {
          setPlaying(false);
          progressFill.style.width = '100%'; progressEl.setAttribute('aria-valuenow', '100');
          setStatus(labels.labelReady);
        }
      };
      audio.onerror = function () { if (serial === runSerial) fallbackToBrowser(true); };
      return audio.play().then(function () { if (serial === runSerial) setPlaying(true); });
    });
  }
  function browserVoice(segment) {
    if (!('speechSynthesis' in window) || !segment) {
      setStatus(labels.labelError, 'error');
      setPlaying(false);
      return;
    }
    window.speechSynthesis.cancel();
    utterance = new SpeechSynthesisUtterance(segment.text);
    utterance.lang = 'ar';
    utterance.rate = 0.96;
    var voices = window.speechSynthesis.getVoices ? window.speechSynthesis.getVoices() : [];
    var arVoice = voices.filter(function (v) { return /^ar([-_]|$)/i.test(v.lang || ''); });
    if (arVoice.length) {
      var preferred = voiceSelect.value === 'noura' ? /female|woman|noura|zira|hedda/i : /male|man|fahad|hoda/i;
      utterance.voice = arVoice.find(function (v) { return preferred.test(v.name); }) || arVoice[0];
    }
    utterance.onend = function () {
      if (!playing) return;
      if (currentSegment < segments.length - 1) {
        showSegment(currentSegment + 1);
        browserVoice(segments[currentSegment]);
      } else {
        setPlaying(false);
        progressFill.style.width = '100%'; progressEl.setAttribute('aria-valuenow', '100');
        setStatus(labels.labelReady);
      }
    };
    utterance.onerror = function () { if (playing) { setPlaying(false); setStatus(labels.labelError, 'error'); } };
    window.speechSynthesis.speak(utterance);
    setPlaying(true);
  }
  function fallbackToBrowser(forceStart) {
    var shouldContinue = playing || forceStart === true;
    mode = 'browser';
    releaseAudio();
    preparedBlob = null; preparedPart = -1;
    engineEl.textContent = labels.labelBrowser;
    if (shouldContinue && segments[currentSegment]) browserVoice(segments[currentSegment]);
    else { setPlaying(false); setStatus(labels.labelReady); }
  }
  function togglePlayback() {
    if (!segments.length || busy) return;
    if (playing) {
      if (mode === 'groq' && audio) audio.pause();
      else if (window.speechSynthesis) window.speechSynthesis.pause();
      setPlaying(false);
      return;
    }
    if (mode === 'browser') {
      if (window.speechSynthesis && window.speechSynthesis.paused) {
        window.speechSynthesis.resume(); setPlaying(true);
      } else browserVoice(segments[currentSegment]);
      return;
    }
    if (audio && audio.paused && audio.currentTime > 0) {
      audio.play().then(function () { setPlaying(true); }).catch(fallbackToBrowser);
      return;
    }
    busy = true;
    playBtn.disabled = true;
    var serial = runSerial;
    var startPart = parts.findIndex(function (p, i) { return i >= currentPart && p.segment === currentSegment; });
    if (startPart < 0) startPart = parts.findIndex(function (p) { return p.segment === currentSegment; });
    if (startPart < 0) startPart = 0;
    playGroqPart(startPart, serial).catch(function () { if (serial === runSerial) fallbackToBrowser(true); }).finally(function () {
      if (serial === runSerial) { busy = false; playBtn.disabled = false; }
    });
  }
  function jump(delta) {
    if (!segments.length || busy) return;
    var wasPlaying = playing;
    stopPlayback(false);
    busy = true;
    var target = Math.max(0, Math.min(segments.length - 1, currentSegment + delta));
    showSegment(target);
    if (mode === 'groq') {
      var partIndex = parts.findIndex(function (p) { return p.segment === target; });
      currentPart = partIndex < 0 ? 0 : partIndex;
      preparedBlob = null; preparedPart = -1;
      if (wasPlaying) {
        var serial = runSerial;
        playGroqPart(currentPart, serial).catch(function () { fallbackToBrowser(wasPlaying); }).finally(function () { if (serial === runSerial) busy = false; });
      } else {
        var serial2 = runSerial;
        fetchPart(currentPart, serial2).catch(function () { fallbackToBrowser(false); }).finally(function () { if (serial2 === runSerial) busy = false; });
      }
    } else {
      busy = false;
      if (wasPlaying) browserVoice(segments[currentSegment]);
    }
    prevBtn.disabled = target <= 0;
    nextBtn.disabled = target >= segments.length - 1;
  }
  function askQuestion(event) {
    if (event) event.preventDefault();
    var question = questionInput ? questionInput.value.trim() : '';
    if (!question || question.length > 220 || busy) {
      if (!question || question.length > 220) setStatus(labels.labelQuestionError || labels.labelError, 'error');
      return;
    }
    stopPlayback();
    var serial = ++runSerial;
    busy = true;
    segments = []; parts = []; currentSegment = 0; currentPart = 0;
    preparedBlob = null; preparedPart = -1; mode = 'browser';
    titleEl.textContent = labels.labelAnswer || labels.labelAsk;
    textEl.textContent = labels.labelWait;
    counterEl.textContent = labels.labelPart + ' 1';
    progressFill.style.width = '0%'; progressEl.setAttribute('aria-valuenow', '0');
    playBtn.disabled = true; stopBtn.disabled = true; prevBtn.disabled = true; nextBtn.disabled = true;
    setStatus(labels.labelWait);
    engineEl.textContent = labels.labelWait;
    jsonPost(player.dataset.askUrl, { question: question }).then(function (data) {
      if (serial !== runSerial) return;
      if (!data.segment) throw new Error('empty_answer');
      segments = [data.segment];
      parts = Array.isArray(data.parts) ? data.parts : [];
      mode = data.tts_available && parts.length ? 'groq' : 'browser';
      engineEl.textContent = (data.provider === 'model' ? labels.labelModel : labels.labelRules) + (mode === 'browser' ? ' · ' + labels.labelBrowser : ' · Groq');
      showSegment(0);
      stopBtn.disabled = false;
      return prepareFirst(serial);
    }).then(function () {
      if (serial !== runSerial) return;
      busy = false;
      playBtn.disabled = mode === 'browser' && !('speechSynthesis' in window);
      stopBtn.disabled = false;
      prevBtn.disabled = true; nextBtn.disabled = true;
    }).catch(function () {
      if (serial !== runSerial) return;
      busy = false;
      setStatus(labels.labelError, 'error');
      textEl.textContent = labels.labelError;
      playBtn.disabled = true; stopBtn.disabled = true;
    });
  }

  function close() {
    stopPlayback();
    player.hidden = true;
    if (openBtn) openBtn.setAttribute('aria-expanded', 'false');
    mapRoot.classList.remove('has-voice');
    if (window.PlanWiseJourney) window.PlanWiseJourney.clearFocus();
  }

  if (openBtn) openBtn.addEventListener('click', function () { start(null); });
  if (closeBtn) closeBtn.addEventListener('click', close);
  if (playBtn) playBtn.addEventListener('click', togglePlayback);
  if (stopBtn) stopBtn.addEventListener('click', function () { stopPlayback(); showSegment(0); setStatus(labels.labelReady); });
  if (nextBtn) nextBtn.addEventListener('click', function () { jump(1); });
  if (prevBtn) prevBtn.addEventListener('click', function () { jump(-1); });
  if (questionForm) questionForm.addEventListener('submit', askQuestion);
  if (voiceSelect) voiceSelect.addEventListener('change', function () {
    if (mode !== 'groq' || !segments.length) return;
    var wasPlaying = playing;
    stopPlayback(false); preparedBlob = null; preparedPart = -1;
    busy = true;
    var serial = runSerial;
    fetchPart(currentPart, serial).then(function () {
      if (wasPlaying) playGroqPart(currentPart, serial);
    }).catch(function () { fallbackToBrowser(wasPlaying); }).finally(function () { if (serial === runSerial) busy = false; });
  });
  document.addEventListener('click', function (event) {
    var button = event.target.closest && event.target.closest('[data-voice-target-kind]');
    if (!button || !mapRoot.contains(button)) return;
    event.preventDefault();
    start({ kind: button.getAttribute('data-voice-target-kind'), id: button.getAttribute('data-voice-target-id') });
  });
})();
