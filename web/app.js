const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let state = { companies: [], applications: [], stats: {}, stale: [], followups: [], settings: { stale_after_days: 14 } };
let currentFilter = 'all';
let currentModel = localStorage.getItem('job-agent-model') || 'qwen3:4b';
let editingApplicationId = null;
let focusedApplicationId = null;
let toastTimer;
let companyLogoFiles = {};
let companyLogoPromise;

const statusNames = { watching: 'Watching', saved: 'Saved', applied: 'Applied', screening: 'Screening', interview: 'Interview', offer: 'Offer', rejected: 'Not selected', withdrawn: 'Withdrawn' };
const activityNames = { role_added: 'Role added', status_change: 'Status change', note: 'Note', recruiter_contact: 'Recruiter contact', interview: 'Interview', follow_up: 'Follow-up' };
const terminal = new Set(['offer', 'rejected', 'withdrawn']);
const initials = (value = '') => value.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase();
const safeWebsite = value => {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch { return ''; }
};
const prettyDate = value => {
  if (!value) return 'Not recorded';
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
};
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);

function renderActivityTimeline(app) {
  const activities = app?.activities || [];
  $('#activity-count').textContent = activities.length;
  $('#activity-timeline').innerHTML = activities.length
    ? activities.map(activity => {
      const date = new Date(activity.occurred_at);
      const when = Number.isNaN(date.valueOf()) ? activity.occurred_at : date.toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
      return `<article class="timeline-entry"><span class="timeline-dot"></span><div class="timeline-entry-head"><strong>${esc(activityNames[activity.type] || activity.type)}</strong><time>${esc(when)}</time></div>${activity.status ? `<small class="timeline-status">${esc(statusNames[activity.status] || activity.status)}</small>` : ''}<p>${esc(activity.note)}</p></article>`;
    }).join('')
    : '<p class="timeline-empty">No activity yet. Log recruiter conversations, interviews, and follow-ups here.</p>';
}

function companyMark(name, className, index) {
  const filename = companyLogoFiles[name];
  if (!filename) return `<span class="${className} color-${index % 5}">${esc(initials(name))}</span>`;
  return `<span class="${className} brand-logo"><img src="/logos/${encodeURIComponent(filename)}" alt="" loading="lazy" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span class="logo-fallback color-${index % 5}" hidden>${esc(initials(name))}</span></span>`;
}

async function api(path, body) {
  const response = await fetch(path, { method: body === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Something went wrong');
  return data;
}

function notify(message, isError = false) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.className = `toast show${isError ? ' error' : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.className = 'toast'; }, 2800);
}

function openDialog(id) { $(`#${id}`).showModal(); }
function closeDialog(id) { $(`#${id}`).close(); }

function matchesFilter(app) {
  if (currentFilter === 'active') return !terminal.has(app.status) && !['watching', 'saved'].includes(app.status);
  if (currentFilter === 'watching') return ['watching', 'saved'].includes(app.status);
  if (currentFilter === 'closed') return terminal.has(app.status);
  if (currentFilter === 'interview') return app.status === 'interview';
  if (currentFilter === 'offer') return app.status === 'offer';
  if (currentFilter === 'followup') return state.followups.some(item => item.id === app.id);
  return true;
}

function setFilter(filter) {
  currentFilter = filter;
  $$('.filter-tab').forEach(tab => tab.classList.toggle('selected', tab.dataset.filter === filter));
  $$('[data-filter-card]').forEach(card => card.classList.toggle('is-active', card.dataset.filterCard === filter));
  render();
}

function focusApplication(applicationId) {
  const app = state.applications.find(item => item.id === applicationId);
  if (!app) return;
  focusedApplicationId = null;
  $('#status-filter').value = 'all';
  $('#search-input').value = `${app.company} ${app.role}`;
  setFilter('all');
  focusedApplicationId = app.id;
  $('#applications').scrollIntoView({ behavior: 'smooth', block: 'start' });
  requestAnimationFrame(() => {
    const row = $(`[data-application-id="${CSS.escape(applicationId)}"]`);
    if (row) {
      row.classList.add('is-focused');
      setTimeout(() => row.classList.remove('is-focused'), 1800);
    }
  });
}

function render() {
  $('#stat-active').textContent = state.stats.active || 0;
  $('#stat-interviews').textContent = state.stats.interviews || 0;
  $('#stat-offers').textContent = state.stats.offers || 0;
  $('#stat-followups').textContent = state.stats.needs_follow_up || 0;
  $('#nav-count').textContent = state.applications.length;
  $('#filter-all').textContent = state.applications.length;
  $('#threshold-value').textContent = `${state.settings.stale_after_days} days`;
  $('#settings-form [name="stale_after_days"]').value = state.settings.stale_after_days;

  const query = $('#search-input').value.trim().toLowerCase();
  const selectedStatus = $('#status-filter').value;
  const sortBy = $('#sort-applications').value;
  const shown = state.applications
    .filter(app => {
      const searchable = [app.company, app.role, app.status, statusNames[app.status], app.location, app.url, app.source, app.work_mode, app.salary, app.requirements, app.job_description, app.applied_date, app.follow_up_date, app.next_action, app.notes, ...(app.activities || []).map(activity => activity.note)].join(' ').toLowerCase();
      return matchesFilter(app) && (!focusedApplicationId || app.id === focusedApplicationId) && (selectedStatus === 'all' || app.status === selectedStatus) && searchable.includes(query);
    })
    .sort((a, b) => {
      if (sortBy === 'company') return a.company.localeCompare(b.company) || a.role.localeCompare(b.role);
      if (sortBy === 'follow-up') return (a.follow_up_date || '9999-12-31').localeCompare(b.follow_up_date || '9999-12-31') || a.company.localeCompare(b.company);
      if (sortBy === 'applied') return (b.applied_date || '').localeCompare(a.applied_date || '') || b.updated_at.localeCompare(a.updated_at);
      return b.updated_at.localeCompare(a.updated_at);
    });
  $('#application-result-count').textContent = `${shown.length} ${shown.length === 1 ? 'opportunity' : 'opportunities'}`;
  $('#application-list').innerHTML = shown.map((app, index) => {
    const roleMissing = !app.role || app.role.trim().toLowerCase() === 'not specified';
    const companyLine = roleMissing ? 'Role not specified' : `${esc(app.company)}${app.location ? ` · ${esc(app.location)}` : ''}`;
    const heading = roleMissing
      ? esc(app.company)
      : safeWebsite(app.url)
        ? `<a class="role-link" href="${esc(safeWebsite(app.url))}" target="_blank" rel="noopener noreferrer">${esc(app.role)} ↗</a>`
        : esc(app.role);
    return `
    <article class="app-row" data-application-id="${esc(app.id)}">
      <div class="company-cell">${companyMark(app.company, 'company-logo', index)}<div class="company-role"><strong>${heading}</strong><small>${companyLine}</small></div></div>
      <div class="app-meta applied-meta"><span>${app.match_score === null || app.match_score === undefined ? (app.applied_date ? 'APPLIED' : 'ADDED') : `MATCH · ${app.match_score}%`}</span>${esc(prettyDate(app.applied_date || app.created_at?.slice(0, 10)))}</div>
      <div><span class="status-pill status-${esc(app.status)}">${esc(statusNames[app.status] || app.status)}</span></div>
      <button class="row-menu" data-update="${esc(app.id)}" title="Update activity" aria-label="Update ${esc(app.company)} application">···</button>
    </article>`;
  }).join('');
  const hasApps = state.applications.length > 0;
  $('#empty-state').classList.toggle('hidden', shown.length > 0 || hasApps);
  if (hasApps && shown.length === 0) $('#application-list').innerHTML = '<div class="company-empty">No opportunities match this view. Try another filter or search.</div>';

  $('#company-list').innerHTML = state.companies.map((company, index) => {
    const count = state.applications.filter(app => app.company_id === company.id).length;
    const website = safeWebsite(company.website || '');
    return `<article class="company-chip"><button type="button" class="company-focus" data-company="${esc(company.name)}" aria-label="Show roles at ${esc(company.name)}">${companyMark(company.name, 'mini-logo', index)}<span class="company-chip-copy"><strong>${esc(company.name)}</strong><small>${count ? `${count} ${count === 1 ? 'role' : 'roles'} · View` : 'On your radar · View roles'}</small></span><span class="company-arrow">↗</span></button>${website ? `<a class="company-site" href="${esc(website)}" target="_blank" rel="noopener noreferrer" aria-label="Open ${esc(company.name)} career portal">Careers</a>` : '<span class="company-site-placeholder" aria-hidden="true"></span>'}</article>`;
  }).join('');
  $('#company-empty').classList.toggle('hidden', state.companies.length > 0);
  $('#company-suggestions').innerHTML = state.companies.map(c => `<option value="${esc(c.name)}"></option>`).join('');
  $('#saved-search-list').innerHTML = (state.saved_searches || []).map(item => `<span class="saved-search-chip"><button type="button" data-run-search="${esc(item.id)}">${esc(item.query)}</button><button type="button" data-delete-search="${esc(item.id)}" aria-label="Remove saved search">×</button></span>`).join('');
  $('#settings-form [name="matching_preferences"]').value = state.settings.matching_preferences || '';

  $('#followup-list').innerHTML = state.followups.slice(0, 4).map(app => {
    const timing = app.reminder_type === 'scheduled'
      ? (app.days_overdue === 0 ? 'Due today' : `${app.days_overdue}d overdue`)
      : `${app.days_since_activity}d quiet`;
    const label = app.reminder_type === 'scheduled' ? `Follow-up ${prettyDate(app.reminder_date)}` : 'No recent activity';
    return `<button type="button" class="followup-item" data-follow-up="${esc(app.id)}" aria-label="Open ${esc(app.role)} at ${esc(app.company)}"><span class="followup-monogram">${esc(initials(app.company))}</span><span class="followup-copy"><strong>${esc(app.company)} · ${esc(app.role)}</strong><small>${esc(app.next_action || label)}</small></span><span class="days-tag">${esc(timing)}</span></button>`;
  }).join('');
  $('#followup-empty').classList.toggle('hidden', state.followups.length > 0);
  $('#followup-list').classList.toggle('hidden', state.followups.length === 0);
}

async function refresh() {
  try {
    if (!companyLogoPromise) companyLogoPromise = api('/logos/manifest.json').catch(() => ({}));
    const [dashboard, logos] = await Promise.all([api('/api/dashboard'), companyLogoPromise]);
    state = dashboard;
    companyLogoFiles = logos;
    render();
  }
  catch (error) { notify(error.message, true); }
}

function addChatMessage(text, role) {
  const node = document.createElement('div');
  node.className = `chat-bubble ${role}`;
  node.textContent = text;
  $('#chat-history').append(node);
  $('#chat-history').scrollTop = $('#chat-history').scrollHeight;
  return node;
}

function showToolTrace(messageNode, tools) {
  if (!tools?.length) return;
  const trace = document.createElement('div');
  trace.className = 'tool-trace';
  trace.textContent = `MCP checked: ${tools.map(tool => tool.label || tool.name).join(' · ')}`;
  messageNode.after(trace);
  $('#chat-history').scrollTop = $('#chat-history').scrollHeight;
}

async function askAssistant(message) {
  if (!message.trim()) return;
  addChatMessage(message, 'user');
  const pending = addChatMessage('Thinking with your local tracker…', 'assistant');
  $('#chat-input').value = '';
  try {
    const result = await api('/api/chat', { message, model: currentModel });
    pending.textContent = result.reply || 'I could not create a response for that question.';
    showToolTrace(pending, result.tools_used);
  } catch (error) {
    pending.textContent = error.message;
  }
}

function setupEvents() {
  ['add-job-top', 'add-job-inline', 'empty-add-job'].forEach(id => $(`#${id}`).addEventListener('click', () => openDialog('job-dialog')));
  ['add-company-top', 'add-company-inline', 'empty-add-company'].forEach(id => $(`#${id}`).addEventListener('click', () => openDialog('company-dialog')));
  $('#settings-button').addEventListener('click', () => openDialog('settings-dialog'));
  $('#threshold-button').addEventListener('click', () => openDialog('settings-dialog'));
  $('#model-button').addEventListener('click', () => openDialog('model-dialog'));
  $$('[data-close]').forEach(button => button.addEventListener('click', () => closeDialog(button.dataset.close)));
  $$('.filter-tab').forEach(button => button.addEventListener('click', () => {
    focusedApplicationId = null;
    setFilter(button.dataset.filter);
  }));
  $$('[data-filter-card]').forEach(card => card.addEventListener('click', () => {
    focusedApplicationId = null;
    $('#status-filter').value = 'all';
    setFilter(card.dataset.filterCard);
    $('#applications').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
  $('#search-input').addEventListener('input', () => { focusedApplicationId = null; render(); });
  $('#status-filter').addEventListener('change', () => { focusedApplicationId = null; render(); });
  $('#sort-applications').addEventListener('change', render);
  $('#save-search-button').addEventListener('click', async () => {
    const query = $('#search-input').value.trim();
    if (!query) return notify('Type a search to save it', true);
    try { await api('/api/saved-searches', { query }); await refresh(); notify('Search saved locally'); }
    catch (error) { notify(error.message, true); }
  });
  $('#saved-search-list').addEventListener('click', async event => {
    const run = event.target.closest('[data-run-search]');
    const remove = event.target.closest('[data-delete-search]');
    if (run) { $('#search-input').value = (state.saved_searches || []).find(item => item.id === run.dataset.runSearch)?.query || ''; render(); }
    if (remove) { try { await api(`/api/saved-searches/${encodeURIComponent(remove.dataset.deleteSearch)}`, {}); await refresh(); } catch (error) { notify(error.message, true); } }
  });
  $('#company-list').addEventListener('click', event => {
    const button = event.target.closest('[data-company]');
    if (!button) return;
    focusedApplicationId = null;
    $('#status-filter').value = 'all';
    $('#search-input').value = button.dataset.company;
    setFilter('all');
    $('#applications').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  $('#followup-list').addEventListener('click', event => {
    const button = event.target.closest('[data-follow-up]');
    if (button) focusApplication(button.dataset.followUp);
  });

  $('#job-form').addEventListener('submit', async event => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const duplicate = await api('/api/duplicates', values);
      if (duplicate.matches.length && !confirm(`This looks like a saved opportunity: ${duplicate.matches.map(item => `${item.role} at ${item.company}`).join(', ')}. Save anyway?`)) return;
      values.allow_duplicate = duplicate.matches.length > 0;
      await api('/api/applications', values); event.currentTarget.reset(); $('#capture-status').textContent = 'Only reads the link you provide.'; closeDialog('job-dialog'); await refresh(); notify('Opportunity saved to your local tracker');
    }
    catch (error) { notify(error.message, true); }
  });
  $('#capture-link-button').addEventListener('click', async () => {
    const form = $('#job-form');
    const url = form.elements.url.value.trim();
    const description = $('#job-description-input').value.trim();
    const button = $('#capture-link-button'); button.disabled = true; button.textContent = 'Reading…';
    try {
      const result = await api('/api/capture-job', { url, description });
      $('#job-description-input').value = result.description;
      form.elements.captured_at.value = result.captured_at;
      form.elements.source.value = url ? 'Captured from job link' : 'Pasted job description';
      $('#capture-status').textContent = `Captured locally · ${new Date(result.captured_at).toLocaleString()}`;
      notify('Job details captured on this device');
    } catch (error) { notify(error.message, true); }
    finally { button.disabled = false; button.textContent = 'Read job page'; }
  });
  $('#extract-job-button').addEventListener('click', async () => {
    const description = $('#job-description-input').value.trim();
    if (!description) return notify('Paste a description or read a job page first', true);
    const button = $('#extract-job-button'); button.disabled = true; button.textContent = 'Extracting locally…';
    try {
      const result = await api('/api/extract-job', { description, model: currentModel });
      const form = $('#job-form');
      for (const field of ['company', 'role', 'location', 'work_mode', 'salary', 'requirements']) if (!form.elements[field].value.trim()) form.elements[field].value = result[field] || '';
      if (!form.elements.source.value) form.elements.source.value = 'Pasted job description';
      if (!form.elements.captured_at.value) form.elements.captured_at.value = new Date().toISOString().slice(0, 19);
      notify('Review the extracted fields, then save');
    } catch (error) { notify(error.message, true); }
    finally { button.disabled = false; button.textContent = 'Fill details with local AI'; }
  });
  $('#company-form').addEventListener('submit', async event => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try { await api('/api/companies', { name: values.name, website: values.website, roles_to_watch: values.roles.split(',').map(role => role.trim()).filter(Boolean) }); event.currentTarget.reset(); closeDialog('company-dialog'); await refresh(); notify('Company added to your watchlist'); }
    catch (error) { notify(error.message, true); }
  });
  $('#settings-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const form = new FormData(event.currentTarget);
      await api('/api/settings', { stale_after_days: Number(form.get('stale_after_days')) });
      await api('/api/preferences', { matching_preferences: form.get('matching_preferences') });
      closeDialog('settings-dialog'); await refresh(); notify('Preferences saved locally');
    }
    catch (error) { notify(error.message, true); }
  });
  $('#import-file').addEventListener('change', event => {
    $('#import-button').disabled = !event.currentTarget.files.length;
  });
  $('#csv-import-file').addEventListener('change', event => {
    $('#csv-import-button').disabled = !event.currentTarget.files.length;
  });
  $('#csv-import-button').addEventListener('click', async () => {
    const input = $('#csv-import-file');
    const file = input.files[0];
    if (!file) return;
    if (!confirm(`Import applications from ${file.name}? New records will be added; matching existing records will be skipped.`)) return;
    const button = $('#csv-import-button');
    button.disabled = true;
    button.textContent = 'Importing…';
    try {
      const response = await fetch('/api/import.csv', { method: 'POST', headers: { 'Content-Type': 'text/csv' }, body: file });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not import CSV');
      input.value = '';
      await refresh();
      notify(`Added ${result.imported.imported} opportunities; skipped ${result.imported.skipped} duplicates`);
    } catch (error) {
      notify(error.message, true);
    } finally {
      button.textContent = 'Import CSV';
      button.disabled = !input.files.length;
    }
  });
  $('#import-button').addEventListener('click', async () => {
    const input = $('#import-file');
    const file = input.files[0];
    if (!file) return;
    if (!confirm(`Import ${file.name}? This replaces the companies, applications, and activity currently in this tracker.`)) return;
    const button = $('#import-button');
    button.disabled = true;
    button.textContent = 'Importing…';
    try {
      const response = await fetch('/api/import', { method: 'POST', headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }, body: file });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not import workbook');
      input.value = '';
      await refresh();
      notify(`Imported ${result.imported.applications} roles and ${result.imported.companies} companies`);
    } catch (error) {
      notify(error.message, true);
    } finally {
      button.textContent = 'Restore Excel backup';
      button.disabled = !input.files.length;
    }
  });
  $('#model-form').addEventListener('submit', event => {
    event.preventDefault(); currentModel = new FormData(event.currentTarget).get('model'); localStorage.setItem('job-agent-model', currentModel); closeDialog('model-dialog'); notify(`Using ${currentModel}`);
  });
  $('#activity-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!editingApplicationId) return;
    const form = event.currentTarget;
    const changes = Object.fromEntries(['status', 'role', 'applied_date', 'follow_up_date', 'next_action', 'notes'].map(name => [name, form.elements[name].value]));
    try {
      await api(`/api/applications/${encodeURIComponent(editingApplicationId)}`, changes);
      closeDialog('activity-dialog');
      await refresh();
      notify('Opportunity updated');
    } catch (error) { notify(error.message, true); }
  });
  $('#log-activity-button').addEventListener('click', async () => {
    if (!editingApplicationId) return;
    const form = $('#activity-form');
    const note = form.elements.timeline_note.value.trim();
    if (!note) return notify('Add a note before logging this activity', true);
    try {
      await api(`/api/applications/${encodeURIComponent(editingApplicationId)}/activity`, { type: form.elements.timeline_type.value, note });
      form.elements.timeline_note.value = '';
      await refresh();
      renderActivityTimeline(state.applications.find(app => app.id === editingApplicationId));
      notify('Activity added to the timeline');
    } catch (error) { notify(error.message, true); }
  });
  $('#application-list').addEventListener('click', async event => {
    const button = event.target.closest('[data-update]');
    if (!button) return;
    const app = state.applications.find(item => item.id === button.dataset.update);
    if (!app) return;
    editingApplicationId = app.id;
    $('#activity-subtitle').textContent = `${app.role} · ${app.company}`;
    const form = $('#activity-form');
    for (const field of ['status', 'role', 'applied_date', 'follow_up_date', 'next_action', 'notes']) form.elements[field].value = app[field] || '';
    form.elements.timeline_type.value = 'note';
    form.elements.timeline_note.value = '';
    renderActivityTimeline(app);
    if (app.role?.trim().toLowerCase() === 'not specified') form.elements.role.value = '';
    openDialog('activity-dialog');
  });
  $('#chat-form').addEventListener('submit', event => { event.preventDefault(); const input = $('#chat-input'); askAssistant(input.value); });
  $$('.suggestion-chip').forEach(button => button.addEventListener('click', () => askAssistant(button.dataset.prompt)));
}

async function checkLocalModel() {
  try {
    const health = await api('/api/health');
    $('#mcp-status').textContent = health.mcp ? 'ready' : 'offline';
    $('#mcp-status').classList.toggle('connected', health.mcp);
    $('#model-status').textContent = health.ollama ? 'online' : 'offline';
    $('#model-status').classList.toggle('connected', health.ollama);
    $('#assistant-status').textContent = health.ollama ? 'Local AI • ready on this device' : 'Ollama not running • tracker still works';
    if (health.models.length) {
      $('#model-select').innerHTML = health.models.map(name => `<option value="${esc(name)}">${esc(name)}</option>`).join('');
      if (health.models.includes(currentModel)) $('#model-select').value = currentModel;
      else {
        currentModel = health.models[0];
        $('#model-select').value = currentModel;
        localStorage.setItem('job-agent-model', currentModel);
      }
    }
  } catch { $('#model-status').textContent = 'offline'; $('#mcp-status').textContent = 'offline'; }
}

$('#today-label').textContent = new Date().toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
setupEvents();
refresh();
checkLocalModel();
