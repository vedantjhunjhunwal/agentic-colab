/* notebook.js — Agentic Colab editor */
(function () {
'use strict';

/* ============================================================
   DATA
   ============================================================ */
const NB = window.__NB__;
const NB_ID = NB.id;
let notebookName = NB.name;
let cells = (NB.content && NB.content.cells) || [];

let activeCellId = null;
let saveTimer = null;
let saving = false;
let assistProvider = '';
let assistApiKey = '';
let assistModel = '';
let lastError = null;   // {language, code, error} for active cell
let manualCache = null;

/* ============================================================
   UTILITIES
   ============================================================ */
function $(s, root) { return (root || document).querySelector(s); }
function $$(s, root) { return Array.from((root || document).querySelectorAll(s)); }
function uid() { return 'c_' + Math.random().toString(36).slice(2, 10); }
function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function toast(msg, dur) {
  const wrap = $('#toasts');
  const el = document.createElement('div');
  el.className = 'toast'; el.textContent = msg;
  wrap.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 300); }, dur || 3000);
}

async function api(method, url, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg;
    try { msg = (await r.json()).error; } catch (_) { msg = r.statusText; }
    throw new Error(msg || r.statusText);
  }
  return r.json();
}

function fmtBytes(b) {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b/1024).toFixed(1) + ' KB';
  return (b/1048576).toFixed(1) + ' MB';
}

function fmtElapsed(ms) {
  if (ms < 1) return '<1 ms';
  if (ms < 1000) return ms + ' ms';
  return (ms/1000).toFixed(2) + ' s';
}

/* ============================================================
   CELL DATA
   ============================================================ */
function findCell(id) { return cells.find(c => c.id === id); }

function getActiveCell() { return activeCellId ? findCell(activeCellId) : null; }

function activeCellIdx() { return cells.findIndex(c => c.id === activeCellId); }

function insertCellAfter(type, language, source) {
  const idx = activeCellIdx();
  const cell = { id: uid(), type: type || 'code', language: language || 'python', source: source || '', outputs: [] };
  if (idx < 0) cells.push(cell);
  else cells.splice(idx + 1, 0, cell);
  renderAll();
  focusCell(cell.id);
  scheduleSave();
  return cell;
}

function deleteCell(id) {
  const idx = cells.findIndex(c => c.id === id);
  if (idx < 0 || cells.length === 1) { toast('Cannot delete the last cell.'); return; }
  cells.splice(idx, 1);
  renderAll();
  const next = cells[Math.min(idx, cells.length - 1)];
  if (next) focusCell(next.id);
  scheduleSave();
}

function moveCellUp(id) {
  const idx = cells.findIndex(c => c.id === id);
  if (idx < 1) return;
  [cells[idx - 1], cells[idx]] = [cells[idx], cells[idx - 1]];
  renderAll();
  focusCell(id);
  scheduleSave();
}

function moveCellDown(id) {
  const idx = cells.findIndex(c => c.id === id);
  if (idx < 0 || idx >= cells.length - 1) return;
  [cells[idx], cells[idx + 1]] = [cells[idx + 1], cells[idx]];
  renderAll();
  focusCell(id);
  scheduleSave();
}

/* ============================================================
   RENDERING
   ============================================================ */
function renderAll() {
  const container = $('#cells');
  container.innerHTML = '';
  cells.forEach((cell, i) => {
    container.appendChild(buildAddRow(cell.id, true, i));
    container.appendChild(buildCellEl(cell));
  });
  container.appendChild(buildAddRow(null, false, cells.length));
  updateTOC();
  updateCellCount();
}

function buildAddRow(afterId, before, idx) {
  const row = document.createElement('div');
  row.className = 'add-row';
  row.innerHTML = `
    <span class="line"></span>
    <button class="add-pill" data-after="${afterId || ''}" data-idx="${idx}" data-type="code">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z"/></svg>+ Code
    </button>
    <button class="add-pill" data-after="${afterId || ''}" data-idx="${idx}" data-type="text">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z"/></svg>+ Text
    </button>
    <span class="line"></span>`;
  row.querySelectorAll('.add-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      const type = btn.dataset.type;
      const afterCellId = btn.dataset.after;
      if (afterCellId) activeCellId = afterCellId;
      else activeCellId = cells.length ? cells[cells.length - 1].id : null;
      insertCellAfter(type, type === 'code' ? 'python' : 'markdown');
    });
  });
  return row;
}

function buildCellEl(cell) {
  const el = document.createElement('div');
  el.className = 'cell' + (cell.type === 'text' ? ' text-cell' : '') + (cell.id === activeCellId ? ' active' : '');
  el.dataset.cellId = cell.id;

  if (cell.type === 'text') {
    el.innerHTML = buildTextCellHTML(cell);
  } else {
    el.innerHTML = buildCodeCellHTML(cell);
  }

  wireCell(el, cell);
  return el;
}

function buildCodeCellHTML(cell) {
  const lang = cell.language || 'python';
  const src = cell.source || '';
  const ec = cell.outputs && cell.outputs[0] && cell.outputs[0].exec_count;
  const isAidl = lang === 'aidl';
  return `
  <div class="gutter">
    <button class="run-btn" title="Run cell (Shift+Enter)">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
    </button>
    <span class="exec-count">${ec != null ? '[' + ec + ']' : '[ ]'}</span>
  </div>
  <div class="cell-main">
    <div class="cell-langbar">
      <select class="lang-select" title="Cell language">
        <option value="python" ${!isAidl ? 'selected' : ''}>Python 3</option>
        <option value="aidl"   ${isAidl  ? 'selected' : ''}>AIDL</option>
      </select>
    </div>
    <div class="cell-tools">
      <button class="icon-btn sm" data-do="up" title="Move up"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 14l5-5 5 5z"/></svg></button>
      <button class="icon-btn sm" data-do="down" title="Move down"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z"/></svg></button>
      <button class="icon-btn sm" data-do="clear" title="Clear output"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg></button>
      <button class="icon-btn sm" data-do="delete" title="Delete cell"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6zM19 4h-3.5l-1-1h-5l-1 1H5v2h14z"/></svg></button>
    </div>
    <div class="editor" data-lang="${lang}">
      <pre class="editor-pre" aria-hidden="true">${highlightCode(src, lang)}</pre>
      <textarea class="editor-ta" spellcheck="false" autocorrect="off" autocapitalize="off">${esc(src)}</textarea>
    </div>
    <div class="outputs">${renderOutputs(cell.outputs || [])}</div>
  </div>`;
}

function buildTextCellHTML(cell) {
  const src = cell.source || '';
  return `
  <div class="gutter"></div>
  <div class="cell-main">
    <div class="cell-tools">
      <button class="icon-btn sm" data-do="up" title="Move up"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 14l5-5 5 5z"/></svg></button>
      <button class="icon-btn sm" data-do="down" title="Move down"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z"/></svg></button>
      <button class="icon-btn sm" data-do="delete" title="Delete cell"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6zM19 4h-3.5l-1-1h-5l-1 1H5v2h14z"/></svg></button>
    </div>
    <div class="md-view md" data-editing="false">${renderMarkdown(src)}</div>
    <textarea class="text-edit hidden" rows="6" placeholder="Markdown…">${esc(src)}</textarea>
  </div>`;
}

function renderOutputs(outputs) {
  if (!outputs || !outputs.length) return '';
  return outputs.map(o => renderOneOutput(o)).join('');
}

function renderOneOutput(o) {
  if (!o) return '';
  let html = '';

  if (o.stdout && o.stdout.trim()) {
    html += `<div class="out-block out-stream">${esc(o.stdout)}</div>`;
  }
  if (o.result && o.result.trim()) {
    html += `<div class="out-block out-result">${esc(o.result)}</div>`;
  }
  if (o.images && o.images.length) {
    o.images.forEach(img => {
      html += `<div class="out-block out-image"><img src="data:image/png;base64,${img}" alt="Output figure" loading="lazy"></div>`;
    });
  }
  if (o.error) {
    const e = o.error;
    html += `<div class="out-block out-error"><div class="ename">${esc(e.ename || 'Error')}</div>${esc(e.evalue || '')}${e.line != null ? ' (line ' + e.line + ')' : ''}\n${esc(e.traceback || '')}</div>`;
    html += `<button class="out-explain" data-error-cell>` +
      `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.09 5.26L19.5 8.5l-4 3.74L16.5 18 12 15.27 7.5 18l1-5.76-4-3.74 5.41-1.24z"/></svg>Explain this error</button>`;
  }
  return html;
}

/* ============================================================
   WIRING cell events
   ============================================================ */
function wireCell(el, cell) {
  // activate on click
  el.addEventListener('mousedown', e => {
    if (!e.target.closest('button') && !e.target.closest('select') && !e.target.closest('a')) {
      activateCell(cell.id);
    }
  });

  if (cell.type === 'code') {
    // textarea editor
    const ta = el.querySelector('.editor-ta');
    const pre = el.querySelector('.editor-pre');
    if (ta && pre) {
      ta.addEventListener('focus', () => activateCell(cell.id));
      ta.addEventListener('input', () => {
        cell.source = ta.value;
        pre.innerHTML = highlightCode(ta.value, cell.language || 'python');
        syncEditorHeight(ta, pre);
        scheduleSave();
      });
      syncEditorHeight(ta, pre);

      // tab/enter smart indent
      ta.addEventListener('keydown', e => handleEditorKey(e, ta, cell));
    }
    // run button
    const runBtn = el.querySelector('.run-btn');
    if (runBtn) runBtn.addEventListener('click', () => runCell(cell.id));

    // lang select
    const sel = el.querySelector('.lang-select');
    if (sel) sel.addEventListener('change', () => {
      cell.language = sel.value;
      el.querySelector('.editor').dataset.lang = sel.value;
      const ta2 = el.querySelector('.editor-ta');
      const pre2 = el.querySelector('.editor-pre');
      if (ta2 && pre2) pre2.innerHTML = highlightCode(ta2.value, cell.language);
      scheduleSave();
    });

    // output explain button
    el.addEventListener('click', e => {
      if (e.target.closest('[data-error-cell]')) {
        explainCellError(cell);
      }
    });
  } else {
    // text cell: click markdown to edit
    const view = el.querySelector('.md-view');
    const ta = el.querySelector('.text-edit');
    if (view && ta) {
      view.addEventListener('dblclick', () => startTextEdit(view, ta, cell));
      ta.addEventListener('blur', () => endTextEdit(view, ta, cell));
      ta.addEventListener('input', () => { cell.source = ta.value; scheduleSave(); });
      ta.addEventListener('keydown', e => {
        if (e.key === 'Escape') ta.blur();
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') ta.blur();
      });
    }
  }

  // toolbar actions
  el.querySelectorAll('[data-do]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const action = btn.dataset.do;
      activateCell(cell.id);
      if (action === 'delete') deleteCell(cell.id);
      else if (action === 'up') moveCellUp(cell.id);
      else if (action === 'down') moveCellDown(cell.id);
      else if (action === 'clear') { cell.outputs = []; refreshOutputs(cell); }
    });
  });
}

function startTextEdit(view, ta, cell) {
  view.classList.add('hidden');
  ta.classList.remove('hidden');
  ta.value = cell.source || '';
  ta.focus();
  ta.style.height = 'auto';
  ta.style.height = Math.max(80, ta.scrollHeight) + 'px';
}

function endTextEdit(view, ta, cell) {
  cell.source = ta.value;
  view.innerHTML = renderMarkdown(cell.source);
  view.classList.remove('hidden');
  ta.classList.add('hidden');
  scheduleSave();
  updateTOC();
}

function syncEditorHeight(ta, pre) {
  const h = Math.max(42, pre.scrollHeight);
  ta.style.height = h + 'px';
}

function handleEditorKey(e, ta, cell) {
  if ((e.key === 'Enter' && e.shiftKey)) {
    e.preventDefault(); runCell(cell.id); return;
  }
  if ((e.key === 'Enter' && (e.ctrlKey || e.metaKey))) {
    e.preventDefault(); runCell(cell.id, true); return;
  }
  if (e.key === 'Tab') {
    e.preventDefault();
    const s = ta.selectionStart, end = ta.selectionEnd;
    const v = ta.value;
    if (e.shiftKey) {
      // dedent
      const lineStart = v.lastIndexOf('\n', s - 1) + 1;
      if (v.slice(lineStart, lineStart + 4) === '    ') {
        ta.value = v.slice(0, lineStart) + v.slice(lineStart + 4);
        ta.selectionStart = ta.selectionEnd = Math.max(lineStart, s - 4);
      }
    } else {
      ta.value = v.slice(0, s) + '    ' + v.slice(end);
      ta.selectionStart = ta.selectionEnd = s + 4;
    }
    cell.source = ta.value;
    ta.dispatchEvent(new Event('input'));
    return;
  }
  if (e.key === 'Enter') {
    // auto-indent
    const pos = ta.selectionStart;
    const before = ta.value.slice(0, pos);
    const lastLine = before.slice(before.lastIndexOf('\n') + 1);
    const indent = lastLine.match(/^(\s*)/)[1];
    const extra = lastLine.trim().endsWith(':') ? '    ' : '';
    const insert = '\n' + indent + extra;
    e.preventDefault();
    const v = ta.value;
    ta.value = v.slice(0, pos) + insert + v.slice(ta.selectionEnd);
    ta.selectionStart = ta.selectionEnd = pos + insert.length;
    cell.source = ta.value;
    ta.dispatchEvent(new Event('input'));
  }
}

function activateCell(id) {
  if (activeCellId === id) return;
  const prev = activeCellId;
  activeCellId = id;
  if (prev) {
    const pEl = cellEl(prev);
    if (pEl) pEl.classList.remove('active');
  }
  const el = cellEl(id);
  if (el) el.classList.add('active');
  lastError = null;
}

function focusCell(id) {
  activateCell(id);
  const el = cellEl(id);
  if (!el) return;
  const ta = el.querySelector('.editor-ta') || el.querySelector('.text-edit');
  if (ta && !ta.classList.contains('hidden')) {
    ta.focus();
    ta.selectionStart = ta.selectionEnd = ta.value.length;
  }
  el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function cellEl(id) { return $(`[data-cell-id="${id}"]`); }

function refreshOutputs(cell) {
  const el = cellEl(cell.id);
  if (!el) return;
  const outEl = el.querySelector('.outputs');
  if (outEl) outEl.innerHTML = renderOutputs(cell.outputs || []);
  const ec = el.querySelector('.exec-count');
  if (ec) {
    const cnt = cell.outputs && cell.outputs[0] && cell.outputs[0].exec_count;
    ec.textContent = cnt != null ? '[' + cnt + ']' : '[ ]';
  }
}

/* ============================================================
   RUN
   ============================================================ */
async function runCell(id, stayOnCell) {
  const cell = findCell(id);
  if (!cell || cell.type === 'text') return;

  activateCell(id);
  const el = cellEl(id);
  if (!el) return;

  el.classList.add('running');
  const connectBtn = $('#connectBtn');
  if (connectBtn) connectBtn.classList.add('busy');
  setKernelStatus('Running…');

  try {
    const result = await api('POST', `/api/notebooks/${NB_ID}/run`, {
      source: cell.source,
      language: cell.language || 'python',
    });

    cell.outputs = [result];
    refreshOutputs(cell);

    // update exec count badge
    const ec = el.querySelector('.exec-count');
    if (ec && result.exec_count != null) ec.textContent = '[' + result.exec_count + ']';

    // status
    if (result.status === 'ok') {
      setKernelStatus('Ready');
      const elapsed = result.elapsed != null ? fmtElapsed(result.elapsed * 1000) : '';
      if (elapsed) { const lr = $('#lastRun'); if (lr) lr.textContent = 'Last run: ' + elapsed; }
      lastError = null;
      // Refresh files panel so outputs written to disk appear (#5)
      if (currentPanel === 'files') refreshFiles();
      else refreshFiles();  // always refresh silently
    } else {
      setKernelStatus('Error');
      lastError = { language: cell.language, code: cell.source, error: result.error };
      // auto-explain
      autoExplain(cell.language, cell.source, result.error);
    }

    scheduleSave();

    // move to next cell (Shift+Enter behavior)
    if (!stayOnCell && result.status === 'ok') {
      const idx = cells.findIndex(c => c.id === id);
      if (idx >= 0 && idx < cells.length - 1) {
        focusCell(cells[idx + 1].id);
      } else if (idx === cells.length - 1) {
        insertCellAfter('code', cell.language);
      }
    }
  } catch (err) {
    toast('Run failed: ' + err.message);
    setKernelStatus('Error');
  } finally {
    el.classList.remove('running');
    if (connectBtn) connectBtn.classList.remove('busy');
  }
}

async function runAll() {
  for (const cell of cells) {
    if (cell.type === 'code') await runCell(cell.id, true);
  }
}

async function runBefore() {
  const idx = activeCellIdx();
  for (let i = 0; i < idx; i++) {
    if (cells[i].type === 'code') await runCell(cells[i].id, true);
  }
}

async function runAfter() {
  const idx = activeCellIdx();
  for (let i = idx; i < cells.length; i++) {
    if (cells[i].type === 'code') await runCell(cells[i].id, true);
  }
}

function setKernelStatus(s) {
  const el = $('#kernelStatus');
  if (el) el.textContent = s;
  const lbl = $('#connectLabel');
  if (lbl) lbl.textContent = s === 'Ready' ? 'Connected' : s;
}

async function restartRuntime() {
  try {
    await api('POST', `/api/notebooks/${NB_ID}/reset`);
    toast('Runtime restarted. Kernel state cleared.');
    setKernelStatus('Ready');
    lastError = null;
  } catch (e) { toast('Restart failed: ' + e.message); }
}

/* ============================================================
   SAVE
   ============================================================ */
function scheduleSave() {
  const el = $('#saveState');
  if (el) el.textContent = 'Saving…';
  clearTimeout(saveTimer);
  saveTimer = setTimeout(doSave, 1200);
}

async function doSave() {
  if (saving) return;
  saving = true;
  try {
    await api('PUT', `/api/notebooks/${NB_ID}`, {
      content: { cells },
      name: notebookName,
    });
    const el = $('#saveState');
    if (el) el.textContent = 'All changes saved';
  } catch (e) {
    const el = $('#saveState');
    if (el) el.textContent = 'Save failed';
    console.error('Save error', e);
  } finally {
    saving = false;
  }
}

window.addEventListener('beforeunload', () => {
  if (saveTimer) {
    clearTimeout(saveTimer);
    navigator.sendBeacon(`/api/notebooks/${NB_ID}`, JSON.stringify({ content: { cells }, name: notebookName }));
  }
});

/* ============================================================
   TITLE EDITING
   ============================================================ */
const titleEl = $('#nbTitle');
if (titleEl) {
  titleEl.addEventListener('blur', async () => {
    const n = titleEl.textContent.trim() || 'Untitled notebook';
    titleEl.textContent = n;
    if (n !== notebookName) {
      notebookName = n;
      document.title = n + ' · Agentic Colab';
      try { await api('POST', `/api/notebooks/${NB_ID}/rename`, { name: n }); }
      catch (e) { toast('Rename failed: ' + e.message); }
    }
  });
  titleEl.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); titleEl.blur(); }
    if (e.key === 'Escape') { titleEl.textContent = notebookName; titleEl.blur(); }
  });
}

/* ============================================================
   MENU SYSTEM
   ============================================================ */
// open/close menus
document.addEventListener('click', e => {
  const menuLabel = e.target.closest('[data-menu] > .menu-label');
  $$('[data-menu]').forEach(m => {
    if (m.contains(menuLabel)) m.classList.toggle('open');
    else m.classList.remove('open');
  });
  if (!e.target.closest('[data-menu]')) $$('[data-menu]').forEach(m => m.classList.remove('open'));
  // account menu
  const acct = $('#acctMenu');
  if (acct && !e.target.closest('#avatarBtn')) acct.style.display = 'none';
});

const avatarBtn = $('#avatarBtn');
const acctMenu = $('#acctMenu');
if (avatarBtn && acctMenu) {
  avatarBtn.addEventListener('click', e => {
    e.stopPropagation();
    acctMenu.style.display = acctMenu.style.display === 'block' ? 'none' : 'block';
  });
}

// dispatch all data-action clicks from anywhere
document.addEventListener('click', e => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  e.preventDefault();
  const action = el.dataset.action;
  $$('[data-menu]').forEach(m => m.classList.remove('open'));
  dispatchAction(action);
});

function dispatchAction(action) {
  switch (action) {
    case 'new': {
      fetch('/api/notebooks', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({name: 'Untitled notebook'}) })
        .then(r => r.json()).then(nb => { window.location.href = '/notebook/' + nb.id; }).catch(e => toast(e.message));
      break;
    }
    case 'rename': titleEl && titleEl.focus(); break;
    case 'save': doSave(); break;
    case 'share': openShareModal(); break;
    case 'kaggle': openKaggleModal(); break;
    case 'download-py': downloadPy(); break;
    case 'insert-code': insertCellAfter('code', 'python'); break;
    case 'insert-text': insertCellAfter('text', 'markdown'); break;
    case 'insert-aidl': insertCellAfter('code', 'aidl'); break;
    case 'clear-outputs': clearAllOutputs(); break;
    case 'delete-cell': { const c = getActiveCell(); if (c) deleteCell(c.id); break; }
    case 'run-all': runAll(); break;
    case 'run-before': runBefore(); break;
    case 'run-after': runAfter(); break;
    case 'restart': restartRuntime(); break;
    case 'restart-run-all': restartRuntime().then(() => runAll()); break;
    case 'manual': openManual(); break;
    case 'about': openModal('#aboutBack'); break;
    case 'toggle-toc': togglePanel('toc'); break;
    case 'toggle-files': togglePanel('files'); break;
    case 'toggle-snippets': togglePanel('snippets'); break;
    case 'toggle-assistant': toggleAssist(); break;
    case 'assistant-settings': toggleAssistSettings(); break;
    case 'find': togglePanel('find'); break;
  }
}

/* keyboard shortcuts */
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); doSave(); }
  if ((e.ctrlKey || e.metaKey) && e.key === 'F9') { e.preventDefault(); runAll(); }
  if ((e.ctrlKey || e.metaKey) && e.key === 'h') { e.preventDefault(); togglePanel('find'); }
  if (e.key === 'F2' && titleEl) titleEl.focus();
  if (e.key === 'Escape') { $$('[data-menu]').forEach(m => m.classList.remove('open')); }
});

/* ============================================================
   PANELS / SIDEBAR
   ============================================================ */
let currentPanel = null;

function togglePanel(panelName) {
  const side = $('#side');
  if (currentPanel === panelName) {
    // close
    side.classList.remove('open');
    $$('[data-panel]').forEach(b => b.classList.remove('active'));
    currentPanel = null;
    return;
  }
  // switch or open
  currentPanel = panelName;
  side.classList.add('open');
  $$('[data-panel]').forEach(b => b.classList.toggle('active', b.dataset.panel === panelName));
  $$('.side-panel').forEach(p => p.style.display = 'none');
  const target = $(`#panel${panelName[0].toUpperCase() + panelName.slice(1)}`);
  if (target) target.style.display = 'flex';

  if (panelName === 'files') refreshFiles();
  if (panelName === 'toc') updateTOC();
  if (panelName === 'snippets') renderSnippets();
}

// panel close buttons
document.addEventListener('click', e => {
  if (e.target.closest('[data-panel-close]')) {
    const side = $('#side');
    side.classList.remove('open');
    $$('[data-panel]').forEach(b => b.classList.remove('active'));
    currentPanel = null;
  }
});

// side panels need display:flex
$$('.side-panel').forEach(p => {
  if (p.style.display !== 'none') p.style.display = 'flex';
  p.style.flexDirection = 'column';
  p.style.height = '100%';
});
$('#panelToc').style.display = 'flex';
$('#panelToc').style.flexDirection = 'column';
$('#panelToc').style.height = '100%';

/* rail buttons */
$$('[data-panel]').forEach(btn => {
  btn.addEventListener('click', () => togglePanel(btn.dataset.panel));
});

/* ============================================================
   TOC
   ============================================================ */
function updateTOC() {
  const list = $('#tocList');
  if (!list) return;
  list.innerHTML = '';
  let found = false;
  cells.forEach(cell => {
    if (cell.type !== 'text') return;
    const lines = (cell.source || '').split('\n');
    lines.forEach(line => {
      const m = line.match(/^(#{1,4})\s+(.*)/);
      if (!m) return;
      found = true;
      const lvl = m[1].length;
      const text = m[2];
      const li = document.createElement('li');
      li.className = 'toc-li lvl-' + lvl;
      const a = document.createElement('a');
      a.href = '#'; a.textContent = text;
      a.addEventListener('click', ev => {
        ev.preventDefault();
        const el = cellEl(cell.id);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      li.appendChild(a);
      list.appendChild(li);
    });
  });
  if (!found) {
    list.innerHTML = '<li class="toc-empty">Add headings in text cells to see them here.</li>';
  }
}

/* ============================================================
   FILES PANEL
   ============================================================ */
async function refreshFiles() {
  try {
    const files = await api('GET', `/api/notebooks/${NB_ID}/files`);
    renderFileList(files);
  } catch (e) { toast('Could not load files: ' + e.message); }
}

function renderFileList(files) {
  const list = $('#fileList');
  if (!list) return;
  list.innerHTML = '';
  if (!files.length) {
    list.innerHTML = '<li style="color:var(--text-faint);font-size:12px;padding:8px 10px">No files yet — upload a dataset.</li>';
    return;
  }
  files.forEach(f => {
    const li = document.createElement('li');
    li.className = 'file-li';
    li.innerHTML = `
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zm4 18H6V4h7v5h5z"/></svg>
      <span class="nm" title="${esc(f.name)}">${esc(f.name)}</span>
      <span class="sz">${fmtBytes(f.size)}</span>
      <button class="icon-btn sm del" title="Delete file" style="color:var(--text-faint)">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6zM19 4h-3.5l-1-1h-5l-1 1H5v2h14z"/></svg>
      </button>`;
    li.querySelector('.del').addEventListener('click', async () => {
      if (!confirm('Delete ' + f.name + '?')) return;
      try {
        await api('DELETE', `/api/notebooks/${NB_ID}/files/${encodeURIComponent(f.name)}`);
        refreshFiles();
      } catch (e) { toast('Delete failed: ' + e.message); }
    });
    list.appendChild(li);
  });
}

// upload button
const uploadBtn = $('#uploadBtn');
const fileInput = $('#fileInput');
const refreshFilesBtn = $('#refreshFiles');
const kaggleBtnEl = $('#kaggleBtn');
if (uploadBtn && fileInput) uploadBtn.addEventListener('click', () => fileInput.click());
if (refreshFilesBtn) refreshFilesBtn.addEventListener('click', refreshFiles);
if (kaggleBtnEl) kaggleBtnEl.addEventListener('click', openKaggleModal);
if (fileInput) fileInput.addEventListener('change', () => { uploadFiles(fileInput.files); fileInput.value = ''; });

// drag & drop
const dropzone = $('#dropzone');
if (dropzone) {
  dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('drag'); });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag'));
  dropzone.addEventListener('drop', e => {
    e.preventDefault(); dropzone.classList.remove('drag');
    uploadFiles(e.dataTransfer.files);
  });
  dropzone.addEventListener('click', () => fileInput && fileInput.click());
}

async function uploadFiles(files) {
  for (const f of Array.from(files)) {
    const fd = new FormData();
    fd.append('file', f);
    try {
      toast('Uploading ' + f.name + '…', 2000);
      await fetch(`/api/notebooks/${NB_ID}/files`, { method: 'POST', body: fd }).then(r => {
        if (!r.ok) throw new Error(r.statusText);
        return r.json();
      });
      toast(f.name + ' uploaded.');
      refreshFiles();
    } catch (e) { toast('Upload failed: ' + e.message); }
  }
}

/* ============================================================
   FIND AND REPLACE
   ============================================================ */
const findInput = $('#findInput');
const replaceInput = $('#replaceInput');
const findCount = $('#findCount');
const findNext = $('#findNext');
const replaceAll = $('#replaceAll');
let findMatches = [], findIdx = 0;

if (findInput) findInput.addEventListener('input', doFind);
if (findNext) findNext.addEventListener('click', () => {
  if (!findMatches.length) { doFind(); return; }
  findIdx = (findIdx + 1) % findMatches.length;
  scrollToMatch(findMatches[findIdx]);
});
if (replaceAll) replaceAll.addEventListener('click', doReplaceAll);

function doFind() {
  const q = findInput.value;
  findMatches = [];
  if (!q) { if (findCount) findCount.textContent = ''; return; }
  cells.forEach((cell, ci) => {
    let idx = 0, src = cell.source;
    while ((idx = src.indexOf(q, idx)) !== -1) {
      findMatches.push({ cellIdx: ci, charIdx: idx });
      idx++;
    }
  });
  if (findCount) findCount.textContent = findMatches.length + ' match' + (findMatches.length !== 1 ? 'es' : '');
  if (findMatches.length) { findIdx = 0; scrollToMatch(findMatches[0]); }
}

function scrollToMatch(m) {
  if (!m) return;
  const cell = cells[m.cellIdx];
  if (cell) {
    const el = cellEl(cell.id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

function doReplaceAll() {
  const q = findInput ? findInput.value : '';
  const r = replaceInput ? replaceInput.value : '';
  if (!q) return;
  let count = 0;
  cells.forEach(cell => {
    const occ = (cell.source.match(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'), 'g')) || []).length;
    if (occ) { cell.source = cell.source.split(q).join(r); count += occ; }
  });
  renderAll();
  toast('Replaced ' + count + ' occurrence' + (count !== 1 ? 's' : ''));
  scheduleSave();
}

/* ============================================================
   CODE SNIPPETS
   ============================================================ */
const SNIPPETS = [
  { title: 'Load CSV (Python)', lang: 'python', code: 'import pandas as pd\n\ndf = pd.read_csv("data.csv")\nprint(df.head())' },
  { title: 'Plot histogram', lang: 'python', code: 'import matplotlib.pyplot as plt\n\ndf["column"].hist(bins=20)\nplt.title("Distribution")\nplt.show()' },
  { title: 'Train classifier (AIDL)', lang: 'aidl', code: 'data = load("data.csv")\nmodel = classifier()\nresult = model.train(data, epochs=20)\nprint("accuracy", model.accuracy)' },
  { title: 'Train regressor (AIDL)', lang: 'aidl', code: 'data = load("data.csv")\nmodel = regressor()\nresult = model.train(data, epochs=20)\nprint("score", model.score)' },
  { title: 'Explore dataset (AIDL)', lang: 'aidl', code: 'data = load("data.csv")\nprint("rows:", data.rows)\nprint("cols:", data.cols)\nprint(data.describe())' },
  { title: 'Loop & conditional (AIDL)', lang: 'aidl', code: 'nums = [1, 2, 3, 4, 5]\nfor x in nums:\n    if x % 2 == 0:\n        print(x, "is even")\n    else:\n        print(x, "is odd")' },
  { title: 'sklearn classifier', lang: 'python', code: 'from sklearn.ensemble import RandomForestClassifier\nfrom sklearn.model_selection import train_test_split\n\nX = df.drop("target", axis=1)\ny = df["target"]\nX_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)\n\nclf = RandomForestClassifier(n_estimators=100)\nclf.fit(X_train, y_train)\nprint("accuracy:", clf.score(X_test, y_test))' },
];

function renderSnippets() {
  const list = $('#snippetList');
  if (!list || list.dataset.rendered) return;
  list.dataset.rendered = '1';
  SNIPPETS.forEach(s => {
    const div = document.createElement('div');
    div.className = 'snippet';
    div.innerHTML = `<div class="t">${esc(s.title)}</div><div class="d"><span class="lang-badge ${s.lang === 'aidl' ? 'aidl' : 'py'}">${s.lang}</span></div>
    <pre>${esc(s.code)}</pre>
    <button class="btn ghost" style="font-size:12px;height:28px;padding:0 10px">Insert cell</button>`;
    div.querySelector('button').addEventListener('click', () => {
      insertCellAfter('code', s.lang, s.code);
      toast('Snippet inserted.');
    });
    list.appendChild(div);
  });
}

/* ============================================================
   MANUAL
   ============================================================ */
async function openManual() {
  openModal('#manualBack');
  const body = $('#manualBody');
  if (!body) return;
  if (manualCache) { body.innerHTML = renderMarkdown(manualCache); return; }
  body.innerHTML = '<div style="color:var(--text-secondary);padding:20px">Loading…</div>';
  try {
    const data = await api('GET', `/api/aidl/manual`);
    manualCache = data.markdown;
    body.innerHTML = renderMarkdown(manualCache);
  } catch (e) { body.textContent = 'Failed to load manual.'; }
}

$('#manualClose') && $('#manualClose').addEventListener('click', () => closeModal('#manualBack'));
$('#manualOk') && $('#manualOk').addEventListener('click', () => closeModal('#manualBack'));
$('#manualInsert') && $('#manualInsert').addEventListener('click', () => {
  closeModal('#manualBack');
  const example = `data = load("your_file.csv")\nmodel = classifier()\nresult = model.train(data, epochs=20)\nprint("accuracy", model.accuracy)\n\nfor i in range(data.rows):\n    pred = model.predict(data, row=i)\n    print("row", i, "->", pred)`;
  insertCellAfter('code', 'aidl', example);
  toast('AIDL example cell inserted.');
});

$('#aboutOk') && $('#aboutOk').addEventListener('click', () => closeModal('#aboutBack'));

function openModal(sel) { const m = $(sel); if (m) m.classList.add('open'); }
function closeModal(sel) { const m = $(sel); if (m) m.classList.remove('open'); }
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-back')) closeModal('#' + e.target.id);
});

/* ============================================================
   ASSISTANT
   ============================================================ */
function toggleAssist() {
  const assist = $('#assist');
  if (!assist) return;
  assist.classList.toggle('collapsed');
}

function toggleAssistSettings() {
  const s = $('#assistSettings');
  if (s) s.classList.toggle('open');
}

const providerSel = $('#provider');
const keyFields = $('#keyFields');
const apiKeyInput = $('#apiKey');
const modelInput = $('#model');
if (providerSel) {
  providerSel.addEventListener('change', () => {
    assistProvider = providerSel.value;
    if (keyFields) keyFields.style.display = assistProvider ? 'block' : 'none';
    updateModeChip();
  });
}
if (apiKeyInput) apiKeyInput.addEventListener('input', () => { assistApiKey = apiKeyInput.value; });
if (modelInput) modelInput.addEventListener('input', () => { assistModel = modelInput.value; });

function updateModeChip() {
  const chip = $('#assistMode');
  if (!chip) return;
  if (assistProvider && assistApiKey) {
    chip.textContent = assistProvider + ' (LLM)';
    chip.className = 'mode-chip llm';
  } else {
    chip.textContent = 'No API key needed';
    chip.className = 'mode-chip';
  }
}

function appendAssistMsg(role, html) {
  const msgs = $('#assistMsgs');
  if (!msgs) return;
  $('#assistEmpty') && ($('#assistEmpty').style.display = 'none');
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  const ico = role === 'user'
    ? '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0 2c-5.33 0-8 2.67-8 4v2h16v-2c0-1.33-2.67-4-8-4z"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.09 5.26L19.5 8.5l-4 3.74L16.5 18 12 15.27 7.5 18l1-5.76-4-3.74 5.41-1.24z"/></svg>';
  div.innerHTML = `<span class="who">${ico}</span><div class="bubble md">${html}</div>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
}

function appendTyping() {
  const msgs = $('#assistMsgs');
  if (!msgs) return;
  const div = document.createElement('div');
  div.className = 'msg bot typing-msg';
  div.innerHTML = `<span class="who"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.09 5.26L19.5 8.5l-4 3.74L16.5 18 12 15.27 7.5 18l1-5.76-4-3.74 5.41-1.24z"/></svg></span>
    <div class="bubble"><span class="typing"><span></span><span></span><span></span></span></div>`;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

async function autoExplain(language, code, error) {
  if (!error) return;
  const typing = appendTyping();
  try {
    const data = await api('POST', `/api/notebooks/${NB_ID}/explain`, {
      language, code, error,
      ...(assistProvider && assistApiKey ? { provider: assistProvider, api_key: assistApiKey, model: assistModel } : {})
    });
    typing.remove();
    appendAssistMsg('bot', renderMarkdown(data.markdown));
  } catch (e) {
    typing.remove();
    appendAssistMsg('bot', renderMarkdown('_Could not get explanation: ' + e.message + '_'));
  }
}

async function explainCellError(cell) {
  if (!cell.outputs || !cell.outputs[0] || !cell.outputs[0].error) return;
  const assist = $('#assist');
  if (assist && assist.classList.contains('collapsed')) assist.classList.remove('collapsed');
  autoExplain(cell.language, cell.source, cell.outputs[0].error);
}

// send chat
const assistText = $('#assistText');
const assistSend = $('#assistSend');
if (assistText) {
  assistText.addEventListener('input', () => {
    assistText.style.height = 'auto';
    assistText.style.height = Math.min(120, assistText.scrollHeight) + 'px';
  });
  assistText.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });
}
if (assistSend) assistSend.addEventListener('click', sendChat);

async function sendChat() {
  const q = assistText ? assistText.value.trim() : '';
  if (!q) return;
  if (assistText) { assistText.value = ''; assistText.style.height = 'auto'; }
  if (assistSend) assistSend.disabled = true;

  appendAssistMsg('user', esc(q));
  const typing = appendTyping();

  const ac = getActiveCell();
  const ctx = ac ? { language: ac.language, code: ac.source, error: lastError ? lastError.error : null } : {};

  try {
    const data = await api('POST', `/api/notebooks/${NB_ID}/assistant`, {
      message: q, ...ctx,
      ...(assistProvider && assistApiKey ? { provider: assistProvider, api_key: assistApiKey, model: assistModel } : {})
    });
    typing.remove();
    appendAssistMsg('bot', renderMarkdown(data.text));
  } catch (e) {
    typing.remove();
    appendAssistMsg('bot', renderMarkdown('_Error: ' + e.message + '_'));
  } finally {
    if (assistSend) assistSend.disabled = false;
  }
}

/* ============================================================
   DOWNLOAD
   ============================================================ */
function downloadIpynb() {
  const nb = {
    nbformat: 4, nbformat_minor: 5,
    metadata: { kernelspec: { display_name: 'Python 3', language: 'python', name: 'python3' }, language_info: { name: 'python' } },
    cells: cells.map(c => {
      if (c.type === 'text') {
        return { cell_type: 'markdown', source: c.source, metadata: {}, outputs: [] };
      }
      const outs = (c.outputs || []).flatMap(o => {
        const out = [];
        if (o.stdout) out.push({ output_type: 'stream', name: 'stdout', text: o.stdout });
        if (o.result) out.push({ output_type: 'execute_result', data: { 'text/plain': o.result }, execution_count: o.exec_count || null, metadata: {} });
        if (o.images) o.images.forEach(img => out.push({ output_type: 'display_data', data: { 'image/png': img }, metadata: {} }));
        if (o.error) out.push({ output_type: 'error', ename: o.error.ename, evalue: o.error.evalue, traceback: [o.error.traceback] });
        return out;
      });
      return { cell_type: 'code', source: c.source, metadata: { language: c.language }, outputs: outs, execution_count: (c.outputs[0] || {}).exec_count || null };
    }),
  };
  const blob = new Blob([JSON.stringify(nb, null, 2)], { type: 'application/json' });
  downloadBlob(blob, (notebookName || 'notebook').replace(/[^a-z0-9_-]/gi, '_') + '.ipynb');
}

function downloadPy() {
  const parts = cells.map(c => {
    if (c.type === 'text') return '# ' + c.source.replace(/\n/g, '\n# ');
    const lang = c.language === 'aidl' ? ' [AIDL]' : '';
    return `# In[${lang}]:\n${c.source}`;
  });
  const blob = new Blob([parts.join('\n\n# %%\n\n')], { type: 'text/plain' });
  downloadBlob(blob, (notebookName || 'notebook').replace(/[^a-z0-9_-]/gi, '_') + '.py');
}

function downloadBlob(blob, filename) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/* ============================================================
   MISC HELPERS
   ============================================================ */
function clearAllOutputs() {
  cells.forEach(c => { c.outputs = []; });
  renderAll();
  scheduleSave();
  toast('All outputs cleared.');
}

function updateCellCount() {
  const el = $('#cellCount');
  if (el) el.textContent = cells.length + ' cell' + (cells.length !== 1 ? 's' : '');
}

/* ============================================================
   SHARE MODAL (#6)
   ============================================================ */
function openShareModal() {
  openModal('#shareBack');
  loadCollaborators();
}

async function loadCollaborators() {
  const list = $('#collabList');
  if (!list) return;
  try {
    const data = await api('GET', `/api/notebooks/${NB_ID}/collaborators`);
    renderCollabList(data.collaborators || []);
  } catch (e) { /* ignore */ }
}

function renderCollabList(collabs) {
  const list = $('#collabList');
  if (!list) return;
  list.innerHTML = '';
  if (!collabs.length) {
    list.innerHTML = '<li style="color:var(--text-faint);font-size:13px;padding:4px 0">No collaborators yet.</li>';
    return;
  }
  collabs.forEach(c => {
    const li = document.createElement('li');
    li.className = 'collab-li';
    li.innerHTML = `<span class="collab-email">${esc(c.email)}</span><span class="collab-role">${esc(c.role)}</span>
      <button class="icon-btn sm" style="color:var(--text-faint)" title="Remove" data-remove-email="${esc(c.email)}">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
      </button>`;
    li.querySelector('[data-remove-email]').addEventListener('click', async () => {
      try {
        await api('DELETE', `/api/notebooks/${NB_ID}/share`, { email: c.email });
        loadCollaborators();
        toast('Removed ' + c.email);
      } catch (e) { toast('Error: ' + e.message); }
    });
    list.appendChild(li);
  });
}

const shareAddBtn = $('#shareAddBtn');
const shareError = $('#shareError');
if (shareAddBtn) {
  shareAddBtn.addEventListener('click', async () => {
    const emailEl = $('#shareEmail');
    const email = emailEl ? emailEl.value.trim() : '';
    if (!email || !email.includes('@')) {
      if (shareError) { shareError.textContent = 'Enter a valid email.'; shareError.style.display = ''; }
      return;
    }
    if (shareError) shareError.style.display = 'none';
    try {
      await api('POST', `/api/notebooks/${NB_ID}/share`, { email });
      if (emailEl) emailEl.value = '';
      loadCollaborators();
      toast(email + ' can now edit this notebook.');
    } catch (e) {
      if (shareError) { shareError.textContent = e.message; shareError.style.display = ''; }
    }
  });
}

/* ============================================================
   KAGGLE MODAL (#4)
   ============================================================ */
function openKaggleModal() {
  openModal('#kaggleBack');
  const errEl = $('#kaggleError');
  const okEl = $('#kaggleOk');
  if (errEl) errEl.style.display = 'none';
  if (okEl) okEl.style.display = 'none';
}

const kaggleImportBtn = $('#kaggleImportBtn');
if (kaggleImportBtn) {
  kaggleImportBtn.addEventListener('click', async () => {
    const slug = ($('#kaggleSlug') || {}).value || '';
    const username = ($('#kaggleUser') || {}).value || '';
    const key = ($('#kaggleKey') || {}).value || '';
    const errEl = $('#kaggleError');
    const okEl = $('#kaggleOk');
    if (!slug.trim()) {
      if (errEl) { errEl.textContent = 'Enter a dataset slug (e.g. uciml/iris).'; errEl.style.display = ''; }
      return;
    }
    if (errEl) errEl.style.display = 'none';
    if (okEl) okEl.style.display = 'none';
    kaggleImportBtn.disabled = true;
    kaggleImportBtn.textContent = 'Importing…';
    try {
      const r = await api('POST', `/api/notebooks/${NB_ID}/kaggle`, { dataset: slug, username, key });
      if (r.error) throw new Error(r.error);
      const names = (r.files || []).map(f => f.name).join(', ');
      if (okEl) { okEl.textContent = `Imported ${r.count} file(s): ${names}`; okEl.style.display = ''; }
      refreshFiles();
    } catch (e) {
      if (errEl) { errEl.textContent = e.message; errEl.style.display = ''; }
    } finally {
      kaggleImportBtn.disabled = false;
      kaggleImportBtn.textContent = 'Import dataset';
    }
  });
}

/* ============================================================
   BOOTSTRAP
   ============================================================ */
renderAll();
if (cells.length) {
  activeCellId = cells[0].id;
  const el = cellEl(activeCellId);
  if (el) el.classList.add('active');
}
refreshFiles();
togglePanel('files');

/* ============================================================
   COLLABORATION POLLING (#6)
   ============================================================ */
let _lastSavedAt = NB.updated_at || 0;
let _localDirty = false;
let _pollInterval = null;

// Mark dirty on any cell edit
document.addEventListener('input', e => {
  if (e.target.closest('.editor-ta') || e.target.closest('.text-edit')) {
    _localDirty = true;
  }
});

function startCollabPolling() {
  if (_pollInterval) return;
  // Only poll if this is a shared notebook or there may be collaborators
  _pollInterval = setInterval(async () => {
    try {
      const data = await api('GET', `/api/notebooks/${NB_ID}`);
      const serverAt = data.updated_at || 0;
      if (serverAt > _lastSavedAt + 2) {
        // Server has newer content
        if (!_localDirty && !saveTimer) {
          // No local unsaved edits — reload cells silently
          cells = (data.content && data.content.cells) || cells;
          _lastSavedAt = serverAt;
          renderAll();
          toast('Notebook updated by a collaborator.', 4000);
          refreshFiles();
        } else {
          // Show banner
          const banner = document.getElementById('collabBadge');
          if (banner) {
            banner.textContent = '⚡ Updated by collaborator';
            banner.style.display = '';
            banner.title = 'Click to reload';
            banner.style.cursor = 'pointer';
            banner.onclick = () => {
              cells = (data.content && data.content.cells) || cells;
              _lastSavedAt = serverAt;
              _localDirty = false;
              renderAll();
              banner.style.display = 'none';
              refreshFiles();
            };
          }
        }
      }
    } catch (e) { /* ignore poll errors */ }
  }, 6000);
}

// Hook into save to reset dirty flag and update lastSavedAt
const _origDoSave = doSave;
window._patchedSave = async function() {
  await _origDoSave();
  _localDirty = false;
  try {
    const data = await api('GET', `/api/notebooks/${NB_ID}`);
    _lastSavedAt = data.updated_at || _lastSavedAt;
  } catch (e) { /* ignore */ }
};

startCollabPolling();

})(); // end IIFE
