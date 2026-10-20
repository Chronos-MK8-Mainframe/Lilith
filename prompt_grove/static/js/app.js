(() => {
  'use strict';

  const state = {
    prompts: [],
    tree: null,
    selectedCategory: 'all',
    selectedCategoryName: 'All prompts',
    mode: 'library',
    query: '',
    sort: 'updated',
    activePromptId: null,
    imagePath: '',
  };

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const api = async (url, options = {}) => {
    const response = await fetch(url, options);
    const type = response.headers.get('content-type') || '';
    const data = type.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) throw new Error((data && data.error) || `Request failed (${response.status})`);
    return data;
  };
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const shortDate = (dateStr) => {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    if (Number.isNaN(date.getTime())) return '';
    const now = new Date();
    const days = Math.floor((new Date(now.toDateString()) - new Date(date.toDateString())) / 86400000);
    if (days <= 0) return 'TODAY';
    if (days === 1) return 'YESTERDAY';
    if (days < 8) return `${days}D AGO`;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }).toUpperCase();
  };
  const imageIsUsable = (path) => /^(https?:\/\/|\/|data:image\/)/i.test(String(path || ''));
  const imageHtml = (path, alt) => imageIsUsable(path)
    ? `<img src="${esc(path)}" alt="${esc(alt || 'Prompt reference')}" loading="lazy" onerror="this.onerror=null;this.parentElement.classList.add('placeholder');this.remove();this.parentElement.insertAdjacentHTML('beforeend','<div class=\'placeholder-art\'><span class=\'placeholder-symbol\'>✳</span><small>IMAGE UNAVAILABLE</small></div>')">`
    : `<div class="placeholder-art"><span class="placeholder-symbol">✳</span><small>${path ? 'LINK NEEDS A WEB PATH' : 'REFERENCE IMAGE'}</small></div>`;

  function toast(message, isError = false) {
    const el = document.createElement('div');
    el.className = `toast${isError ? ' error' : ''}`;
    el.innerHTML = `<span class="toast-mark">${isError ? '!' : '✓'}</span><span>${esc(message)}</span>`;
    $('#toast-region').appendChild(el);
    window.setTimeout(() => el.remove(), 3400);
  }

  function openModal(id) {
    const modal = document.getElementById(id);
    modal.hidden = false;
    document.body.style.overflow = 'hidden';
    const focusable = modal.querySelector('input:not([type=hidden]), textarea, button');
    if (focusable) window.setTimeout(() => focusable.focus(), 30);
  }
  function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.hidden = true;
    if ($$('.modal-backdrop').every((el) => el.hidden)) document.body.style.overflow = '';
  }
  function resetEditor() {
    $('#prompt-form').reset();
    $('#prompt-id').value = '';
    $('#prompt-title').value = '';
    $('#prompt-category').value = state.selectedCategory !== 'all' && state.selectedCategory !== 'uncategorized' ? state.selectedCategory : '';
    $('#prompt-text').value = '';
    $('#prompt-image').value = '';
    $('#prompt-notes').value = '';
    $('#prompt-tags').value = '';
    $('#prompt-char-count').textContent = '0 chars';
    $('#editor-title').textContent = 'Plant a new prompt';
    $('#save-prompt').innerHTML = '<span>✓</span> Save prompt';
    $('#delete-prompt').hidden = true;
    $('#editor-error').hidden = true;
    $('#upload-status').textContent = 'PNG, JPG, WEBP · 12 MB max';
    state.imagePath = '';
    renderEditorImage('');
  }
  function renderEditorImage(path) {
    state.imagePath = path || '';
    const target = $('#editor-image-preview');
    target.innerHTML = imageIsUsable(path)
      ? `<img src="${esc(path)}" alt="Reference preview" onerror="this.onerror=null;this.parentElement.innerHTML='<div class=\'preview-placeholder\'><span>▧</span><small>IMAGE NOT FOUND</small></div>'">`
      : '<div class="preview-placeholder"><span>▧</span><small>IMAGE PREVIEW</small></div>';
  }
  function openCreate(category = '') {
    resetEditor();
    if (category) $('#prompt-category').value = category;
    openModal('prompt-modal');
  }
  function openEdit(id) {
    const p = state.prompts.find((item) => Number(item.id) === Number(id));
    if (!p) return;
    resetEditor();
    state.activePromptId = p.id;
    $('#prompt-id').value = p.id;
    $('#prompt-title').value = p.title || '';
    $('#prompt-category').value = p.category_path || '';
    $('#prompt-text').value = p.prompt_text || '';
    $('#prompt-image').value = p.image_preview || '';
    $('#prompt-notes').value = p.notes || '';
    $('#prompt-tags').value = p.tags || '';
    $('#prompt-char-count').textContent = `${(p.prompt_text || '').length} chars`;
    $('#editor-title').textContent = 'Tend to this prompt';
    $('#save-prompt').innerHTML = '<span>✓</span> Save changes';
    $('#delete-prompt').hidden = false;
    renderEditorImage(p.image_preview || '');
    openModal('prompt-modal');
  }

  function getVisiblePrompts() {
    let items = state.prompts.slice();
    if (state.selectedCategory === 'uncategorized') items = items.filter((p) => !p.category_path);
    else if (state.selectedCategory !== 'all') {
      const path = state.selectedCategory;
      items = items.filter((p) => p.category_path === path || p.category_path.startsWith(path + '/'));
    }
    const q = state.query.trim().toLowerCase();
    if (q) items = items.filter((p) => [p.title, p.prompt_text, p.category_path, p.notes, p.tags].join(' ').toLowerCase().includes(q));
    if (state.sort === 'title') items.sort((a, b) => a.title.localeCompare(b.title));
    else if (state.sort === 'category') items.sort((a, b) => a.category_path.localeCompare(b.category_path) || a.title.localeCompare(b.title));
    else if (state.sort === 'created') items.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    else items.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
    return items;
  }

  function renderCards() {
    const items = getVisiblePrompts();
    const grid = $('#prompt-grid');
    grid.innerHTML = '';
    $('#visible-count').textContent = `${items.length} ${items.length === 1 ? 'item' : 'items'}`;
    $('#collection-title').textContent = state.selectedCategoryName;
    $('#breadcrumb-current').textContent = state.selectedCategoryName;
    $('#all-count').textContent = state.prompts.length;
    $('#uncat-count').textContent = state.prompts.filter((p) => !p.category_path).length;
    $('#footer-count').textContent = `${state.prompts.length} ${state.prompts.length === 1 ? 'prompt' : 'prompts'} saved`;
    $('#page-title').innerHTML = state.selectedCategory === 'all'
      ? 'Every good idea<br><em>starts somewhere.</em>'
      : `${esc(state.selectedCategoryName.split('/').pop())}<br><em>ideas, growing.</em>`;
    $('#empty-state').hidden = items.length !== 0 || state.query.length > 0;
    $('#filter-empty').hidden = items.length !== 0 || !state.query.length;
    if (!items.length) return;

    items.forEach((p) => {
      const category = p.category_path ? p.category_path.replaceAll('/', ' / ') : 'UNCATEGORIZED';
      const tags = (p.tags_list || []).slice(0, 3).map((tag) => `<span class="tag">${esc(tag)}</span>`).join('');
      const imageClass = imageIsUsable(p.image_preview) ? 'card-image' : 'card-image placeholder';
      const card = document.createElement('article');
      card.className = 'prompt-card';
      card.innerHTML = `
        <div class="${imageClass}">${imageHtml(p.image_preview, p.title)}<div class="card-image-overlay"><span class="type-chip">PROMPT #${String(p.id).padStart(3, '0')}</span></div><span class="image-view-hint">OPEN DETAILS ↗</span></div>
        <div class="card-body">
          <div class="card-kicker-row"><span class="card-category" title="${esc(category)}">${esc(category)}</span><span class="card-date">${esc(shortDate(p.updated_at))}</span></div>
          <h3 class="card-title" title="${esc(p.title)}">${esc(p.title || 'Untitled prompt')}</h3>
          <p class="prompt-snippet">${esc(p.prompt_text)}</p>
          <div class="card-tags">${tags}</div>
          <div class="card-footer"><span class="card-meta">${p.image_preview ? '▧ WITH REFERENCE' : '✳ TEXT PROMPT'}</span><div class="card-actions"><button class="card-action edit-action" type="button" data-id="${p.id}">Edit ↗</button><button class="card-action copy-action" type="button" data-copy-id="${p.id}">⧉ Copy</button></div></div>
        </div>`;
      card.addEventListener('click', (event) => {
        if (event.target.closest('button')) return;
        openEdit(p.id);
      });
      grid.appendChild(card);
    });
    $$('.edit-action').forEach((button) => button.addEventListener('click', () => openEdit(button.dataset.id)));
    $$('.copy-action').forEach((button) => button.addEventListener('click', () => copyPrompt(button.dataset.copyId)));
  }

  async function copyPrompt(id) {
    const p = state.prompts.find((item) => Number(item.id) === Number(id));
    if (!p) return;
    try {
      await navigator.clipboard.writeText(p.prompt_text);
      toast('Prompt copied to clipboard.');
    } catch (_err) {
      const area = document.createElement('textarea');
      area.value = p.prompt_text;
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand('copy');
      area.remove();
      toast(ok ? 'Prompt copied to clipboard.' : 'Could not copy automatically. Open Edit to copy the text.', !ok);
    }
  }

  function flattenCategoryTree(tree) {
    const result = [];
    const visit = (node, parentPath = '', depth = 0) => {
      (node.children || []).forEach((child) => {
        if (child.type === 'prompt') return;
        const path = parentPath ? `${parentPath}/${child.name}` : child.name;
        result.push({ ...child, path, depth });
        visit(child, path, depth + 1);
      });
    };
    if (tree) visit(tree);
    return result;
  }

  function renderCategoryTree() {
    const root = state.tree;
    const host = $('#category-tree');
    if (!root) return;
    const promptCount = state.prompts.length;
    $('#all-count').textContent = promptCount;
    $('#uncat-count').textContent = state.prompts.filter((p) => !p.category_path).length;
    $('#all-prompts').classList.toggle('active', state.selectedCategory === 'all');
    $('#uncategorized-link').classList.toggle('active', state.selectedCategory === 'uncategorized');
    host.innerHTML = '';
    const categoryNodes = flattenCategoryTree(root);
    if (!categoryNodes.length) {
      host.innerHTML = '<div class="tree-loading">No branches yet. Add a categorized prompt to start.</div>';
      return;
    }
    const addNode = (node, parentEl, parentPath = '') => {
      if (node.type === 'prompt') return;
      const path = node.type === 'category' ? (parentPath ? `${parentPath}/${node.name}` : node.name) : '';
      const childCategories = (node.children || []).filter((child) => child.type === 'category');
      const row = document.createElement('button');
      row.type = 'button';
      row.className = `category-row${state.selectedCategory === path ? ' selected' : ''}`;
      row.style.paddingLeft = `${8 + (node.depth || 0) * 5}px`;
      row.innerHTML = `<span class="category-caret">${childCategories.length ? '⌄' : '·'}</span><span class="category-folder">${childCategories.length ? '▱' : '▰'}</span><span class="category-label" title="${esc(path)}">${esc(node.name)}</span><span class="category-count">${node.count || 0}</span>`;
      row.addEventListener('click', () => selectCategory(path, node.name));
      parentEl.appendChild(row);
      if (childCategories.length) {
        const wrap = document.createElement('div');
        wrap.className = 'category-children';
        parentEl.appendChild(wrap);
        childCategories.forEach((child) => addNode(child, wrap, path));
      }
    };
    (root.children || []).filter((child) => child.type === 'category' && child.id !== 'uncategorized').forEach((node) => addNode(node, host));
    if ((root.children || []).some((child) => child.id === 'uncategorized')) {
      const uncat = document.createElement('div');
      uncat.className = 'uncat-tree-label';
      uncat.style.display = 'none';
    }
  }

  function selectCategory(path, name) {
    state.selectedCategory = path || 'all';
    state.selectedCategoryName = path ? (path === 'uncategorized' ? 'Uncategorized' : path.replaceAll('/', ' / ')) : 'All prompts';
    if (state.mode !== 'library') setMode('library');
    if (path === 'uncategorized') state.selectedCategoryName = 'Uncategorized';
    renderCategoryTree();
    renderCards();
  }

  function setMode(mode) {
    state.mode = mode;
    $('#library-view').hidden = mode !== 'library';
    $('#graph-view').hidden = mode !== 'graph';
    $('#library-tab').classList.toggle('active', mode === 'library');
    $('#graph-tab').classList.toggle('active', mode === 'graph');
    $('#library-tab').setAttribute('aria-selected', mode === 'library' ? 'true' : 'false');
    $('#graph-tab').setAttribute('aria-selected', mode === 'graph' ? 'true' : 'false');
    if (mode === 'graph') renderGraph();
  }

  async function loadData() {
    const [prompts, tree] = await Promise.all([api('/api/prompts'), api('/api/tree')]);
    state.prompts = prompts;
    state.tree = tree;
    renderCategoryTree();
    renderCards();
    if (state.mode === 'graph') renderGraph();
  }

  function svgElement(tag, attrs = {}, textContent = '') {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, String(value)));
    if (textContent) element.textContent = textContent;
    return element;
  }

  function renderGraph() {
    const host = $('#graph-canvas');
    const root = state.tree;
    if (!root) return;
    const cursor = { x: 82 };
    const flatNodes = [];
    const layout = (node, depth = 0, parent = null) => {
      const current = { ...node, depth, parent, children: [] };
      current.children = (node.children || []).map((child) => layout(child, depth + 1, current));
      if (!current.children.length) {
        current.x = cursor.x;
        cursor.x += node.type === 'prompt' ? 190 : 180;
      } else {
        current.x = current.children.reduce((sum, child) => sum + child.x, 0) / current.children.length;
      }
      current.y = 66 + depth * 126;
      flatNodes.push(current);
      return current;
    };
    const layoutRoot = layout(root);
    const maxDepth = flatNodes.reduce((max, node) => Math.max(max, node.depth), 0);
    const width = Math.max(850, cursor.x + 55);
    const height = Math.max(470, 130 + maxDepth * 126);
    $('#graph-node-count').textContent = `${flatNodes.length} nodes`;
    host.innerHTML = '';
    if (!state.prompts.length) {
      host.innerHTML = '<div class="graph-placeholder"><span>✳</span><span>Your tree is waiting for its first prompt. Add one or import JSON to grow a branch.</span></div>';
      return;
    }
    const svg = svgElement('svg', { width, height, viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Prompt category tree graph' });
    const edges = svgElement('g', { class: 'graph-edges' });
    const nodeGroup = svgElement('g', { class: 'graph-nodes' });
    flatNodes.forEach((node) => {
      if (!node.parent) return;
      const fromY = node.parent.y + 26;
      const toY = node.y - 26;
      const midY = (fromY + toY) / 2;
      const path = svgElement('path', {
        d: `M ${node.parent.x} ${fromY} C ${node.parent.x} ${midY}, ${node.x} ${midY}, ${node.x} ${toY}`,
        class: `graph-edge${node.type === 'prompt' ? ' edge-prompt' : ''}`,
      });
      edges.appendChild(path);
    });
    flatNodes.forEach((node) => {
      const group = svgElement('g', {
        class: `graph-node node-${node.type}`,
        transform: `translate(${node.x}, ${node.y})`,
        tabindex: node.type === 'prompt' || node.type === 'category' ? '0' : '-1',
        role: node.type === 'prompt' ? 'button' : 'group',
        'aria-label': `${node.type}: ${node.name}`,
      });
      const isPrompt = node.type === 'prompt';
      const isRoot = node.type === 'root';
      const nodeWidth = isRoot ? 150 : isPrompt ? 168 : Math.min(165, Math.max(118, node.name.length * 7 + 32));
      const nodeHeight = isPrompt ? 64 : 48;
      group.appendChild(svgElement('rect', { x: -nodeWidth / 2, y: -nodeHeight / 2, width: nodeWidth, height: nodeHeight, rx: isPrompt ? 8 : 11, ry: isPrompt ? 8 : 11 }));
      const mainLabel = node.name.length > (isPrompt ? 24 : 20) ? node.name.slice(0, isPrompt ? 22 : 18) + '…' : node.name;
      group.appendChild(svgElement('text', { x: 0, y: isPrompt ? -6 : 4, 'text-anchor': 'middle', 'font-family': 'Manrope, sans-serif', 'font-size': isRoot ? 12 : 10, 'font-weight': 800 }, mainLabel));
      if (isPrompt) {
        group.appendChild(svgElement('text', { x: 0, y: 13, 'text-anchor': 'middle', class: 'node-subtitle' }, `PROMPT #${String(node.prompt_id).padStart(3, '0')}`));
      } else if (!isRoot) {
        group.appendChild(svgElement('text', { x: 0, y: 17, 'text-anchor': 'middle', class: 'node-subtitle' }, `${node.count || 0} ${(node.count || 0) === 1 ? 'PROMPT' : 'PROMPTS'}`));
      }
      if (node.type === 'prompt') {
        const activate = () => openEdit(node.prompt_id);
        group.addEventListener('click', activate);
        group.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); } });
      } else if (node.type === 'category') {
        group.addEventListener('click', () => {
          const path = getNodeCategoryPath(node, state.tree);
          selectCategory(path, node.name);
        });
      }
      nodeGroup.appendChild(group);
    });
    svg.append(edges, nodeGroup);
    host.appendChild(svg);
  }

  function getNodeCategoryPath(target, root) {
    if (target.id === 'uncategorized') return 'uncategorized';
    let found = '';
    const walk = (node, path = '') => {
      if (node.type === 'prompt') return;
      const next = node.type === 'category' ? (path ? `${path}/${node.name}` : node.name) : '';
      if (node.type === 'category' && String(node.id) === String(target.id)) found = next;
      (node.children || []).forEach((child) => walk(child, next));
    };
    walk(root);
    return found;
  }

  async function submitPrompt(event) {
    event.preventDefault();
    $('#editor-error').hidden = true;
    const payload = {
      title: $('#prompt-title').value.trim(),
      Category: $('#prompt-category').value.trim(),
      Prompt: $('#prompt-text').value.trim(),
      image_preview: $('#prompt-image').value.trim() || state.imagePath,
      notes: $('#prompt-notes').value.trim(),
      tags: $('#prompt-tags').value.trim(),
    };
    if (!payload.Prompt) {
      $('#editor-error').textContent = 'Prompt text is required.';
      $('#editor-error').hidden = false;
      return;
    }
    const id = $('#prompt-id').value;
    const button = $('#save-prompt');
    button.disabled = true;
    button.textContent = 'Saving…';
    try {
      await api(id ? `/api/prompts/${id}` : '/api/prompts', {
        method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      closeModal('prompt-modal');
      await loadData();
      toast(id ? 'Prompt updated.' : 'Prompt saved to your grove.');
    } catch (error) {
      $('#editor-error').textContent = error.message;
      $('#editor-error').hidden = false;
    } finally {
      button.disabled = false;
      button.innerHTML = id ? '<span>✓</span> Save changes' : '<span>✓</span> Save prompt';
    }
  }

  async function deleteActivePrompt() {
    const id = $('#prompt-id').value;
    if (!id) return;
    if (!window.confirm('Delete this prompt? This action cannot be undone.')) return;
    try {
      await api(`/api/prompts/${id}`, { method: 'DELETE' });
      closeModal('prompt-modal');
      await loadData();
      toast('Prompt deleted.');
    } catch (error) { toast(error.message, true); }
  }

  async function uploadImage(file) {
    if (!file) return;
    $('#upload-status').textContent = 'Uploading image…';
    const formData = new FormData();
    formData.append('image', file);
    try {
      const result = await api('/api/upload-image', { method: 'POST', body: formData });
      $('#prompt-image').value = result.path;
      renderEditorImage(result.path);
      $('#upload-status').textContent = 'Image uploaded ✓';
      toast('Reference image uploaded.');
    } catch (error) {
      $('#upload-status').textContent = 'Upload failed';
      toast(error.message, true);
    } finally { $('#image-file').value = ''; }
  }

  async function importJson() {
    $('#import-error').hidden = true;
    const source = $('#json-input').value.trim();
    if (!source) {
      $('#import-error').textContent = 'Paste JSON or choose a JSON file first.';
      $('#import-error').hidden = false;
      return;
    }
    const button = $('#run-import');
    button.disabled = true;
    button.textContent = 'Importing…';
    try {
      const result = await api('/api/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ json: source }) });
      closeModal('import-modal');
      $('#json-input').value = '';
      $('#json-file-name').textContent = 'or paste JSON below';
      await loadData();
      toast(result.message || 'Import complete.');
    } catch (error) {
      $('#import-error').textContent = error.message;
      $('#import-error').hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = 'Import prompts ↥';
    }
  }

  function setupEvents() {
    $('#new-prompt-top').addEventListener('click', () => openCreate());
    $('#empty-new').addEventListener('click', () => openCreate());
    $('#add-category-prompt').addEventListener('click', () => openCreate());
    $('#empty-import').addEventListener('click', () => openModal('import-modal'));
    $('#import-trigger').addEventListener('click', () => openModal('import-modal'));
    $('#all-prompts').addEventListener('click', () => selectCategory('', 'All prompts'));
    $('#uncategorized-link').addEventListener('click', () => selectCategory('uncategorized', 'Uncategorized'));
    $('#library-tab').addEventListener('click', () => setMode('library'));
    $('#graph-tab').addEventListener('click', () => setMode('graph'));
    $('#graph-refresh').addEventListener('click', async () => { await loadData(); toast('Tree graph rebuilt.'); });
    $('#refresh-button').addEventListener('click', async () => { await loadData(); toast('Library refreshed.'); });
    $('#search-input').addEventListener('input', (event) => { state.query = event.target.value; renderCards(); });
    $('#sort-select').addEventListener('change', (event) => { state.sort = event.target.value; renderCards(); });
    $('#prompt-form').addEventListener('submit', submitPrompt);
    $('#delete-prompt').addEventListener('click', deleteActivePrompt);
    $('#prompt-text').addEventListener('input', (event) => { $('#prompt-char-count').textContent = `${event.target.value.length} chars`; });
    $('#prompt-image').addEventListener('input', (event) => renderEditorImage(event.target.value.trim()));
    $('#image-file').addEventListener('change', (event) => uploadImage(event.target.files[0]));
    $('#json-file').addEventListener('change', async (event) => {
      const file = event.target.files[0];
      if (!file) return;
      $('#json-file-name').textContent = file.name;
      try { $('#json-input').value = await file.text(); }
      catch (_error) { toast('Could not read that file.', true); }
      event.target.value = '';
    });
    $('#run-import').addEventListener('click', importJson);
    $$('[data-close]').forEach((button) => button.addEventListener('click', () => closeModal(button.dataset.close)));
    $$('.modal-backdrop').forEach((backdrop) => backdrop.addEventListener('click', (event) => { if (event.target === backdrop) closeModal(backdrop.id); }));
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') $$('.modal-backdrop').forEach((modal) => closeModal(modal.id));
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); $('#search-input').focus(); }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') { event.preventDefault(); openCreate(); }
    });
  }

  async function boot() {
    setupEvents();
    try { await loadData(); }
    catch (error) {
      $('#prompt-grid').innerHTML = `<div class="form-error">Could not connect to the local app: ${esc(error.message)}. Reload the page after starting the Python server.</div>`;
      toast('Could not load the prompt library.', true);
    }
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
