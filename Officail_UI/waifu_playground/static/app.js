(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const STORAGE_KEY = 'waifu-playground-phase1-settings';
  const DEFAULT_STATE = {
    mood: 'neutral', emotion_intensity: 20, affection: 10, energy: 70,
    relationship: 'getting to know each other', inner_thought: '', actions: [], memories: []
  };
  const DEFAULTS = {
    baseUrl: 'http://localhost:1234/v1', apiKey: '', rpModel: '', emotionModel: '', temperature: '0.8',
    characterName: 'Aoi',
    persona: 'A gentle, teasing, affectionate anime companion who is attentive and emotionally expressive.',
    systemPrompt: "Stay in character, respond naturally, and preserve continuity. Never control the user's actions, thoughts, or dialogue. Use vivid but concise dialogue, small actions, and emotional nuance.",
    stateTemplate: JSON.stringify(DEFAULT_STATE, null, 2)
  };
  let settings = { ...DEFAULTS };
  let history = [];
  let currentState = { ...DEFAULT_STATE };
  let currentEmotion = {};
  let lastRaw = null;
  let busy = false;
  let activeTab = 'state';
  let toastTimer;
  const messagesEl = $('messageList');

  function toast(message) {
    const el = $('toast'); el.textContent = message; el.classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 3600);
  }
  function updateStatus(label, percent, modelText) {
    $('statusLabel').textContent = label;
    $('statusPercent').textContent = percent == null ? '—' : `${percent}%`;
    $('progressFill').style.width = `${percent || 3}%`;
    $('progressFill').classList.toggle('processing', label === 'Processing…');
    if (modelText != null) $('modelStatus').textContent = modelText;
  }
  function setBusy(value) {
    busy = value; $('sendBtn').disabled = value; $('typingRow').hidden = !value;
    $('typingText').textContent = `${settings.characterName || 'Aoi'} is thinking…`;
    $('messageInput').disabled = value;
    if (value) updateStatus('Processing…', 73, settings.rpModel || 'Roleplay model');
    else updateStatus(settings.rpModel ? 'Ready' : 'Choose a model', settings.rpModel ? 100 : 3, settings.rpModel || 'No model selected');
  }
  function appendMessage(role, content, meta, flag) {
    const wrap = document.createElement('div'); wrap.className = `message ${role}`;
    const metaEl = document.createElement('div'); metaEl.className = 'message-meta'; metaEl.textContent = meta || (role === 'user' ? 'YOU' : settings.characterName.toUpperCase());
    const bubble = document.createElement('div'); bubble.className = 'message-bubble'; bubble.textContent = content;
    wrap.append(metaEl, bubble);
    if (flag) { const badge = document.createElement('div'); badge.className = 'message-flag'; badge.textContent = flag; wrap.appendChild(badge); }
    messagesEl.appendChild(wrap); messagesEl.scrollTop = messagesEl.scrollHeight;
    return wrap;
  }
  function renderWelcome() {
    messagesEl.replaceChildren();
    appendMessage('assistant', "Hehe… you're finally here.", `${settings.characterName.toUpperCase()} · LOCAL COMPANION`);
    const second = appendMessage('assistant', "I've been waiting for you…", `${settings.characterName.toUpperCase()} · OPENING LINE`);
    second.style.opacity = '.45';
    $('heroCharacterName').textContent = settings.characterName || 'Aoi';
    $('chatCharacterLabel').textContent = `${settings.characterName || 'Aoi'} · AI Waifu`;
    $('messageInput').placeholder = `Say something to ${settings.characterName || 'Aoi'}…  (Enter to send)`;
    $('typingText').textContent = `${settings.characterName || 'Aoi'} is thinking…`;
  }
  function loadSettingsToForm() {
    $('baseUrlInput').value = settings.baseUrl;
    $('apiKeyInput').value = settings.apiKey;
    $('rpModelInput').value = settings.rpModel;
    $('emotionModelInput').value = settings.emotionModel;
    $('temperatureInput').value = settings.temperature;
    $('temperatureValue').textContent = Number(settings.temperature).toFixed(2);
    $('characterNameInput').value = settings.characterName;
    $('personaInput').value = settings.persona;
    $('systemPromptInput').value = settings.systemPrompt;
    $('stateTemplateInput').value = settings.stateTemplate;
  }
  function readFormSettings() {
    let stateTemplate;
    try {
      stateTemplate = JSON.parse($('stateTemplateInput').value);
      if (!stateTemplate || Array.isArray(stateTemplate) || typeof stateTemplate !== 'object') throw new Error('The state template must be a JSON object.');
    } catch (err) { throw new Error(`Invalid state template JSON: ${err.message}`); }
    const url = $('baseUrlInput').value.trim().replace(/\/+$/, '') || DEFAULTS.baseUrl;
    if (!/^https?:\/\//i.test(url)) throw new Error('LM Studio URL must start with http:// or https://');
    return {
      baseUrl: url, apiKey: $('apiKeyInput').value,
      rpModel: $('rpModelInput').value.trim(), emotionModel: $('emotionModelInput').value.trim(),
      temperature: $('temperatureInput').value, characterName: $('characterNameInput').value.trim() || 'Aoi',
      persona: $('personaInput').value.trim(), systemPrompt: $('systemPromptInput').value.trim(),
      stateTemplate: JSON.stringify(stateTemplate, null, 2)
    };
  }
  function syncCharacterUi() {
    const name = settings.characterName || 'Aoi';
    $('heroCharacterName').textContent = name;
    $('chatCharacterLabel').textContent = `${name} · AI Waifu`;
    $('messageInput').placeholder = `Say something to ${name}…  (Enter to send)`;
    $('typingText').textContent = `${name} is thinking…`;
  }
  function saveSettings(quiet = false) {
    try {
      settings = readFormSettings();
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(settings)); } catch { /* The app still works when browser storage is disabled. */ }
      loadSettingsToForm(); syncCharacterUi();
      updateStatus(settings.rpModel ? 'Ready' : 'Choose a model', settings.rpModel ? 100 : 3, settings.rpModel || 'No model selected');
      if (!quiet) toast('Settings saved on this browser.');
      return true;
    } catch (err) { toast(err.message); return false; }
  }
  function getPayload(message) {
    return {
      base_url: settings.baseUrl, api_key: settings.apiKey, rp_model: settings.rpModel,
      emotion_model: settings.emotionModel || 'same', user_message: message, history: history.slice(-24),
      character_name: settings.characterName, persona: settings.persona, system_prompt: settings.systemPrompt,
      state_template: settings.stateTemplate, current_state: currentState, current_emotion: currentEmotion,
      temperature: Number(settings.temperature)
    };
  }
  async function sendMessage(message) {
    if (busy) return;
    const text = message.trim(); if (!text) return;
    if (!settings.rpModel) { toast('Choose a roleplay model in Settings first.'); $('settingsOverlay').hidden = false; return; }
    try { JSON.parse(settings.stateTemplate); } catch { toast('Fix the state JSON in Settings before chatting.'); $('settingsOverlay').hidden = false; return; }
    appendMessage('user', text, 'YOU'); $('messageInput').value = ''; resizeInput(); setBusy(true);
    try {
      const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(getPayload(text)) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
      const reply = String(data.reply || '…');
      history.push({ role: 'user', content: text }, { role: 'assistant', content: reply }); history = history.slice(-24);
      if (data.state && typeof data.state === 'object' && !Array.isArray(data.state)) currentState = data.state;
      if (data.emotion && typeof data.emotion === 'object') currentEmotion = data.emotion;
      lastRaw = { rp_model: data.rp_model, emotion_model: data.emotion_model, rp_json_valid: data.rp_json_valid, raw_rp: data.raw_rp, state: currentState, emotion: currentEmotion };
      appendMessage('assistant', reply, settings.characterName.toUpperCase(), data.rp_json_valid ? '' : 'Model output was not valid JSON; state retained. Check Raw output.');
      $('heroModelName').textContent = settings.rpModel;
      updateStatus('Ready', 100, settings.rpModel);
      if (currentEmotion._error) toast('Reply received; emotion tracker failed. See Emotion tab.');
      if (activeTab) renderInspector();
    } catch (err) {
      appendMessage('assistant', `I couldn't reach the model: ${err.message}`, 'CONNECTION ERROR', 'Check the LM Studio Local Server and selected model in Settings.');
      updateStatus('Connection error', 3, 'Check LM Studio'); toast(err.message);
    } finally { setBusy(false); }
  }
  async function refreshModels() {
    const baseUrl = $('baseUrlInput').value.trim().replace(/\/+$/, '') || DEFAULTS.baseUrl;
    $('connectionMessage').textContent = 'Connecting…'; $('connectionMessage').className = 'connection-message';
    $('refreshModelsBtn').disabled = true;
    try {
      const response = await fetch('/api/models', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base_url: baseUrl, api_key: $('apiKeyInput').value }) });
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
      const list = $('modelOptions'); list.replaceChildren();
      for (const model of data.models || []) { const option = document.createElement('option'); option.value = model.id; list.appendChild(option); }
      $('connectionMessage').textContent = `${(data.models || []).length} model(s) found`;
      $('connectionMessage').className = 'connection-message ok';
      if (!settings.rpModel && data.models?.length) $('rpModelInput').value = data.models[0].id;
      toast(`Connected to LM Studio. Found ${(data.models || []).length} model(s).`);
    } catch (err) { $('connectionMessage').textContent = err.message; $('connectionMessage').className = 'connection-message error'; toast(err.message); }
    finally { $('refreshModelsBtn').disabled = false; }
  }
  function openInspector(tab) { $('inspector').hidden = false; if (tab) activeTab = tab; renderInspector(); }
  function renderInspector() {
    const host = $('inspectorContent'); host.replaceChildren();
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === activeTab));
    if (activeTab === 'state') {
      const pre = document.createElement('pre'); pre.className = 'json-pre'; pre.textContent = JSON.stringify(currentState, null, 2); host.appendChild(pre);
      const btn = document.createElement('button'); btn.className = 'secondary-button'; btn.style.marginTop = '12px'; btn.textContent = 'Copy state JSON'; btn.onclick = () => copyText(JSON.stringify(currentState, null, 2)); host.appendChild(btn);
      return;
    }
    if (activeTab === 'raw') {
      const pre = document.createElement('pre'); pre.className = 'json-pre'; pre.textContent = lastRaw ? JSON.stringify(lastRaw, null, 2) : 'No model response yet. Raw model output will appear here after your first turn.'; host.appendChild(pre); return;
    }
    if (!Object.keys(currentEmotion).length) { const p = document.createElement('p'); p.className = 'empty-inspector'; p.textContent = 'The emotion sub-agent will report the character’s emotion after the first reply.'; host.appendChild(p); return; }
    const emotion = currentEmotion;
    const top = document.createElement('div'); top.className = 'emotion-top';
    const orb = document.createElement('div'); orb.className = 'emotion-orb'; orb.textContent = emojiFor(emotion.primary_emotion);
    const title = document.createElement('div'); const name = document.createElement('div'); name.className = 'emotion-title'; name.textContent = emotion.primary_emotion || 'unknown';
    const sub = document.createElement('div'); sub.className = 'emotion-subtitle'; sub.textContent = (emotion.secondary_emotions || []).join(' · ') || 'No secondary emotions'; title.append(name, sub); top.append(orb, title); host.appendChild(top);
    addMetric(host, 'Valence', `${Number(emotion.valence) || 0} / 100`, Math.max(0, Math.min(100, ((Number(emotion.valence) || 0) + 100) / 2)));
    addMetric(host, 'Arousal', `${Number(emotion.arousal) || 0}%`, emotion.arousal);
    addMetric(host, 'Confidence', `${Number(emotion.confidence) || 0}%`, emotion.confidence);
    if (Array.isArray(emotion.signals) && emotion.signals.length) { const pills = document.createElement('div'); pills.className = 'signal-list'; emotion.signals.forEach(s => { const pill = document.createElement('span'); pill.className = 'signal-pill'; pill.textContent = String(s); pills.appendChild(pill); }); host.appendChild(pills); }
    const note = document.createElement('div'); note.className = 'note-box'; note.textContent = emotion.note || 'No evidence note returned.'; host.appendChild(note);
    if (emotion._error) { const error = document.createElement('p'); error.className = 'empty-inspector'; error.textContent = 'This is a sub-agent error, not the roleplay response. Check that the emotion model is loaded.'; host.appendChild(error); }
  }
  function addMetric(host, label, value, width) {
    const outer = document.createElement('div'); outer.className = 'metric'; const head = document.createElement('div'); head.className = 'metric-head';
    const left = document.createElement('span'); left.textContent = label; const right = document.createElement('span'); right.textContent = value; head.append(left, right);
    const track = document.createElement('div'); track.className = 'metric-track'; const fill = document.createElement('div'); fill.className = 'metric-fill'; fill.style.width = `${Math.max(0, Math.min(100, Number(width) || 0))}%`; track.appendChild(fill); outer.append(head, track); host.appendChild(outer);
  }
  function emojiFor(emotion = '') { const s = String(emotion).toLowerCase(); if (/love|affection|fond/.test(s)) return '♥'; if (/joy|happy|excited|amused/.test(s)) return '☺'; if (/sad|lonely|grief/.test(s)) return '☂'; if (/angry|frustrat|annoy/.test(s)) return '⚡'; if (/fear|anxious|nervous/.test(s)) return '…'; if (/surpris|curious/.test(s)) return '✦'; return '✧'; }
  async function copyText(text) { try { await navigator.clipboard.writeText(text); toast('Copied to clipboard.'); } catch { toast('Clipboard access is unavailable in this browser.'); } }
  function resizeInput() { const el = $('messageInput'); el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 88)}px`; }
  function resetChat() { history = []; currentState = { ...DEFAULT_STATE }; currentEmotion = {}; lastRaw = null; renderWelcome(); renderInspector(); $('messageInput').focus(); toast('New chat started. Character state reset.'); }
  function toggleSettings(show) { $('settingsOverlay').hidden = !show; if (show) loadSettingsToForm(); }

  try { const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); if (saved && typeof saved === 'object') settings = { ...settings, ...saved }; } catch { /* Ignore invalid local preferences. */ }
  loadSettingsToForm(); renderWelcome(); setBusy(false);
  $('heroModelName').textContent = settings.rpModel || 'Your local companion';
  $('chatForm').addEventListener('submit', event => { event.preventDefault(); sendMessage($('messageInput').value); });
  $('messageInput').addEventListener('input', resizeInput);
  $('messageInput').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('chatForm').requestSubmit(); } });
  $('settingsNav').addEventListener('click', () => toggleSettings(true));
  $('profileNav').addEventListener('click', () => openInspector('state'));
  $('inspectorBtn').addEventListener('click', () => openInspector('state'));
  $('closeInspectorBtn').addEventListener('click', () => { $('inspector').hidden = true; });
  $('closeSettingsBtn').addEventListener('click', () => toggleSettings(false));
  $('settingsOverlay').addEventListener('click', event => { if (event.target === $('settingsOverlay')) toggleSettings(false); });
  $('refreshModelsBtn').addEventListener('click', refreshModels);
  $('temperatureInput').addEventListener('input', () => { $('temperatureValue').textContent = Number($('temperatureInput').value).toFixed(2); });
  $('saveSettingsBtn').addEventListener('click', () => { if (saveSettings()) { toggleSettings(false); $('heroModelName').textContent = settings.rpModel || 'Your local companion'; } });
  $('resetSettingsBtn').addEventListener('click', () => { settings = { ...DEFAULTS }; loadSettingsToForm(); saveSettings(true); toast('Defaults restored.'); });
  $('newChatBtn').addEventListener('click', resetChat);
  $('homeNav').addEventListener('click', () => { $('inspector').hidden = true; $('settingsOverlay').hidden = true; });
  $('chatNav').addEventListener('click', () => $('messageInput').focus());
  $('focusBtn').addEventListener('click', () => $('stage').classList.toggle('immersive'));
  $('emotionQuickBtn').addEventListener('click', () => openInspector('emotion'));
  document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => { activeTab = tab.dataset.tab; renderInspector(); }));
  $('downloadStateBtn').addEventListener('click', () => {
    const payload = { character: settings.characterName, state: currentState, emotion: currentEmotion, history, exported_at: new Date().toISOString() };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'waifu-character-state.json'; a.click(); URL.revokeObjectURL(url);
  });
  $('micBtn').addEventListener('click', () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) { toast('Voice input is not supported in this browser.'); return; }
    const recognition = new SpeechRecognition(); recognition.lang = navigator.language || 'en-US'; recognition.interimResults = false;
    recognition.onresult = event => { $('messageInput').value = event.results[0][0].transcript; resizeInput(); $('messageInput').focus(); };
    recognition.onerror = () => toast('Voice input was not available. Check microphone permission.'); recognition.start();
  });
  window.addEventListener('keydown', event => { if (event.key === 'Escape') { toggleSettings(false); $('inspector').hidden = true; } });
  updateStatus(settings.rpModel ? 'Ready' : 'Choose a model', settings.rpModel ? 100 : 3, settings.rpModel || 'No model selected');
  if (settings.rpModel) $('heroModelName').textContent = settings.rpModel;
})();
