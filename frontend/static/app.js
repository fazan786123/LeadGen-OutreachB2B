const API = '';  // same origin

// ── Toast ──────────────────────────────────────────────────────────────
const toastContainer = document.getElementById('toast-container');

function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  toastContainer.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ── API helpers ────────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const msg = err.detail || res.statusText;
    pipeLog(`❌ ${method} ${path} → ${msg}`, 'err');
    throw new Error(msg);
  }
  return res.json();
}

// ── Badge ──────────────────────────────────────────────────────────────
function badge(val, prefix = '') {
  if (!val) return '<span class="badge badge-not_searched">—</span>';
  const cls = (prefix + val).replace(/\s/g, '_').toLowerCase();
  return `<span class="badge badge-${cls}">${val}</span>`;
}

function sourceBadge(source) {
  if (!source) return '';
  const map = {
    website_scrape:  { icon: '🌐', label: 'website',  cls: 'source-website' },
    team_page:       { icon: '👥', label: 'team page', cls: 'source-website' },
    brave_linkedin:  { icon: '🔗', label: 'linkedin', cls: 'source-pattern' },
    brave_search:    { icon: '🔍', label: 'web search',cls: 'source-pattern' },
    pattern_guess:   { icon: '🔍', label: 'pattern',  cls: 'source-pattern' },
    apollo:          { icon: '🚀', label: 'apollo',   cls: 'source-api' },
    snov:            { icon: '❄️',  label: 'snov',     cls: 'source-api' },
    skrapp:          { icon: '🥊', label: 'skrapp',   cls: 'source-api' },
    findthat:        { icon: '🔎', label: 'findthat', cls: 'source-api' },
    hunter:          { icon: '🏹', label: 'hunter',   cls: 'source-api' },
  };
  const m = map[source] || { icon: '?', label: source, cls: 'source-api' };
  return `<span class="${m.cls}" title="${source}">${m.icon} ${m.label}</span>`;
}

function gradeBadge(grade, reason) {
  if (!grade) return '<span class="grade-unknown" title="Not validated">?</span>';
  const icons = { valid: '✓', risky: '⚠', invalid: '✕' };
  const labels = { valid: 'Valid', risky: 'Risky', invalid: 'Invalid' };
  const tip = reason ? reason.replace(/_/g, ' ') : grade;
  return `<span class="grade-${grade}" title="${esc(tip)}">${icons[grade] || '?'} ${labels[grade] || grade}</span>`;
}

// ── Modal ──────────────────────────────────────────────────────────────
function openModal(html) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `<div class="modal">${html}</div>`;
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  document.body.appendChild(overlay);
  return overlay;
}

// ── Dashboard / Pipeline page ──────────────────────────────────────────
let _pipePollInterval = null;
let _pipeRunning = false;

async function initDashboard() {
  initMaxResultsSlider();
  await loadDashboardStats();
  await loadDashboardResults();
}

function initMaxResultsSlider() {
  const slider = document.getElementById('pipe-max-results');
  const label = document.getElementById('pipe-max-label');
  const unlimited = document.getElementById('pipe-max-unlimited');
  if (!slider || !label) return;

  function updateLabel() {
    if (unlimited?.checked) {
      label.textContent = '∞';
      label.classList.add('unlimited');
      slider.disabled = true;
    } else {
      label.textContent = slider.value;
      label.classList.remove('unlimited');
      slider.disabled = false;
    }
  }

  slider.addEventListener('input', updateLabel);
  unlimited?.addEventListener('change', updateLabel);
}

function getMaxResults() {
  if (document.getElementById('pipe-max-unlimited')?.checked) return 0;
  return parseInt(document.getElementById('pipe-max-results').value) || 100;  // default 100
}

async function loadDashboardStats() {
  try {
    const data = await api('GET', '/api/dashboard/stats');
    const L = data.leads;
    document.getElementById('mini-total').textContent = L.total;
    document.getElementById('mini-email').textContent = L.with_email;
    const validData = await api('GET', '/api/leads?email_grade=valid&limit=1');
    const validEl = document.getElementById('mini-valid');
    if (validEl) validEl.textContent = validData.total;
  } catch (_) { /* stats optional on first load */ }
}

async function loadDashboardResults() {
  try {
    const data = await api('GET', '/api/leads?limit=20');
    renderDashboardResults(data.leads, data.total);
  } catch (e) {
    toast('Failed to load results: ' + e.message, 'error');
  }
}

function renderDashboardResults(leads, total) {
  const tbody = document.getElementById('dash-results-tbody');
  const sub = document.getElementById('results-subtitle');
  if (sub) sub.textContent = total ? `${total} leads in database — showing latest ${Math.min(20, total)}` : 'Run a search to see leads here';

  if (!leads.length) {
    tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><div class="icon">🗺️</div>Enter a keyword and location above, then hit <strong>Run Pipeline</strong>.</div></td></tr>`;
    return;
  }

  tbody.innerHTML = leads.map(l => `
    <tr>
      <td>
        <strong>${esc(l.business_name)}</strong>
        ${l.maps_url ? `<br><a href="${esc(l.maps_url)}" target="_blank" style="color:var(--accent);font-size:11px">View on Maps</a>` : ''}
      </td>
      <td>${l.website ? `<a href="${esc(l.website)}" target="_blank" style="color:var(--accent)">${esc(l.domain || l.website)}</a>` : '—'}</td>
      <td><small style="color:var(--text2)">${esc(l.address || '—')}</small></td>
      <td>${l.phone ? `<a href="tel:${esc(l.phone)}" style="color:var(--text)">${esc(l.phone)}</a>` : '—'}</td>
      <td>${l.rating ? `⭐ ${l.rating} <small style="color:var(--text2)">(${l.review_count || 0})</small>` : '—'}</td>
      <td><small style="color:var(--text2)">${esc(l.category || '—')}</small></td>
    </tr>
  `).join('');
}

function pipeLog(msg, type = '') {
  const timestamp = `[${new Date().toLocaleTimeString()}]`;

  // Write to progress log (clears each run)
  const log = document.getElementById('prog-log');
  if (log) {
    const line = document.createElement('span');
    line.className = 'log-line ' + type;
    line.textContent = `${timestamp} ${msg}`;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  // Also write to persistent activity log
  const activity = document.getElementById('activity-log');
  if (activity) {
    const line = document.createElement('span');
    line.className = 'log-line ' + type;
    line.textContent = `${timestamp} ${msg}`;
    activity.appendChild(line);
    activity.scrollTop = activity.scrollHeight;
  }
}

function clearActivityLog() {
  const el = document.getElementById('activity-log');
  if (el) el.innerHTML = '';
}

function setPipeStep(step, state) {
  const el = document.querySelector(`.pipe-step[data-step="${step}"]`);
  if (el) { el.classList.remove('active', 'done'); if (state) el.classList.add(state); }
}

function setPipeProgress(pct, title, subtitle, detail) {
  const bar = document.getElementById('prog-bar');
  const card = document.getElementById('pipe-progress-card');
  if (card) card.classList.remove('hidden');
  if (bar) bar.style.width = pct + '%';
  if (title) document.getElementById('prog-title').textContent = title;
  if (subtitle) document.getElementById('prog-subtitle').textContent = subtitle;
  if (detail !== undefined) document.getElementById('prog-detail').textContent = detail;
}

async function runSearch() {
  if (_pipeRunning) return;

  const keyword = document.getElementById('pipe-keyword').value.trim();
  const location = document.getElementById('pipe-location').value.trim();
  if (!keyword || !location) {
    toast('Please enter a business type and location', 'error');
    return;
  }

  const maxResults = getMaxResults();

  _pipeRunning = true;
  const btn = document.getElementById('pipe-search-btn');
  const enrichBtn = document.getElementById('pipe-enrich-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Searching…';
  enrichBtn.disabled = true;

  document.getElementById('prog-log').innerHTML = '';
  document.querySelectorAll('.pipe-step').forEach(s => s.classList.remove('active', 'done'));
  document.querySelectorAll('.pipe-step-line').forEach(l => l.classList.remove('done'));

  try {
    setPipeStep('search', 'active');
    setPipeProgress(5, 'Searching Google Maps…', `${keyword} in ${location}`, 'Connecting to Maps API…');
    pipeLog(`Starting smart search: "${keyword}" in ${location}${maxResults ? ` (target ${maxResults})` : ' (no limit)'}`, 'info');

    const res = await api('POST', '/api/leads/smart-scrape', {
      keyword, location, target: maxResults,
    });
    pipeLog(`Search job #${res.job_id} started`, 'info');
    const added = await _pollGridJob(res.job_id);

    setPipeStep('search', 'done');
    document.querySelector('.pipe-step-line')?.classList.add('done');
    setPipeProgress(100, 'Maps search complete ✓', `${added} new leads added`, 'Click Enrich Leads to find decision makers & emails');
    pipeLog(`Done — ${added} new leads added`, 'ok');
    toast(`Found ${added} new leads — click Enrich Leads to continue`, 'success');
    await loadDashboardResults();
    await loadDashboardStats();
    enrichBtn.disabled = false;

  } catch (e) {
    setPipeProgress(0, 'Search failed', e.message, '');
    pipeLog('Error: ' + e.message, 'err');
    toast('Search error: ' + e.message, 'error');
  } finally {
    _pipeRunning = false;
    btn.disabled = false;
    btn.textContent = '🗺️ Search Maps';
  }
}

async function runEnrich() {
  if (_pipeRunning) return;

  _pipeRunning = true;
  const btn = document.getElementById('pipe-enrich-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Enriching…';

  try {
    // ── Step 2: Find decision makers ────────────────────────────────
    setPipeStep('people', 'active');
    setPipeProgress(10, 'Finding decision makers…', 'Brave Search', 'Looking up owners & CEOs…');
    pipeLog('Queuing Brave Search for decision makers…', 'info');
    const peopleRes = await api('POST', '/api/leads/find-persons-bulk');
    pipeLog(peopleRes.message, peopleRes.queued ? 'ok' : 'info');
    await _waitForBulk('people', 10, 40);
    setPipeStep('people', 'done');
    document.querySelectorAll('.pipe-step-line')[1]?.classList.add('done');
    await loadDashboardResults();

    // ── Step 3: Find emails ─────────────────────────────────────────
    setPipeStep('emails', 'active');
    setPipeProgress(45, 'Finding emails…', 'Running email finder chain', 'Apollo → Snov → Hunter…');
    pipeLog('Queuing email finder chain…', 'info');
    const emailRes = await api('POST', '/api/leads/find-emails-bulk');
    pipeLog(emailRes.message, emailRes.queued ? 'ok' : 'info');
    await _waitForBulk('emails', 45, 75);
    setPipeStep('emails', 'done');
    document.querySelectorAll('.pipe-step-line')[2]?.classList.add('done');
    await loadDashboardResults();
    await loadDashboardStats();

    // ── Step 4: Validate emails ─────────────────────────────────────
    setPipeStep('validate', 'active');
    setPipeProgress(80, 'Validating emails…', 'SMTP + format checks', 'This may take a minute…');
    pipeLog('Queuing email validation…', 'info');
    const valRes = await api('POST', '/api/leads/validate-emails-bulk');
    pipeLog(valRes.message, valRes.queued ? 'ok' : 'info');
    await _waitForBulk('validate', 80, 98);
    setPipeStep('validate', 'done');
    document.querySelectorAll('.pipe-step-line')[3]?.classList.add('done');

    setPipeProgress(100, 'Enrichment complete ✓', 'All steps finished', '');
    document.getElementById('prog-icon').textContent = '✓';
    pipeLog('Enrichment finished successfully', 'ok');
    toast('Enrichment complete!', 'success');
    await loadDashboardResults();
    await loadDashboardStats();

  } catch (e) {
    setPipeProgress(0, 'Enrichment failed', e.message, '');
    pipeLog('Error: ' + e.message, 'err');
    toast('Enrichment error: ' + e.message, 'error');
  } finally {
    _pipeRunning = false;
    btn.disabled = false;
    btn.textContent = '⚡ Enrich Leads';
  }
}

function _pollGridJob(jobId) {
  return new Promise((resolve, reject) => {
    let added = 0;
    let lastPassLabel = '';
    _gridPollInterval = setInterval(async () => {
      try {
        const job = await api('GET', `/api/leads/scrape-jobs/${jobId}`);
        const pct = Math.min(24, Math.round((job.progress_pct || 0) * 0.24));
        const passLabel = job.pass_label || '';
        const subtitle = passLabel || `Viewport ${job.viewports_done} / ${job.viewports_total}`;
        setPipeProgress(pct, 'Searching Google Maps…', subtitle, `${job.leads_found || 0} businesses found — ${job.leads_added || 0} new`);

        if (passLabel && passLabel !== lastPassLabel) {
          pipeLog(passLabel, 'info');
          lastPassLabel = passLabel;
        }

        if (job.status === 'done') {
          clearInterval(_gridPollInterval);
          added = job.leads_added;
          pipeLog(`Smart search done — ${job.leads_added} new leads added`, 'ok');
          resolve(added);
        } else if (job.status === 'failed') {
          clearInterval(_gridPollInterval);
          reject(new Error(job.error || 'Smart scrape failed'));
        }
      } catch (e) {
        clearInterval(_gridPollInterval);
        reject(e);
      }
    }, 3000);
  });
}

async function _waitForBulk(step, pctStart, pctEnd) {
  // Background tasks have no progress API — poll lead counts until stable or timeout
  const maxWait = step === 'validate' ? 120000 : 180000;
  const interval = 4000;
  const start = Date.now();
  let lastCount = -1;
  let stableRounds = 0;

  while (Date.now() - start < maxWait) {
    await new Promise(r => setTimeout(r, interval));
    const elapsed = Date.now() - start;
    const pct = pctStart + Math.min(pctEnd - pctStart, (elapsed / maxWait) * (pctEnd - pctStart));
    setPipeProgress(Math.round(pct), document.getElementById('prog-title').textContent, 'Processing in background…', `Elapsed ${Math.round(elapsed / 1000)}s`);

    try {
      const data = await api('GET', '/api/leads?limit=1');
      const count = data.total;
      if (count === lastCount) {
        stableRounds++;
        if (stableRounds >= 3) break;
      } else {
        stableRounds = 0;
        lastCount = count;
      }
      await loadDashboardResults();
    } catch (_) { break; }
  }
}


// ── Leads page ────────────────────────────────────────────────────────
const PAGE_SIZE = 50;
let _leadsCurrentPage = 1;
let _leadsTotalPages = 1;
let _leadsTotalCount = 0;
let _activeTab = 'all';

async function initLeads() {
  await loadLeads();
  document.getElementById('search-input').addEventListener('input', debounce(() => { _leadsCurrentPage = 1; loadLeads(); }, 400));
  document.getElementById('filter-status').addEventListener('change', () => { _leadsCurrentPage = 1; loadLeads(); });
  document.getElementById('filter-email-status').addEventListener('change', () => { _leadsCurrentPage = 1; loadLeads(); });
  document.getElementById('filter-grade')?.addEventListener('change', () => { _leadsCurrentPage = 1; loadLeads(); });
}

function switchTab(tab, el) {
  _activeTab = tab;
  _leadsCurrentPage = 1;
  document.querySelectorAll('.leads-tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  loadLeads();
}

function changePage(delta) {
  const next = _leadsCurrentPage + delta;
  if (next < 1 || next > _leadsTotalPages) return;
  _leadsCurrentPage = next;
  loadLeads();
  // Scroll table back to top
  document.querySelector('.table-wrapper')?.scrollTo(0, 0);
}

function goToPage(page) {
  if (page < 1 || page > _leadsTotalPages) return;
  _leadsCurrentPage = page;
  loadLeads();
  document.querySelector('.table-wrapper')?.scrollTo(0, 0);
}

async function loadLeads() {
  const search = document.getElementById('search-input')?.value || '';
  const status = document.getElementById('filter-status')?.value || '';
  const emailStatus = document.getElementById('filter-email-status')?.value || '';
  const grade = document.getElementById('filter-grade')?.value || '';
  const skip = (_leadsCurrentPage - 1) * PAGE_SIZE;

  const params = new URLSearchParams({ skip, limit: PAGE_SIZE });
  if (search) params.set('search', search);
  if (status) params.set('status', status);
  if (emailStatus) params.set('email_status', emailStatus);
  if (grade) params.set('email_grade', grade);
  if (_activeTab === 'with-website') params.set('has_website', 'true');
  if (_activeTab === 'no-website') params.set('has_website', 'false');

  try {
    const data = await api('GET', `/api/leads?${params}`);
    _leadsTotalCount = data.total;
    _leadsTotalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));

    // Clamp current page if filters reduced total
    if (_leadsCurrentPage > _leadsTotalPages) {
      _leadsCurrentPage = _leadsTotalPages;
    }

    renderLeadsTable(data.leads);
    renderPagination();

    const tabLabel = _activeTab === 'no-website' ? 'leads without a website'
      : _activeTab === 'with-website' ? 'leads with a website' : 'leads';
    document.getElementById('leads-count').textContent = `${data.total.toLocaleString()} ${tabLabel}`;
  } catch (e) {
    toast('Failed to load leads: ' + e.message, 'error');
  }
}

function renderPagination() {
  const bar = document.getElementById('pagination-bar');
  const pagesEl = document.getElementById('pg-pages');
  const infoEl = document.getElementById('pg-info');
  const prevBtn = document.getElementById('pg-prev');
  const nextBtn = document.getElementById('pg-next');

  if (_leadsTotalPages <= 1) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';

  prevBtn.disabled = _leadsCurrentPage === 1;
  nextBtn.disabled = _leadsCurrentPage === _leadsTotalPages;

  // Build page number buttons with ellipsis for large ranges
  const pages = [];
  const cur = _leadsCurrentPage;
  const total = _leadsTotalPages;

  if (total <= 7) {
    for (let i = 1; i <= total; i++) pages.push(i);
  } else {
    pages.push(1);
    if (cur > 3) pages.push('…');
    for (let i = Math.max(2, cur - 1); i <= Math.min(total - 1, cur + 1); i++) pages.push(i);
    if (cur < total - 2) pages.push('…');
    pages.push(total);
  }

  pagesEl.innerHTML = pages.map(p =>
    p === '…'
      ? `<span class="pg-btn ellipsis">…</span>`
      : `<button class="pg-btn${p === cur ? ' active' : ''}" onclick="goToPage(${p})">${p}</button>`
  ).join('');

  const start = (_leadsCurrentPage - 1) * PAGE_SIZE + 1;
  const end = Math.min(_leadsCurrentPage * PAGE_SIZE, _leadsTotalCount);
  infoEl.textContent = `${start.toLocaleString()}–${end.toLocaleString()} of ${_leadsTotalCount.toLocaleString()}`;
}

function renderContacts(lead) {
  // Use contacts array if available, fall back to legacy single-contact fields
  const contacts = (lead.contacts && lead.contacts.length)
    ? lead.contacts
    : (lead.decision_maker_name ? [{ name: lead.decision_maker_name, title: lead.decision_maker_title, source: lead.email_source }] : []);

  if (!contacts.length) return '—';

  return contacts.map((c, i) => {
    return `<div style="${i > 0 ? 'margin-top:6px;padding-top:6px;border-top:1px solid var(--border)' : ''}">
      <strong style="font-size:12px">${esc(c.name)}</strong>
      ${c.title ? `<br><small style="color:var(--text2)">${esc(c.title)}</small>` : ''}
      ${c.source ? `<br>${sourceBadge(c.source)}` : ''}
    </div>`;
  }).join('');
}

function renderLeadsTable(leads) {
  const tbody = document.getElementById('leads-tbody');
  const isNoWebsite = _activeTab === 'no-website';

  if (!leads.length) {
    const msg = isNoWebsite ? 'No leads without a website found.' : 'No leads yet. Run a search to get started.';
    tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><div class="icon">${isNoWebsite ? '🚫' : '🔍'}</div>${msg}</div></td></tr>`;
    return;
  }

  tbody.innerHTML = leads.map(l => {
    const contact = l.contacts?.[0] || (l.decision_maker_name ? { name: l.decision_maker_name, title: l.decision_maker_title } : null);
    const isActive = _panelLeadId === l.id;
    return `
    <tr class="lead-row${isActive ? ' active-row' : ''}" onclick="openLeadPanel(${l.id})" style="${l.email_grade === 'invalid' ? 'opacity:0.5' : ''}">
      <td class="lead-name-cell">
        <strong>${esc(l.business_name)}</strong>
        <small>${l.website ? `<a href="${esc(l.website)}" target="_blank" style="color:var(--accent)" onclick="event.stopPropagation()">${esc(l.domain || l.website)}</a>` : `<span style="color:var(--warn)">No website</span>`}</small>
      </td>
      <td class="lead-contact-cell">
        ${contact
          ? `<div style="font-weight:500">${esc(contact.name)}</div><div style="color:var(--text2);font-size:11px">${esc(contact.title || '')}</div>`
          : `<span style="color:var(--text2)">—</span>`}
      </td>
      <td class="lead-email-cell">
        ${l.decision_maker_email
          ? `<div class="email-addr">${esc(l.decision_maker_email)}</div><div style="margin-top:2px">${gradeBadge(l.email_grade, l.email_valid_reason)}</div>`
          : badge(l.email_status)}
      </td>
      <td>${badge(l.status)}</td>
      <td onclick="event.stopPropagation()" style="text-align:right">
        <button class="btn btn-sm btn-danger" onclick="deleteLead(${l.id})" title="Delete lead">✕</button>
      </td>
    </tr>`;
  }).join('');
}

async function findPerson(leadId) {
  try {
    toast('Searching Brave for decision-maker...', 'info');
    const res = await api('POST', `/api/leads/${leadId}/find-person`);
    if (res.status === 'found') {
      const n = res.lead.contacts?.length || 1;
      toast(`Found ${n} contact${n > 1 ? 's' : ''}: ${res.lead.decision_maker_name} via ${res.source}`, 'success');
    } else {
      toast('No decision-maker found', 'error');
    }
    await loadLeads();
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

async function bulkFindPersons() {
  try {
    const res = await api('POST', '/api/leads/find-persons-bulk');
    if (res.queued === 0) { toast('No leads need a decision-maker lookup', 'info'); return; }
    _openBulkProgressModal(res.job_id, `👤 Finding Decision Makers — ${res.queued} leads`);
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

async function findEmail(leadId) {
  try {
    toast('Running email finder chain...', 'info');
    const res = await api('POST', `/api/leads/${leadId}/find-email`);
    toast(res.status === 'found' ? `Found: ${res.lead.decision_maker_email} (${res.source})` : 'No email found', res.status === 'found' ? 'success' : 'error');
    await loadLeads();
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

async function deleteLead(leadId) {
  // Inline confirmation via toast instead of blocking confirm()
  const id = 'del-' + leadId;
  const existing = document.getElementById(id);
  if (existing) {
    existing.remove();
    try {
      await api('DELETE', `/api/leads/${leadId}`);
      if (_panelLeadId === leadId) closeLeadPanel();
      toast('Lead deleted', 'success');
      await loadLeads();
    } catch (e) {
      toast('Error: ' + e.message, 'error');
    }
    return;
  }
  const el = document.createElement('div');
  el.id = id;
  el.className = 'toast toast-error';
  el.innerHTML = `Delete this lead? <button onclick="deleteLead(${leadId})" style="margin-left:10px;background:none;border:none;color:inherit;font-weight:700;cursor:pointer;text-decoration:underline">Confirm</button>`;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

async function editLead(leadId) {
  const lead = await api('GET', `/api/leads/${leadId}`);
  const overlay = openModal(`
    <div class="modal-title">Edit Lead — ${esc(lead.business_name)}</div>
    <div class="form-group">
      <label class="form-label">Status</label>
      <select id="edit-status" class="form-control">
        ${['new','contacted','replied','converted','unsubscribed'].map(s => `<option value="${s}" ${lead.status === s ? 'selected' : ''}>${s}</option>`).join('')}
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">Decision Maker Name</label>
      <input id="edit-dm-name" class="form-control" value="${esc(lead.decision_maker_name || '')}">
    </div>
    <div class="form-group">
      <label class="form-label">Decision Maker Email</label>
      <input id="edit-dm-email" class="form-control" value="${esc(lead.decision_maker_email || '')}">
    </div>
    <div class="form-group">
      <label class="form-label">Notes</label>
      <textarea id="edit-notes" class="form-control">${esc(lead.notes || '')}</textarea>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancel</button>
      <button class="btn btn-primary" onclick="saveLeadEdit(${leadId})">Save</button>
    </div>
  `);
}

async function saveLeadEdit(leadId) {
  try {
    await api('PATCH', `/api/leads/${leadId}`, {
      status: document.getElementById('edit-status').value,
      decision_maker_name: document.getElementById('edit-dm-name').value,
      decision_maker_email: document.getElementById('edit-dm-email').value,
      notes: document.getElementById('edit-notes').value,
    });
    document.querySelector('.modal-overlay')?.remove();
    toast('Lead updated', 'success');
    await loadLeads();
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

// Quick Scrape modal
function openScrapeModal() {
  openModal(`
    <div class="modal-title">Quick Search — Google Maps</div>
    <p style="color:var(--text2);font-size:13px;margin-bottom:16px">Single query, up to 60 results. Fast.</p>
    <div class="form-group">
      <label class="form-label">Business type / keyword</label>
      <input id="scrape-keyword" class="form-control" placeholder="e.g. roofing company, dental clinic, law firm">
    </div>
    <div class="form-group">
      <label class="form-label">Location</label>
      <input id="scrape-location" class="form-control" placeholder="e.g. Austin TX, London UK">
    </div>
    <div class="form-group">
      <label class="form-label">Max results</label>
      <input id="scrape-max" class="form-control" type="number" value="20" min="1" max="60">
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancel</button>
      <button class="btn btn-primary" id="scrape-btn" onclick="runScrape()">Scrape</button>
    </div>
  `);
}

async function runScrape() {
  const btn = document.getElementById('scrape-btn');
  btn.disabled = true; btn.textContent = 'Scraping...';
  try {
    const res = await api('POST', '/api/leads/scrape', {
      keyword: document.getElementById('scrape-keyword').value,
      location: document.getElementById('scrape-location').value,
      max_results: parseInt(document.getElementById('scrape-max').value),
    });
    document.querySelector('.modal-overlay')?.remove();
    toast(`Added ${res.added} new leads (${res.skipped} duplicates skipped)`, 'success');
    await loadLeads();
  } catch (e) {
    toast('Scrape error: ' + e.message, 'error');
    btn.disabled = false; btn.textContent = 'Scrape';
  }
}

// Area Sweep / Deep Sweep modal
function openGridScrapeModal() {
  openModal(`
    <div class="modal-title">⚡ Grid Scraper</div>
    <div style="display:flex;gap:8px;margin-bottom:16px;">
      <button id="mode-grid" class="btn btn-primary btn-sm" onclick="setGridMode('grid')">Area Sweep <small>(36 viewports)</small></button>
      <button id="mode-deep" class="btn btn-ghost btn-sm" onclick="setGridMode('deep')">🔥 Deep Sweep <small>(324 viewports)</small></button>
    </div>
    <p id="mode-desc" style="color:var(--text2);font-size:13px;margin-bottom:16px">
      36 viewports × up to 60 results each (paginated) — up to <strong style="color:var(--text)">2,160 raw results</strong>.
    </p>
    <div class="form-group">
      <label class="form-label">Business type / keyword</label>
      <input id="grid-keyword" class="form-control" placeholder="e.g. roofing company, dentist, law firm">
    </div>
    <div class="form-group">
      <label class="form-label">Location / City</label>
      <input id="grid-location" class="form-control" placeholder="e.g. Austin TX, Houston TX, London UK">
    </div>
    <div class="form-group">
      <label class="form-label">Grid square size</label>
      <select id="grid-size" class="form-control">
        <option value="1000">1 km — dense city centre</option>
        <option value="2000" selected>2 km — standard city (matches n8n default 3000/3×2)</option>
        <option value="3000">3 km — large city</option>
        <option value="5000">5 km — metro area</option>
        <option value="10000">10 km — entire region</option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">Max leads to collect <small style="color:var(--text2)">(0 = unlimited)</small></label>
      <input id="grid-max" class="form-control" type="number" value="0" min="0" placeholder="0 = no limit">
    </div>
    <div id="grid-progress-wrap" style="display:none;margin-bottom:16px;">
      <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px;">
        <span id="grid-progress-label" style="color:var(--text2)">Starting...</span>
        <span id="grid-progress-pct" style="color:var(--accent)">0%</span>
      </div>
      <div style="background:var(--bg3);border-radius:6px;height:8px;overflow:hidden;">
        <div id="grid-progress-bar" style="height:100%;background:var(--accent);width:0%;transition:width 0.4s;border-radius:6px;"></div>
      </div>
      <div style="margin-top:8px;font-size:12px;color:var(--text2)" id="grid-progress-detail"></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancel</button>
      <button class="btn btn-primary" id="grid-btn" onclick="runGridScrape()">⚡ Start</button>
    </div>
  `);
  window._gridMode = 'grid';
}

function setGridMode(mode) {
  window._gridMode = mode;
  document.getElementById('mode-grid').className = `btn btn-sm ${mode === 'grid' ? 'btn-primary' : 'btn-ghost'}`;
  document.getElementById('mode-deep').className = `btn btn-sm ${mode === 'deep' ? 'btn-primary' : 'btn-ghost'}`;
  document.getElementById('mode-desc').innerHTML = mode === 'deep'
    ? '9 centers × 36 viewports × 60 results = 324 viewport calls — up to <strong style="color:var(--text)">19,440 raw results</strong>. Takes longer.'
    : '36 viewports × up to 60 results each (paginated) — up to <strong style="color:var(--text)">2,160 raw results</strong>.';
}

let _gridPollInterval = null;

async function runGridScrape() {
  const btn = document.getElementById('grid-btn');
  btn.disabled = true; btn.textContent = 'Starting...';

  try {
    const res = await api('POST', '/api/leads/scrape-grid', {
      keyword: document.getElementById('grid-keyword').value,
      location: document.getElementById('grid-location').value,
      square_size: parseInt(document.getElementById('grid-size').value),
      mode: window._gridMode || 'grid',
      max_items: parseInt(document.getElementById('grid-max').value) || 0,
    });

    document.getElementById('grid-progress-wrap').style.display = 'block';
    btn.textContent = 'Running...';

    // Poll for progress every 3 seconds
    _gridPollInterval = setInterval(async () => {
      try {
        const job = await api('GET', `/api/leads/scrape-jobs/${res.job_id}`);
        const pct = job.progress_pct || 0;

        document.getElementById('grid-progress-bar').style.width = pct + '%';
        document.getElementById('grid-progress-pct').textContent = pct + '%';
        document.getElementById('grid-progress-label').textContent =
          `Viewport ${job.viewports_done} / ${job.viewports_total}`;
        document.getElementById('grid-progress-detail').textContent =
          `${job.leads_found} unique businesses found so far`;

        if (job.status === 'done') {
          clearInterval(_gridPollInterval);
          document.getElementById('grid-progress-bar').style.width = '100%';
          document.getElementById('grid-progress-pct').textContent = '100%';
          document.getElementById('grid-progress-label').textContent = 'Done!';
          document.getElementById('grid-progress-detail').textContent =
            `✓ Added ${job.leads_added} new leads (${job.leads_found - job.leads_added} duplicates skipped)`;
          btn.textContent = 'Done';
          toast(`Area Sweep complete — ${job.leads_added} new leads added`, 'success');
          await loadLeads();
        } else if (job.status === 'failed') {
          clearInterval(_gridPollInterval);
          toast('Grid scrape failed: ' + (job.error || 'unknown error'), 'error');
          btn.disabled = false; btn.textContent = '⚡ Retry';
        }
      } catch (e) {
        // poll errors are non-fatal
      }
    }, 3000);

  } catch (e) {
    toast('Error: ' + e.message, 'error');
    btn.disabled = false; btn.textContent = '⚡ Start Area Sweep';
  }
}

async function bulkFindEmails() {
  try {
    const res = await api('POST', '/api/leads/find-emails-bulk');
    if (res.queued === 0) { toast('No leads need an email lookup (all searched or no domain)', 'info'); return; }
    _openBulkProgressModal(res.job_id, `🔍 Finding Emails — ${res.queued} leads`);
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

async function validateEmail(leadId) {
  try {
    toast('Running validation checks...', 'info');
    const res = await api('POST', `/api/leads/${leadId}/validate-email`);
    const icons = { valid: '✓', risky: '⚠', invalid: '✕' };
    const types = { valid: 'success', risky: 'info', invalid: 'error' };
    toast(`${icons[res.grade] || '?'} ${res.grade.toUpperCase()} — ${(res.reason || '').replace(/_/g, ' ')}`, types[res.grade] || 'info');
    await loadLeads();
  } catch (e) {
    toast('Validation error: ' + e.message, 'error');
  }
}

async function bulkValidateEmails() {
  try {
    toast('Queuing bulk email validation (SMTP checks)...', 'info');
    const res = await api('POST', '/api/leads/validate-emails-bulk');
    toast(res.message, 'success');
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

// ── Campaigns page ────────────────────────────────────────────────────
async function initCampaigns() {
  await loadCampaigns();
}

async function loadCampaigns() {
  try {
    const campaigns = await api('GET', '/api/campaigns');
    const tbody = document.getElementById('campaigns-tbody');
    if (!campaigns.length) {
      tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><div class="icon">📧</div>No campaigns yet.</div></td></tr>`;
      return;
    }
    tbody.innerHTML = campaigns.map(c => `
      <tr>
        <td><strong>${esc(c.name)}</strong></td>
        <td>${esc(c.subject)}</td>
        <td>${badge(c.status)}</td>
        <td>${new Date(c.created_at).toLocaleDateString()}</td>
        <td>
          <button class="btn btn-sm btn-primary" onclick="openSendModal(${c.id}, '${esc(c.name)}')">Send</button>
          <button class="btn btn-sm btn-ghost" onclick="editCampaign(${c.id})">Edit</button>
          <button class="btn btn-sm btn-danger" onclick="deleteCampaign(${c.id})">✕</button>
        </td>
      </tr>
    `).join('');
  } catch (e) {
    toast('Failed to load campaigns: ' + e.message, 'error');
  }
}

function openNewCampaignModal() {
  openModal(`
    <div class="modal-title">New Campaign</div>
    <div class="form-group">
      <label class="form-label">Campaign Name</label>
      <input id="c-name" class="form-control" placeholder="e.g. Roofers Austin Q3">
    </div>
    <div class="form-group">
      <label class="form-label">Subject Line</label>
      <input id="c-subject" class="form-control" value="Quick question about {{ business_name }}">
    </div>
    <div class="form-group">
      <label class="form-label">Email Body <small style="color:var(--text2)">— use {{ business_name }}, {{ decision_maker_name }}, {{ website }}</small></label>
      <textarea id="c-body" class="form-control" rows="10">Hi {{ decision_maker_name or 'there' }},

I came across {{ business_name }} and was really impressed by your work.

I wanted to reach out because I think we could help {{ business_name }} get more clients. Would you be open to a quick 15-minute call this week?

Best,
[Your Name]</textarea>
    </div>
    <div class="form-group">
      <label class="form-label">Delay between sends (seconds)</label>
      <input id="c-delay" class="form-control" type="number" value="60" min="10">
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancel</button>
      <button class="btn btn-primary" onclick="createCampaign()">Create</button>
    </div>
  `);
}

async function createCampaign() {
  try {
    await api('POST', '/api/campaigns', {
      name: document.getElementById('c-name').value,
      subject: document.getElementById('c-subject').value,
      body: document.getElementById('c-body').value,
      send_delay_seconds: parseInt(document.getElementById('c-delay').value),
    });
    document.querySelector('.modal-overlay')?.remove();
    toast('Campaign created', 'success');
    await loadCampaigns();
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

async function editCampaign(id) {
  const c = await api('GET', `/api/campaigns/${id}`);
  openModal(`
    <div class="modal-title">Edit Campaign</div>
    <div class="form-group">
      <label class="form-label">Campaign Name</label>
      <input id="c-name" class="form-control" value="${esc(c.name)}">
    </div>
    <div class="form-group">
      <label class="form-label">Subject</label>
      <input id="c-subject" class="form-control" value="${esc(c.subject)}">
    </div>
    <div class="form-group">
      <label class="form-label">Body</label>
      <textarea id="c-body" class="form-control" rows="10">${esc(c.body)}</textarea>
    </div>
    <div class="form-group">
      <label class="form-label">Delay (seconds)</label>
      <input id="c-delay" class="form-control" type="number" value="${c.send_delay_seconds}">
    </div>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancel</button>
      <button class="btn btn-primary" onclick="saveCampaign(${id})">Save</button>
    </div>
  `);
}

async function saveCampaign(id) {
  try {
    await api('PATCH', `/api/campaigns/${id}`, {
      name: document.getElementById('c-name').value,
      subject: document.getElementById('c-subject').value,
      body: document.getElementById('c-body').value,
      send_delay_seconds: parseInt(document.getElementById('c-delay').value),
    });
    document.querySelector('.modal-overlay')?.remove();
    toast('Campaign saved', 'success');
    await loadCampaigns();
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

async function deleteCampaign(id) {
  if (!confirm('Delete this campaign?')) return;
  try {
    await api('DELETE', `/api/campaigns/${id}`);
    toast('Campaign deleted', 'success');
    await loadCampaigns();
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

async function openSendModal(campaignId, campaignName) {
  const leads = await api('GET', '/api/leads?limit=200&email_status=found');
  openModal(`
    <div class="modal-title">Send Campaign — ${esc(campaignName)}</div>
    <p style="color:var(--text2);font-size:13px;margin-bottom:16px">
      This will send to leads that have an email and match the selected status.<br>
      Daily cap applies.
    </p>
    <div class="form-group">
      <label class="form-label">Send to leads with status</label>
      <select id="send-filter" class="form-control">
        <option value="new">new (never contacted)</option>
        <option value="">all leads with email</option>
      </select>
    </div>
    <p style="color:var(--text2);font-size:12px;margin-bottom:16px">
      ${leads.total} leads have emails — eligible count depends on status filter above.
    </p>
    <div class="modal-footer">
      <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancel</button>
      <button class="btn btn-success" onclick="sendCampaign(${campaignId})">Send Emails</button>
    </div>
  `);
}

async function sendCampaign(campaignId) {
  const filterStatus = document.getElementById('send-filter').value;
  try {
    const res = await api('POST', '/api/outreach/send', {
      campaign_id: campaignId,
      filter_status: filterStatus || null,
    });
    document.querySelector('.modal-overlay')?.remove();
    toast(`Sending ${res.queued} emails in background...`, 'success');
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

// ── Activity / Logs page ───────────────────────────────────────────────
async function initActivity() {
  await loadLogs();
}

async function loadLogs() {
  try {
    const data = await api('GET', '/api/outreach/logs?limit=100');
    const tbody = document.getElementById('logs-tbody');
    if (!data.logs.length) {
      tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><div class="icon">📭</div>No emails sent yet.</div></td></tr>`;
      return;
    }
    tbody.innerHTML = data.logs.map(l => `
      <tr>
        <td>${esc(l.to_email)}</td>
        <td>${esc(l.subject || '').substring(0, 60)}</td>
        <td>${badge(l.status)}</td>
        <td>${l.sent_at ? new Date(l.sent_at).toLocaleString() : '—'}</td>
        <td>${l.error_message ? `<small style="color:#f87171">${esc(l.error_message)}</small>` : '—'}</td>
      </tr>
    `).join('');
    document.getElementById('logs-count').textContent = `${data.total} emails total`;
  } catch (e) {
    toast('Failed to load logs: ' + e.message, 'error');
  }
}

function _openBulkProgressModal(jobId, title) {
  const overlay = openModal(`
    <div class="modal-title">${esc(title)}</div>
    <div style="margin-bottom:12px;">
      <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px;">
        <span id="bulk-current" style="color:var(--text2);font-style:italic">Starting…</span>
        <span id="bulk-pct" style="color:var(--accent);font-weight:700">0%</span>
      </div>
      <div style="background:var(--bg3);border-radius:6px;height:8px;overflow:hidden;">
        <div id="bulk-bar" style="height:100%;background:var(--accent);width:0%;transition:width 0.4s;border-radius:6px;"></div>
      </div>
      <div style="font-size:12px;color:var(--text2);margin-top:6px;" id="bulk-counts"></div>
    </div>
    <div id="bulk-log" style="
      background:var(--bg3);border:1px solid var(--border);border-radius:8px;
      padding:10px 14px;max-height:320px;overflow-y:auto;
      font-size:12px;font-family:'Courier New',monospace;line-height:1.8;
    "></div>
    <div class="modal-footer" style="margin-top:16px;">
      <button class="btn btn-ghost" id="bulk-close-btn" onclick="this.closest('.modal-overlay').remove()" disabled>Please wait…</button>
    </div>
  `);

  let lastLogLen = 0;
  const iv = setInterval(async () => {
    try {
      const job = await api('GET', `/api/leads/bulk-jobs/${jobId}`);
      const pct = job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;

      document.getElementById('bulk-bar').style.width = pct + '%';
      document.getElementById('bulk-pct').textContent = pct + '%';
      document.getElementById('bulk-current').textContent = job.current || (job.status === 'done' ? 'Complete!' : 'Processing…');
      document.getElementById('bulk-counts').textContent = `${job.done} / ${job.total} processed`;

      const logEl = document.getElementById('bulk-log');
      if (logEl && job.log.length > lastLogLen) {
        const newLines = job.log.slice(lastLogLen);
        newLines.forEach(line => {
          const span = document.createElement('div');
          span.textContent = line;
          span.style.color = line.startsWith('  ✓') ? 'var(--accent2)'
                           : line.startsWith('  —') ? 'var(--text2)'
                           : line.startsWith('❌') ? 'var(--danger)'
                           : line.startsWith('✅') ? 'var(--accent2)'
                           : 'var(--text)';
          logEl.appendChild(span);
        });
        logEl.scrollTop = logEl.scrollHeight;
        lastLogLen = job.log.length;
      }

      if (job.status === 'done' || job.status === 'failed') {
        clearInterval(iv);
        const closeBtn = document.getElementById('bulk-close-btn');
        if (closeBtn) { closeBtn.disabled = false; closeBtn.textContent = 'Close'; }
        await loadLeads();
      }
    } catch (_) { clearInterval(iv); }
  }, 2000);
}

// Polls refreshFn every 5s until lead count stabilises or timeout expires
function _pollUntilStable(refreshFn, timeoutMs = 180000) {
  let lastCount = -1;
  let stableRounds = 0;
  const start = Date.now();
  const iv = setInterval(async () => {
    if (Date.now() - start > timeoutMs) { clearInterval(iv); return; }
    try {
      const data = await api('GET', '/api/leads?limit=1');
      if (data.total === lastCount) {
        stableRounds++;
        if (stableRounds >= 3) { clearInterval(iv); return; }
      } else {
        stableRounds = 0;
        lastCount = data.total;
      }
      await refreshFn();
    } catch (_) { clearInterval(iv); }
  }, 5000);
}

// ── Lead Detail Panel ──────────────────────────────────────────────────
let _panelLeadId = null;
let _panelLead = null;

// Close on Escape key
document.addEventListener('keydown', e => { if (e.key === 'Escape' && _panelLeadId) closeLeadPanel(); });

async function openLeadPanel(leadId) {
  const alreadyOpen = _panelLeadId === leadId;
  _panelLeadId = leadId;

  document.getElementById('lead-panel-overlay').classList.add('open');
  document.getElementById('lead-panel').classList.add('open');

  // Highlight the active row
  document.querySelectorAll('tr.lead-row').forEach(r => r.classList.remove('active-row'));
  document.querySelectorAll('tr.lead-row').forEach(r => {
    if (r.getAttribute('onclick')?.includes(`(${leadId})`)) r.classList.add('active-row');
  });

  if (!alreadyOpen) {
    document.getElementById('lp-title').textContent = 'Loading...';
    document.getElementById('lp-sub').textContent = '';
    document.getElementById('lp-contacts').innerHTML = '<span class="lp-empty">Loading...</span>';
    document.getElementById('lp-email-display').innerHTML = '<span class="lp-empty">Loading...</span>';
    document.getElementById('lp-email-logs').innerHTML = '<span class="lp-empty">Loading...</span>';
  }

  try {
    const lead = await api('GET', `/api/leads/${leadId}`);
    _panelLead = lead;
    populateLeadPanel(lead);
  } catch (e) {
    document.getElementById('lp-title').textContent = 'Error loading lead';
  }
}

function closeLeadPanel() {
  document.getElementById('lead-panel-overlay').classList.remove('open');
  document.getElementById('lead-panel').classList.remove('open');
  document.querySelectorAll('tr.lead-row.active-row').forEach(r => r.classList.remove('active-row'));
  _panelLeadId = null;
  _panelLead = null;
}

function populateLeadPanel(lead) {
  // Header
  document.getElementById('lp-title').textContent = lead.business_name;
  document.getElementById('lp-sub').textContent = [lead.category, lead.address].filter(Boolean).join(' · ') || '—';
  document.getElementById('lp-status').value = lead.status || 'new';

  // Business info
  document.getElementById('lp-phone').innerHTML = lead.phone
    ? `<a href="tel:${esc(lead.phone)}" style="color:var(--accent)">${esc(lead.phone)}</a>` : '—';
  document.getElementById('lp-rating').textContent = lead.rating
    ? `⭐ ${lead.rating} (${lead.review_count || 0})` : '—';
  document.getElementById('lp-category').textContent = lead.category || '—';
  document.getElementById('lp-website').innerHTML = lead.website
    ? `<a href="${esc(lead.website)}" target="_blank" style="color:var(--accent)">${esc(lead.domain || lead.website)}</a>` : '—';
  document.getElementById('lp-address').textContent = lead.address || '—';

  // Maps link
  const mapsLink = document.getElementById('lp-maps-link');
  if (lead.maps_url) { mapsLink.href = lead.maps_url; }
  else { mapsLink.style.pointerEvents = 'none'; mapsLink.style.opacity = '0.4'; }

  // Contacts
  const contacts = lead.contacts?.length ? lead.contacts
    : lead.decision_maker_name ? [{ name: lead.decision_maker_name, title: lead.decision_maker_title }] : [];
  const contactsEl = document.getElementById('lp-contacts');
  contactsEl.innerHTML = contacts.length ? contacts.map(c => `
    <div class="contact-card">
      <div class="contact-card-left">
        <div class="contact-card-name">${esc(c.name)}</div>
        ${c.title ? `<div class="contact-card-title">${esc(c.title)}</div>` : ''}
        ${c.email ? `<div style="font-size:11px;color:var(--accent2);margin-top:2px">${esc(c.email)}</div>` : ''}
      </div>
      <div>${c.source ? sourceBadge(c.source) : ''}</div>
    </div>`).join('')
    : '<span class="lp-empty">None found yet — click Find Person above</span>';

  // Update person button label
  document.getElementById('lp-btn-person-label').textContent = contacts.length ? 'Re-search' : 'Find Person';

  // Email
  const emailEl = document.getElementById('lp-email-display');
  if (lead.decision_maker_email) {
    emailEl.innerHTML = `
      <div class="lp-email-found">
        <div>
          <div class="lp-email-address">${esc(lead.decision_maker_email)}</div>
          <div class="lp-email-meta">
            ${lead.email_source ? sourceBadge(lead.email_source) : ''}
            ${gradeBadge(lead.email_grade, lead.email_valid_reason)}
          </div>
        </div>
        <button class="btn btn-sm btn-ghost" onclick="navigator.clipboard.writeText('${esc(lead.decision_maker_email)}').then(()=>toast('Copied','success'))">Copy</button>
      </div>`;
    // Show compose section when email is known
    document.getElementById('lp-compose-section').style.display = '';
    document.getElementById('lp-btn-validate-label').textContent = lead.email_grade ? 'Re-validate' : 'Validate';
  } else {
    emailEl.innerHTML = `<span class="lp-empty">No email found yet — click Find Email above</span>`;
    document.getElementById('lp-compose-section').style.display = 'none';
    document.getElementById('lp-btn-validate-label').textContent = 'Validate';
  }

  // Show/hide email & validate buttons
  document.getElementById('lp-btn-email').style.opacity = lead.domain ? '1' : '0.4';
  document.getElementById('lp-btn-email').disabled = !lead.domain;
  document.getElementById('lp-btn-validate').style.opacity = lead.decision_maker_email ? '1' : '0.4';
  document.getElementById('lp-btn-validate').disabled = !lead.decision_maker_email;

  // Notes
  document.getElementById('lp-notes').value = lead.notes || '';

  // Email history
  const logsEl = document.getElementById('lp-email-logs');
  const logs = lead.email_logs || [];
  logsEl.innerHTML = logs.length ? logs.map(log => `
    <div class="email-log-item">
      <div class="email-log-subject">${esc(log.subject || '(no subject)')}</div>
      <div class="email-log-meta">
        ${esc(log.to_email)} &nbsp;·&nbsp; ${badge(log.status)} &nbsp;·&nbsp;
        ${log.sent_at ? new Date(log.sent_at).toLocaleString() : '—'}
      </div>
      ${log.error_message ? `<div style="font-size:11px;color:var(--danger);margin-top:2px">${esc(log.error_message)}</div>` : ''}
    </div>`).join('')
    : '<span class="lp-empty">No emails sent yet</span>';
}

async function updateLeadStatus(sel) {
  if (!_panelLeadId) return;
  try {
    await api('PATCH', `/api/leads/${_panelLeadId}`, { status: sel.value });
    // Update row badge in table without full reload
    const row = document.querySelector(`tr.lead-row.active-row td:nth-child(4)`);
    if (row) row.innerHTML = badge(sel.value);
    toast('Status updated', 'success');
  } catch (e) {
    toast('Failed to update status', 'error');
  }
}

async function saveLeadNotes() {
  if (!_panelLeadId) return;
  const btn = event?.target;
  if (btn) { btn.textContent = 'Saving...'; btn.disabled = true; }
  try {
    await api('PATCH', `/api/leads/${_panelLeadId}`, { notes: document.getElementById('lp-notes').value });
    toast('Notes saved', 'success');
  } catch (e) {
    toast('Failed to save notes', 'error');
  } finally {
    if (btn) { btn.textContent = 'Save Notes'; btn.disabled = false; }
  }
}

function _setPanelBtnLoading(btnId, labelId, loadingText) {
  const btn = document.getElementById(btnId);
  const label = document.getElementById(labelId);
  if (btn) btn.disabled = true;
  if (label) label.textContent = loadingText;
}

function _resetPanelBtn(btnId, labelId, defaultText) {
  const btn = document.getElementById(btnId);
  const label = document.getElementById(labelId);
  if (btn) btn.disabled = false;
  if (label) label.textContent = defaultText;
}

async function findPersonFromPanel() {
  if (!_panelLeadId) return;
  _setPanelBtnLoading('lp-btn-person', 'lp-btn-person-label', 'Searching...');
  try {
    const res = await api('POST', `/api/leads/${_panelLeadId}/find-person`);
    if (res.status === 'found') {
      const n = res.lead.contacts?.length || 1;
      toast(`Found ${n} contact${n > 1 ? 's' : ''} via ${res.source}`, 'success');
      const lead = await api('GET', `/api/leads/${_panelLeadId}`);
      populateLeadPanel(lead);
      _refreshTableRow(lead);
    } else {
      toast('No decision-maker found', 'error');
      _resetPanelBtn('lp-btn-person', 'lp-btn-person-label', 'Find Person');
    }
  } catch (e) {
    toast('Error: ' + e.message, 'error');
    _resetPanelBtn('lp-btn-person', 'lp-btn-person-label', 'Find Person');
  }
}

async function findEmailFromPanel() {
  if (!_panelLeadId) return;
  _setPanelBtnLoading('lp-btn-email', 'lp-btn-email-label', 'Searching...');
  try {
    const res = await api('POST', `/api/leads/${_panelLeadId}/find-email`);
    if (res.status === 'found') {
      toast(`Email found: ${res.lead.decision_maker_email}`, 'success');
    } else {
      toast('No email found', 'error');
    }
    const lead = await api('GET', `/api/leads/${_panelLeadId}`);
    populateLeadPanel(lead);
    _refreshTableRow(lead);
  } catch (e) {
    toast('Error: ' + e.message, 'error');
    _resetPanelBtn('lp-btn-email', 'lp-btn-email-label', 'Find Email');
  }
}

async function validateEmailFromPanel() {
  if (!_panelLeadId) return;
  _setPanelBtnLoading('lp-btn-validate', 'lp-btn-validate-label', 'Checking...');
  try {
    const res = await api('POST', `/api/leads/${_panelLeadId}/validate-email`);
    const icons = { valid: '✓', risky: '⚠', invalid: '✕' };
    toast(`${icons[res.grade] || ''} ${res.grade} — ${(res.reason || '').replace(/_/g, ' ')}`, res.grade === 'valid' ? 'success' : 'error');
    const lead = await api('GET', `/api/leads/${_panelLeadId}`);
    populateLeadPanel(lead);
    _refreshTableRow(lead);
  } catch (e) {
    toast('Error: ' + e.message, 'error');
    _resetPanelBtn('lp-btn-validate', 'lp-btn-validate-label', 'Validate');
  }
}

function toggleCompose() {
  const form = document.getElementById('lp-compose-form');
  const toggle = document.getElementById('lp-compose-toggle');
  const isOpen = form.style.display !== 'none';
  form.style.display = isOpen ? 'none' : '';
  toggle.textContent = isOpen ? 'Compose' : 'Cancel';
  if (!isOpen && _panelLead) {
    // Pre-fill subject with business name
    const subj = document.getElementById('lp-compose-subject');
    if (!subj.value) subj.value = `Quick question about ${_panelLead.business_name}`;
    document.getElementById('lp-compose-body').focus();
  }
}

async function sendEmailFromPanel() {
  if (!_panelLeadId || !_panelLead) return;
  const subject = document.getElementById('lp-compose-subject').value.trim();
  const body = document.getElementById('lp-compose-body').value.trim();
  const email = _panelLead.decision_maker_email;

  if (!subject || !body) { toast('Subject and body are required', 'error'); return; }
  if (!email) { toast('No email address found for this lead', 'error'); return; }

  const btn = document.getElementById('lp-send-btn');
  btn.disabled = true; btn.textContent = 'Sending...';

  try {
    await api('POST', '/api/outreach/send-single', {
      lead_id: _panelLeadId,
      to_email: email,
      subject,
      body,
    });
    toast('Email sent!', 'success');
    // Close compose, refresh logs
    toggleCompose();
    document.getElementById('lp-compose-subject').value = '';
    document.getElementById('lp-compose-body').value = '';
    const lead = await api('GET', `/api/leads/${_panelLeadId}`);
    _panelLead = lead;
    populateLeadPanel(lead);
    // Auto-update status to contacted
    if (lead.status === 'new') {
      await api('PATCH', `/api/leads/${_panelLeadId}`, { status: 'contacted' });
      document.getElementById('lp-status').value = 'contacted';
    }
  } catch (e) {
    toast('Failed to send: ' + e.message, 'error');
  } finally {
    btn.disabled = false; btn.textContent = 'Send Email';
  }
}

// Refresh a single table row without reloading all leads
function _refreshTableRow(lead) {
  const contact = lead.contacts?.[0] || (lead.decision_maker_name ? { name: lead.decision_maker_name, title: lead.decision_maker_title } : null);
  const row = document.querySelector('tr.lead-row.active-row');
  if (!row) return;
  const cells = row.querySelectorAll('td');
  if (cells[1]) cells[1].innerHTML = contact
    ? `<div style="font-weight:500">${esc(contact.name)}</div><div style="color:var(--text2);font-size:11px">${esc(contact.title || '')}</div>`
    : '<span style="color:var(--text2)">—</span>';
  if (cells[2]) cells[2].innerHTML = lead.decision_maker_email
    ? `<div class="email-addr">${esc(lead.decision_maker_email)}</div><div style="margin-top:2px">${gradeBadge(lead.email_grade, lead.email_valid_reason)}</div>`
    : badge(lead.email_status);
  if (cells[3]) cells[3].innerHTML = badge(lead.status);
}

// ── Utilities ──────────────────────────────────────────────────────────
function esc(str) {
  return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
