let currentPage = 'dashboard';
let modalItemId = null;
let modalDirty = false;
let suggestions = { topics: [], content_types: [], tones: [] };
let generatedImages = [];
let selectedImageIdx = null;
let bulkSelected = new Set();

// Platform character limits
const PLATFORM_LIMITS = { instagram: 2200, linkedin: 3000, facebook: 63206 };

// ── Theme Toggle ──────────────────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem('nestpost-theme');
  if (saved === 'light') document.body.classList.add('light-theme');
  updateThemeUI();
}

function toggleTheme() {
  document.body.classList.toggle('light-theme');
  const isLight = document.body.classList.contains('light-theme');
  localStorage.setItem('nestpost-theme', isLight ? 'light' : 'dark');
  updateThemeUI();
}

function updateThemeUI() {
  const isLight = document.body.classList.contains('light-theme');
  const iconEl = document.getElementById('theme-icon');
  if (iconEl) {
    iconEl.innerHTML = isLight
      ? '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"/>'
      : '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"/>';
  }
}

// Init theme before page renders
initTheme();

document.addEventListener('DOMContentLoaded', async () => {
  showPage('generate');
  setGreeting();
  await Promise.all([loadHealth(), loadStats(), loadSuggestions(), loadModels(), loadSettings(), loadCurrentUser(), loadBrandLogo(), loadR2Status()]);
  loadRecentContent();
});

function setGreeting() {
  const h = new Date().getHours();
  const greetings = [[6,'Good morning!'],[12,'Good afternoon!'],[18,'Good evening!'],[22,'Working late!']];
  const g = greetings.reduce((a, b) => h >= b[0] ? b : a)[1];
  const el = document.getElementById('greeting-text');
  if (el) el.textContent = g;
  const d = document.getElementById('today-date');
  if (d) d.textContent = new Date().toLocaleDateString('en-AU', { weekday:'long', day:'numeric', month:'long', year:'numeric' });
}

function showPage(page) {
  document.querySelectorAll('[id^="page-"]').forEach(el => { el.style.display = 'none'; el.classList.remove('page-in'); });
  document.querySelectorAll('.nav-link').forEach(el => el.classList.remove('active'));
  const pageEl = document.getElementById(`page-${page}`);
  if (pageEl) { pageEl.style.display = ''; pageEl.classList.add('page-in'); }
  const navEl = document.getElementById(`nav-${page}`);
  if (navEl) navEl.classList.add('active');
  currentPage = page;
  if (page === 'library') loadLibrary();
  if (page === 'dashboard') { loadStats(); loadRecentContent(); }
  if (page === 'users') loadUsers();
}

async function loadHealth() {
  try {
    const data = await api('/api/provider-status');
    renderProviderStatus('text-provider-status', data.text, {
      ollama: 'Ollama', groq: 'Groq', gemini: 'Gemini', deepseek: 'Deepseek', qwen: 'Qwen',
    });
    renderProviderStatus('image-provider-status', data.image, {
      imagen4: 'Imagen 4', gemini_native: 'Nano Banana', gemini_native_paid: 'Nano Banana 2',
      stability: 'Stability AI', dalle: 'DALL-E 3',
    });
    if (data.video) {
      renderProviderStatus('video-provider-status', data.video, {
        veo3: 'Veo 3.1', kling: 'Kling AI', fal: 'WAN 2.1 (fal)', runway: 'Runway Gen-4', luma: 'Luma',
      });
      // Populate wizard video provider cards
      _buildWizardVideoProviderCards(data.video);
    }
  } catch { /* silent */ }
}

// Build video provider pill-cards for the wizard
function _buildWizardVideoProviderCards(videoData) {
  const container = document.getElementById('wizard-video-provider-cards');
  if (!container) return;
  container.innerHTML = '';

  // Maps sidebar status key → actual provider ID used by video_client.py
  const providerIdMap = { veo3: 'veo3_free', kling: 'kling_free', runway: 'runway', luma: 'luma', fal: 'fal_wan', atlascloud_video: 'atlascloud_video' };
  const providerMeta = {
    veo3:             { label: 'Veo 3.1',           icon: '🎬', note: 'Google — Paid only' },
    kling:            { label: 'Kling AI',          icon: '🎞️', note: 'Standard credits' },
    fal:              { label: 'WAN 2.1 (fal)',     icon: '⚡', note: 'Free credits included' },
    runway:           { label: 'Runway Gen-4',      icon: '🚀', note: 'Paid' },
    luma:             { label: 'Luma Dream',        icon: '✨', note: 'Paid' },
    atlascloud_video: { label: 'Atlas Cloud Video', icon: '☁️', note: 'Kling 3.0 Pro & more' },
  };

  // Preferred auto-select order: Atlas Cloud > Kling > fal > paid providers
  const preferredOrder = ['atlascloud_video', 'kling', 'fal', 'runway', 'luma', 'veo3'];
  const enabledKeys = new Set();
  const cards = {};

  Object.entries(videoData).forEach(([key, info]) => {
    const providerId = providerIdMap[key] || key;   // e.g. 'kling' → 'kling_free'
    const meta  = providerMeta[key] || { label: key, icon: '🎥', note: '' };
    const ready = info.online;
    const isPaid = info.paid === true;
    if (ready) enabledKeys.add(key);

    // Status indicator: green = ready, amber = paid (no key), red = no key (free tier)
    let statusDot, statusLabel;
    if (ready) {
      statusDot = '#4ade80'; statusLabel = '● Ready';
    } else if (isPaid) {
      statusDot = '#fbbf24'; statusLabel = '● Paid — purchase credits';
    } else {
      statusDot = '#ef4444'; statusLabel = '● No key';
    }

    const card = document.createElement('div');
    card.id = `wvp-${key}`;
    card.dataset.provider = providerId;
    card.style.cssText = `padding:10px 16px;border-radius:10px;border:2px solid ${ready ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.05)'};background:${ready ? 'rgba(15,23,42,0.4)' : 'rgba(15,23,42,0.2)'};cursor:${ready ? 'pointer' : 'not-allowed'};transition:all 0.15s;opacity:${ready ? '1' : '0.4'};min-width:120px;`;
    card.innerHTML = `
      <div style="font-size:1.1rem;margin-bottom:4px;">${meta.icon}</div>
      <div style="font-weight:700;font-size:0.8rem;color:${ready ? '#f1f5f9' : '#475569'};">${meta.label}</div>
      <div style="font-size:0.68rem;color:${statusDot};margin-top:2px;">${statusLabel}</div>
      <div style="font-size:0.65rem;color:#64748b;margin-top:1px;">${meta.note}</div>
    `;
    if (ready) card.onclick = () => setWizardVideoProvider(providerId, card);
    container.appendChild(card);
    cards[key] = card;
  });

  // Auto-select preferred available provider (Kling > fal > Runway > Luma > Veo3)
  const autoKey = preferredOrder.find(k => enabledKeys.has(k));
  if (autoKey) {
    wizardState.videoProvider = providerIdMap[autoKey] || autoKey;
    const autoCard = cards[autoKey];
    if (autoCard) { autoCard.style.borderColor = '#6366f1'; autoCard.style.background = 'rgba(99,102,241,0.15)'; }
  }
}

function setWizardVideoProvider(provider, card) {
  wizardState.videoProvider = provider;
  document.querySelectorAll('#wizard-video-provider-cards > div').forEach(c => {
    c.style.borderColor = 'rgba(255,255,255,0.12)';
    c.style.background  = 'rgba(15,23,42,0.4)';
  });
  card.style.borderColor = '#6366f1';
  card.style.background  = 'rgba(99,102,241,0.15)';
  updateWizardGenBtn();
}

function renderProviderStatus(containerId, providers, labels) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const rows = Object.entries(providers).map(([key, info]) => {
    const online = info.online;
    let dot, color, label;
    if (online === true) {
      dot = '#2dd4bf'; color = '#2dd4bf'; label = 'Online';
    } else if (online === false) {
      dot = '#ef4444'; color = '#ef4444'; label = 'Offline';
    } else {
      dot = '#475569'; color = '#64748b'; label = 'No key';
    }
    const name = info.label || labels[key] || key;
    const urlNote = info.url ? ` <span style="color:#475569;font-size:0.6rem;">(${info.url.replace(/^https?:\/\//, '').split('/')[0]})</span>` : '';
    return `<div style="display:flex;align-items:center;justify-content:space-between;padding:2px 0;">
      <div style="display:flex;align-items:center;gap:6px;font-size:0.72rem;color:#cbd5e1;font-weight:500;">
        <span style="width:6px;height:6px;border-radius:50%;background:${dot};display:inline-block;flex-shrink:0;${online === true ? 'animation:pulse 2s infinite;' : ''}"></span>
        ${name}${urlNote}
      </div>
      <span style="font-size:0.6rem;font-weight:600;color:${color};">${label}</span>
    </div>`;
  });
  el.innerHTML = rows.join('');
}

async function loadStats() {
  try {
    const data = await api('/api/stats');
    document.getElementById('stat-total').textContent = data.total;
    document.getElementById('stat-draft').textContent = data.draft;
    document.getElementById('stat-approved').textContent = data.approved;
    document.getElementById('stat-posted').textContent = data.posted;
  } catch { /* silent */ }
}

async function loadRecentContent() {
  try {
    const data = await api('/api/stats');
    const el = document.getElementById('recent-content');
    if (!el) return;
    if (!data.recent?.length) {
      el.innerHTML = `
        <div style="text-align:center;padding:40px 0;color:#475569;">
          <svg width="40" height="40" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="margin:0 auto 12px;display:block;opacity:0.35;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
          <p style="margin:0;font-size:0.875rem;font-weight:500;color:#64748b;">No posts yet — hit <strong style="color:#818cf8;">Generate Now</strong> to get started</p>
        </div>`;
      return;
    }
    el.innerHTML = data.recent.map(item => {
      const caption = safeCaption(item.caption);
      const preview = caption.substring(0, 90) + (caption.length > 90 ? '...' : '');
      return `
        <div onclick="openModal(${item.id})" style="display:flex;align-items:center;gap:14px;padding:12px 14px;border-radius:12px;cursor:pointer;transition:background 0.15s;" onmouseover="this.style.background='rgba(255,255,255,0.04)'" onmouseout="this.style.background='transparent'">
          <div style="width:38px;height:38px;border-radius:11px;flex-shrink:0;${platBg(item.platform)};display:flex;align-items:center;justify-content:center;">
            <span style="font-size:17px;">${platEmoji(item.platform)}</span>
          </div>
          <div style="flex:1;min-width:0;">
            <div style="font-weight:600;color:#f1f5f9;font-size:0.875rem;margin-bottom:2px;">${item.topic || 'Post'}</div>
            <div style="font-size:0.78rem;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${preview}</div>
          </div>
          <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
            ${statusBadge(item.status)}
          </div>
        </div>`;
    }).join('');
  } catch { /* silent */ }
}

async function loadSuggestions() {
  try {
    suggestions = await api('/api/suggestions');
    // Store topics globally for the V3 wizard topic picker
    window._topicTemplates = suggestions.topics || [];
    const topicSel = document.getElementById('manual-topic');
    if (topicSel) suggestions.topics.forEach(t => topicSel.appendChild(new Option(t.topic, t.id)));
    const ctSel = document.getElementById('manual-content-type');
    if (ctSel) suggestions.content_types.forEach(ct => ctSel.appendChild(new Option(ct, ct)));
    const toneSel = document.getElementById('manual-tone');
    if (toneSel) suggestions.tones.forEach(t => toneSel.appendChild(new Option(t, t)));
  } catch { /* silent */ }
}

async function loadModels() {
  try {
    const data = await api('/api/models');
    const models = data.models?.length ? data.models : ['llama3.2'];
    ['quick-ollama-model','manual-ollama-model'].forEach(id => {
      const sel = document.getElementById(id);
      if (sel) sel.innerHTML = models.map(m => `<option value="${m}">${m}</option>`).join('');
    });
    const label = document.getElementById('ollama-model-label');
    if (label && models[0]) label.textContent = models[0];
  } catch {
    ['quick-ollama-model','manual-ollama-model'].forEach(id => {
      const sel = document.getElementById(id);
      if (sel) sel.innerHTML = '<option value="llama3.2">llama3.2</option>';
    });
  }
}

function updateModelVisibility(mode) {
  const prefix = mode === 'quick' ? 'quick' : 'manual';
  const provider = document.getElementById(`${prefix}-ai-provider`)?.value;
  const modelSel = document.getElementById(`${prefix}-ollama-model`);
  const modelLabel = modelSel?.previousElementSibling;
  const isOllama = provider === 'ollama';
  const isAiFiesta = provider === 'aifiesta';
  if (modelSel) modelSel.style.display = isOllama ? '' : 'none';
  if (modelLabel) modelLabel.style.display = isOllama ? '' : 'none';
  const fiestaBanner = document.getElementById(`${prefix}-aifiesta-banner`);
  if (fiestaBanner) fiestaBanner.style.display = isAiFiesta ? '' : 'none';
}

function togglePlatCard(card, mode) {
  const checkbox = card.querySelector('input');
  const platform = card.dataset.platform;
  const selected = card.dataset.selected === '1';
  const indicator = card.querySelector('.plat-check-indicator');

  checkbox.checked = !selected;
  card.dataset.selected = selected ? '0' : '1';

  if (!selected) {
    card.classList.add(`sel-${platform === 'instagram' ? 'ig' : platform === 'linkedin' ? 'li' : 'fb'}`);
    if (indicator) {
      const colors = { instagram: '#e1306c', linkedin: '#0a66c2', facebook: '#1877f2' };
      indicator.textContent = '✓ Selected';
      indicator.style.color = colors[platform];
      indicator.style.fontWeight = '600';
    }
  } else {
    card.classList.remove('sel-ig','sel-li','sel-fb');
    if (indicator) {
      indicator.textContent = '+ Select';
      indicator.style.color = '#94a3b8';
      indicator.style.fontWeight = '500';
    }
  }
}

function setGenMode(mode) {
  document.getElementById('mode-quick').style.display = mode === 'quick' ? '' : 'none';
  document.getElementById('mode-manual').style.display = mode === 'manual' ? '' : 'none';
  document.getElementById('tab-quick').className = 'mode-tab' + (mode === 'quick' ? ' active' : '');
  document.getElementById('tab-manual').className = 'mode-tab' + (mode === 'manual' ? ' active' : '');
  document.getElementById('gen-results').style.display = 'none';
  document.getElementById('gen-loading').style.display = 'none';
}

async function quickGenerate(platform) {
  showPage('generate');
  // V3 wizard: pre-select the given platform if provided and scroll to wizard
  if (platform) {
    setTimeout(() => {
      const cards = document.querySelectorAll('#wizard-platform-cards .plat-card');
      cards.forEach(card => {
        const isTarget = card.dataset.platform === platform;
        const indicator = card.querySelector('.plat-check-indicator');
        const colors = { instagram: '#e1306c', linkedin: '#0a66c2', facebook: '#1877f2' };
        card.dataset.selected = isTarget ? '1' : '0';
        card.classList.remove('sel-ig', 'sel-li', 'sel-fb');
        if (isTarget) {
          const suffix = platform === 'instagram' ? 'ig' : platform === 'linkedin' ? 'li' : 'fb';
          card.classList.add(`sel-${suffix}`);
          if (indicator) { indicator.textContent = '✓ Selected'; indicator.style.color = colors[platform]; indicator.style.fontWeight = '600'; }
        } else {
          if (indicator) { indicator.textContent = '+ Select'; indicator.style.color = '#94a3b8'; indicator.style.fontWeight = '500'; }
        }
      });
      updateWizardGenBtn();
      document.getElementById('wizard-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 150);
  }
}

async function runGenerate(mode) {
  const isQuick = mode === 'quick';
  const checkClass = isQuick ? '.platform-check' : '.manual-platform-check';
  const platforms = [...document.querySelectorAll(`${checkClass}`)].filter(c => c.checked).map(c => c.value);

  if (!platforms.length) { showToast('Please select at least one platform', 'error'); return; }

  const btnId = isQuick ? 'gen-quick-btn' : 'gen-manual-btn';
  setGenerating(true, btnId);

  const provider = document.getElementById(isQuick ? 'quick-ai-provider' : 'manual-ai-provider')?.value || 'ollama';
  const ollamaModel = document.getElementById(isQuick ? 'quick-ollama-model' : 'manual-ollama-model')?.value || 'llama3.2';

  const body = { mode: isQuick ? 'quick' : 'manual', platforms, ai_provider: provider, ollama_model: ollamaModel };
  if (!isQuick) {
    const topicId = document.getElementById('manual-topic')?.value;
    const contentType = document.getElementById('manual-content-type')?.value;
    const tone = document.getElementById('manual-tone')?.value;
    const custom = document.getElementById('manual-custom-topic')?.value.trim();
    if (topicId) body.topic_id = topicId;
    if (contentType) body.content_type = contentType;
    if (tone) body.tone = tone;
    if (custom) body.custom_topic = custom;
  }

  try {
    const data = await api('/api/generate', 'POST', body);
    setGenerating(false, btnId);

    if (data.aifiesta_mode) {
      showAiFiestaPrompt(data);
      return;
    }

    data.errors?.forEach(e => showToast(`${e.platform}: ${e.error}`, 'error'));
    if (data.generated?.length) {
      showToast(`Generated ${data.generated.length} post${data.generated.length > 1 ? 's' : ''}`, 'success');
      showGeneratedResults(data.generated, data);
      loadStats(); loadRecentContent();
    }
  } catch (err) {
    setGenerating(false, btnId);
    showToast(err.message, 'error');
  }
}

function showAiFiestaPrompt(data) {
  const results = document.getElementById('gen-results');
  const list = document.getElementById('gen-results-list');
  list.innerHTML = '';
  const card = document.createElement('div');
  card.style.cssText = 'background:rgba(15,23,42,0.8);border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:24px;color:#e2e8f0;backdrop-filter:blur(16px);';
  card.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
      <span style="font-size:1.4rem;">🎪</span>
      <div>
        <div style="font-weight:700;font-size:1rem;color:#f1f5f9;">AI Fiesta — Queued for Generation</div>
        <div style="font-size:0.78rem;color:#64748b;margin-top:2px;">
          Topic: <strong style="color:#a5b4fc;">${data.topic}</strong> &nbsp;·&nbsp;
          Type: <strong style="color:#a5b4fc;">${data.content_type}</strong> &nbsp;·&nbsp;
          Platform: <strong style="color:#a5b4fc;">${data.platform}</strong>
        </div>
      </div>
    </div>
    <div style="background:rgba(30,41,59,0.6);border:1px solid rgba(255,255,255,0.06);border-radius:10px;padding:14px;margin-bottom:16px;font-size:0.78rem;line-height:1.6;color:#94a3b8;max-height:160px;overflow-y:auto;white-space:pre-wrap;font-family:monospace;">${data.prompt}</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;">
      <button class="btn-primary" onclick="navigator.clipboard.writeText(${JSON.stringify(data.prompt)}).then(()=>showToast('Prompt copied!','success'))" style="font-size:0.8rem;padding:8px 16px;">
        📋 Copy Prompt
      </button>
      <div style="font-size:0.78rem;color:#64748b;display:flex;align-items:center;">
        Claude will automatically use AI Fiesta to generate &amp; save this content.
      </div>
    </div>`;
  list.appendChild(card);
  results.style.display = '';
  showToast('AI Fiesta prompt ready — generating via browser...', 'success');
}

function showGeneratedResults(items, meta) {
  const results = document.getElementById('gen-results');
  const list = document.getElementById('gen-results-list');
  list.innerHTML = '';
  if (meta?.topic) {
    const info = document.createElement('div');
    info.style.cssText = 'background:rgba(99,102,241,0.1);border:1px solid rgba(99,102,241,0.2);border-radius:10px;padding:10px 14px;margin-bottom:4px;font-size:0.8rem;color:#a5b4fc;display:flex;align-items:center;gap:10px;flex-wrap:wrap;';
    info.innerHTML = `<span>🎯 <strong>Topic:</strong> ${meta.topic}</span><span style="color:rgba(165,180,252,0.4);">|</span><span><strong>Type:</strong> ${meta.content_type}</span><span style="color:rgba(165,180,252,0.4);">|</span><span><strong>Tone:</strong> ${meta.tone}</span>`;
    list.appendChild(info);
  }
  items.forEach(item => list.appendChild(buildContentCard(item, true)));
  results.style.display = '';
}

async function loadLibrary() {
  const grid = document.getElementById('library-grid');
  if (!grid) return;
  grid.innerHTML = skeletonGrid(4);
  bulkSelected.clear();
  updateBulkBar();
  try {
    const params = new URLSearchParams(window.libraryFilter || {});
    const searchInput = document.getElementById('library-search');
    if (searchInput && searchInput.value.trim()) params.set('search', searchInput.value.trim());
    const data = await api(`/api/content?${params}`);
    grid.innerHTML = '';
    // Show result count
    const countEl = document.getElementById('library-count');
    if (countEl) countEl.textContent = `${data.total || data.content.length} post${(data.total || data.content.length) !== 1 ? 's' : ''}`;
    if (!data.content?.length) {
      grid.innerHTML = `
        <div style="grid-column:1/-1;text-align:center;padding:64px 24px;color:#64748b;">
          <svg width="48" height="48" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="margin:0 auto 16px;display:block;opacity:0.3;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg>
          <p style="font-size:1rem;font-weight:700;color:#f1f5f9;margin:0 0 6px;">No content found</p>
          <p style="font-size:0.875rem;margin:0 0 18px;color:#64748b;">Try a different filter, or generate new content.</p>
          <button class="btn-primary" onclick="showPage('generate')">Generate Content</button>
        </div>`;
      return;
    }
    data.content.forEach(item => grid.appendChild(buildContentCard(item, false)));
  } catch (err) {
    grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:#ef4444;font-size:0.875rem;">${err.message}</div>`;
  }
}

function filterLibrary(key, value, btn) {
  window.libraryFilter = key ? { [key]: value } : {};
  document.querySelectorAll('.filter-tab').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  loadLibrary();
}

let _searchDebounce;
function searchLibrary(val) {
  clearTimeout(_searchDebounce);
  _searchDebounce = setTimeout(() => loadLibrary(), 300);
}

function toggleBulkSelect(id, checkbox, event) {
  event.stopPropagation();
  if (checkbox.checked) bulkSelected.add(id); else bulkSelected.delete(id);
  updateBulkBar();
}

function updateBulkBar() {
  const bar = document.getElementById('bulk-bar');
  if (!bar) return;
  if (bulkSelected.size > 0) {
    bar.style.display = 'flex';
    document.getElementById('bulk-count').textContent = `${bulkSelected.size} selected`;
  } else {
    bar.style.display = 'none';
  }
}

async function bulkAction(action) {
  if (!bulkSelected.size) return;
  const label = action === 'delete' ? 'delete' : action === 'approve' ? 'approve' : 'mark as posted';
  if (!confirm(`${label.charAt(0).toUpperCase() + label.slice(1)} ${bulkSelected.size} item(s)?`)) return;
  try {
    await api('/api/content/bulk-action', 'POST', { ids: [...bulkSelected], action });
    showToast(`${bulkSelected.size} item(s) ${action === 'delete' ? 'deleted' : action === 'approve' ? 'approved' : 'marked as posted'}`, 'success');
    bulkSelected.clear();
    updateBulkBar();
    loadLibrary();
    loadStats();
  } catch (err) { showToast(err.message, 'error'); }
}

function buildContentCard(item, isNew) {
  const div = document.createElement('div');
  div.style.cssText = 'background:rgba(15,23,42,0.65);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border-radius:18px;border:1px solid rgba(255,255,255,0.08);overflow:hidden;transition:box-shadow 0.2s,transform 0.2s;cursor:pointer;display:flex;flex-direction:column;box-shadow:0 4px 24px rgba(0,0,0,0.2);';
  div.onmouseover = () => { div.style.boxShadow = '0 8px 32px rgba(0,0,0,0.4)'; div.style.transform = 'translateY(-2px)'; };
  div.onmouseout = () => { div.style.boxShadow = '0 4px 24px rgba(0,0,0,0.2)'; div.style.transform = ''; };
  div.onclick = () => openModal(item.id);

  const caption = safeCaption(item.caption);
  const preview = caption.substring(0, 160) + (caption.length > 160 ? '...' : '');
  const hashPreview = (item.hashtags || '').substring(0, 60) + ((item.hashtags || '').length > 60 ? '...' : '');
  const dateStr = new Date(item.created_at).toLocaleDateString('en-AU', { day:'numeric', month:'short' });

  const hasImage = !!item.image_path;
  const hasVideo = !!item.video_path;
  div.innerHTML = `
    ${hasImage
      ? `<div style="height:140px;overflow:hidden;flex-shrink:0;position:relative;">
           <img src="${item.image_path}?t=${Date.now()}" style="width:100%;height:100%;object-fit:cover;" onerror="this.parentElement.style.display='none'" />
           <div style="position:absolute;top:8px;right:8px;display:flex;gap:4px;">
             <span style="background:rgba(0,0,0,0.5);color:#fff;font-size:0.65rem;font-weight:700;padding:2px 8px;border-radius:99px;">📸 AI</span>
             ${hasVideo ? '<span style="background:rgba(236,72,153,0.8);color:#fff;font-size:0.65rem;font-weight:700;padding:2px 8px;border-radius:99px;">🎬 Video</span>' : ''}
           </div>
         </div>`
      : `<div class="strip-${item.platform === 'instagram' ? 'ig' : item.platform === 'linkedin' ? 'li' : 'fb'}" style="height:5px;flex-shrink:0;"></div>`
    }
    <div style="padding:18px 20px;display:flex;flex-direction:column;flex:1;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
        <div style="display:flex;align-items:center;gap:9px;">
          <input type="checkbox" onclick="toggleBulkSelect(${item.id},this,event)" style="width:16px;height:16px;accent-color:#6366f1;cursor:pointer;flex-shrink:0;" title="Select for bulk action" />
          <div class="plat-icon-${item.platform === 'instagram' ? 'ig' : item.platform === 'linkedin' ? 'li' : 'fb'}" style="width:30px;height:30px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:14px;">
            <span>${platEmoji(item.platform)}</span>
          </div>
          <div>
            <div style="font-size:0.8125rem;font-weight:700;color:#f1f5f9;">${platLabel(item.platform)}</div>
            <div style="font-size:0.7rem;color:#64748b;font-weight:500;">${item.content_type || ''}</div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:6px;">
          ${isNew ? '<span style="font-size:0.7rem;font-weight:700;background:rgba(99,102,241,0.2);color:#a5b4fc;padding:2px 8px;border-radius:99px;border:1px solid rgba(165,180,252,0.25);">NEW</span>' : ''}
          ${statusBadge(item.status)}
        </div>
      </div>
      <h3 style="font-size:0.9375rem;font-weight:700;color:#f1f5f9;margin:0 0 8px;line-height:1.3;">${item.topic || 'Post'}</h3>
      <p style="font-size:0.8125rem;color:#94a3b8;line-height:1.6;margin:0 0 10px;flex:1;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">${preview}</p>
      ${hashPreview ? `<p style="font-size:0.75rem;color:#818cf8;margin:0 0 14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${hashPreview}</p>` : ''}
      <div style="display:flex;align-items:center;justify-content:space-between;padding-top:12px;border-top:1px solid rgba(255,255,255,0.06);margin-top:auto;">
        <span style="font-size:0.75rem;color:#475569;font-weight:500;">${dateStr}</span>
        <div style="display:flex;gap:4px;" onclick="event.stopPropagation()">
          <button class="btn-ghost" onclick="quickCopyCard(${item.id},event)" style="font-size:0.75rem;">📋 Copy</button>
          <button class="btn-ghost" onclick="openModal(${item.id})" style="font-size:0.75rem;color:#818cf8;font-weight:600;">View →</button>
        </div>
      </div>
    </div>`;
  return div;
}

async function quickCopyCard(id, event) {
  event.stopPropagation();
  try {
    const item = await api(`/api/content/${id}`);
    await navigator.clipboard.writeText(`${safeCaption(item.caption)}\n\n${item.hashtags || ''}`);
    showToast('Post copied to clipboard', 'success');
  } catch { showToast('Could not copy', 'error'); }
}

async function openModal(id) {
  modalItemId = id; modalDirty = false;
  const modal = document.getElementById('modal');
  modal.style.display = 'flex';
  modal.classList.add('modal-back');
  try {
    const item = await api(`/api/content/${id}`);
    const caption = safeCaption(item.caption);
    document.getElementById('modal-topic').textContent = item.topic || 'Post';
    document.getElementById('modal-type').textContent = `${platLabel(item.platform)} · ${item.content_type || ''}`;
    document.getElementById('modal-platform-badge').innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px;font-size:0.75rem;font-weight:700;padding:3px 12px;border-radius:99px;${platBadgeStyle(item.platform)}">${platEmoji(item.platform)} ${platLabel(item.platform)}</span>`;

    const captionEl = document.getElementById('modal-caption-text');
    const hashtagsEl = document.getElementById('modal-hashtags-text');
    if (captionEl) captionEl.value = caption;
    if (hashtagsEl) hashtagsEl.value = item.hashtags || '';

    // Set platform limit for character counter
    window._modalPlatform = item.platform;
    updateCharCount();

    document.getElementById('modal-image-suggestion').textContent = item.image_suggestion || 'No image suggestion available.';
    updateFullPreview();

    generatedImages = [];
    selectedImageIdx = null;
    document.getElementById('modal-image-prompt').value = item.image_prompt || '';
    document.getElementById('modal-image-results').style.display = 'none';
    document.getElementById('modal-image-loading').style.display = 'none';
    const savedSection = document.getElementById('modal-saved-image');
    if (item.image_path) {
      savedSection.style.display = '';
      document.getElementById('modal-saved-image-preview').src = item.image_path + '?t=' + Date.now();
    } else {
      savedSection.style.display = 'none';
    }

    // Video state init
    document.getElementById('modal-video-prompt').value = item.video_prompt || '';
    document.getElementById('modal-video-suggestions').style.display = 'none';
    document.getElementById('modal-video-result').style.display = 'none';
    document.getElementById('modal-video-loading').style.display = 'none';
    document.getElementById('modal-stock-results').style.display = 'none';
    const savedVideoSection = document.getElementById('modal-saved-video');
    if (item.video_path) {
      savedVideoSection.style.display = '';
      document.getElementById('modal-saved-video-preview').src = item.video_path + '?t=' + Date.now();
    } else {
      savedVideoSection.style.display = 'none';
    }
    // Always show video section so users can generate video from any post
    const modalVideoSection = document.getElementById('modal-video-section');
    if (modalVideoSection) modalVideoSection.style.display = '';
    window._generatedVideoB64 = null;
    window._generatedVideoMime = null;

    const approveBtn = document.getElementById('modal-approve-btn');
    approveBtn.innerHTML = item.status === 'approved' ? '<svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg> Approved' : '<svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg> Approve';
    approveBtn.disabled = item.status === 'approved';
    // Hide "View in Library" button from previous approval
    const viewLibBtn = document.getElementById('modal-view-library-btn');
    if (viewLibBtn) viewLibBtn.style.display = 'none';
    document.getElementById('modal-save-btn').style.display = 'none';
  } catch (err) { showToast(err.message, 'error'); closeModal(); }
}

function handleModalBackdrop(e) { if (e.target === document.getElementById('modal')) closeModal(); }

function closeModal() {
  const modal = document.getElementById('modal');
  modal.style.display = 'none';
  modal.classList.remove('modal-back');
  modalItemId = null; modalDirty = false;
}

function markModalDirty() {
  modalDirty = true;
  document.getElementById('modal-save-btn').style.display = '';
  updateFullPreview();
  updateCharCount();
}

function updateCharCount() {
  const el = document.getElementById('modal-char-count');
  const captionEl = document.getElementById('modal-caption-text');
  if (!el || !captionEl) return;
  const platform = window._modalPlatform || 'instagram';
  const limit = PLATFORM_LIMITS[platform] || 2200;
  const len = captionEl.value.length;
  const pct = Math.round((len / limit) * 100);
  const color = pct > 95 ? '#ef4444' : pct > 80 ? '#fbbf24' : '#2dd4bf';
  el.innerHTML = `<span style="color:${color};font-weight:600;">${len}</span><span style="color:#64748b;"> / ${limit}</span>`;
}

function updateFullPreview() {
  const captionEl = document.getElementById('modal-caption-text');
  const hashtagsEl = document.getElementById('modal-hashtags-text');
  const previewEl = document.getElementById('modal-full-preview');
  if (captionEl && hashtagsEl && previewEl) {
    previewEl.textContent = `${captionEl.value}\n\n${hashtagsEl.value}`;
  }
}

async function saveModal() {
  if (!modalItemId) return;
  try {
    await api(`/api/content/${modalItemId}`, 'PUT', {
      caption: document.getElementById('modal-caption-text').value,
      hashtags: document.getElementById('modal-hashtags-text').value,
    });
    showToast('Saved', 'success');
    modalDirty = false;
    document.getElementById('modal-save-btn').style.display = 'none';
    if (currentPage === 'library') loadLibrary();
    loadRecentContent();
  } catch (err) { showToast(err.message, 'error'); }
}

async function approveItem() {
  if (!modalItemId) return;
  const approvedId = modalItemId;
  try {
    await api(`/api/content/${modalItemId}`, 'PUT', { status: 'approved' });
    showToast('Approved', 'success');
    const btn = document.getElementById('modal-approve-btn');
    btn.innerHTML = '<svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg> Approved';
    btn.disabled = true;

    // Show "View in Library" button
    let viewBtn = document.getElementById('modal-view-library-btn');
    if (!viewBtn) {
      viewBtn = document.createElement('button');
      viewBtn.id = 'modal-view-library-btn';
      viewBtn.className = 'btn-secondary';
      viewBtn.style.cssText = 'font-size:0.8rem;padding:8px 16px;margin-left:8px;';
      btn.parentElement.appendChild(viewBtn);
    }
    viewBtn.innerHTML = '<svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg> View in Library';
    viewBtn.style.display = '';
    viewBtn.onclick = () => { closeModal(); showPage('library'); setTimeout(() => openModal(approvedId), 400); };

    loadStats();
    if (currentPage === 'library') loadLibrary();
  } catch (err) { showToast(err.message, 'error'); }
}

async function markPosted() {
  if (!modalItemId) return;
  try {
    await api(`/api/content/${modalItemId}`, 'PUT', { status: 'posted' });
    showToast('Marked as posted', 'success');
    closeModal(); loadStats();
    if (currentPage === 'library') loadLibrary();
  } catch (err) { showToast(err.message, 'error'); }
}

async function deleteItem() {
  if (!modalItemId || !confirm('Delete this post permanently?')) return;
  try {
    await api(`/api/content/${modalItemId}`, 'DELETE');
    showToast('Deleted', 'success');
    closeModal(); loadStats(); loadRecentContent();
    if (currentPage === 'library') loadLibrary();
  } catch (err) { showToast(err.message, 'error'); }
}

async function copyField(fieldId) {
  const el = document.getElementById(fieldId);
  if (!el) return;
  await navigator.clipboard.writeText(el.value);
  showToast('Copied', 'success');
}

async function copyFullPost() {
  const caption = document.getElementById('modal-caption-text')?.value || '';
  const hashtags = document.getElementById('modal-hashtags-text')?.value || '';
  await navigator.clipboard.writeText(`${caption}\n\n${hashtags}`);
  showToast('Full post copied to clipboard', 'success');
}

async function loadSettings() {
  try {
    const data = await api('/api/settings');
    const map = { ollama_url:'s-ollama-url', default_model:'s-default-model', default_ollama_model:'s-default-ollama-model' };
    Object.entries(map).forEach(([k,id]) => { const el = document.getElementById(id); if (el && data[k]) el.value = data[k]; });
    const imgProv = document.getElementById('s-default-image-provider');
    if (imgProv && data.default_image_provider) imgProv.value = data.default_image_provider;
    const vidProv = document.getElementById('s-default-video-provider');
    if (vidProv && data.default_video_provider) vidProv.value = data.default_video_provider;
    // Load non-sensitive Atlas Cloud model name
    const acModel = document.getElementById('s-atlascloud-model');
    if (acModel && data.atlascloud_model) acModel.value = data.atlascloud_model;
    const acVideoModel = document.getElementById('s-atlascloud-video-model');
    if (acVideoModel && data.atlascloud_video_model) acVideoModel.value = data.atlascloud_video_model;
    const sensitive = ['groq_api_key','gemini_api_key','deepseek_api_key','qwen_api_key','atlascloud_api_key','gemini_paid_api_key','stability_api_key','openai_api_key','linkedin_client_id','linkedin_client_secret','linkedin_access_token','facebook_page_id','facebook_access_token','kling_api_key','kling_secret_key','runway_api_key','luma_api_key','fal_api_key','pexels_api_key','r2_access_key_id','r2_secret_access_key'];
    // Non-sensitive R2 fields
    const r2Fields = { r2_account_id:'s-r2-account-id', r2_bucket_name:'s-r2-bucket-name', r2_public_url:'s-r2-public-url' };
    Object.entries(r2Fields).forEach(([k,id]) => { const el = document.getElementById(id); if (el && data[k]) el.value = data[k]; });
    // Video retention
    const retEl = document.getElementById('s-video-retention-days');
    if (retEl && data.video_retention_days) retEl.value = data.video_retention_days;
    sensitive.forEach(k => {
      const el = document.getElementById(`s-${k.replace(/_/g,'-')}`);
      if (el && data[k] === '••••••••') el.placeholder = '••••••••  (saved & encrypted)';
    });
  } catch { /* silent */ }
}

async function saveSettings() {
  const settings = {
    ollama_url: document.getElementById('s-ollama-url')?.value,
    default_model: document.getElementById('s-default-model')?.value,
    default_ollama_model: document.getElementById('s-default-ollama-model')?.value,
    groq_api_key: document.getElementById('s-groq-api-key')?.value,
    gemini_api_key: document.getElementById('s-gemini-api-key')?.value,
    deepseek_api_key: document.getElementById('s-deepseek-api-key')?.value,
    qwen_api_key: document.getElementById('s-qwen-api-key')?.value,
    atlascloud_api_key: document.getElementById('s-atlascloud-api-key')?.value,
    atlascloud_model: document.getElementById('s-atlascloud-model')?.value,
    atlascloud_video_model: document.getElementById('s-atlascloud-video-model')?.value,
    gemini_paid_api_key: document.getElementById('s-gemini-paid-api-key')?.value,
    stability_api_key: document.getElementById('s-stability-api-key')?.value,
    openai_api_key: document.getElementById('s-openai-api-key')?.value,
    default_image_provider: document.getElementById('s-default-image-provider')?.value,
    linkedin_client_id: document.getElementById('s-linkedin-client-id')?.value,
    linkedin_client_secret: document.getElementById('s-linkedin-client-secret')?.value,
    linkedin_access_token: document.getElementById('s-linkedin-access-token')?.value,
    facebook_page_id: document.getElementById('s-facebook-page-id')?.value,
    facebook_access_token: document.getElementById('s-facebook-access-token')?.value,
    kling_api_key: document.getElementById('s-kling-api-key')?.value,
    kling_secret_key: document.getElementById('s-kling-secret-key')?.value,
    runway_api_key: document.getElementById('s-runway-api-key')?.value,
    luma_api_key: document.getElementById('s-luma-api-key')?.value,
    fal_api_key: document.getElementById('s-fal-api-key')?.value,
    pexels_api_key: document.getElementById('s-pexels-api-key')?.value,
    default_video_provider: document.getElementById('s-default-video-provider')?.value,
    r2_account_id: document.getElementById('s-r2-account-id')?.value,
    r2_access_key_id: document.getElementById('s-r2-access-key-id')?.value,
    r2_secret_access_key: document.getElementById('s-r2-secret-access-key')?.value,
    r2_bucket_name: document.getElementById('s-r2-bucket-name')?.value,
    r2_public_url: document.getElementById('s-r2-public-url')?.value,
    video_retention_days: document.getElementById('s-video-retention-days')?.value,
  };
  try {
    await api('/api/settings', 'POST', { settings });
    showToast('Settings saved', 'success');
    loadHealth(); loadModels();
  } catch (err) { showToast(err.message, 'error'); }
}

// ── R2 Storage Status & Video Retention ──────────────────────────────────────

async function loadR2Status() {
  try {
    const data = await api('/api/video/storage-status');
    const dot = document.getElementById('r2-status-dot');
    const text = document.getElementById('r2-status-text');
    const stats = document.getElementById('r2-storage-stats');

    if (dot && text) {
      if (data.r2_configured) {
        dot.style.background = '#2dd4bf';
        text.textContent = `R2 configured — bucket: ${data.r2_bucket}`;
        text.style.color = '#2dd4bf';
      } else {
        dot.style.background = '#f59e0b';
        text.textContent = 'R2 not configured — videos stored as database blobs';
        text.style.color = '#f59e0b';
      }
    }

    if (stats) {
      stats.innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;">
          <span>Total videos stored:</span> <strong style="color:#f1f5f9;">${data.total_videos}</strong>
          <span>In R2 (URL):</span> <strong style="color:#2dd4bf;">${data.r2_stored}</strong>
          <span>In database (blob):</span> <strong style="color:#f59e0b;">${data.blob_stored}</strong>
          <span>Due for cleanup:</span> <strong style="color:${data.due_for_cleanup > 0 ? '#f87171' : '#2dd4bf'};">${data.due_for_cleanup}</strong>
          <span>Retention period:</span> <strong style="color:#f1f5f9;">${data.retention_days} days</strong>
        </div>
      `;
    }
  } catch { /* silent */ }
}

async function triggerVideoCleanup() {
  try {
    const data = await api('/api/video/cleanup', 'POST');
    showToast(`Cleanup complete — ${data.deleted} video(s) deleted`, data.deleted > 0 ? 'success' : 'success');
    loadR2Status();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// ── Brand Logo Management ─────────────────────────────────────────────────
async function loadBrandLogo() {
  try {
    const data = await api('/api/brand-logo');
    const img = document.getElementById('logo-preview-img');
    const empty = document.getElementById('logo-preview-empty');
    const removeBtn = document.getElementById('logo-remove-btn');
    const statusText = document.getElementById('logo-status-text');
    if (data.has_logo) {
      img.src = '/api/brand-logo/image?t=' + Date.now();
      img.style.display = '';
      empty.style.display = 'none';
      removeBtn.style.display = '';
      statusText.textContent = 'Logo active — will be overlaid on all saved images.';
    } else {
      img.style.display = 'none';
      empty.style.display = '';
      removeBtn.style.display = 'none';
      statusText.textContent = 'No logo uploaded. Images will be saved without a watermark.';
    }
  } catch { /* silent */ }
}

async function handleLogoUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  if (file.size > 2 * 1024 * 1024) {
    showToast('Logo file must be under 2MB', 'error');
    return;
  }
  const reader = new FileReader();
  reader.onload = async () => {
    const base64 = reader.result.split(',')[1];
    const mime = file.type || 'image/png';
    try {
      await api('/api/brand-logo', 'POST', { image_base64: base64, mime_type: mime });
      showToast('Brand logo uploaded — it will appear on all future saved images', 'success');
      loadBrandLogo();
    } catch (err) {
      showToast('Failed to upload logo: ' + err.message, 'error');
    }
  };
  reader.readAsDataURL(file);
  event.target.value = '';
}

async function removeBrandLogo() {
  if (!confirm('Remove brand logo? Future images will be saved without a watermark.')) return;
  try {
    await api('/api/brand-logo', 'DELETE');
    showToast('Brand logo removed', 'success');
    loadBrandLogo();
  } catch (err) {
    showToast('Failed to remove logo: ' + err.message, 'error');
  }
}

function setGenerating(on, btnId) {
  const btn = document.getElementById(btnId);
  const loading = document.getElementById('gen-loading');
  const results = document.getElementById('gen-results');
  if (on) {
    if (btn) { btn.disabled = true; btn.innerHTML = `<svg class="spin" width="16" height="16" fill="none" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" opacity="0.25"/><path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Generating...`; }
    if (loading) loading.style.display = '';
    if (results) results.style.display = 'none';
  } else {
    if (btn) { btn.disabled = false; btn.innerHTML = `<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg> Generate Content`; }
    if (loading) loading.style.display = 'none';
  }
}

function skeletonGrid(n) {
  return Array(n).fill(`
    <div style="background:rgba(15,23,42,0.65);backdrop-filter:blur(16px);border-radius:18px;border:1px solid rgba(255,255,255,0.08);overflow:hidden;">
      <div style="height:5px;background:rgba(30,41,59,0.6);"></div>
      <div style="padding:18px 20px;">
        <div class="skel" style="height:12px;width:80px;margin-bottom:14px;"></div>
        <div class="skel" style="height:16px;width:60%;margin-bottom:10px;"></div>
        <div class="skel" style="height:11px;width:100%;margin-bottom:7px;"></div>
        <div class="skel" style="height:11px;width:90%;margin-bottom:7px;"></div>
        <div class="skel" style="height:11px;width:70%;margin-bottom:14px;"></div>
        <div style="display:flex;justify-content:space-between;padding-top:12px;border-top:1px solid rgba(255,255,255,0.06);">
          <div class="skel" style="height:11px;width:50px;"></div>
          <div class="skel" style="height:11px;width:80px;"></div>
        </div>
      </div>
    </div>`).join('');
}

function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const colors = { success: '#2dd4bf', error: '#ef4444', info: '#818cf8' };
  const icons = { success: '✓', error: '✕', info: 'ℹ' };
  const toast = document.createElement('div');
  toast.style.cssText = `background:rgba(15,23,42,0.85);backdrop-filter:blur(16px);border:1px solid ${colors[type]}33;border-left:4px solid ${colors[type]};border-radius:12px;padding:12px 16px;font-size:0.875rem;font-weight:600;color:#e2e8f0;box-shadow:0 4px 20px rgba(0,0,0,0.3);display:flex;align-items:center;gap:9px;pointer-events:all;min-width:240px;max-width:360px;`;
  toast.innerHTML = `<span style="color:${colors[type]};font-size:1rem;">${icons[type]}</span>${message}`;
  toast.classList.add('t-in');
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.remove('t-in');
    toast.classList.add('t-out');
    setTimeout(() => toast.remove(), 280);
  }, 3500);
}

function safeCaption(caption) {
  if (!caption) return '';
  if (typeof caption !== 'string') {
    if (caption.caption) return caption.caption;
    try { return JSON.stringify(caption); } catch { return String(caption); }
  }
  if (caption.trim().startsWith('{')) {
    try {
      const parsed = JSON.parse(caption);
      if (parsed && parsed.caption) return parsed.caption;
    } catch { /* malformed JSON */ }
    const m = caption.match(/"caption"\s*:\s*"((?:[^"\\]|\\.)*)"/);
    if (m) {
      try { return JSON.parse('"' + m[1] + '"'); } catch { return m[1]; }
    }
  }
  return caption;
}

function platEmoji(p) { return { instagram:'📷', linkedin:'💼', facebook:'👥' }[p] || '📄'; }
function platLabel(p) { return { instagram:'Instagram', linkedin:'LinkedIn', facebook:'Facebook' }[p] || p; }
function platBg(p) {
  return { instagram:'background:linear-gradient(135deg,#f09433,#bc1888)', linkedin:'background:#0a66c2', facebook:'background:#1877f2' }[p] || 'background:#6366f1';
}
function platBadgeStyle(p) {
  const s = {
    instagram: 'background:rgba(225,48,108,0.15);color:#f472b6;border:1px solid rgba(244,114,182,0.25);',
    linkedin: 'background:rgba(10,102,194,0.15);color:#60a5fa;border:1px solid rgba(96,165,250,0.25);',
    facebook: 'background:rgba(24,119,242,0.15);color:#60a5fa;border:1px solid rgba(96,165,250,0.25);',
  };
  return s[p] || 'background:rgba(99,102,241,0.15);color:#a5b4fc;border:1px solid rgba(165,180,252,0.25);';
}

function statusBadge(status) {
  const conf = {
    draft: { bg:'rgba(146,64,14,0.15)', color:'#fbbf24', border:'rgba(251,191,36,0.25)', label:'Draft' },
    approved: { bg:'rgba(99,102,241,0.15)', color:'#a5b4fc', border:'rgba(165,180,252,0.25)', label:'Approved' },
    posted: { bg:'rgba(45,212,191,0.15)', color:'#2dd4bf', border:'rgba(45,212,191,0.25)', label:'Posted' },
  };
  const c = conf[status] || conf.draft;
  return `<span style="display:inline-flex;align-items:center;padding:2px 9px;border-radius:99px;font-size:0.72rem;font-weight:700;background:${c.bg};color:${c.color};border:1px solid ${c.border};">${c.label}</span>`;
}

function updateImageModelInfo() {
  const provider = document.getElementById('modal-image-provider')?.value;
  const info = document.getElementById('modal-image-model-info');
  if (!info) return;
  const providerInfo = {
    imagen4:            { text: 'Uses your Gemini API key — up to 4 images per generation', color: '#2dd4bf' },
    imagen4_fast:       { text: 'Uses your Gemini API key — up to 4 images, faster', color: '#2dd4bf' },
    gemini_native:      { text: 'Uses your Gemini API key — 1 context-aware image (free)', color: '#2dd4bf' },
    gemini_native_paid: { text: 'Uses Nano Banana 2 paid key — 1 high-quality image', color: '#fbbf24' },
    stability:          { text: 'Uses Stability AI key — up to 4 images', color: '#818cf8' },
    dalle:              { text: 'Uses OpenAI key — 1 image per generation', color: '#818cf8' },
  };
  const p = providerInfo[provider] || providerInfo.imagen4;
  info.innerHTML = `<span style="width:6px;height:6px;border-radius:50%;background:${p.color};display:inline-block;"></span> ${p.text}`;
}

async function refineImagePrompt() {
  if (!modalItemId) return;
  const btn = document.getElementById('modal-refine-btn');
  btn.textContent = '⏳ Refining...';
  btn.disabled = true;
  try {
    const data = await api('/api/refine-image-prompt', 'POST', { content_id: modalItemId });
    document.getElementById('modal-image-prompt').value = data.prompt || '';
    showToast('Prompt refined — edit it if needed', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btn.textContent = '✨ Auto-refine prompt';
    btn.disabled = false;
  }
}

async function generateImages() {
  if (!modalItemId) return;
  const prompt = document.getElementById('modal-image-prompt')?.value?.trim();
  if (!prompt) { showToast('Write or refine an image prompt first', 'error'); return; }

  const provider = document.getElementById('modal-image-provider')?.value || 'imagen4';
  const aspectRatio = document.getElementById('modal-aspect-ratio')?.value || '1:1';
  const maxImages = { imagen4: 4, imagen4_fast: 4, gemini_native: 1, gemini_native_paid: 1, stability: 4, dalle: 1 };
  const numImages = maxImages[provider] || 4;

  const btn = document.getElementById('modal-gen-image-btn');
  const loading = document.getElementById('modal-image-loading');
  const results = document.getElementById('modal-image-results');
  btn.disabled = true;
  btn.innerHTML = '<svg class="spin" width="15" height="15" fill="none" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" opacity="0.25"/><path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Generating...';
  loading.style.display = '';
  results.style.display = 'none';
  generatedImages = [];
  selectedImageIdx = null;

  try {
    const data = await api('/api/generate-image', 'POST', {
      content_id: modalItemId,
      prompt,
      provider,
      num_images: numImages,
      aspect_ratio: aspectRatio,
    });

    generatedImages = data.images || [];
    if (!generatedImages.length) {
      showToast('No images returned — try a different model or prompt', 'error');
      return;
    }

    renderImageGrid();
    showToast(`Generated ${generatedImages.length} image${generatedImages.length > 1 ? 's' : ''} — pick your favourite`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<svg width="15" height="15" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg> Generate Images';
    loading.style.display = 'none';
  }
}

function renderImageGrid() {
  const grid = document.getElementById('modal-image-grid');
  const results = document.getElementById('modal-image-results');
  grid.innerHTML = '';

  generatedImages.forEach((img, idx) => {
    const card = document.createElement('div');
    card.id = `img-option-${idx}`;
    card.style.cssText = 'position:relative;border-radius:12px;overflow:hidden;cursor:pointer;border:3px solid transparent;transition:all 0.2s;';
    card.onmouseover = () => { if (selectedImageIdx !== idx) card.style.borderColor = 'rgba(165,180,252,0.3)'; };
    card.onmouseout = () => { if (selectedImageIdx !== idx) card.style.borderColor = 'transparent'; };
    card.onclick = () => selectImage(idx);

    const imgEl = document.createElement('img');
    imgEl.src = `data:${img.mime_type};base64,${img.base64}`;
    imgEl.style.cssText = 'width:100%;display:block;aspect-ratio:1;object-fit:cover;';
    card.appendChild(imgEl);

    const overlay = document.createElement('div');
    overlay.className = 'img-select-overlay';
    overlay.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(99,102,241,0.0);transition:background 0.2s;';
    card.appendChild(overlay);

    grid.appendChild(card);
  });

  if (generatedImages.length === 1) {
    grid.style.gridTemplateColumns = '1fr';
  } else {
    grid.style.gridTemplateColumns = 'repeat(2,1fr)';
  }

  results.style.display = '';
}

function selectImage(idx) {
  selectedImageIdx = idx;

  generatedImages.forEach((_, i) => {
    const card = document.getElementById(`img-option-${i}`);
    if (!card) return;
    const overlay = card.querySelector('.img-select-overlay');
    if (i === idx) {
      card.style.borderColor = '#6366f1';
      card.style.boxShadow = '0 0 0 2px rgba(99,102,241,0.3)';
      overlay.style.background = 'rgba(99,102,241,0.12)';
      overlay.innerHTML = '<div style="background:#6366f1;color:#fff;border-radius:99px;padding:6px 16px;font-size:0.78rem;font-weight:700;box-shadow:0 2px 8px rgba(99,102,241,0.4);">✓ Selected</div>';
    } else {
      card.style.borderColor = 'transparent';
      card.style.boxShadow = 'none';
      overlay.style.background = 'rgba(0,0,0,0)';
      overlay.innerHTML = '';
    }
  });

  saveSelectedImage();
}

async function saveSelectedImage() {
  if (selectedImageIdx === null || !modalItemId) return;
  const img = generatedImages[selectedImageIdx];
  const prompt = document.getElementById('modal-image-prompt')?.value || '';

  try {
    const data = await api('/api/save-image', 'POST', {
      content_id: modalItemId,
      image_base64: img.base64,
      image_prompt: prompt,
      mime_type: img.mime_type,
    });

    const savedSection = document.getElementById('modal-saved-image');
    const preview = document.getElementById('modal-saved-image-preview');
    preview.src = data.image_path + '?t=' + Date.now();
    savedSection.style.display = '';

    showToast('Image saved', 'success');
    if (currentPage === 'library') loadLibrary();
    loadRecentContent();
  } catch (err) {
    showToast('Failed to save image: ' + err.message, 'error');
  }
}

function regenerateImages() {
  generateImages();
}

async function removeImage() {
  if (!modalItemId) return;
  try {
    await api(`/api/content/${modalItemId}/image`, 'DELETE');
    document.getElementById('modal-saved-image').style.display = 'none';
    document.getElementById('modal-image-results').style.display = 'none';
    generatedImages = [];
    selectedImageIdx = null;
    showToast('Image removed', 'success');
    if (currentPage === 'library') loadLibrary();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// ── Video Generation ─────────────────────────────────────────────────────

function updateVideoModelInfo() {
  const provider = document.getElementById('modal-video-provider')?.value;
  const info = document.getElementById('modal-video-model-info');
  if (!info) return;
  const providerInfo = {
    veo3_free:  { text: 'Uses your Gemini API key — top quality, ~5-10 free generations/day', color: '#2dd4bf' },
    veo3_paid:  { text: 'Uses your Gemini API key — full quality, $0.50/sec', color: '#fbbf24' },
    kling_free: { text: 'Uses Kling API key — 66 free credits/day, 720p watermarked', color: '#2dd4bf' },
    kling_pro:  { text: 'Uses Kling API key — 1080p, no watermark', color: '#fbbf24' },
    atlascloud_video: { text: 'Uses Atlas Cloud API key — model configurable in Settings (Kling 3.0 Pro by default)', color: '#38bdf8' },
    runway:     { text: 'Uses Runway API key — $0.05-0.10/sec, strong character coherence', color: '#fbbf24' },
    luma:       { text: 'Uses Luma API key — $0.20/video, good for product reveals', color: '#fbbf24' },
  };
  const p = providerInfo[provider] || providerInfo.veo3_free;
  info.innerHTML = `<span style="width:6px;height:6px;border-radius:50%;background:${p.color};display:inline-block;"></span> ${p.text}`;
}

function toggleVideoPaidModels() {
  const usePaid = document.getElementById('modal-video-use-paid')?.checked;
  const select = document.getElementById('modal-video-provider');
  if (!select) return;
  if (usePaid) {
    select.value = 'veo3_paid';
  } else {
    select.value = 'veo3_free';
  }
  updateVideoModelInfo();
}

async function suggestVideoPrompts() {
  if (!modalItemId) return;
  const btn = document.getElementById('modal-video-suggest-btn');
  btn.textContent = '⏳ Generating...';
  btn.disabled = true;
  try {
    const data = await api('/api/video/suggest-prompts', 'POST', { content_id: modalItemId });
    const prompts = data.prompts || [];
    const container = document.getElementById('modal-video-prompt-cards');
    container.innerHTML = '';

    const styleColors = { Cinematic: '#6366f1', Dynamic: '#f97316', Minimal: '#2dd4bf' };

    prompts.forEach(p => {
      const card = document.createElement('div');
      const borderColor = styleColors[p.style] || '#6366f1';
      card.style.cssText = `background:rgba(15,23,42,0.6);border:1px solid ${borderColor}40;border-radius:12px;padding:12px;cursor:pointer;transition:all 0.2s;`;
      card.onmouseover = () => { card.style.borderColor = borderColor; card.style.background = 'rgba(15,23,42,0.9)'; };
      card.onmouseout = () => { card.style.borderColor = borderColor + '40'; card.style.background = 'rgba(15,23,42,0.6)'; };
      card.onclick = () => {
        document.getElementById('modal-video-prompt').value = p.prompt;
        const aspectSelect = document.getElementById('modal-video-aspect');
        if (aspectSelect && p.suggested_aspect_ratio) aspectSelect.value = p.suggested_aspect_ratio;
        const durSelect = document.getElementById('modal-video-duration');
        if (durSelect && p.suggested_length) durSelect.value = String(p.suggested_length);
        showToast(`${p.style} prompt loaded — edit if needed, then generate`, 'success');
      };

      card.innerHTML = `
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">
          <span style="background:${borderColor};color:#fff;font-size:0.68rem;font-weight:700;padding:2px 8px;border-radius:99px;">${p.style}</span>
          <span style="font-size:0.68rem;color:#64748b;">${p.suggested_length || 8}s · ${p.suggested_aspect_ratio || '9:16'}</span>
        </div>
        <div style="font-size:0.78rem;color:#cbd5e1;line-height:1.5;">${p.prompt}</div>
      `;
      container.appendChild(card);
    });

    document.getElementById('modal-video-suggestions').style.display = '';
    showToast('3 video prompts generated — click one to use it', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btn.textContent = '🎬 Suggest Prompts';
    btn.disabled = false;
  }
}

async function generateVideo() {
  if (!modalItemId) return;
  const prompt = document.getElementById('modal-video-prompt')?.value?.trim();
  if (!prompt) { showToast('Write or select a video prompt first', 'error'); return; }

  const provider = document.getElementById('modal-video-provider')?.value || 'veo3_free';
  const aspectRatio = document.getElementById('modal-video-aspect')?.value || '9:16';
  const duration = parseInt(document.getElementById('modal-video-duration')?.value || '8');

  const btn = document.getElementById('modal-gen-video-btn');
  const loading = document.getElementById('modal-video-loading');
  const result = document.getElementById('modal-video-result');
  btn.disabled = true;
  btn.innerHTML = '<svg class="spin" width="15" height="15" fill="none" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" opacity="0.25"/><path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Generating...';
  loading.style.display = '';
  result.style.display = 'none';

  try {
    const data = await api('/api/video/generate', 'POST', {
      content_id: modalItemId,
      prompt,
      provider,
      aspect_ratio: aspectRatio,
      duration,
    });

    if (data.video_base64) {
      window._generatedVideoB64 = data.video_base64;
      window._generatedVideoMime = data.mime_type || 'video/mp4';

      const preview = document.getElementById('modal-video-preview');
      preview.src = `data:${data.mime_type};base64,${data.video_base64}`;
      result.style.display = '';
      showToast('Video generated — preview it below, then save or regenerate', 'success');
    } else {
      showToast('No video returned — try a different model or prompt', 'error');
    }
  } catch (err) {
    if (err.message?.includes('429') || err.message?.includes('rate_limited')) {
      showToast('Rate limit reached — try a different model or wait a bit', 'error');
    } else {
      showToast(err.message, 'error');
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<svg width="15" height="15" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg> Generate Video';
    loading.style.display = 'none';
  }
}

function regenerateVideo() {
  generateVideo();
}

async function saveGeneratedVideo() {
  if (!window._generatedVideoB64 || !modalItemId) return;
  const prompt = document.getElementById('modal-video-prompt')?.value || '';

  try {
    const data = await api('/api/video/save', 'POST', {
      content_id: modalItemId,
      video_base64: window._generatedVideoB64,
      video_prompt: prompt,
      mime_type: window._generatedVideoMime || 'video/mp4',
    });

    const savedSection = document.getElementById('modal-saved-video');
    const preview = document.getElementById('modal-saved-video-preview');
    preview.src = data.video_path + '?t=' + Date.now();
    savedSection.style.display = '';

    showToast('Video saved', 'success');
    if (currentPage === 'library') loadLibrary();
    loadRecentContent();
  } catch (err) {
    showToast('Failed to save video: ' + err.message, 'error');
  }
}

async function removeVideo() {
  if (!modalItemId) return;
  try {
    await api(`/api/content/${modalItemId}/video`, 'DELETE');
    document.getElementById('modal-saved-video').style.display = 'none';
    document.getElementById('modal-video-result').style.display = 'none';
    window._generatedVideoB64 = null;
    window._generatedVideoMime = null;
    showToast('Video removed', 'success');
    if (currentPage === 'library') loadLibrary();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function searchStockFootage() {
  if (!modalItemId) return;
  const caption = document.getElementById('modal-caption-text')?.value || '';
  const query = prompt('Search stock footage (Pexels):', caption.split('\n')[0]?.substring(0, 50) || 'smart home');
  if (!query) return;

  const aspect = document.getElementById('modal-video-aspect')?.value || '9:16';
  const orientation = aspect === '16:9' ? 'landscape' : aspect === '1:1' ? 'square' : 'portrait';

  try {
    const data = await api('/api/video/stock-footage', 'POST', { query, orientation, per_page: 6 });
    const grid = document.getElementById('modal-stock-grid');
    grid.innerHTML = '';

    if (!data.videos?.length) {
      showToast('No stock footage found for that query', 'error');
      return;
    }

    data.videos.forEach(v => {
      const card = document.createElement('div');
      card.style.cssText = 'position:relative;border-radius:12px;overflow:hidden;cursor:pointer;border:2px solid transparent;transition:all 0.2s;';
      card.onmouseover = () => { card.style.borderColor = '#2dd4bf'; };
      card.onmouseout = () => { card.style.borderColor = 'transparent'; };
      card.onclick = () => {
        window.open(v.url, '_blank');
        showToast('Stock footage link opened — download and use in your editor', 'success');
      };

      card.innerHTML = `
        <img src="${v.preview}" style="width:100%;aspect-ratio:16/9;object-fit:cover;display:block;" />
        <div style="position:absolute;bottom:0;left:0;right:0;background:linear-gradient(transparent,rgba(0,0,0,0.8));padding:8px;font-size:0.72rem;color:#fff;">
          ${v.duration}s · ${v.width}x${v.height}
        </div>
      `;
      grid.appendChild(card);
    });

    document.getElementById('modal-stock-results').style.display = '';
    showToast(`Found ${data.videos.length} stock clips — click to open`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function loadCurrentUser() {
  try {
    const user = await api('/api/me');
    window._currentUser = user;
    const usernameEl = document.getElementById('settings-username');
    const roleEl = document.getElementById('settings-role');
    if (usernameEl) usernameEl.textContent = user.display_name || user.username;
    if (roleEl) roleEl.textContent = user.role === 'masteradmin' ? 'Master Admin' : 'Admin';
    // Show User Management nav for masteradmin only
    const navUsers = document.getElementById('nav-users');
    if (navUsers) navUsers.style.display = user.role === 'masteradmin' ? '' : 'none';
    // Environment badge — only shown when not production
    const envBadge = document.getElementById('env-badge');
    if (envBadge && user.app_env && user.app_env !== 'production') {
      envBadge.textContent = user.app_env.toUpperCase();
      envBadge.style.display = 'inline-block';
      // Colour-code: staging = amber, dev/other = red
      if (user.app_env === 'staging') {
        envBadge.style.background = '#fbbf24';
        envBadge.style.color = '#78350f';
      } else {
        envBadge.style.background = '#ef4444';
        envBadge.style.color = '#fff';
      }
      // Also tint the browser tab title so you can tell staging apart in the tab bar
      document.title = `[${user.app_env.toUpperCase()}] ${document.title}`;
    }
  } catch { /* silent */ }
}

async function changePassword() {
  const current = document.getElementById('s-current-password')?.value;
  const newPw = document.getElementById('s-new-password')?.value;
  const confirm = document.getElementById('s-confirm-password')?.value;

  if (!current) { showToast('Enter your current password', 'error'); return; }
  if (!newPw || newPw.length < 6) { showToast('New password must be at least 6 characters', 'error'); return; }
  if (newPw !== confirm) { showToast('New passwords do not match', 'error'); return; }

  try {
    await api('/api/change-password', 'POST', { current_password: current, new_password: newPw });
    showToast('Password changed successfully', 'success');
    document.getElementById('s-current-password').value = '';
    document.getElementById('s-new-password').value = '';
    document.getElementById('s-confirm-password').value = '';
  } catch (err) { showToast(err.message, 'error'); }
}

// ── User Management ───────────────────────────────────────────────────────

async function loadUsers() {
  const table = document.getElementById('users-table');
  const countEl = document.getElementById('users-count');
  if (!table) return;
  table.innerHTML = '<div style="padding:20px;text-align:center;color:#64748b;font-size:0.8rem;">Loading...</div>';
  try {
    const data = await api('/api/users');
    const users = data.users || [];
    if (countEl) countEl.textContent = `${users.length} user${users.length !== 1 ? 's' : ''}`;
    if (!users.length) {
      table.innerHTML = '<div style="padding:32px;text-align:center;color:#64748b;">No users found.</div>';
      return;
    }
    table.innerHTML = users.map(u => {
      const isMaster = u.role === 'masteradmin';
      const roleBadge = isMaster
        ? '<span style="font-size:0.7rem;font-weight:700;background:rgba(251,191,36,0.12);color:#fbbf24;border:1px solid rgba(251,191,36,0.25);padding:2px 8px;border-radius:99px;">Master Admin</span>'
        : u.role === 'admin'
        ? '<span style="font-size:0.7rem;font-weight:700;background:rgba(99,102,241,0.12);color:#a5b4fc;border:1px solid rgba(99,102,241,0.25);padding:2px 8px;border-radius:99px;">Admin</span>'
        : '<span style="font-size:0.7rem;font-weight:700;background:rgba(45,212,191,0.12);color:#2dd4bf;border:1px solid rgba(45,212,191,0.25);padding:2px 8px;border-radius:99px;">Viewer</span>';
      const actions = isMaster
        ? '<span style="font-size:0.72rem;color:#475569;font-style:italic;">Protected</span>'
        : `<button class="btn-ghost" onclick="promptResetPassword(${u.id},'${u.username}')" style="font-size:0.72rem;color:#818cf8;">Reset Password</button>
           <button class="btn-ghost" onclick="confirmDeleteUser(${u.id},'${u.username}')" style="font-size:0.72rem;color:#f87171;">Delete</button>`;
      return `<div style="display:flex;align-items:center;justify-content:space-between;padding:14px 20px;border-bottom:1px solid rgba(255,255,255,0.04);">
        <div style="display:flex;align-items:center;gap:12px;min-width:0;">
          <div style="width:36px;height:36px;border-radius:10px;background:${isMaster ? 'linear-gradient(135deg,#f59e0b,#d97706)' : 'linear-gradient(135deg,#6366f1,#8b5cf6)'};display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:0.8rem;flex-shrink:0;">${(u.display_name || u.username).charAt(0).toUpperCase()}</div>
          <div style="min-width:0;">
            <div style="font-weight:700;font-size:0.875rem;color:#f1f5f9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${u.display_name || u.username}</div>
            <div style="font-size:0.75rem;color:#64748b;">@${u.username} ${roleBadge}</div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:4px;flex-shrink:0;">${actions}</div>
      </div>`;
    }).join('');
  } catch (err) {
    table.innerHTML = `<div style="padding:20px;text-align:center;color:#f87171;font-size:0.8rem;">${err.message}</div>`;
  }
}

function showAddUserForm() {
  document.getElementById('add-user-form').style.display = '';
  document.getElementById('new-user-username').focus();
}

function hideAddUserForm() {
  document.getElementById('add-user-form').style.display = 'none';
  ['new-user-username','new-user-display','new-user-password'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
}

async function createUser() {
  const username = document.getElementById('new-user-username')?.value.trim();
  const display_name = document.getElementById('new-user-display')?.value.trim();
  const password = document.getElementById('new-user-password')?.value;
  const role = document.getElementById('new-user-role')?.value || 'admin';

  if (!username || username.length < 3) { showToast('Username must be at least 3 characters', 'error'); return; }
  if (!password || password.length < 6) { showToast('Password must be at least 6 characters', 'error'); return; }

  try {
    await api('/api/users', 'POST', { username, password, role, display_name: display_name || username });
    showToast(`User '${username}' created`, 'success');
    hideAddUserForm();
    loadUsers();
  } catch (err) { showToast(err.message, 'error'); }
}

function promptResetPassword(userId, username) {
  const newPw = prompt(`Enter new password for @${username} (min 6 characters):`);
  if (!newPw) return;
  if (newPw.length < 6) { showToast('Password must be at least 6 characters', 'error'); return; }
  resetUserPassword(userId, username, newPw);
}

async function resetUserPassword(userId, username, newPassword) {
  try {
    await api(`/api/users/${userId}/reset-password`, 'POST', { new_password: newPassword });
    showToast(`Password reset for @${username}`, 'success');
  } catch (err) { showToast(err.message, 'error'); }
}

async function confirmDeleteUser(userId, username) {
  if (!confirm(`Delete user @${username}? This cannot be undone.`)) return;
  try {
    await api(`/api/users/${userId}`, 'DELETE');
    showToast(`User @${username} deleted`, 'success');
    loadUsers();
  } catch (err) { showToast(err.message, 'error'); }
}

async function logoutUser() {
  try { await api('/api/logout', 'POST'); } catch { /* ignore */ }
  window.location.href = '/login';
}

// ── V3 Content Creation Wizard ────────────────────────────────────────────────

let wizardState = { intent: null, duration: 10, topicMode: 'auto', selectedTopicId: null, videoProvider: null };
let _wizardTopicsPopulated = false;
let _wizardCurrentContentId = null;
let _wizardGeneratedImages = [];

function setWizardIntent(intent) {
  wizardState.intent = intent;

  const imgCard = document.getElementById('wizard-intent-image');
  const vidCard = document.getElementById('wizard-intent-video');

  if (imgCard) {
    imgCard.style.borderColor = intent === 'image' ? '#6366f1' : 'rgba(255,255,255,0.1)';
    imgCard.style.background  = intent === 'image' ? 'rgba(99,102,241,0.1)' : 'rgba(15,23,42,0.4)';
  }
  if (vidCard) {
    vidCard.style.borderColor = intent === 'video' ? '#ec4899' : 'rgba(255,255,255,0.1)';
    vidCard.style.background  = intent === 'video' ? 'rgba(236,72,153,0.08)' : 'rgba(15,23,42,0.4)';
  }

  const durRow = document.getElementById('wizard-duration-row');
  if (durRow) durRow.style.display = intent === 'video' ? '' : 'none';

  const vidProvRow = document.getElementById('wizard-video-provider-row');
  if (vidProvRow) vidProvRow.style.display = intent === 'video' ? '' : 'none';

  const aiLabel = document.getElementById('wizard-ai-label');
  if (aiLabel) aiLabel.textContent = intent === 'video' ? 'Caption AI Engine' : 'AI Engine';

  updateWizardGenBtn();
}

function toggleWizardPlatform(card) {
  // Multi-select: toggle the clicked card
  const colors = { instagram: '#e1306c', linkedin: '#0a66c2', facebook: '#1877f2' };
  const platform = card.dataset.platform;
  const suffix = platform === 'instagram' ? 'ig' : platform === 'linkedin' ? 'li' : 'fb';
  const isSelected = card.dataset.selected === '1';
  const ind = card.querySelector('.plat-check-indicator');

  if (isSelected) {
    // Deselect — but keep at least one selected
    const container = document.getElementById('wizard-platform-cards');
    const selectedCount = container.querySelectorAll('.plat-card[data-selected="1"]').length;
    if (selectedCount <= 1) return; // prevent zero selection
    card.dataset.selected = '0';
    card.classList.remove(`sel-${suffix}`);
    if (ind) { ind.textContent = '+ Select'; ind.style.color = '#94a3b8'; ind.style.fontWeight = '500'; }
  } else {
    card.dataset.selected = '1';
    card.classList.add(`sel-${suffix}`);
    if (ind) { ind.textContent = '✓ Selected'; ind.style.color = colors[platform]; ind.style.fontWeight = '600'; }
  }

  updateWizardGenBtn();
}

function setWizardDuration(dur) {
  wizardState.duration = dur;
  [5, 10].forEach(d => {
    const btn = document.getElementById(`wdur-${d}`);
    if (!btn) return;
    const active = d === dur;
    btn.style.background   = active ? 'rgba(99,102,241,0.15)' : 'transparent';
    btn.style.color        = active ? '#818cf8' : '#94a3b8';
    btn.style.borderColor  = active ? '#6366f1' : 'rgba(255,255,255,0.12)';
    btn.textContent = `${d}s` + (active ? ' ✓' : '');
  });
  updateWizardGenBtn();
}

function setTopicMode(mode) {
  wizardState.topicMode = mode;
  wizardState.selectedTopicId = null;

  const autoCard   = document.getElementById('wizard-topic-auto');
  const chooseCard = document.getElementById('wizard-topic-choose');
  const chooser    = document.getElementById('wizard-topic-chooser');

  if (autoCard) {
    autoCard.style.borderColor = mode === 'auto' ? '#6366f1' : 'rgba(255,255,255,0.1)';
    autoCard.style.background  = mode === 'auto' ? 'rgba(99,102,241,0.1)' : 'rgba(15,23,42,0.3)';
  }
  if (chooseCard) {
    chooseCard.style.borderColor = mode === 'choose' ? '#6366f1' : 'rgba(255,255,255,0.1)';
    chooseCard.style.background  = mode === 'choose' ? 'rgba(99,102,241,0.1)' : 'rgba(15,23,42,0.3)';
  }
  if (chooser) chooser.style.display = mode === 'choose' ? '' : 'none';

  if (mode === 'choose') populateWizardTopics();
  updateWizardGenBtn();
}

function populateWizardTopics() {
  if (_wizardTopicsPopulated) return;
  const grid = document.getElementById('wizard-topic-grid');
  if (!grid) return;
  const topics = window._topicTemplates || [];
  if (!topics.length) {
    grid.innerHTML = '<span style="font-size:0.8rem;color:#64748b;">No topics available — type a custom topic below.</span>';
    _wizardTopicsPopulated = true;
    return;
  }
  grid.innerHTML = '';
  topics.forEach(t => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = t.topic;
    btn.style.cssText = 'padding:6px 14px;border-radius:99px;border:1px solid rgba(255,255,255,0.12);font-size:0.78rem;font-weight:600;background:transparent;color:#94a3b8;cursor:pointer;transition:all 0.15s;';
    btn.onclick = () => selectWizardTopic(t.id, btn);
    grid.appendChild(btn);
  });
  _wizardTopicsPopulated = true;
}

function selectWizardTopic(topicId, btn) {
  wizardState.selectedTopicId = topicId;
  const grid = document.getElementById('wizard-topic-grid');
  if (grid) {
    grid.querySelectorAll('button').forEach(b => {
      b.style.background   = 'transparent';
      b.style.color        = '#94a3b8';
      b.style.borderColor  = 'rgba(255,255,255,0.12)';
    });
  }
  if (btn) {
    btn.style.background   = 'rgba(99,102,241,0.15)';
    btn.style.color        = '#a5b4fc';
    btn.style.borderColor  = '#6366f1';
  }
  updateWizardGenBtn();
}

function updateWizardGenBtn() {
  const btn  = document.getElementById('wizard-gen-btn');
  const hint = document.getElementById('wizard-gen-hint');
  if (!btn) return;

  const platformSelected = !!document.querySelector('#wizard-platform-cards .plat-card[data-selected="1"]');
  const intentSelected   = !!wizardState.intent;

  const ready = intentSelected && platformSelected;
  btn.disabled = !ready;
  btn.style.background    = ready ? '' : 'rgba(99,102,241,0.35)';
  btn.style.color         = ready ? '' : 'rgba(255,255,255,0.4)';
  btn.style.cursor        = ready ? 'pointer' : 'not-allowed';

  // Remove inline styles so .btn-primary kicks in when enabled
  if (ready) {
    btn.removeAttribute('style');
    btn.style.display = 'inline-flex';
    btn.style.alignItems = 'center';
    btn.style.gap = '8px';
    btn.style.padding = '13px 28px';
  }

  if (hint) {
    if (!intentSelected && !platformSelected) {
      hint.textContent = 'Select intent + platform to continue';
    } else if (!intentSelected) {
      hint.textContent = 'Select Image Post or Video Post above';
    } else if (!platformSelected) {
      hint.textContent = 'Select a platform to continue';
    } else {
      hint.textContent = wizardState.intent === 'video'
        ? `Ready — generate ${wizardState.duration}s ${wizardState.videoProvider ? `with ${wizardState.videoProvider.replace('_', ' ')}` : 'video'}`
        : 'Ready — click to generate!';
    }
  }
}

function onVariantModeChange() {
  const mode = document.getElementById('wizard-variant-mode')?.value || 'auto';
  const wrap = document.getElementById('wizard-pick-format-wrap');
  if (!wrap) return;
  wrap.style.display = (mode === 'pick') ? 'flex' : 'none';
  wrap.style.flexDirection = 'column';
}

async function wizardGenerate() {
  const selectedCards = document.querySelectorAll('#wizard-platform-cards .plat-card[data-selected="1"]');
  const platforms = selectedCards.length
    ? [...selectedCards].map(c => c.dataset.platform)
    : ['instagram'];
  const provider   = document.getElementById('wizard-ai-provider')?.value || 'gemini';
  const customTopic = document.getElementById('wizard-custom-topic')?.value.trim() || '';

  const chosenTopic = wizardState.topicMode === 'choose' && wizardState.selectedTopicId;
  const variantMode   = document.getElementById('wizard-variant-mode')?.value || 'auto';
  const pickedFormat  = document.getElementById('wizard-post-format')?.value || 'classic_paragraph';
  const emojiDensity  = document.getElementById('wizard-emoji-density')?.value || 'balanced';
  const body = {
    mode: chosenTopic ? 'manual' : 'quick',
    platforms,
    ai_provider: provider,
    variant_mode: variantMode,
    emoji_density: emojiDensity,
  };
  if (variantMode === 'pick') body.post_format = pickedFormat;
  if (chosenTopic) {
    body.topic_id = wizardState.selectedTopicId;
  }
  if (customTopic) body.custom_topic = customTopic;

  // Show loading, hide wizard
  document.getElementById('wizard-card').style.display = 'none';
  document.getElementById('gen-loading').style.display = '';
  document.getElementById('gen-loading-text').textContent = 'Generating your content…';
  document.getElementById('gen-results').style.display = 'none';

  try {
    const data = await api('/api/generate', 'POST', body);
    document.getElementById('gen-loading').style.display = 'none';

    if (data.aifiesta_mode) {
      showAiFiestaPrompt(data);
      document.getElementById('gen-results').style.display = '';
      return;
    }

    data.errors?.forEach(e => showToast(`${e.platform}: ${e.error}`, 'error'));

    if (data.generated?.length) {
      loadStats();
      loadRecentContent();
      // Multi-variant: show picker screen so user can choose between 3 formats
      if (data.variant_mode === 'multi' && data.generated.length > 1) {
        showToast(`Generated ${data.generated.length} variants — pick your favourite`, 'success');
        showWizardResults(data.generated, wizardState.intent, data);
      } else {
        // Single post: skip results screen, go straight to post view
        showToast('Post generated — opening…', 'success');
        const firstId = data.generated[0].id;
        showPage('library');
        openModal(firstId);
      }
    } else {
      // Nothing generated — show wizard again
      document.getElementById('wizard-card').style.display = '';
      showToast('No content generated — try again', 'error');
    }
  } catch (err) {
    document.getElementById('gen-loading').style.display = 'none';
    document.getElementById('wizard-card').style.display = '';
    showToast(err.message, 'error');
  }
}

function showWizardResults(items, intent, meta) {
  const results  = document.getElementById('gen-results');
  const list     = document.getElementById('gen-results-list');
  const chips    = document.getElementById('gen-meta-chips');
  const imgSec   = document.getElementById('gen-image-section');
  const vidSec   = document.getElementById('gen-video-section');

  list.innerHTML = '';
  if (chips) {
    if (meta?.topic) {
      chips.style.display = 'flex';
      const formatLabels = (items || []).map(i => i.post_format_label).filter(Boolean);
      const formatChip = formatLabels.length
        ? `<span style="color:rgba(165,180,252,0.4);">|</span><span><strong>Format:</strong> ${[...new Set(formatLabels)].join(' + ')}</span>`
        : '';
      chips.innerHTML = `<span>🎯 <strong>Topic:</strong> ${meta.topic}</span><span style="color:rgba(165,180,252,0.4);">|</span><span><strong>Type:</strong> ${meta.content_type}</span><span style="color:rgba(165,180,252,0.4);">|</span><span><strong>Tone:</strong> ${meta.tone}</span>${formatChip}`;
    } else {
      chips.style.display = 'none';
    }
  }

  items.forEach(item => list.appendChild(buildContentCard(item, true)));
  results.style.display = '';

  // Hide both media sections to start
  if (imgSec) imgSec.style.display = 'none';
  if (vidSec) vidSec.style.display = 'none';

  if (!items.length) return;

  const firstItem = items[0];
  _wizardCurrentContentId = firstItem.id;

  if (intent === 'image') {
    wizardAutoImages(firstItem);
  } else if (intent === 'video') {
    wizardAutoVideoPrompts(firstItem);
  }
}

async function wizardAutoImages(item) {
  const imgSec    = document.getElementById('gen-image-section');
  const imgLoad   = document.getElementById('gen-image-loading');
  const imgGrid   = document.getElementById('gen-image-grid');
  const imgError  = document.getElementById('gen-image-error');
  const imgSaved  = document.getElementById('gen-image-saved');

  if (!imgSec) return;
  imgSec.style.display = '';
  if (imgGrid)       { imgGrid.style.display  = 'none'; imgGrid.innerHTML = ''; }
  if (imgError)      { imgError.style.display = 'none'; }
  if (imgSaved)      { imgSaved.style.display = 'none'; }
  const imgPromptRow = document.getElementById('gen-image-prompt-row');
  const imgPromptTA  = document.getElementById('gen-image-prompt');
  if (imgPromptRow)  imgPromptRow.style.display = 'none';
  if (imgLoad)       imgLoad.style.display = '';

  imgSec.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  try {
    // Refine the prompt only — don't auto-generate (saves credits)
    const refineData = await api('/api/refine-image-prompt', 'POST', { content_id: item.id });
    const prompt = refineData.prompt || item.image_suggestion || 'A modern smart home scene';

    if (imgLoad) imgLoad.style.display = 'none';
    if (imgPromptTA)  imgPromptTA.value = prompt;
    if (imgPromptRow) imgPromptRow.style.display = '';
    const imgSub = document.getElementById('gen-image-subtitle');
    if (imgSub) imgSub.textContent = 'Review the prompt, then generate images';
  } catch (err) {
    if (imgLoad) imgLoad.style.display = 'none';
    // Still show the prompt row with a fallback so user can proceed
    if (imgPromptTA)  imgPromptTA.value = item.image_suggestion || 'A modern smart home scene';
    if (imgPromptRow) imgPromptRow.style.display = '';
  }
}

async function wizardGenerateImages() {
  const contentId = _wizardCurrentContentId;
  const imgLoad = document.getElementById('gen-image-loading');
  const imgGrid = document.getElementById('gen-image-grid');
  const imgError = document.getElementById('gen-image-error');
  const imgBtn  = document.getElementById('gen-image-btn');
  const prompt  = document.getElementById('gen-image-prompt')?.value?.trim();

  if (!prompt)     { showToast('Enter an image prompt first', 'error'); return; }
  if (!contentId)  { showToast('No content — regenerate first', 'error'); return; }

  if (imgError)  imgError.style.display = 'none';
  if (imgGrid)   { imgGrid.style.display = 'none'; imgGrid.innerHTML = ''; }
  if (imgLoad)   imgLoad.style.display = '';
  if (imgBtn)    { imgBtn.disabled = true; imgBtn.textContent = 'Generating…'; }

  try {
    const genData = await api('/api/generate-image', 'POST', {
      content_id: contentId,
      prompt,
      provider: 'imagen4',
      num_images: 4,
      aspect_ratio: '1:1',
      idempotency_key: crypto.randomUUID(),
    });

    _wizardGeneratedImages = genData.images || [];
    if (!_wizardGeneratedImages.length) throw new Error('No images returned');

    if (imgLoad) imgLoad.style.display = 'none';
    const imgSub = document.getElementById('gen-image-subtitle');
    if (imgSub) imgSub.textContent = 'Choose an image for your post';
    if (imgGrid) {
      imgGrid.innerHTML = '';
      imgGrid.style.display = 'grid';
      _wizardGeneratedImages.forEach((img, idx) => {
        const wrap = document.createElement('div');
        wrap.id = `wiz-img-${idx}`;
        wrap.style.cssText = 'position:relative;border-radius:12px;overflow:hidden;cursor:pointer;border:3px solid transparent;transition:all 0.2s;';
        wrap.onmouseover = () => { if (!wrap.dataset.selected) wrap.style.borderColor = 'rgba(165,180,252,0.3)'; };
        wrap.onmouseout  = () => { if (!wrap.dataset.selected) wrap.style.borderColor = 'transparent'; };
        wrap.onclick = () => wizardSelectImage(idx, contentId);

        const imgEl = document.createElement('img');
        imgEl.src = `data:${img.mime_type};base64,${img.base64}`;
        imgEl.style.cssText = 'width:100%;display:block;aspect-ratio:1;object-fit:cover;';
        wrap.appendChild(imgEl);

        const badge = document.createElement('div');
        badge.style.cssText = 'position:absolute;top:8px;left:8px;background:rgba(15,23,42,0.7);border-radius:6px;padding:3px 8px;font-size:0.7rem;font-weight:700;color:#e2e8f0;';
        badge.textContent = `${idx + 1}`;
        wrap.appendChild(badge);

        imgGrid.appendChild(wrap);
      });
    }
    showToast('4 images ready — click to select one', 'success');
  } catch (err) {
    if (imgLoad) imgLoad.style.display = 'none';
    const imgSubErr = document.getElementById('gen-image-subtitle');
    if (imgSubErr) imgSubErr.textContent = 'Image generation failed';
    if (imgError) {
      imgError.textContent = `Image generation failed: ${err.message}`;
      imgError.style.display = '';
    }
  } finally {
    if (imgBtn) { imgBtn.disabled = false; imgBtn.innerHTML = '<svg width="15" height="15" fill="none" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="3" stroke="currentColor" stroke-width="2"/><path stroke="currentColor" stroke-width="2" d="M3 15l5-5 4 4 3-3 6 6"/></svg> Generate Images'; }
  }
}

async function wizardSelectImage(idx, contentId) {
  const img = _wizardGeneratedImages[idx];
  if (!img) return;

  // Highlight selection
  _wizardGeneratedImages.forEach((_, i) => {
    const wrap = document.getElementById(`wiz-img-${i}`);
    if (wrap) {
      wrap.style.borderColor = i === idx ? '#6366f1' : 'transparent';
      wrap.dataset.selected  = i === idx ? '1' : '';
    }
  });

  try {
    await api('/api/save-image', 'POST', {
      content_id: contentId,
      image_base64: img.base64,
      image_prompt: img.prompt || '',
      mime_type: img.mime_type || 'image/png',
    });
    showToast('Image saved — opening post…', 'success');
    // Navigate directly to the post view modal
    setTimeout(() => {
      showPage('library');
      openModal(contentId);
    }, 600);
  } catch (err) {
    showToast(`Save failed: ${err.message}`, 'error');
  }
}

async function wizardAutoVideoPrompts(item) {
  const vidSec   = document.getElementById('gen-video-section');
  const vidLoad  = document.getElementById('gen-video-loading');
  const vidPrompts = document.getElementById('gen-video-prompts');
  const vidError = document.getElementById('gen-video-error');

  if (!vidSec) return;
  vidSec.style.display = '';
  if (vidPrompts) { vidPrompts.style.display = 'none'; vidPrompts.innerHTML = ''; }
  if (vidError)   vidError.style.display = 'none';
  if (vidLoad)    vidLoad.style.display = '';

  vidSec.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  try {
    const data = await api('/api/video/suggest-prompts', 'POST', { content_id: item.id });
    const prompts = data.prompts || [];

    if (vidLoad) vidLoad.style.display = 'none';
    if (!prompts.length) throw new Error('No prompt suggestions returned');

    if (vidPrompts) {
      vidPrompts.innerHTML = '';
      const styles = [
        { label: 'Cinematic',  color: '#818cf8', bg: 'rgba(99,102,241,0.1)',  border: 'rgba(99,102,241,0.25)'  },
        { label: 'Dynamic',    color: '#fb923c', bg: 'rgba(251,146,60,0.08)', border: 'rgba(251,146,60,0.25)'  },
        { label: 'Minimal',    color: '#2dd4bf', bg: 'rgba(45,212,191,0.08)', border: 'rgba(45,212,191,0.25)'  },
      ];
      prompts.slice(0, 3).forEach((p, idx) => {
        const s = styles[idx] || styles[0];
        const card = document.createElement('div');
        card.id = `wiz-vprompt-${idx}`;
        card.style.cssText = `border:2px solid ${s.border};border-radius:12px;padding:16px;cursor:pointer;transition:all 0.2s;background:transparent;`;
        card.onmouseover = () => { card.style.background = s.bg; };
        card.onmouseout  = () => { if (!card.dataset.selected) card.style.background = 'transparent'; };
        card.onclick = () => selectWizardVideoPrompt(idx);

        const promptText = typeof p === 'string' ? p : (p.prompt || p.text || JSON.stringify(p));
        card.innerHTML = `
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
            <span style="font-size:0.7rem;font-weight:700;padding:3px 10px;border-radius:20px;background:${s.bg};color:${s.color};border:1px solid ${s.border};">${s.label}</span>
          </div>
          <div style="font-size:0.82rem;color:#cbd5e1;line-height:1.55;">${promptText}</div>`;
        card.dataset.prompt = promptText;
        vidPrompts.appendChild(card);
      });
      vidPrompts.style.display = 'flex';
    }
    showToast('Video prompts ready — pick a style', 'success');
  } catch (err) {
    if (vidLoad) vidLoad.style.display = 'none';
    if (vidError) {
      vidError.textContent = `Prompt generation failed: ${err.message}`;
      vidError.style.display = '';
    }
  }
}

function selectWizardVideoPrompt(idx) {
  // Highlight selected card
  for (let i = 0; i < 3; i++) {
    const c = document.getElementById(`wiz-vprompt-${i}`);
    if (c) {
      c.dataset.selected = i === idx ? '1' : '';
      c.style.borderColor = i === idx ? '#6366f1' : c.style.borderColor;
      if (i !== idx) c.style.background = 'transparent';
    }
  }
  const selected = document.getElementById(`wiz-vprompt-${idx}`);
  if (selected) selected.style.background = 'rgba(99,102,241,0.1)';

  // Populate textarea
  const card = document.getElementById(`wiz-vprompt-${idx}`);
  const promptText = card?.dataset.prompt || '';
  const textarea = document.getElementById('gen-video-prompt-text');
  if (textarea) textarea.value = promptText;

  // Show editor
  const editor = document.getElementById('gen-video-editor');
  if (editor) editor.style.display = '';
  editor?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function wizardGenerateVideo() {
  const contentId  = _wizardCurrentContentId;
  const prompt     = document.getElementById('gen-video-prompt-text')?.value.trim();
  const aspect     = document.getElementById('gen-video-aspect')?.value || '9:16';
  const duration   = wizardState.duration || 8;
  const vidResult  = document.getElementById('gen-video-result');
  const vidError   = document.getElementById('gen-video-error');
  const genBtn     = document.getElementById('gen-video-gen-btn');

  if (!contentId) { showToast('No content ID — please regenerate', 'error'); return; }
  if (!prompt)    { showToast('Please enter a video prompt', 'error'); return; }

  const provider = wizardState.videoProvider || 'kling_free';
  if (!wizardState.videoProvider) {
    showToast('Select a video provider above first', 'error'); return;
  }

  if (vidResult) vidResult.style.display = 'none';
  if (vidError)  vidError.style.display = 'none';

  // Start elapsed timer on button
  let elapsedSec = 0;
  const elapsedTimer = setInterval(() => {
    elapsedSec++;
    if (genBtn) genBtn.innerHTML = `<svg class="spin" width="15" height="15" fill="none" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" opacity="0.25"/><path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Generating… ${elapsedSec}s`;
  }, 1000);
  if (genBtn) { genBtn.disabled = true; genBtn.innerHTML = '<svg class="spin" width="15" height="15" fill="none" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" opacity="0.25"/><path fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Generating… 0s'; }

  try {
    const data = await api('/api/video/generate', 'POST', {
      content_id: contentId,
      prompt,
      provider,
      aspect_ratio: aspect,
      duration,
      use_paid: provider.endsWith('_pro') || provider.endsWith('_paid'),
      idempotency_key: crypto.randomUUID(),
    });
    clearInterval(elapsedTimer);

    // Save the video
    if (data.video_base64) {
      await api('/api/video/save', 'POST', {
        content_id: contentId,
        video_base64: data.video_base64,
        video_prompt: prompt,
        mime_type: data.mime_type || 'video/mp4',
      });
    }

    // Show inline video player
    if (vidResult) {
      if (data.video_base64) {
        vidResult.innerHTML = `
          <div style="border-radius:12px;overflow:hidden;margin-bottom:10px;">
            <video controls style="width:100%;display:block;border-radius:12px;" src="data:${data.mime_type || 'video/mp4'};base64,${data.video_base64}"></video>
          </div>
          <div style="font-size:0.8rem;color:#86efac;font-weight:600;">✓ Video saved to post</div>`;
      } else {
        vidResult.innerHTML = `<div style="font-size:0.8rem;color:#86efac;">✓ Video generated and saved</div>`;
      }
      vidResult.style.display = '';
    }

    showToast('Video generated and saved!', 'success');
    loadStats(); loadRecentContent();
  } catch (err) {
    clearInterval(elapsedTimer);
    if (vidError) {
      vidError.textContent = `Video generation failed: ${err.message}`;
      vidError.style.display = '';
    }
    showToast(err.message, 'error');
  } finally {
    clearInterval(elapsedTimer);
    if (genBtn) {
      genBtn.disabled = false;
      genBtn.innerHTML = '<svg width="15" height="15" fill="none" stroke="currentColor" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3" stroke-width="2"/></svg> Generate Video';
    }
  }
}

function resetWizard() {
  // Reset state
  wizardState = { intent: null, duration: 10, topicMode: 'auto', selectedTopicId: null, videoProvider: null };
  _wizardCurrentContentId = null;
  _wizardGeneratedImages  = [];

  // Reset intent cards
  const imgCard = document.getElementById('wizard-intent-image');
  const vidCard = document.getElementById('wizard-intent-video');
  if (imgCard) { imgCard.style.borderColor = 'rgba(255,255,255,0.1)'; imgCard.style.background = 'rgba(15,23,42,0.4)'; }
  if (vidCard) { vidCard.style.borderColor = 'rgba(255,255,255,0.1)'; vidCard.style.background = 'rgba(15,23,42,0.4)'; }

  // Reset duration row
  const durRow = document.getElementById('wizard-duration-row');
  if (durRow) durRow.style.display = 'none';
  setWizardDuration(10);

  // Reset platform (Instagram pre-selected)
  const cards = document.querySelectorAll('#wizard-platform-cards .plat-card');
  const colors = { instagram: '#e1306c', linkedin: '#0a66c2', facebook: '#1877f2' };
  cards.forEach(card => {
    const platform = card.dataset.platform;
    const isIG = platform === 'instagram';
    const ind = card.querySelector('.plat-check-indicator');
    card.dataset.selected = isIG ? '1' : '0';
    card.classList.remove('sel-ig', 'sel-li', 'sel-fb');
    if (isIG) {
      card.classList.add('sel-ig');
      if (ind) { ind.textContent = '✓ Selected'; ind.style.color = colors.instagram; ind.style.fontWeight = '600'; }
    } else {
      if (ind) { ind.textContent = '+ Select'; ind.style.color = '#94a3b8'; ind.style.fontWeight = '500'; }
    }
  });

  // Reset topic mode
  setTopicMode('auto');
  const customInput = document.getElementById('wizard-custom-topic');
  if (customInput) customInput.value = '';

  // Reset AI provider to Gemini
  const provSel = document.getElementById('wizard-ai-provider');
  if (provSel) provSel.value = 'gemini';

  // Reset variant mode to auto and hide pick-format dropdown
  const variantSel = document.getElementById('wizard-variant-mode');
  if (variantSel) variantSel.value = 'auto';
  onVariantModeChange();

  // Reset generate button
  updateWizardGenBtn();

  // Show wizard, hide results
  const wizardCard = document.getElementById('wizard-card');
  const results    = document.getElementById('gen-results');
  const loading    = document.getElementById('gen-loading');
  if (wizardCard) wizardCard.style.display = '';
  if (results)    results.style.display    = 'none';
  if (loading)    loading.style.display    = 'none';

  wizardCard?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── End V3 Wizard ─────────────────────────────────────────────────────────────

async function api(url, method = 'GET', body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  if (res.status === 401) {
    window.location.href = '/login';
    throw new Error('Session expired');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || err.error || err.message || res.statusText);
  }
  return res.json();
}
