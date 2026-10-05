const ROLE_ACCESS = {
  admin: ['dashboard', 'accounts', 'promises', 'activities', 'tasks', 'reports', 'strategy', 'clients', 'users', 'audit'],
  supervisor: ['dashboard', 'accounts', 'promises', 'activities', 'tasks', 'reports', 'strategy', 'clients'],
  collector: ['dashboard', 'accounts', 'promises', 'activities', 'tasks', 'reports'],
  client: ['dashboard', 'accounts', 'reports', 'clients'],
  management: ['dashboard', 'reports', 'strategy']
};

const state = {
  accounts: [],
  promises: [],
  activities: [],
  clients: [],
  users: [],
  auditLogs: [],
  tasks: [],
  payments: [],
  collectors: [],
  metrics: {},
  activeView: 'dashboard',
  currentUser: null
};

function getPriority(daysPastDue) {
  if (daysPastDue >= 60) return 'High';
  if (daysPastDue >= 30) return 'Medium';
  return 'Low';
}

function formatCurrency(value) {
  return `₱${Number(value).toLocaleString()}`;
}

function escapeHTML(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[character]);
}

function showNotice(message, isError = false) {
  const notice = document.getElementById('appNotice');
  notice.textContent = message;
  notice.classList.toggle('error', isError);
}

async function requestJSON(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message || `Request failed (${response.status})`);
  return payload;
}

function getAccessForRole(role) {
  return ROLE_ACCESS[role] || [];
}

function updateCurrentUser(displayName, role) {
  state.currentUser = {
    username: displayName || 'admin',
    role: role || 'admin',
    fullName: displayName || 'System Administrator'
  };
}

function getDefaultView() {
  const allowed = getAccessForRole(state.currentUser?.role || '');
  return allowed.includes(state.activeView) ? state.activeView : allowed[0];
}

function applyRoleAccess() {
  const currentRole = state.currentUser?.role || '';
  const allowedViews = getAccessForRole(currentRole);

  document.querySelectorAll('.nav-item').forEach((button) => {
    const visible = allowedViews.includes(button.dataset.view);
    button.style.display = visible ? 'block' : 'none';
    button.classList.toggle('active', visible && button.dataset.view === state.activeView);
  });

  document.querySelectorAll('.page-view').forEach((section) => {
    const key = section.id.replace('View', '');
    const visible = allowedViews.includes(key);
    const active = visible && key === state.activeView;
    section.style.display = active ? 'block' : 'none';
    section.classList.toggle('active', active);
  });

  const currentUserEl = document.getElementById('currentUser');
  if (currentUserEl) {
    const suffix = currentRole.charAt(0).toUpperCase() + currentRole.slice(1);
    currentUserEl.textContent = `${state.currentUser?.fullName || 'System Administrator'} (${suffix})`;
  }

  const nextView = getDefaultView();
  if (nextView && state.activeView !== nextView) {
    setActiveView(nextView);
  }
}

function setActiveView(viewName) {
  const allowed = getAccessForRole(state.currentUser?.role || '');
  const nextView = allowed.includes(viewName) ? viewName : allowed[0];
  state.activeView = nextView;

  const viewMap = {
    dashboard: 'CollectFlow Dashboard',
    accounts: 'Account Management',
    promises: 'Promise to Pay Center',
    activities: 'Collection Activity Timeline',
    tasks: 'Follow-up Queue',
    reports: 'Portfolio Reports',
    clients: 'Client Portfolio Manager',
    strategy: 'Strategy Simulation',
    users: 'User Administration',
    audit: 'Audit Trail'
  };

  document.querySelectorAll('.nav-item').forEach((button) => {
    button.classList.toggle('active', button.dataset.view === nextView);
  });

  document.querySelectorAll('.page-view').forEach((section) => {
    const key = section.id.replace('View', '');
    const visible = allowed.includes(key);
    const active = visible && key === nextView;
    section.style.display = active ? 'block' : 'none';
    section.classList.toggle('active', active);
  });

  document.getElementById('pageTitle').textContent = viewMap[nextView] || 'CollectFlow';
  document.getElementById('sectionLabel').textContent = viewMap[nextView] || 'Dashboard';
  if (nextView === 'users') loadAdminUsers();
  if (nextView === 'audit') loadAuditLogs();
}

async function loadDashboard() {
  const role = state.currentUser?.role || '';
  const allowed = getAccessForRole(role);
  const requests = [
    requestJSON('/api/metrics').then((payload) => { state.metrics = payload; }),
    requestJSON('/api/accounts').then((payload) => { state.accounts = payload.accounts || []; })
  ];
  if (allowed.includes('promises') || role === 'management') {
    requests.push(requestJSON('/api/promises').then((payload) => { state.promises = payload.promises || []; }));
  } else {
    state.promises = [];
  }
  if (allowed.includes('activities') || role === 'client') {
    requests.push(requestJSON('/api/activities').then((payload) => { state.activities = payload.activities || []; }));
  } else {
    state.activities = [];
  }
  if (allowed.includes('clients')) {
    requests.push(requestJSON('/api/clients').then((payload) => { state.clients = payload.clients || []; }));
  } else {
    state.clients = [];
  }
  if (allowed.includes('tasks')) {
    requests.push(requestJSON('/api/tasks').then((payload) => { state.tasks = payload.tasks || []; }));
  } else {
    state.tasks = [];
  }
  if (allowed.includes('payments')) {
    requests.push(requestJSON('/api/payments').then((payload) => { state.payments = payload.payments || []; }));
  } else {
    state.payments = [];
  }
  if (['admin', 'supervisor'].includes(role)) {
    requests.push(requestJSON('/api/collectors').then((payload) => { state.collectors = payload.collectors || []; }));
  } else {
    state.collectors = role === 'collector' ? [{ fullName: state.currentUser.fullName }] : [];
  }
  await Promise.all(requests);

  renderStats();
  renderQueueTable();
  renderActivities();
  renderFullActivities();
  renderPromises();
  renderPromiseOptions();
  renderAccountList();
  renderTasks();
  renderPayments();
  renderClientList();
  renderReports();
  populateClientOptions();
  populateCollectorOptions();
  document.getElementById('queueSummary').textContent = `${state.accounts.length} accounts`;
  document.getElementById('queueStatus').textContent = state.metrics.queueStatus || 'Needs action';
  configureRoleControls();
}

function configureRoleControls() {
  const role = state.currentUser?.role;
  const writeAccount = ['admin', 'supervisor'].includes(role);
  const accountForm = document.getElementById('accountForm');
  accountForm.closest('.form-panel').hidden = !writeAccount;
  document.getElementById('clientForm').closest('.form-panel').hidden = !writeAccount;
  document.getElementById('taskAssignmentField').hidden = false;
  document.getElementById('taskCollector').value = state.currentUser?.fullName || '';
  const hasCollectors = state.collectors.length > 0;
  accountForm.querySelector('button[type="submit"]').disabled = !hasCollectors;
  document.getElementById('collectorSetupHint').textContent = hasCollectors
    ? ''
    : 'Create an active Collector user in User Administration before adding or assigning accounts.';
  const taskCollector = document.getElementById('taskCollector');
  const isCollector = role === 'collector';
  taskCollector.disabled = isCollector;
  taskCollector.required = !isCollector;
  document.getElementById('taskCollectorLabel').textContent = isCollector ? 'Assigned to me' : 'Assign to';
  const hasAssignedAccounts = state.accounts.length > 0;
  document.getElementById('taskForm').querySelector('button[type="submit"]').disabled = !hasAssignedAccounts || (!isCollector && !hasCollectors);
  document.getElementById('taskAccountHint').textContent = hasAssignedAccounts || !isCollector
    ? ''
    : 'No accounts are assigned to you yet. Ask a Supervisor to assign an account before creating its follow-up.';
  document.getElementById('taskSetupHint').textContent = isCollector || hasCollectors
    ? ''
    : 'Create an active Collector user before assigning follow-up tasks.';
}

function renderStats() {
  const { totalAccounts, totalBalance, overdueCount, recoveryRate, amountCollectedMonth, activePromises, brokenPromises } = state.metrics;
  const stats = [
    { label: 'Total Accounts', value: Number(totalAccounts || 0).toLocaleString() },
    { label: 'Outstanding', value: formatCurrency(totalBalance || 0) },
    { label: 'Overdue', value: String(overdueCount || 0) },
    { label: 'Collected this month', value: formatCurrency(amountCollectedMonth || 0) },
    { label: 'Active promises', value: Number(activePromises || 0).toLocaleString() },
    { label: 'Broken promises', value: Number(brokenPromises || 0).toLocaleString() },
    { label: 'Aging exposure', value: `${recoveryRate || 0}%` }
  ];

  document.getElementById('statsGrid').innerHTML = stats.map((item) => `
    <div class="stat-card">
      <div class="meta">
        <span>${item.label}</span>
      </div>
      <h3>${item.value}</h3>
      <small>Current portfolio</small>
    </div>
  `).join('');
}

function renderQueueTable() {
  const sorted = [...state.accounts].sort((a, b) => b.daysPastDue - a.daysPastDue);
  const table = document.getElementById('queueTable');

  table.innerHTML = sorted.map((account) => {
    const priority = getPriority(account.daysPastDue);
    return `
      <tr>
        <td>${escapeHTML(account.accountNumber)}</td>
        <td>${escapeHTML(account.client)}</td>
        <td>${escapeHTML(account.collector)}</td>
        <td>${account.daysPastDue}</td>
        <td><span class="priority ${priority.toLowerCase()}">${priority}</span></td>
        <td><span class="status-pill">${escapeHTML(account.status)}</span></td>
      </tr>
    `;
  }).join('');
}

function renderActivities() {
  const list = document.getElementById('activityList');
  list.innerHTML = (state.activities || []).map((item) => `
    <li>
      <strong>${escapeHTML(item.title)}</strong>
      <span>${escapeHTML(item.detail)}</span>
    </li>
  `).join('');
}

function renderPromiseOptions() {
  const accountOptions = state.accounts.map((account) =>
    `<option value="${escapeHTML(account.accountNumber)}">${escapeHTML(account.accountNumber)}</option>`
  ).join('');
  ['promiseAccount', 'paymentAccount', 'activityAccount', 'taskAccount', 'summaryAccount'].forEach((id) => {
    const select = document.getElementById(id);
    if (select) select.innerHTML = accountOptions;
  });
  const paymentPromise = document.getElementById('paymentPromise');
  if (paymentPromise) {
    paymentPromise.innerHTML = '<option value="">No linked promise</option>' + state.promises.map((promise) =>
      `<option value="${Number(promise.id)}">${escapeHTML(promise.accountNumber)} · ${formatCurrency(promise.amount)}</option>`
    ).join('');
  }
  const paymentAccount = document.getElementById('paymentAccount');
  if (paymentAccount) paymentAccount.dispatchEvent(new Event('change'));
}

function renderPromises() {
  const list = document.getElementById('promisesList');
  if (list) {
    list.innerHTML = (state.promises || []).slice(0, 4).map((promise) => `
      <div class="promise-item">
        <div>
          <strong>${escapeHTML(promise.accountNumber)}</strong>
          <small>Due ${escapeHTML(promise.dueDate)}</small>
        </div>
        <strong>${formatCurrency(promise.amount)}</strong>
      </div>
    `).join('');
  }

  const table = document.getElementById('promiseTable');
  if (table) {
    table.innerHTML = (state.promises || []).map((promise) => `
      <tr>
        <td>${escapeHTML(promise.accountNumber)}</td>
        <td>${formatCurrency(promise.amount)}</td>
        <td>${escapeHTML(promise.dueDate)}</td>
        <td>${escapeHTML(promise.paymentMethod || 'Unspecified')}</td>
        <td><span class="status-pill ${promise.status === 'Broken' ? 'inactive' : 'success'}">${escapeHTML(promise.status)}</span></td>
        <td class="action-cell">
          ${['admin', 'supervisor', 'collector'].includes(state.currentUser?.role) && promise.status !== 'Fulfilled' ? `
            <select data-promise-status="${Number(promise.id)}" aria-label="New promise status">
              ${['Upcoming', 'Due', 'Fulfilled', 'Broken'].map((status) => `<option ${status === promise.status ? 'selected' : ''}>${status}</option>`).join('')}
            </select>
            <button class="table-action" type="button" data-save-promise="${Number(promise.id)}">Save</button>
          ` : ''}
          ${state.currentUser?.role === 'admin' ? `<button class="table-action danger-action" type="button" data-delete-type="promises" data-delete-id="${Number(promise.id)}">Delete</button>` : ''}
        </td>
      </tr>
    `).join('');
  }
}

function renderAccountList() {
  const target = document.getElementById('accountsTable');
  if (!target) return;

  target.innerHTML = state.accounts.map((account) => `
    <tr>
      <td><strong>${escapeHTML(account.accountNumber)}</strong></td>
      <td>${escapeHTML(account.client)}</td>
      <td>${formatCurrency(account.balance)}</td>
      <td>${Number(account.daysPastDue)}</td>
      <td>${escapeHTML(account.collector)}</td>
      <td><span class="status-pill">${escapeHTML(account.status)}</span></td>
      <td class="action-cell">
        ${['admin', 'supervisor', 'collector'].includes(state.currentUser?.role) ? `<button type="button" class="table-action" data-edit-account="${Number(account.id)}">Update</button>` : ''}
        ${state.currentUser?.role === 'admin' ? `<button type="button" class="table-action danger-action" data-delete-type="accounts" data-delete-id="${Number(account.id)}">Delete</button>` : ''}
      </td>
    </tr>
  `).join('');
}

function renderClientList() {
  const target = document.getElementById('clientList');
  if (!target) return;

  target.innerHTML = (state.clients || []).map((client) => `
    <div class="list-item">
      <div>
        <strong>${escapeHTML(client.name)}</strong>
        <small>${escapeHTML(client.industry)}</small>
      </div>
      <div class="list-meta">
        <span>${client.totalAccounts || 0} accounts</span>
        ${state.currentUser?.role === 'admin' ? `<button class="table-action danger-action" type="button" data-delete-type="clients" data-delete-id="${Number(client.id)}">Delete</button>` : ''}
      </div>
    </div>
  `).join('');
}

function renderFullActivities() {
  const target = document.getElementById('fullActivityList');
  if (!target) return;
  target.innerHTML = state.activities.map((activity) => `
    <li>
      <strong>${escapeHTML(activity.title)} · ${escapeHTML(activity.accountNumber || '')}</strong>
      <span>${escapeHTML(activity.detail)}</span>
      ${state.currentUser?.role === 'admin' ? `<button class="table-action danger-action" type="button" data-delete-type="activities" data-delete-id="${Number(activity.id)}">Delete</button>` : ''}
    </li>
  `).join('');
}

function renderTasks() {
  const target = document.getElementById('tasksTable');
  if (!target) return;
  target.innerHTML = state.tasks.map((task) => `
    <tr>
      <td>${escapeHTML(task.accountNumber)}</td>
      <td>${escapeHTML(task.title)}</td>
      <td>${escapeHTML(task.assignedTo)}</td>
      <td>${escapeHTML(task.dueDate)}</td>
      <td><span class="status-pill ${task.status === 'Completed' ? 'success' : ''}">${escapeHTML(task.status)}</span></td>
      <td class="action-cell">
        ${task.status !== 'Completed' ? `<button class="table-action" type="button" data-task-complete="${Number(task.id)}">Complete</button>` : ''}
        ${state.currentUser?.role === 'admin' ? `<button class="table-action danger-action" type="button" data-delete-type="tasks" data-delete-id="${Number(task.id)}">Delete</button>` : ''}
      </td>
    </tr>
  `).join('');
}

function renderPayments() {
  const target = document.getElementById('paymentsTable');
  if (!target) return;
  target.innerHTML = state.payments.map((payment) => `
    <tr>
      <td>${escapeHTML(payment.accountNumber)}</td>
      <td>${formatCurrency(payment.amount)}</td>
      <td>${escapeHTML(payment.paymentMethod)}</td>
      <td>${escapeHTML(payment.reference || '—')}</td>
      <td>${escapeHTML(new Date(payment.paidAt).toLocaleString())}</td>
      <td>${state.currentUser?.role === 'admin' ? `<button class="table-action danger-action" type="button" data-delete-type="payments" data-delete-id="${Number(payment.id)}">Delete</button>` : ''}</td>
    </tr>
  `).join('');
}

function renderReports() {
  const reportCards = document.getElementById('reportCards');
  if (!reportCards) return;

  const cards = [
    { label: 'Accounts at Risk', value: state.accounts.filter((a) => a.daysPastDue > 30).length },
    { label: 'Avg. DPD', value: Math.round((state.accounts.reduce((sum, a) => sum + a.daysPastDue, 0) || 0) / Math.max(state.accounts.length, 1)) },
    { label: 'Collectors', value: new Set(state.accounts.map((a) => a.collector)).size },
    { label: 'Collected this month', value: formatCurrency(state.metrics.amountCollectedMonth || 0) },
    { label: 'Active promises', value: state.metrics.activePromises || 0 },
    { label: 'Broken promises', value: state.metrics.brokenPromises || 0 }
  ];

  reportCards.innerHTML = cards.map((item) => `
    <div class="stat-card">
      <div class="meta">
        <span>${item.label}</span>
      </div>
      <h3>${item.value}</h3>
      <small>Operational insight</small>
    </div>
  `).join('');

  const reportList = document.getElementById('reportList');
  if (reportList) {
    const summaries = [
      `${state.accounts.length} active accounts under review this week.`,
      `${state.promises.length} promises are currently tracked for upcoming follow-ups.`,
      `${state.metrics.overdueCount || 0} accounts are above 30 days overdue.`,
      `Collector productivity is monitored by account volume and priority aging.`
    ];

    reportList.innerHTML = summaries.map((item) => `<li><strong>${item}</strong></li>`).join('');
  }

  const summaryForm = document.getElementById('summaryForm');
  if (summaryForm) {
    summaryForm.hidden = !['admin', 'supervisor', 'collector'].includes(state.currentUser?.role);
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const username = document.getElementById('loginUsername').value.trim();
  const password = document.getElementById('loginPassword').value;
  const errorMessage = document.getElementById('loginError');
  errorMessage.textContent = '';

  try {
    const payload = await requestJSON('/api/login', {
      method: 'POST',
      body: JSON.stringify({ username, password })
    });
    state.currentUser = payload.user;
    document.getElementById('loginScreen').hidden = true;
    document.getElementById('appShell').hidden = false;
    applyRoleAccess();
    setActiveView('dashboard');
    await loadDashboard();
  } catch (error) {
    errorMessage.textContent = error.message;
  }
}

async function restoreSession() {
  try {
    const { user } = await requestJSON('/api/session');
    if (!user) return;
    state.currentUser = user;
    document.getElementById('loginScreen').hidden = true;
    document.getElementById('appShell').hidden = false;
    applyRoleAccess();
    setActiveView('dashboard');
    await loadDashboard();
  } catch (error) {
    document.getElementById('loginError').textContent = error.message;
  }
}

async function signOut() {
  try {
    await requestJSON('/api/logout', { method: 'POST', body: '{}' });
  } finally {
    state.currentUser = null;
    document.getElementById('appShell').hidden = true;
    document.getElementById('loginScreen').hidden = false;
    document.getElementById('loginForm').reset();
  }
}

function populateClientOptions() {
  const options = state.clients.map((client) =>
    `<option value="${escapeHTML(client.name)}">${escapeHTML(client.name)}</option>`
  ).join('');
  ['newClientName', 'client'].forEach((id) => {
    const select = document.getElementById(id);
    if (select) select.innerHTML = options;
  });
}

function populateCollectorOptions() {
  const options = state.collectors.length ? state.collectors.map((collector) =>
    `<option value="${escapeHTML(collector.fullName)}">${escapeHTML(collector.fullName)}</option>`
  ).join('') : '<option value="" selected disabled>No active collector users</option>';
  ['collector', 'editCollector', 'taskCollector'].forEach((id) => {
    const select = document.getElementById(id);
    if (select) select.innerHTML = options;
  });
  document.getElementById('taskCollector').value = state.currentUser?.fullName || '';
}

async function loadAdminUsers() {
  try {
    const payload = await requestJSON('/api/users');
    state.users = payload.users || [];
    document.getElementById('usersTable').innerHTML = state.users.map((user) => `
      <tr>
        <td><strong>${escapeHTML(user.fullName)}</strong><small class="table-subtext">@${escapeHTML(user.username)}</small></td>
        <td>${escapeHTML(user.role)}</td>
        <td>${escapeHTML(user.clientName || 'Agency-wide')}</td>
        <td><span class="status-pill ${user.isActive ? 'success' : 'inactive'}">${user.isActive ? 'Active' : 'Inactive'}</span></td>
        <td class="action-cell"><button class="table-action" type="button" data-user-id="${Number(user.id)}" data-active="${Boolean(user.isActive)}">${user.isActive ? 'Deactivate' : 'Reactivate'}</button><button class="table-action danger-action" type="button" data-delete-type="users" data-delete-id="${Number(user.id)}">Delete</button></td>
      </tr>
    `).join('');
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function loadAuditLogs() {
  try {
    const payload = await requestJSON('/api/audit');
    state.auditLogs = payload.auditLogs || [];
    document.getElementById('auditTable').innerHTML = state.auditLogs.map((entry) => `
      <tr>
        <td>${escapeHTML(new Date(entry.createdAt).toLocaleString())}</td>
        <td>${escapeHTML(entry.actorUsername)}</td>
        <td><span class="audit-action">${escapeHTML(entry.action)}</span></td>
        <td>${escapeHTML(entry.details)}</td>
      </tr>
    `).join('');
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function createUser(event) {
  event.preventDefault();
  try {
    await requestJSON('/api/users', {
      method: 'POST',
      body: JSON.stringify({
        username: document.getElementById('newUsername').value,
        fullName: document.getElementById('newFullName').value,
        role: document.getElementById('newRole').value,
        password: document.getElementById('newPassword').value,
        clientName: document.getElementById('newRole').value === 'client'
          ? document.getElementById('newClientName').value
          : ''
      })
    });
    event.target.reset();
    document.getElementById('userPortfolioField').hidden = true;
    populateClientOptions();
    await loadAdminUsers();
    showNotice('User created. The temporary password is not shown again.');
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function toggleUserActive(button) {
  const userId = button.dataset.userId;
  const isActive = button.dataset.active !== 'true';
  try {
    await requestJSON(`/api/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify({ isActive })
    });
    await loadAdminUsers();
    showNotice(`User ${isActive ? 'reactivated' : 'deactivated'}.`);
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function changePassword(event) {
  event.preventDefault();
  try {
    await requestJSON('/api/password', {
      method: 'POST',
      body: JSON.stringify({
        currentPassword: document.getElementById('currentPassword').value,
        newPassword: document.getElementById('newPasswordChange').value
      })
    });
    event.target.reset();
    showNotice('Password updated. Other signed-in sessions were ended.');
  } catch (error) {
    showNotice(error.message, true);
  }
}

function openAccountEditor(accountId) {
  const account = state.accounts.find((item) => Number(item.id) === Number(accountId));
  if (!account) return;
  document.getElementById('editAccountId').value = account.id;
  document.getElementById('editAccountNumber').textContent = account.accountNumber;
  document.getElementById('editAccountStatus').value = account.status;
  document.getElementById('editCollector').value = account.collector;
  document.getElementById('editBalance').value = account.balance;
  document.getElementById('editDaysPastDue').value = account.daysPastDue;
  document.getElementById('editAssignmentFields').hidden = state.currentUser.role === 'collector';
  document.getElementById('accountDialog').showModal();
}

async function saveAccountChanges(event) {
  event.preventDefault();
  const payload = { status: document.getElementById('editAccountStatus').value };
  if (state.currentUser.role !== 'collector') {
    payload.balance = Number(document.getElementById('editBalance').value);
    payload.daysPastDue = Number(document.getElementById('editDaysPastDue').value);
    if (document.getElementById('editCollector').value) {
      payload.collector = document.getElementById('editCollector').value;
    }
  }
  try {
    await requestJSON(`/api/accounts/${document.getElementById('editAccountId').value}`, {
      method: 'PATCH', body: JSON.stringify(payload)
    });
    document.getElementById('accountDialog').close();
    await loadDashboard();
    showNotice('Account updated.');
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function savePromiseStatus(promiseId) {
  const select = document.querySelector(`[data-promise-status="${promiseId}"]`);
  try {
    await requestJSON(`/api/promises/${promiseId}`, {
      method: 'PATCH', body: JSON.stringify({ status: select.value })
    });
    await loadDashboard();
    showNotice('Promise status updated. Broken promises create a follow-up task.');
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function createActivity(event) {
  event.preventDefault();
  try {
    await requestJSON('/api/activities', {
      method: 'POST',
      body: JSON.stringify({
        accountNumber: document.getElementById('activityAccount').value,
        title: document.getElementById('activityTitle').value,
        detail: document.getElementById('activityDetail').value
      })
    });
    event.target.reset();
    await loadDashboard();
    showNotice('Collection activity saved to the account timeline.');
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function createTask(event) {
  event.preventDefault();
  try {
    await requestJSON('/api/tasks', {
      method: 'POST',
      body: JSON.stringify({
        accountNumber: document.getElementById('taskAccount').value,
        title: document.getElementById('taskTitle').value,
        dueDate: document.getElementById('taskDate').value,
        assignedTo: document.getElementById('taskCollector').value
      })
    });
    event.target.reset();
    document.getElementById('taskCollector').value = state.currentUser.fullName;
    await loadDashboard();
    showNotice('Follow-up task created.');
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function completeTask(taskId) {
  try {
    await requestJSON(`/api/tasks/${taskId}`, {
      method: 'PATCH', body: JSON.stringify({ status: 'Completed' })
    });
    await loadDashboard();
    showNotice('Follow-up completed.');
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function recordPayment(event) {
  event.preventDefault();
  try {
    await requestJSON('/api/payments', {
      method: 'POST',
      body: JSON.stringify({
        accountNumber: document.getElementById('paymentAccount').value,
        promiseId: document.getElementById('paymentPromise').value || null,
        amount: Number(document.getElementById('paymentAmount').value),
        paymentMethod: document.getElementById('paymentMethod').value,
        reference: document.getElementById('paymentReference').value
      })
    });
    event.target.reset();
    await loadDashboard();
    showNotice('Payment recorded and account balance updated.');
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function deleteRecord(kind, id) {
  if (!window.confirm(`Delete this ${kind.slice(0, -1)}? This action cannot be undone.`)) return;
  try {
    await requestJSON(`/api/${kind}/${id}`, { method: 'DELETE' });
    await loadDashboard();
    if (state.activeView === 'users') await loadAdminUsers();
    if (state.activeView === 'audit') await loadAuditLogs();
    showNotice(`${kind.slice(0, -1)} deleted.`);
  } catch (error) {
    showNotice(error.message, true);
  }
}

function runStrategy(event) {
  event.preventDefault();
  const strategy = new FormData(event.target).get('strategy');
  const upcomingAccounts = new Set(state.promises.filter((promise) => ['Upcoming', 'Due'].includes(promise.status)).map((promise) => promise.accountNumber));
  const accounts = [...state.accounts].sort((left, right) => {
    if (strategy === 'balance') return Number(right.balance) - Number(left.balance);
    if (strategy === 'promise') return Number(upcomingAccounts.has(right.accountNumber)) - Number(upcomingAccounts.has(left.accountNumber));
    return Number(right.daysPastDue) - Number(left.daysPastDue);
  });
  document.getElementById('strategyResults').innerHTML = `
    <table><thead><tr><th>Queue order</th><th>Account</th><th>Collector</th><th>Balance</th><th>Days due</th><th>Priority</th></tr></thead>
    <tbody>${accounts.map((account, index) => `<tr><td>${index + 1}</td><td>${escapeHTML(account.accountNumber)}</td><td>${escapeHTML(account.collector)}</td><td>${formatCurrency(account.balance)}</td><td>${Number(account.daysPastDue)}</td><td>${getPriority(account.daysPastDue)}</td></tr>`).join('')}</tbody></table>
    <p>${accounts.length} accounts ordered using ${escapeHTML(strategy)} priority.</p>
  `;
}

function draftInteractionSummary(event) {
  event.preventDefault();
  const notes = document.getElementById('summaryNotes').value.trim();
  document.getElementById('summaryDraft').value = `Interaction summary: ${notes}\nFollow-up: Review the requested arrangement according to agency policy.\nStatus: Draft; collector review required.`;
}

async function confirmInteractionSummary() {
  const accountNumber = document.getElementById('summaryAccount').value;
  const summary = document.getElementById('summaryDraft').value.trim();
  if (!accountNumber || !summary) {
    showNotice('Select an account and draft a summary before confirming.', true);
    return;
  }
  try {
    await requestJSON('/api/activities', {
      method: 'POST',
      body: JSON.stringify({ accountNumber, title: 'Reviewed interaction summary', detail: summary })
    });
    document.getElementById('summaryForm').reset();
    await loadDashboard();
    showNotice('Reviewed summary added to the account timeline.');
  } catch (error) {
    showNotice(error.message, true);
  }
}

document.querySelectorAll('.nav-item').forEach((button) => {
  button.addEventListener('click', () => setActiveView(button.dataset.view));
});

document.getElementById('loginForm').addEventListener('submit', handleLogin);
document.getElementById('logoutButton').addEventListener('click', signOut);
document.getElementById('passwordForm').addEventListener('submit', changePassword);
document.getElementById('userForm').addEventListener('submit', createUser);
document.getElementById('accountEditForm').addEventListener('submit', saveAccountChanges);
document.getElementById('cancelAccountEdit').addEventListener('click', () => document.getElementById('accountDialog').close());
document.getElementById('paymentForm').addEventListener('submit', recordPayment);
document.getElementById('activityForm').addEventListener('submit', createActivity);
document.getElementById('taskForm').addEventListener('submit', createTask);
document.getElementById('strategyForm').addEventListener('submit', runStrategy);
document.getElementById('summaryForm').addEventListener('submit', draftInteractionSummary);
document.getElementById('confirmSummary').addEventListener('click', confirmInteractionSummary);
document.getElementById('refreshUsers').addEventListener('click', loadAdminUsers);
document.getElementById('refreshAudit').addEventListener('click', loadAuditLogs);
document.getElementById('usersTable').addEventListener('click', (event) => {
  const button = event.target.closest('[data-user-id]');
  if (button) toggleUserActive(button);
});
document.getElementById('newRole').addEventListener('change', (event) => {
  document.getElementById('userPortfolioField').hidden = event.target.value !== 'client';
});
document.getElementById('refreshDashboard').addEventListener('click', loadDashboard);
document.getElementById('accountsTable').addEventListener('click', (event) => {
  const button = event.target.closest('[data-edit-account]');
  if (button) openAccountEditor(button.dataset.editAccount);
});
document.getElementById('promiseTable').addEventListener('click', (event) => {
  const button = event.target.closest('[data-save-promise]');
  if (button) savePromiseStatus(button.dataset.savePromise);
});
document.getElementById('appShell').addEventListener('click', (event) => {
  const deleteButton = event.target.closest('[data-delete-type]');
  if (deleteButton) return deleteRecord(deleteButton.dataset.deleteType, deleteButton.dataset.deleteId);
  const taskButton = event.target.closest('[data-task-complete]');
  if (taskButton) return completeTask(taskButton.dataset.taskComplete);
});

document.getElementById('accountForm').addEventListener('submit', async (event) => {
  event.preventDefault();

  const payload = {
    client: document.getElementById('client').value,
    balance: Number(document.getElementById('balance').value),
    daysPastDue: Number(document.getElementById('daysPastDue').value),
    collector: document.getElementById('collector').value,
    status: document.getElementById('status').value
  };

  try {
    const result = await requestJSON('/api/accounts', { method: 'POST', body: JSON.stringify(payload) });
    event.target.reset();
    await loadDashboard();
    setActiveView('accounts');
    document.getElementById('accountNumberPreview').textContent = result.account.accountNumber;
    showNotice(`Account ${result.account.accountNumber} created.`);
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.getElementById('promiseForm').addEventListener('submit', async (event) => {
  event.preventDefault();

  const payload = {
    accountNumber: document.getElementById('promiseAccount').value,
    amount: Number(document.getElementById('promiseAmount').value),
    dueDate: document.getElementById('promiseDate').value,
    paymentMethod: document.getElementById('promiseMethod').value
  };

  try {
    await requestJSON('/api/promises', { method: 'POST', body: JSON.stringify(payload) });
    event.target.reset();
    await loadDashboard();
    setActiveView('promises');
    showNotice('Promise recorded.');
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.getElementById('paymentAccount').addEventListener('change', (event) => {
  const selectedAccount = event.target.value;
  const matchingPromises = state.promises.filter((promise) => promise.accountNumber === selectedAccount);
  const select = document.getElementById('paymentPromise');
  select.innerHTML = '<option value="">No linked promise</option>' + matchingPromises.map((promise) =>
    `<option value="${Number(promise.id)}">${escapeHTML(promise.dueDate)} · ${formatCurrency(promise.amount)}</option>`
  ).join('');
});

document.getElementById('clientForm').addEventListener('submit', async (event) => {
  event.preventDefault();

  const payload = {
    name: document.getElementById('clientName').value,
    industry: document.getElementById('clientIndustry').value
  };

  try {
    await requestJSON('/api/clients', { method: 'POST', body: JSON.stringify(payload) });
    event.target.reset();
    await loadDashboard();
    setActiveView('clients');
    showNotice('Client portfolio added.');
  } catch (error) {
    showNotice(error.message, true);
  }
});

restoreSession();

if (typeof module !== 'undefined') {
  module.exports = { getPriority, getAccessForRole, escapeHTML, state };
}
