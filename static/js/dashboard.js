/* dashboard.js */
(function () {
  /* ---- helpers ---- */
  function $(s, root) { return (root || document).querySelector(s); }
  function $$(s, root) { return Array.from((root || document).querySelectorAll(s)); }

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
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    return r.json();
  }

  function relTime(epoch) {
    if (!epoch) return '—';
    const d = new Date(epoch * 1000);
    const diff = (Date.now() - d) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: diff > 31536000 ? 'numeric' : undefined });
  }

  /* ---- format timestamps ---- */
  $$('[data-ts]').forEach(el => {
    const ts = parseFloat(el.dataset.ts);
    el.textContent = relTime(ts);
  });

  /* ---- search ---- */
  const searchEl = $('#search');
  if (searchEl) {
    searchEl.addEventListener('input', () => {
      const q = searchEl.value.trim().toLowerCase();
      $$('.nb-row').forEach(row => {
        const name = (row.dataset.name || '').toLowerCase();
        row.style.display = q && !name.includes(q) ? 'none' : '';
      });
    });
  }

  /* ---- new notebook ---- */
  async function createNotebook() {
    try {
      const nb = await api('POST', '/api/notebooks', { name: 'Untitled notebook' });
      window.location.href = '/notebook/' + nb.id;
    } catch (e) { toast('Could not create notebook: ' + e.message); }
  }
  ['#newNb', '#newNb2'].forEach(s => {
    const el = $(s);
    if (el) el.addEventListener('click', createNotebook);
  });

  /* ---- delete ---- */
  document.addEventListener('click', async e => {
    const btn = e.target.closest('.del-nb');
    if (!btn) return;
    const row = btn.closest('.nb-row');
    const id = row && row.dataset.id;
    if (!id) return;
    const name = row.querySelector('a') ? row.querySelector('a').textContent.trim() : 'this notebook';
    if (!confirm('Delete "' + name + '"? This cannot be undone.')) return;
    try {
      await api('DELETE', '/api/notebooks/' + id);
      row.remove();
      if (!$$('.nb-row').length) {
        const emptyState = document.getElementById('emptyState');
        if (emptyState) emptyState.style.display = '';
        const tbl = document.querySelector('.nb-table');
        if (tbl) tbl.style.display = 'none';
      }
      toast('Notebook deleted.');
    } catch (e) { toast('Delete failed: ' + e.message); }
  });

  /* ---- avatar menu ---- */
  const avatarBtn = $('#avatarBtn');
  const acctMenu = $('#acctMenu');
  if (avatarBtn && acctMenu) {
    avatarBtn.addEventListener('click', e => {
      e.stopPropagation();
      acctMenu.style.display = acctMenu.style.display === 'block' ? 'none' : 'block';
    });
    document.addEventListener('click', () => { if (acctMenu) acctMenu.style.display = 'none'; });
  }
})();
