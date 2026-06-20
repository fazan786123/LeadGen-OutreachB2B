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
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// ── Badge ──────────────────────────────────────────────────────────────
function badge(val, prefix = '') {
  if (!val) return '<span class="badge badge-not_searched">—</span>';
  const cls = (prefix + val).replace(/\s/g, '_').toLowerCase();
  return `<span class="badge badge-${cls}">${val}</span>`;
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

// ── Dashboard page ─────────────────────────────────────────────────────
async function initDashboard() {
  try {
    const data = await api('GET', '/api/dashboard/stats');
    const L = data.leads, E = data.emails;

    document.getElementById('stat-total-leads').textContent = L.total;
    document.getElementById('stat-with-email').textContent = L.with_email;
    document.getElementById('stat-contacted').textContent = L.contacted;
    document.getElementById('stat-replied').textContent = L.replied;
    document.getElementById('stat-converted').textContent = L.converted;
    document.getElementById('stat-sent-today').textContent = E.sent_today;
    document.getElementById('stat-total-sent').textContent = E.total_sent;
    document.getElementById('stat-failed').textContent = E.total_failed;

    // 7-day chart
    const chart = data.charts.emails_last_7_days;
    const max = Math.max(...chart.map(d => d.sent), 1);
    const bars = document.getElementById('chart-bars');
    const labels = document.getElementById('chart-labels');
    bars.innerHTML = '';
    labels.innerHTML = '';
    chart.forEach(d => {
      const pct = Math.round((d.sent / max) * 100);
      bars.innerHTML += `<div class="chart-bar" style="height:${pct}%" data-val="${d.sent}"></div>`;
      labels.innerHTML += `<div class="chart-label">${d.date}</div>`;
    });
  } catch (e) {
    toast('Failed to load stats: ' + e.message, 'error');
  }
}

// ── Leads page ────────────────────────────────────────────────────────
let leadsPage = { skip: 0, limit: 50 };

async function initLeads() {
  await loadLeads();

  document.getElementById('search-input').addEventListener('input', debounce(loadLeads, 400));
  document.getElementById('filter-status').addEventListener('change', loadLeads);
  document.getElementById('filter-email-status').addEventListener('change', loadLeads);
  document.getElementById('filter-grade')?.addEventListener('change', loadLeads);
}

async function loadLeads() {
  const search = document.getElementById('search-input')?.value || '';
  const status = document.getElementById('filter-status')?.value || '';
  const emailStatus = document.getElementById('filter-email-status')?.value || '';
  const grade = document.getElementById('filter-grade')?.value || '';

  const params = new URLSearchParams({ skip: leadsPage.skip, limit: leadsPage.limit });
  if (search) params.set('search', search);
  if (status) params.set('status', status);
  if (emailStatus) params.set('email_status', emailStatus);
  if (grade) params.set('email_grade', grade);

  try {
    const data = await api('GET', `/api/leads?${params}`);
    renderLeadsTable(data.leads);
    document.getElementById('leads-count').textContent = `${data.total} leads`;
  } catch (e) {
    toast('Failed to load leads: ' + e.message, 'error');
  }
}

function renderLeadsTable(leads) {
  const tbody = document.getElementById('leads-tbody');
  if (!leads.length) {
    tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state"><div class="icon">🔍</div>No leads yet. Run a scrape to get started.</div></td></tr>`;
    return;
  }
  tbody.innerHTML = leads.map(l => `
    <tr style="${l.email_grade === 'invalid' ? 'opacity:0.5' : ''}">
      <td><strong>${esc(l.business_name)}</strong><br><small style="color:var(--text2)">${esc(l.address || '')}</small></td>
      <td>${l.website ? `<a href="${esc(l.website)}" target="_blank" style="color:var(--accent)">${esc(l.domain || l.website)}</a>` : '—'}</td>
      <td>${badge(l.email_status)}</td>
      <td>${l.decision_maker_email ? `<strong>${esc(l.decision_maker_name || '')}</strong><br><small>${esc(l.decision_maker_email)}</small>` : '—'}</td>
      <td>${gradeBadge(l.email_grade, l.email_valid_reason)}</td>
      <td>${badge(l.status)}</td>
      <td>${l.rating ? '⭐ ' + l.rating : '—'}</td>
      <td>
        ${!l.decision_maker_email && l.domain ? `<button class="btn btn-sm btn-primary" onclick="findEmail(${l.id})">Find Email</button> ` : ''}
        ${l.decision_maker_email && !l.email_grade ? `<button class="btn btn-sm btn-warn" onclick="validateEmail(${l.id})">Validate</button> ` : ''}
        <button class="btn btn-sm btn-ghost" onclick="editLead(${l.id})">Edit</button>
        <button class="btn btn-sm btn-danger" onclick="deleteLead(${l.id})">✕</button>
      </td>
    </tr>
  `).join('');
}

async function findEmail(leadId) {
  try {
    toast('Searching Hunter.io...', 'info');
    const res = await api('POST', `/api/leads/${leadId}/find-email`);
    toast(res.status === 'found' ? `Found: ${res.lead.decision_maker_email}` : 'No email found', res.status === 'found' ? 'success' : 'error');
    await loadLeads();
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
}

async function deleteLead(leadId) {
  if (!confirm('Delete this lead?')) return;
  try {
    await api('DELETE', `/api/leads/${leadId}`);
    toast('Lead deleted', 'success');
    await loadLeads();
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  }
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
      <button id="mode-deep" class="btn btn-ghost btn-sm" onclick="setGridMode('deep')">🔥 Deep Sweep <small>(216 viewports)</small></button>
    </div>
    <p id="mode-desc" style="color:var(--text2);font-size:13px;margin-bottom:16px">
      36 viewport rectangles tiling the area — up to <strong style="color:var(--text)">720 raw results</strong>.
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
        <option value="2000" selected>2 km — standard city</option>
        <option value="3000">3 km — large city</option>
        <option value="5000">5 km — metro area</option>
        <option value="10000">10 km — entire region</option>
      </select>
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
    ? '6 sweep centers × 36 viewports = 216 total — up to <strong style="color:var(--text)">4,320 raw results</strong>. Takes longer.'
    : '36 viewport rectangles tiling the area — up to <strong style="color:var(--text)">720 raw results</strong>.';
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
    toast('Queuing bulk email search...', 'info');
    const res = await api('POST', '/api/leads/find-emails-bulk');
    toast(res.message, 'success');
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

// ── Utilities ──────────────────────────────────────────────────────────
function esc(str) {
  return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
