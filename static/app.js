// ══════════ State ══════════
let currentPage = 'dashboard';
let modalItemId = null;
let modalDirty = false;
let suggestions = { topics: [], content_types: [], tones: [] };
let generatedImages = [];    // [{base64, mime_type}, ...]
let selectedImageIdx = null; // index of user-picked image

// ══════════ Init ══════════
document.addEventListener('DOMContentLoaded', async () => {
  setGreeting();
  await Promise.all([loadHealth(), loadStats(), loadSuggestions(), loadModels(), loadSettings()]);
  loadRecentContent();
});

// ══════════ Greeting & Date ══════════
function setGreeting() {
  const h = new Date().getHours();
  const greetings = [[6,'Good morning! ☀️'],[12,'Good afternoon! 👋'],[18,'Good evening! 🌙'],[22,'Working late! 🌟']];
  const g = greetings.reduce((a, b) => h >= b[0] ? b : a)[1];
  const el = document.getElementById('greeting-text');
  if (el) el.textContent = g;
  const d = document.getElementById('today-date');
  if (d) d.textContent = new Date().toLocaleDateString('en-AU', { weekday:'long', day:'numeric', month:'long', year:'numeric' });
}

// ══════════ Navigation ══════════
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
}

// ══════════ Provider Status ══════════
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
  } catch { /* silent */ }
}

function renderProviderStatus(containerId, providers, labels) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const rows = Object.entries(providers).map(([key, info]) => {
    const online = info.online;
    let dot, color, label;
    if (online === true) {
      dot = '#10b981'; color = '#10b981'; label = 'Online';
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

// ══════════ Stats ══════════
async function loadStats() {
  try {
    const data = await api('/api/stats');
    document.getElementById('stat-total').textContent = data.total;
    document.getElementById('stat-draft').textContent = data.draft;
    document.getElementById('stat-approved').textContent = data.approved;
    document.getElementById('stat-posted').textContent = data.posted;
  } catch { /* silent */ }
}

// ══════════ Recent Content ══════════
async function loadRecentContent() {
  try {
    const data = await api('/api/stats');
    const el = document.getElementById('recent-content');
    if (!data.recent?.length) {
      el.innerHTML = `
        <div style="text-align:center;padding:40px 0;color:#cbd5e1;">
          <svg width="40" height="40" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="margin:0 auto 12px;display:block;opacity:0.35;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
          <p style="margin:0;font-size:0.875rem;font-weight:500;color:#94a3b8;">No posts yet — hit <strong style="color:#6366f1;">Generate Now</strong> to get started</p>
        </div>`;
      return;
    }
    el.innerHTML = data.recent.map(item => {
      const caption = safeCaption(item.caption);
      const preview = caption.substring(0, 90) + (caption.length > 90 ? '...' : '');
      return `
        <div onclick="openModal(${item.id})" style="display:flex;align-items:center;gap:14px;padding:12px 14px;border-radius:12px;cursor:pointer;transition:background 0.15s;" onmouseover="this.style.background='#f8fafc'" onmouseout="this.style.background='transparent'">
          <div style="width:38px;height:38px;border-radius:11px;flex-shrink:0;${platBg(item.platform)};display:flex;align-items:center;justify-content:center;">
            <span style="font-size:17px;">${platEmoji(item.platform)}</span>
          </div>
          <div style="flex:1;min-width:0;">
            <div style="font-weight:600;color:#0f172a;font-size:0.875rem;margin-bottom:2px;">${item.topic || 'Post'}</div>
            <div style="font-size:0.78rem;color:#94a3b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${preview}</div>
          </div>
          <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
            ${statusBadge(item.status)}
          </div>
        </div>`;
    }).join('');
  } catch { /* silent */ }
}

// ══════════ Suggestions ══════════
async function loadSuggestions() {
  try {
    suggestions = await api('/api/suggestions');
    const topicSel = document.getElementById('manual-topic');
    suggestions.topics.forEach(t => topicSel.appendChild(new Option(t.topic, t.id)));
    const ctSel = document.getElementById('manual-content-type');
    suggestions.content_types.forEach(ct => ctSel.appendChild(new Option(ct, ct)));
    const toneSel = document.getElementById('manual-tone');
    suggestions.tones.forEach(t => toneSel.appendChild(new Option(t, t)));
  } catch { /* silent */ }
}

// ══════════ Models ══════════
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

  // Show/hide AI Fiesta info banner
  const fiestaBanner = document.getElementById(`${prefix}-aifiesta-banner`);
  if (fiestaBanner) fiestaBanner.style.display = isAiFiesta ? '' : 'none';
}

// ══════════ Platform Card Toggle ══════════
function togglePlatCard(card, mode) {
  const checkbox = card.querySelector('input');
  const platform = card.dataset.platform;
  const selected = card.dataset.selected === '1';
  const indicator = card.querySelector('.plat-check-indicator');

  checkbox.checked = !selected;
  card.dataset.selected = selected ? '0' : '1';

  if (!selected) {
    // Now selected
    card.classList.add(`sel-${platform === 'instagram' ? 'ig' : platform === 'linkedin' ? 'li' : 'fb'}`);
    if (indicator) {
      const colors = { instagram: '#e1306c', linkedin: '#0a66c2', facebook: '#1877f2' };
      indicator.textContent = '✓ Selected';
      indicator.style.color = colors[platform];
      indicator.style.fontWeight = '600';
    }
  } else {
    // Now deselected
    card.classList.remove('sel-ig','sel-li','sel-fb');
    if (indicator) {
      indicator.textContent = '+ Select';
      indicator.style.color = '#94a3b8';
      indicator.style.fontWeight = '500';
    }
  }
}

// ══════════ Generate Mode Tabs ══════════
function setGenMode(mode) {
  document.getElementById('mode-quick').style.display = mode === 'quick' ? '' : 'none';
  document.getElementById('mode-manual').style.display = mode === 'manual' ? '' : 'none';
  document.getElementById('tab-quick').className = 'mode-tab' + (mode === 'quick' ? ' active' : '');
  document.getElementById('tab-manual').className = 'mode-tab' + (mode === 'manual' ? ' active' : '');
  document.getElementById('gen-results').style.display = 'none';
  document.getElementById('gen-loading').style.display = 'none';
}

// ══════════ Generate ══════════
async function quickGenerate() {
  showPage('generate');
  setTimeout(() => runGenerate('quick'), 150);
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

    // ── AI Fiesta mode: display the prompt for browser-based generation ──────
    if (data.aifiesta_mode) {
      showAiFiestaPrompt(data);
      return;
    }

    data.errors?.forEach(e => showToast(`${e.platform}: ${e.error}`, 'error'));
    if (data.generated?.length) {
      showToast(`✓ Generated ${data.generated.length} post${data.generated.length > 1 ? 's' : ''}`, 'success');
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
  card.style.cssText = 'background:#0f172a;border-radius:16px;padding:24px;color:#e2e8f0;';
  card.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
      <span style="font-size:1.4rem;">🎪</span>
      <div>
        <div style="font-weight:700;font-size:1rem;color:#fff;">AI Fiesta — Queued for Generation</div>
        <div style="font-size:0.78rem;color:#94a3b8;margin-top:2px;">
          Topic: <strong style="color:#a5b4fc;">${data.topic}</strong> &nbsp;·&nbsp;
          Type: <strong style="color:#a5b4fc;">${data.content_type}</strong> &nbsp;·&nbsp;
          Platform: <strong style="color:#a5b4fc;">${data.platform}</strong>
        </div>
      </div>
    </div>
    <div style="background:#1e293b;border-radius:10px;padding:14px;margin-bottom:16px;font-size:0.78rem;line-height:1.6;color:#94a3b8;max-height:160px;overflow-y:auto;white-space:pre-wrap;font-family:monospace;">${data.prompt}</div>
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
  showToast('🎪 AI Fiesta prompt ready — generating via browser...', 'success');
}

function showGeneratedResults(items, meta) {
  const results = document.getElementById('gen-results');
  const list = document.getElementById('gen-results-list');
  list.innerHTML = '';
  if (meta?.topic) {
    const info = document.createElement('div');
    info.style.cssText = 'background:#f0f4ff;border-radius:10px;padding:10px 14px;margin-bottom:4px;font-size:0.8rem;color:#4338ca;display:flex;align-items:center;gap:10px;flex-wrap:wrap;';
    info.innerHTML = `<span>🎯 <strong>Topic:</strong> ${meta.topic}</span><span style="color:#a5b4fc;">|</span><span><strong>Type:</strong> ${meta.content_type}</span><span style="color:#a5b4fc;">|</span><span><strong>Tone:</strong> ${meta.tone}</span>`;
    list.appendChild(info);
  }
  items.forEach(item => list.appendChild(buildContentCard(item, true)));
  results.style.display = '';
}

// ══════════ Library ══════════
async function loadLibrary() {
  const grid = document.getElementById('library-grid');
  grid.innerHTML = skeletonGrid(4);
  try {
    const params = new URLSearchParams(window.libraryFilter || {});
    const data = await api(`/api/content?${params}`);
    grid.innerHTML = '';
    if (!data.content?.length) {
      grid.innerHTML = `
        <div style="grid-column:1/-1;text-align:center;padding:64px 24px;color:#94a3b8;">
          <svg width="48" height="48" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="margin:0 auto 16px;display:block;opacity:0.3;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg>
          <p style="font-size:1rem;font-weight:700;color:#0f172a;margin:0 0 6px;">No content found</p>
          <p style="font-size:0.875rem;margin:0 0 18px;">Try a different filter, or generate new content.</p>
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

// ══════════ Content Card Builder ══════════
function buildContentCard(item, isNew) {
  const div = document.createElement('div');
  div.style.cssText = 'background:#fff;border-radius:18px;border:1px solid #eef0f4;overflow:hidden;transition:box-shadow 0.2s,transform 0.2s;cursor:pointer;display:flex;flex-direction:column;box-shadow:0 1px 4px rgba(0,0,0,0.05);';
  div.onmouseover = () => { div.style.boxShadow = '0 8px 28px rgba(0,0,0,0.1)'; div.style.transform = 'translateY(-2px)'; };
  div.onmouseout = () => { div.style.boxShadow = '0 1px 4px rgba(0,0,0,0.05)'; div.style.transform = ''; };
  div.onclick = () => openModal(item.id);

  const caption = safeCaption(item.caption);
  const preview = caption.substring(0, 160) + (caption.length > 160 ? '...' : '');
  const hashPreview = (item.hashtags || '').substring(0, 60) + ((item.hashtags || '').length > 60 ? '...' : '');
  const dateStr = new Date(item.created_at).toLocaleDateString('en-AU', { day:'numeric', month:'short' });

  const hasImage = !!item.image_path;
  div.innerHTML = `
    <!-- Color strip or image -->
    ${hasImage
      ? `<div style="height:140px;overflow:hidden;flex-shrink:0;position:relative;">
           <img src="${item.image_path}?t=${Date.now()}" style="width:100%;height:100%;object-fit:cover;" />
           <div style="position:absolute;top:8px;right:8px;background:rgba(0,0,0,0.5);color:#fff;font-size:0.65rem;font-weight:700;padding:2px 8px;border-radius:99px;">📸 AI</div>
         </div>`
      : `<div class="strip-${item.platform === 'instagram' ? 'ig' : item.platform === 'linkedin' ? 'li' : 'fb'}" style="height:5px;flex-shrink:0;"></div>`
    }
    <div style="padding:18px 20px;display:flex;flex-direction:column;flex:1;">
      <!-- Header -->
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
        <div style="display:flex;align-items:center;gap:9px;">
          <div class="plat-icon-${item.platform === 'instagram' ? 'ig' : item.platform === 'linkedin' ? 'li' : 'fb'}" style="width:30px;height:30px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:14px;">
            <span>${platEmoji(item.platform)}</span>
          </div>
          <div>
            <div style="font-size:0.8125rem;font-weight:700;color:#0f172a;">${platLabel(item.platform)}</div>
            <div style="font-size:0.7rem;color:#94a3b8;font-weight:500;">${item.content_type || ''}</div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:6px;">
          ${isNew ? '<span style="font-size:0.7rem;font-weight:700;background:#eef2ff;color:#4f46e5;padding:2px 8px;border-radius:99px;border:1px solid #c7d2fe;">NEW</span>' : ''}
          ${statusBadge(item.status)}
        </div>
      </div>
      <!-- Topic -->
      <h3 style="font-size:0.9375rem;font-weight:700;color:#0f172a;margin:0 0 8px;line-height:1.3;">${item.topic || 'Post'}</h3>
      <!-- Caption preview -->
      <p style="font-size:0.8125rem;color:#64748b;line-height:1.6;margin:0 0 10px;flex:1;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">${preview}</p>
      <!-- Hashtags -->
      ${hashPreview ? `<p style="font-size:0.75rem;color:#a5b4fc;margin:0 0 14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${hashPreview}</p>` : ''}
      <!-- Footer -->
      <div style="display:flex;align-items:center;justify-content:space-between;padding-top:12px;border-top:1px solid #f8fafc;margin-top:auto;">
        <span style="font-size:0.75rem;color:#cbd5e1;font-weight:500;">${dateStr}</span>
        <div style="display:flex;gap:4px;" onclick="event.stopPropagation()">
          <button class="btn-ghost" onclick="quickCopyCard(${item.id},event)" style="font-size:0.75rem;">📋 Copy</button>
          <button class="btn-ghost" onclick="openModal(${item.id})" style="font-size:0.75rem;color:#6366f1;font-weight:600;">View →</button>
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
    showToast('✓ Post copied to clipboard', 'success');
  } catch { showToast('Could not copy', 'error'); }
}

// ══════════ Modal ══════════
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
    document.getElementById('modal-caption-text').value = caption;
    document.getElementById('modal-hashtags-text').value = item.hashtags || '';
    document.getElementById('modal-image-suggestion').textContent = item.image_suggestion || 'No image suggestion available.';
    updateFullPreview();

    // Reset image generation state
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

    const approveBtn = document.getElementById('modal-approve-btn');
    approveBtn.innerHTML = item.status === 'approved' ? '<svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg> Approved' : '<svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg> Approve';
    approveBtn.disabled = item.status === 'approved';
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
}

function updateFullPreview() {
  const caption = document.getElementById('modal-caption-text').value;
  const hashtags = document.getElementById('modal-hashtags-text').value;
  document.getElementById('modal-full-preview').textContent = `${caption}\n\n${hashtags}`;
}

async function saveModal() {
  if (!modalItemId) return;
  try {
    await api(`/api/content/${modalItemId}`, 'PUT', {
      caption: document.getElementById('modal-caption-text').value,
      hashtags: document.getElementById('modal-hashtags-text').value,
    });
    showToast('✓ Saved', 'success');
    modalDirty = false;
    document.getElementById('modal-save-btn').style.display = 'none';
    if (currentPage === 'library') loadLibrary();
    loadRecentContent();
  } catch (err) { showToast(err.message, 'error'); }
}

async function approveItem() {
  if (!modalItemId) return;
  try {
    await api(`/api/content/${modalItemId}`, 'PUT', { status: 'approved' });
    showToast('✓ Approved', 'success');
    const btn = document.getElementById('modal-approve-btn');
    btn.innerHTML = '<svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg> Approved';
    btn.disabled = true;
    loadStats();
    if (currentPage === 'library') loadLibrary();
  } catch (err) { showToast(err.message, 'error'); }
}

async function markPosted() {
  if (!modalItemId) return;
  try {
    await api(`/api/content/${modalItemId}`, 'PUT', { status: 'posted' });
    showToast('✓ Marked as posted', 'success');
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

// ══════════ Copy helpers ══════════
async function copyField(fieldId) {
  const val = document.getElementById(fieldId).value;
  await navigator.clipboard.writeText(val);
  showToast('✓ Copied', 'success');
}

async function copyFullPost() {
  const caption = document.getElementById('modal-caption-text').value;
  const hashtags = document.getElementById('modal-hashtags-text').value;
  await navigator.clipboard.writeText(`${caption}\n\n${hashtags}`);
  showToast('✓ Full post copied to clipboard', 'success');
}

// ══════════ Settings ══════════
async function loadSettings() {
  try {
    const data = await api('/api/settings');
    const map = { ollama_url:'s-ollama-url', default_model:'s-default-model', default_ollama_model:'s-default-ollama-model' };
    Object.entries(map).forEach(([k,id]) => { const el = document.getElementById(id); if (el && data[k]) el.value = data[k]; });
    // Load image provider default
    const imgProv = document.getElementById('s-default-image-provider');
    if (imgProv && data.default_image_provider) imgProv.value = data.default_image_provider;
    const sensitive = ['groq_api_key','gemini_api_key','deepseek_api_key','qwen_api_key','gemini_paid_api_key','stability_api_key','openai_api_key','linkedin_client_id','linkedin_client_secret','linkedin_access_token','facebook_page_id','facebook_access_token'];
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
    gemini_paid_api_key: document.getElementById('s-gemini-paid-api-key')?.value,
    stability_api_key: document.getElementById('s-stability-api-key')?.value,
    openai_api_key: document.getElementById('s-openai-api-key')?.value,
    default_image_provider: document.getElementById('s-default-image-provider')?.value,
    linkedin_client_id: document.getElementById('s-linkedin-client-id')?.value,
    linkedin_client_secret: document.getElementById('s-linkedin-client-secret')?.value,
    linkedin_access_token: document.getElementById('s-linkedin-access-token')?.value,
    facebook_page_id: document.getElementById('s-facebook-page-id')?.value,
    facebook_access_token: document.getElementById('s-facebook-access-token')?.value,
  };
  try {
    await api('/api/settings', 'POST', { settings });
    showToast('✓ Settings saved', 'success');
    loadHealth(); loadModels();
  } catch (err) { showToast(err.message, 'error'); }
}

// ══════════ Loading states ══════════
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
    <div style="background:#fff;border-radius:18px;border:1px solid #eef0f4;overflow:hidden;">
      <div style="height:5px;background:#f1f5f9;"></div>
      <div style="padding:18px 20px;">
        <div class="skel" style="height:12px;width:80px;margin-bottom:14px;"></div>
        <div class="skel" style="height:16px;width:60%;margin-bottom:10px;"></div>
        <div class="skel" style="height:11px;width:100%;margin-bottom:7px;"></div>
        <div class="skel" style="height:11px;width:90%;margin-bottom:7px;"></div>
        <div class="skel" style="height:11px;width:70%;margin-bottom:14px;"></div>
        <div style="display:flex;justify-content:space-between;padding-top:12px;border-top:1px solid #f8fafc;">
          <div class="skel" style="height:11px;width:50px;"></div>
          <div class="skel" style="height:11px;width:80px;"></div>
        </div>
      </div>
    </div>`).join('');
}

// ══════════ Toast ══════════
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  const colors = { success: '#059669', error: '#dc2626', info: '#4f46e5' };
  const icons = { success: '✓', error: '✕', info: 'ℹ' };
  const toast = document.createElement('div');
  toast.style.cssText = `background:#fff;border:1.5px solid ${colors[type]}22;border-left:4px solid ${colors[type]};border-radius:12px;padding:12px 16px;font-size:0.875rem;font-weight:600;color:#1e293b;box-shadow:0 4px 20px rgba(0,0,0,0.12);display:flex;align-items:center;gap:9px;pointer-events:all;min-width:240px;max-width:360px;`;
  toast.innerHTML = `<span style="color:${colors[type]};font-size:1rem;">${icons[type]}</span>${message}`;
  toast.classList.add('t-in');
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.remove('t-in');
    toast.classList.add('t-out');
    setTimeout(() => toast.remove(), 280);
  }, 3500);
}

// ══════════ Helpers ══════════
function safeCaption(caption) {
  if (!caption) return '';
  // Handle raw JSON stored as caption (valid or truncated/malformed)
  if (caption.trim().startsWith('{')) {
    // Try valid JSON parse first
    try {
      const parsed = JSON.parse(caption);
      if (parsed && parsed.caption) return parsed.caption;
    } catch { /* malformed JSON — try regex extraction below */ }
    // Fallback: extract "caption" field via regex even from malformed/truncated JSON
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
    instagram: 'background:linear-gradient(135deg,#fdf2f8,#fff7ed);color:#be185d;border:1px solid #f9a8d4;',
    linkedin: 'background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;',
    facebook: 'background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;',
  };
  return s[p] || 'background:#eef2ff;color:#4338ca;border:1px solid #c7d2fe;';
}

function statusBadge(status) {
  const conf = {
    draft: { bg:'#fef9ec', color:'#92400e', border:'#fde68a', label:'Draft' },
    approved: { bg:'#eef2ff', color:'#3730a3', border:'#c7d2fe', label:'Approved' },
    posted: { bg:'#ecfdf5', color:'#065f46', border:'#a7f3d0', label:'Posted' },
  };
  const c = conf[status] || conf.draft;
  return `<span style="display:inline-flex;align-items:center;padding:2px 9px;border-radius:99px;font-size:0.72rem;font-weight:700;background:${c.bg};color:${c.color};border:1px solid ${c.border};">${c.label}</span>`;
}

// ══════════ Image Generation ══════════

function updateImageModelInfo() {
  const provider = document.getElementById('modal-image-provider')?.value;
  const info = document.getElementById('modal-image-model-info');
  if (!info) return;
  const providerInfo = {
    imagen4:            { text: 'Uses your Gemini API key — up to 4 images per generation', color: '#10b981' },
    imagen4_fast:       { text: 'Uses your Gemini API key — up to 4 images, faster', color: '#10b981' },
    gemini_native:      { text: 'Uses your Gemini API key — 1 context-aware image (free)', color: '#10b981' },
    gemini_native_paid: { text: 'Uses Nano Banana 2 paid key — 1 high-quality image', color: '#f59e0b' },
    stability:          { text: 'Uses Stability AI key — up to 4 images', color: '#6366f1' },
    dalle:              { text: 'Uses OpenAI key — 1 image per generation', color: '#6366f1' },
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
    card.onmouseover = () => { if (selectedImageIdx !== idx) card.style.borderColor = '#c7d2fe'; };
    card.onmouseout = () => { if (selectedImageIdx !== idx) card.style.borderColor = 'transparent'; };
    card.onclick = () => selectImage(idx);

    const imgEl = document.createElement('img');
    imgEl.src = `data:${img.mime_type};base64,${img.base64}`;
    imgEl.style.cssText = 'width:100%;display:block;aspect-ratio:1;object-fit:cover;';
    card.appendChild(imgEl);

    // Selection overlay
    const overlay = document.createElement('div');
    overlay.className = 'img-select-overlay';
    overlay.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(99,102,241,0.0);transition:background 0.2s;';
    card.appendChild(overlay);

    grid.appendChild(card);
  });

  // Adjust grid for single image
  if (generatedImages.length === 1) {
    grid.style.gridTemplateColumns = '1fr';
  } else {
    grid.style.gridTemplateColumns = 'repeat(2,1fr)';
  }

  results.style.display = '';
}

function selectImage(idx) {
  selectedImageIdx = idx;

  // Update visual selection
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

  // Auto-save the selected image
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

    // Show saved image preview
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

// ══════════ Logout ══════════
async function logoutUser() {
  try { await api('/api/logout', 'POST'); } catch { /* ignore */ }
  window.location.href = '/login';
}

// ══════════ API ══════════
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
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}
