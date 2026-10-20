const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let state = { companies: [], applications: [], stats: {}, stale: [], settings: { stale_after_days: 14 } };
let currentFilter = 'all';
let currentModel = localStorage.getItem('job-agent-model') || 'qwen3:4b';
let toastTimer;

const statusNames = { watching: 'Watching', saved: 'Saved', applied: 'Applied', screening: 'Screening', interview: 'Interview', offer: 'Offer', rejected: 'Not selected', withdrawn: 'Withdrawn' };
const terminal = new Set(['offer', 'rejected', 'withdrawn']);
const initials = (value = '') => value.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase();
const prettyDate = value => {
  if (!value) return 'Not recorded';
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
};
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);

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
  return true;
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
  const shown = state.applications.filter(app => matchesFilter(app) && `${app.company} ${app.role} ${app.status} ${app.location}`.toLowerCase().includes(query));
  $('#application-list').innerHTML = shown.map((app, index) => `
    <article class="app-row">
      <div class="company-cell"><span class="company-logo color-${index % 5}">${esc(initials(app.company))}</span><div class="company-role"><strong>${esc(app.role)}</strong><small>${esc(app.company)}${app.location ? ` · ${esc(app.location)}` : ''}</small></div></div>
      <div class="app-meta applied-meta"><span>${app.applied_date ? 'APPLIED' : 'ADDED'}</span>${esc(prettyDate(app.applied_date || app.created_at?.slice(0, 10)))}</div>
      <div><span class="status-pill status-${esc(app.status)}">${esc(statusNames[app.status] || app.status)}</span></div>
      <button class="row-menu" data-update="${esc(app.id)}" title="Update activity" aria-label="Update ${esc(app.role)}">···</button>
    </article>`).join('');
  const hasApps = state.applications.length > 0;
  $('#empty-state').classList.toggle('hidden', shown.length > 0 || hasApps);
  if (hasApps && shown.length === 0) $('#application-list').innerHTML = '<div class="company-empty">No opportunities match this view. Try another filter or search.</div>';

  $('#company-list').innerHTML = state.companies.map((company, index) => {
    const count = state.applications.filter(app => app.company_id === company.id).length;
    return `<div class="company-chip"><span class="mini-logo color-${index % 5}">${esc(initials(company.name))}</span><strong>${esc(company.name)}</strong><small>${count ? `${count} ${count === 1 ? 'role' : 'roles'}` : 'On your radar'}</small></div>`;
  }).join('');
  $('#company-empty').classList.toggle('hidden', state.companies.length > 0);
  $('#company-suggestions').innerHTML = state.companies.map(c => `<option value="${esc(c.name)}"></option>`).join('');

  $('#followup-list').innerHTML = state.stale.slice(0, 4).map(app => `<div class="followup-item"><span class="followup-monogram">${esc(initials(app.company))}</span><div class="followup-copy"><strong>${esc(app.company)} · ${esc(app.role)}</strong><small>${esc(app.next_action || 'Consider a thoughtful check-in')}</small></div><span class="days-tag">${app.days_since_activity}d</span></div>`).join('');
  $('#followup-empty').classList.toggle('hidden', state.stale.length > 0);
  $('#followup-list').classList.toggle('hidden', state.stale.length === 0);
}

async function refresh() {
  try { state = await api('/api/dashboard'); render(); }
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

async function askAssistant(message) {
  if (!message.trim()) return;
  addChatMessage(message, 'user');
  const pending = addChatMessage('Thinking with your local tracker…', 'assistant');
  $('#chat-input').value = '';
  try {
    const result = await api('/api/chat', { message, model: currentModel });
    pending.textContent = result.reply || 'I could not create a response for that question.';
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
    $$('.filter-tab').forEach(tab => tab.classList.remove('selected'));
    button.classList.add('selected'); currentFilter = button.dataset.filter; render();
  }));
  $('#search-input').addEventListener('input', render);

  $('#job-form').addEventListener('submit', async event => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try { await api('/api/applications', values); event.currentTarget.reset(); closeDialog('job-dialog'); await refresh(); notify('Opportunity saved to your local tracker'); }
    catch (error) { notify(error.message, true); }
  });
  $('#company-form').addEventListener('submit', async event => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try { await api('/api/companies', { name: values.name, website: values.website, roles_to_watch: values.roles.split(',').map(role => role.trim()).filter(Boolean) }); event.currentTarget.reset(); closeDialog('company-dialog'); await refresh(); notify('Company added to your watchlist'); }
    catch (error) { notify(error.message, true); }
  });
  $('#settings-form').addEventListener('submit', async event => {
    event.preventDefault();
    try { await api('/api/settings', { stale_after_days: Number(new FormData(event.currentTarget).get('stale_after_days')) }); closeDialog('settings-dialog'); await refresh(); notify('Reminder setting saved'); }
    catch (error) { notify(error.message, true); }
  });
  $('#model-form').addEventListener('submit', event => {
    event.preventDefault(); currentModel = new FormData(event.currentTarget).get('model'); localStorage.setItem('job-agent-model', currentModel); closeDialog('model-dialog'); notify(`Using ${currentModel}`);
  });
  $('#application-list').addEventListener('click', async event => {
    const button = event.target.closest('[data-update]');
    if (!button) return;
    const app = state.applications.find(item => item.id === button.dataset.update);
    const status = prompt(`Update status for ${app.role} at ${app.company}:\n${Object.entries(statusNames).map(([key, label]) => `${key}: ${label}`).join('\n')}`, app.status);
    if (!status) return;
    const normalized = status.toLowerCase().trim();
    if (!statusNames[normalized]) return notify('That status is not recognized', true);
    const note = prompt('Optional: add a short activity note', '');
    try { await api(`/api/applications/${encodeURIComponent(app.id)}`, { status: normalized, last_activity_date: new Date().toISOString().slice(0, 10), ...(note ? { notes: `${app.notes ? `${app.notes}\n` : ''}${new Date().toLocaleDateString()}: ${note}` } : {}) }); await refresh(); notify('Application activity updated'); }
    catch (error) { notify(error.message, true); }
  });
  $('#chat-form').addEventListener('submit', event => { event.preventDefault(); const input = $('#chat-input'); askAssistant(input.value); });
  $$('.suggestion-chip').forEach(button => button.addEventListener('click', () => askAssistant(button.dataset.prompt)));
}

async function checkLocalModel() {
  try {
    const health = await api('/api/health');
    $('#model-status').textContent = health.ollama ? 'online' : 'offline';
    $('#model-status').classList.toggle('connected', health.ollama);
    $('#assistant-status').textContent = health.ollama ? 'Local AI • ready on this device' : 'Ollama not running • tracker still works';
    if (health.models.length) {
      $('#model-select').innerHTML = health.models.map(name => `<option value="${esc(name)}">${esc(name)}</option>`).join('');
      if (health.models.includes(currentModel)) $('#model-select').value = currentModel;
      else currentModel = health.models[0];
    }
  } catch { $('#model-status').textContent = 'offline'; }
}

$('#today-label').textContent = new Date().toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
setupEvents();
refresh();
checkLocalModel();
