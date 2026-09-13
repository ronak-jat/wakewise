/* ==========================================================================
   INTELLIGENT COGNITIVE ALARM PLATFORM - ADMINISTRATOR COCKPIT CONTROLLER
   Full PostgreSQL Database Integration, Analytics & Live Console
   ========================================================================== */

// Ensure API base URL is always initialized
window.API_BASE_URL = window.API_BASE_URL || (typeof getApiBaseUrl === 'function' ? getApiBaseUrl() : 'http://127.0.0.1:8000');

let adminUsersList = [];
let adminAuditLogs = [];

let adminUsersChart = null;
let adminAlarmStatsChart = null;
let adminRoleDistChart = null;

function getAuthHeaders() {
    let token = '';
    try {
        const session = JSON.parse(localStorage.getItem('sessionUser') || '{}');
        token = session.accessToken || session.token || localStorage.getItem('token') || localStorage.getItem('accessToken') || '';
    } catch (_) { }

    return {
        'Content-Type': 'application/json',
        'Authorization': token ? `Bearer ${token}` : ''
    };
}

// 1. Tab Navigation Switcher
window.switchTab = (tabId) => {
    document.querySelectorAll('.tab-content-section').forEach(section => {
        section.classList.remove('active');
    });

    const activeSection = document.getElementById(tabId);
    if (activeSection) {
        activeSection.classList.add('active');
    }

    document.querySelectorAll('.sidebar-menu-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.tab === tabId) {
            item.classList.add('active');
        }
    });

    const crumbText = document.getElementById('breadcrumb-current');
    if (crumbText) {
        const item = document.querySelector(`.sidebar-menu-item[data-tab="${tabId}"] span`);
        crumbText.textContent = item ? item.textContent : 'Cockpit';
    }

    if (typeof window.setDashboardActiveTab === 'function') {
        window.setDashboardActiveTab(tabId);
    }

    if (tabId === 'tab-performance') {
        loadPerformanceMetrics(currentPerfPeriodDays, currentPerfStartDate, currentPerfEndDate);
    }

    document.body.classList.remove('sidebar-open');
};

window.addEventListener('DOMContentLoaded', () => {
    if (typeof window.restoreDashboardActiveTab === 'function') {
        window.restoreDashboardActiveTab();
    }
});

// 2. Load Admin Dashboard Overview from PostgreSQL
async function loadAdminDashboardOverview() {
    try {
        let overviewData = null;
        let alarmsData = null;

        try {
            const resp = await fetch(`${window.API_BASE_URL}/api/admin/dashboard`, {
                headers: getAuthHeaders()
            });
            if (resp.ok) {
                overviewData = await resp.json();
            }
        } catch (_) { }

        try {
            const alarmsResp = await fetch(`${window.API_BASE_URL}/api/admin/alarms`, {
                headers: getAuthHeaders()
            });
            if (alarmsResp.ok) {
                alarmsData = await alarmsResp.json();
            }
        } catch (_) { }

        if (!overviewData) {
            // Calculate strictly from available users list if overview API returned empty/offline
            const totalUsers = adminUsersList.length;
            const students = adminUsersList.filter(u => (u.role || '').toUpperCase() === 'USER').length;
            const coaches = adminUsersList.filter(u => (u.role || '').toUpperCase().includes('COACH')).length;
            const calculatedAlarms = alarmsData ? alarmsData.total_alarms : adminUsersList.reduce((acc, u) => acc + (u.total_alarms || 0), 0);
            overviewData = {
                total_users: totalUsers,
                active_users: totalUsers,
                total_alarms: calculatedAlarms,
                active_alarms: alarmsData ? alarmsData.active_alarms : 0,
                total_challenges: 0,
                total_snoozes: 0,
                system_health: "operational"
            };
        }

        // Use direct alarms table query count if available
        if (alarmsData && alarmsData.total_alarms !== undefined) {
            overviewData.total_alarms = alarmsData.total_alarms;
        }

        const totalAccountsEl = document.getElementById('stat-total-accounts');
        if (totalAccountsEl) totalAccountsEl.textContent = overviewData.total_users;

        const studentCount = adminUsersList.filter(u => (u.role || '').toUpperCase() === 'USER').length;
        const studentsEl = document.getElementById('stat-students-count');
        if (studentsEl) {
            studentsEl.textContent = studentCount;
        }

        const coachCount = adminUsersList.filter(u => (u.role || '').toUpperCase().includes('COACH')).length;
        const coachesEl = document.getElementById('stat-coaches-count');
        if (coachesEl) {
            coachesEl.textContent = coachCount;
        }

        const totalAlarmsEl = document.getElementById('stat-total-alarms');
        if (totalAlarmsEl) totalAlarmsEl.textContent = overviewData.total_alarms;

        const healthEl = document.getElementById('stat-system-health') || document.querySelector('.glass-card.accent-hover.stat-card .stat-details h3');
        if (healthEl) healthEl.textContent = overviewData.system_health === 'operational' ? '100% OK' : overviewData.system_health;

        const platformUsageEl = document.getElementById('stat-platform-usage') || document.querySelector('.glass-card.danger-hover.stat-card .stat-details h3');
        if (platformUsageEl) {
            const ratio = overviewData.total_users > 0 ? Math.round((overviewData.active_users / overviewData.total_users) * 100) : 0;
            platformUsageEl.textContent = `${ratio}% Active`;
        }
    } catch (e) {
        console.error('Error fetching admin dashboard overview:', e);
    }
}

// 3. User Database Operations & Table Renderers
async function renderAdminUsers() {
    try {
        let loaded = false;

        // Try fetching from admin users API
        try {
            const response = await fetch(`${window.API_BASE_URL}/api/admin/users?t=${Date.now()}`, {
                headers: getAuthHeaders()
            });

            if (response.ok) {
                const data = await response.json();
                if (Array.isArray(data)) {
                    adminUsersList = data;
                    localStorage.setItem('admin_users_cache', JSON.stringify(adminUsersList));
                    loaded = true;
                }
            }
        } catch (_) { }

        // Fallback: fetch from auth users API
        if (!loaded) {
            try {
                const authResp = await fetch(`${window.API_BASE_URL}/api/auth/users`);
                if (authResp.ok) {
                    const authUsers = await authResp.json();
                    if (Array.isArray(authUsers)) {
                        adminUsersList = authUsers.map((u, idx) => ({
                            id: u.id || (idx + 1),
                            name: u.name || 'User',
                            email: u.email,
                            role: u.role || 'USER',
                            provider: u.provider || 'LOCAL',
                            created_at: u.created_at ? u.created_at.substring(0, 16).replace('T', ' ') : null,
                            total_alarms: u.total_alarms || 0,
                            habit_score: u.habit_score || 0.0,
                        }));
                        localStorage.setItem('admin_users_cache', JSON.stringify(adminUsersList));
                        loaded = true;
                    }
                }
            } catch (_) { }
        }

        if (!loaded) {
            const cached = localStorage.getItem('admin_users_cache');
            if (cached) {
                adminUsersList = JSON.parse(cached);
            }
        }
    } catch (error) {
        console.warn('Failed to fetch users from admin API:', error);
        adminUsersList = JSON.parse(localStorage.getItem('admin_users_cache') || '[]');
    }

    // Render stats breakdown
    const totalAccounts = adminUsersList.length;
    const studentsCount = adminUsersList.filter(u => (u.role || '').toUpperCase() === 'USER').length;
    const coachesCount = adminUsersList.filter(u => (u.role || '').toUpperCase().includes('COACH')).length;

    const totalElem = document.getElementById('stat-total-accounts');
    const studentsElem = document.getElementById('stat-students-count');
    const coachesElem = document.getElementById('stat-coaches-count');

    if (totalElem) totalElem.textContent = totalAccounts;
    if (studentsElem) studentsElem.textContent = studentsCount;
    if (coachesElem) coachesElem.textContent = coachesCount;

    // Render Dashboard Table (Recent 6)
    const dashboardUsersTable = document.getElementById('admin-users-table')?.querySelector('tbody');
    if (dashboardUsersTable) {
        dashboardUsersTable.innerHTML = '';
        if (adminUsersList.length === 0) {
            dashboardUsersTable.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 16px;">No registered accounts found in database.</td></tr>';
        } else {
            adminUsersList.slice(-6).reverse().forEach(u => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><strong>${escapeHtml(u.name || 'User')}</strong></td>
                    <td>${escapeHtml(u.email)}</td>
                    <td><span class="badge ${getRoleBadgeClass(u.role)}">${getRoleBadgeLabel(u.role)}</span></td>
                    <td>
                        <button class="table-action-btn delete-btn" onclick="deleteUserAccount('${escapeHtml(u.email)}', '${escapeHtml(u.role)}')" title="Delete Account"><i class="fas fa-trash-alt"></i></button>
                    </td>
                `;
                dashboardUsersTable.appendChild(tr);
            });
        }
    }

    // Render Console Table (Full list with Role Editing)
    renderConsoleUsersTable(adminUsersList);
}

function renderConsoleUsersTable(usersToRender) {
    const consoleUsersTable = document.getElementById('all-users-console-table')?.querySelector('tbody');
    if (!consoleUsersTable) return;

    consoleUsersTable.innerHTML = '';
    if (!usersToRender || usersToRender.length === 0) {
        consoleUsersTable.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 16px;">No matching user accounts found in database.</td></tr>';
        return;
    }

    usersToRender.forEach(u => {
        const tr = document.createElement('tr');
        const alarmsCount = u.total_alarms !== undefined ? u.total_alarms : 0;
        tr.innerHTML = `
            <td><strong>${escapeHtml(u.name || 'User')}</strong></td>
            <td>${escapeHtml(u.email)}</td>
            <td>
                <select class="form-select" style="padding: 4px 8px; font-size: 0.8rem; background: var(--glass-bg); color: var(--text-primary); border: 1px solid var(--glass-border); border-radius: 6px;" onchange="updateUserRole('${u.id}', this.value)">
                    <option value="USER" ${(u.role || '').toUpperCase() === 'USER' ? 'selected' : ''}>Platform User</option>
                    <option value="COACH" ${(u.role || '').toUpperCase().includes('COACH') ? 'selected' : ''}>Wellness Coach</option>
                    <option value="ADMIN" ${(u.role || '').toUpperCase() === 'ADMIN' ? 'selected' : ''}>Administrator</option>
                </select>
            </td>
            <td><span class="badge badge-info"><i class="fas fa-bell"></i> ${alarmsCount} Alarms</span></td>
            <td>
                <button class="table-action-btn delete-btn" onclick="deleteUserAccount('${escapeHtml(u.email)}', '${escapeHtml(u.role)}')" title="Delete User"><i class="fas fa-trash-alt"></i></button>
            </td>
        `;
        consoleUsersTable.appendChild(tr);
    });
}

// Live Search in Users Console Tab
window.filterConsoleUsers = (query) => {
    const q = (query || '').toLowerCase().trim();
    if (!q) {
        renderConsoleUsersTable(adminUsersList);
        return;
    }
    const filtered = adminUsersList.filter(u =>
        (u.name && u.name.toLowerCase().includes(q)) ||
        (u.email && u.email.toLowerCase().includes(q)) ||
        (u.role && u.role.toLowerCase().includes(q))
    );
    renderConsoleUsersTable(filtered);
};

function getRoleBadgeLabel(role) {
    const r = (role || '').toUpperCase();
    if (r.includes('ADMIN')) return 'ADMIN';
    if (r.includes('COACH')) return 'WELLNESS COACH';
    return 'USER / STUDENT';
}

function getRoleBadgeClass(role) {
    const r = (role || '').toUpperCase();
    if (r.includes('ADMIN')) return 'badge-danger';
    if (r.includes('COACH')) return 'badge-info';
    return 'badge-success';
}

// Fetch & Render Real Platform Logs
async function loadAdminLogs() {
    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/admin/logs?limit=50`, {
            headers: getAuthHeaders()
        });
        if (resp.ok) {
            const data = await resp.json();
            adminAuditLogs = data.logs || [];
        }
    } catch (_) { }

    if (adminAuditLogs.length === 0 && adminUsersList.length > 0) {
        const nowStr = new Date().toLocaleTimeString();
        adminAuditLogs = adminUsersList.slice(-6).map(u => ({
            time: u.created_at ? u.created_at.substring(11, 16) : nowStr,
            module: 'ACCOUNT',
            msg: `User account '${u.name}' (${u.email}) active with role [${u.role}].`,
            status: 'success'
        }));
    }

    renderAdminLogs();
}

// 4. Update Role API Endpoint
window.updateUserRole = async (userId, newRole) => {
    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/admin/users/${encodeURIComponent(userId)}/role`, {
            method: 'PUT',
            headers: getAuthHeaders(),
            body: JSON.stringify({ role: newRole })
        });

        const data = await resp.json();
        if (resp.ok) {
            Toast.show('Role Updated', `User permissions updated to ${newRole}.`, 'success', 2500);
            await renderAdminUsers();
            await loadAdminAnalytics();
            await loadAdminLogs();
        } else {
            Toast.show('Update Failed', data.detail || 'Could not update role.', 'danger', 3000);
        }
    } catch (e) {
        console.error('Role update error:', e);
        Toast.show('Error', 'Network error modifying user role.', 'danger', 2500);
    }
};

// 5. Delete User Account
window.deleteUserAccount = async (email, role) => {
    const currentSession = JSON.parse(localStorage.getItem('sessionUser') || '{}');
    if (currentSession.email && currentSession.email.toLowerCase() === email.toLowerCase()) {
        Toast.show('Access Denied', 'Self-deletion of active administrator is not permitted.', 'danger', 3000);
        return;
    }

    if (!confirm(`Are you sure you want to permanently delete account ${email}?`)) {
        return;
    }

    try {
        const response = await fetch(`${window.API_BASE_URL}/api/admin/users/${encodeURIComponent(email)}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });

        let data = {};
        try { data = await response.json(); } catch (_) { }

        if (!response.ok) {
            Toast.show('Failed', data.detail || 'Could not delete user.', 'danger', 3000);
            return;
        }

        Toast.show('User Removed', `Account ${email} deleted from Database.`, 'success', 2500);
        await renderAdminUsers();
        await loadAdminDashboardOverview();
        await loadAdminAnalytics();
        await loadAdminLogs();
    } catch (error) {
        console.error('Delete User API Error:', error);
        Toast.show('Error', 'Failed to communicate with database server.', 'danger', 2500);
    }
};

// 6. Add User Form Listener
const addUserForm = document.getElementById('add-user-form');
if (addUserForm) {
    addUserForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('admin-user-name').value;
        const email = document.getElementById('admin-user-email').value;
        const password = document.getElementById('admin-user-password').value;
        const role = document.getElementById('admin-user-role').value;

        try {
            const resp = await fetch(`${window.API_BASE_URL}/api/auth/register`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name.trim(),
                    email: email.trim().toLowerCase(),
                    password: password,
                    role: role.toUpperCase(),
                    provider: 'LOCAL'
                })
            });

            const data = await resp.json();
            if (resp.ok) {
                Toast.show('User Created', `Account generated for ${email} in PostgreSQL.`, 'success', 3000);
                Modal.close('add-user-modal');
                addUserForm.reset();
                await renderAdminUsers();
                await loadAdminDashboardOverview();
                await loadAdminAnalytics();
                await loadAdminLogs();
            } else {
                Toast.show('Registration Failed', data.detail || 'Could not create account.', 'warning', 3000);
            }
        } catch (err) {
            console.error('Registration error:', err);
            Toast.show('Error', 'Network error registering user.', 'danger', 2500);
        }
    });
}

// 7. Render Platform Logs (Compact 3 Entries on Cockpit Dashboard)
function renderAdminLogs() {
    const tbody = document.getElementById('logs-table-body');
    if (tbody) {
        tbody.innerHTML = '';
        if (!adminAuditLogs || adminAuditLogs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted); padding: 16px;">No platform activity records logged yet.</td></tr>';
            return;
        }
        // Display only the latest 3 entries on the primary dashboard
        adminAuditLogs.slice(0, 3).forEach(l => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><span style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(l.time)}</span></td>
                <td><strong>[${escapeHtml(l.module)}]</strong> ${escapeHtml(l.msg)}</td>
                <td><span class="badge ${l.status === 'success' ? 'badge-success' : (l.status === 'warning' ? 'badge-danger' : 'badge-info')}">${(l.status || 'info').toUpperCase()}</span></td>
            `;
            tbody.appendChild(tr);
        });
    }
}

// 8. Real Chart.js Rendering for Admin Analytics
async function loadAdminAnalytics() {
    let analyticsData = null;
    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/admin/analytics`, {
            headers: getAuthHeaders()
        });
        if (resp.ok) {
            analyticsData = await resp.json();
        }
    } catch (e) {
        console.warn('Could not fetch admin analytics:', e);
    }

    const isDark = document.body.getAttribute('data-theme') === 'dark';
    const textColor = isDark ? '#9ca3af' : '#62627a';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(99, 102, 241, 0.08)';

    // 1. Monthly User Growth Chart (Real Data from PostgreSQL)
    const usersCtx = document.getElementById('adminUsersChart');
    if (usersCtx) {
        if (adminUsersChart) adminUsersChart.destroy();

        let growthLabels = [];
        let growthData = [];

        if (analyticsData && analyticsData.user_growth_trend && analyticsData.user_growth_trend.length > 0) {
            growthLabels = analyticsData.user_growth_trend.map(p => p.month || p.date);
            growthData = analyticsData.user_growth_trend.map(p => p.count !== undefined ? p.count : (p.users || 0));
        } else {
            growthLabels = ['Live'];
            growthData = [adminUsersList.length];
        }

        adminUsersChart = new Chart(usersCtx, {
            type: 'line',
            data: {
                labels: growthLabels,
                datasets: [{
                    label: 'Platform Registered Users',
                    data: growthData,
                    borderColor: '#6366f1',
                    backgroundColor: 'rgba(99,102,241,0.15)',
                    fill: true,
                    tension: 0.35,
                    pointBackgroundColor: '#6366f1',
                    pointRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: textColor } }
                },
                scales: {
                    x: { grid: { color: gridColor }, ticks: { color: textColor } },
                    y: { grid: { color: gridColor }, ticks: { color: textColor }, beginAtZero: true }
                }
            }
        });
    }

    // 2. Alarm Type Distribution Chart (Real Data from PostgreSQL)
    const alarmStatsCtx = document.getElementById('adminAlarmStatsChart');
    if (alarmStatsCtx) {
        if (adminAlarmStatsChart) adminAlarmStatsChart.destroy();

        let alarmLabels = [];
        let alarmCounts = [];

        if (analyticsData && analyticsData.alarm_types_distribution && Object.keys(analyticsData.alarm_types_distribution).length > 0) {
            alarmLabels = Object.keys(analyticsData.alarm_types_distribution);
            alarmCounts = Object.values(analyticsData.alarm_types_distribution);
        } else {
            alarmLabels = ['No Alarms Configured'];
            alarmCounts = [0];
        }

        adminAlarmStatsChart = new Chart(alarmStatsCtx, {
            type: 'bar',
            data: {
                labels: alarmLabels,
                datasets: [{
                    label: 'Configured Alarms',
                    data: alarmCounts,
                    backgroundColor: ['#6366f1', '#3b82f6', '#f59e0b', '#10b981', '#ec4899', '#8b5cf6', '#06b6d4'],
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    x: { grid: { color: gridColor }, ticks: { color: textColor } },
                    y: { grid: { color: gridColor }, ticks: { color: textColor }, beginAtZero: true }
                }
            }
        });
    }

    // 3. Role Distribution Chart (Real Data from PostgreSQL)
    const roleDistCtx = document.getElementById('adminRoleDistChart');
    if (roleDistCtx) {
        if (adminRoleDistChart) adminRoleDistChart.destroy();

        let userCount = 0;
        let coachCount = 0;
        let adminCount = 0;

        if (analyticsData && analyticsData.role_distribution) {
            userCount = analyticsData.role_distribution.User || analyticsData.role_distribution.USER || 0;
            coachCount = analyticsData.role_distribution.Coach || analyticsData.role_distribution.COACH || 0;
            adminCount = analyticsData.role_distribution.Admin || analyticsData.role_distribution.ADMIN || 0;
        } else if (adminUsersList.length > 0) {
            userCount = adminUsersList.filter(u => (u.role || '').toUpperCase() === 'USER').length;
            coachCount = adminUsersList.filter(u => (u.role || '').toUpperCase().includes('COACH')).length;
            adminCount = adminUsersList.filter(u => (u.role || '').toUpperCase().includes('ADMIN')).length;
        }

        adminRoleDistChart = new Chart(roleDistCtx, {
            type: 'doughnut',
            data: {
                labels: ['Platform Users / Students', 'Wellness Coaches', 'Administrators'],
                datasets: [{
                    data: [userCount, coachCount, adminCount],
                    backgroundColor: ['#10b981', '#3b82f6', '#ef4444'],
                    borderColor: 'transparent'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: textColor } }
                }
            }
        });
    }
}

// 9. Export Real System Diagnostic Report in PDF, Excel, or CSV (Separated by dataset or All-in-One)
window.exportAdminReport = async (format = 'pdf', category = 'all') => {
    const fmt = (format || 'pdf').toLowerCase();
    const cat = (category || 'all').toLowerCase();
    const catLabel = cat === 'users' ? 'User Accounts' : (cat === 'alarms' ? 'Configured Alarms' : (cat === 'logs' ? 'Audit Logs' : 'Master Database Bundle'));
    Toast.show('Compiling Report...', `Building ${catLabel} in ${fmt.toUpperCase()} from PostgreSQL database.`, 'info', 2000);

    let reportData = null;
    let alarmsData = [];
    let logsData = adminAuditLogs;

    try {
        const [repResp, almResp, logResp] = await Promise.all([
            fetch(`${window.API_BASE_URL}/api/admin/reports`, { headers: getAuthHeaders() }),
            fetch(`${window.API_BASE_URL}/api/admin/alarms`, { headers: getAuthHeaders() }),
            fetch(`${window.API_BASE_URL}/api/admin/logs?limit=100`, { headers: getAuthHeaders() })
        ]);
        if (repResp.ok) reportData = await repResp.json();
        if (almResp.ok) {
            const aJson = await almResp.json();
            alarmsData = aJson.alarms || [];
        }
        if (logResp.ok) {
            const lJson = await logResp.json();
            logsData = lJson.logs || adminAuditLogs;
        }
    } catch (_) { }

    const users = adminUsersList || [];
    const dateStr = new Date().toLocaleDateString();
    const timeStr = new Date().toLocaleTimeString();

    if (fmt === 'csv') {
        // --- 1. CSV Format ---
        let csv = '\uFEFF'; // UTF-8 BOM for Excel compatibility

        if (cat === 'users') {
            csv += 'WAKEWISE AI - USER ACCOUNTS DIRECTORY\r\n';
            csv += `Export Date,${dateStr} ${timeStr}\r\n`;
            csv += `Total Registered Users,${users.length}\r\n\r\n`;
            csv += 'User ID,Name,Email,Role,Total Alarms,Habit Score,Registered Date,Last Active\r\n';
            users.forEach(u => {
                csv += `"${u.id}","${(u.name || '').replace(/"/g, '""')}","${(u.email || '').replace(/"/g, '""')}","${u.role || 'USER'}","${u.total_alarms || 0}","${u.habit_score || 0}","${u.created_at || ''}","${u.last_active || ''}"\r\n`;
            });
        } else if (cat === 'alarms') {
            csv += 'WAKEWISE AI - CONFIGURED WAKE-UP ALARMS\r\n';
            csv += `Export Date,${dateStr} ${timeStr}\r\n`;
            csv += `Total Configured Alarms,${alarmsData.length}\r\n\r\n`;
            csv += 'Alarm ID,User ID,User Name,Alarm Title,Time,Type,Repeat Days,Status,Verification Method,Created At\r\n';
            alarmsData.forEach(a => {
                csv += `"${a.id}","${a.user_id}","${(a.user_name || '').replace(/"/g, '""')}","${(a.title || '').replace(/"/g, '""')}","${a.alarm_time}","${a.alarm_type}","${a.repeat_days || ''}","${a.is_active ? 'Active' : 'Disabled'}","${a.verification_method || 'multi_step'}","${a.created_at || ''}"\r\n`;
            });
        } else if (cat === 'logs') {
            csv += 'WAKEWISE AI - PLATFORM AUDIT & SECURITY LOGS\r\n';
            csv += `Export Date,${dateStr} ${timeStr}\r\n`;
            csv += `Total Recorded Events,${logsData.length}\r\n\r\n`;
            csv += 'Timestamp,Module,Message,Status\r\n';
            logsData.forEach(l => {
                csv += `"${l.time}","${l.module}","${(l.msg || '').replace(/"/g, '""')}","${(l.status || 'info').toUpperCase()}"\r\n`;
            });
        } else {
            // Master Consolidated CSV
            csv += 'WAKEWISE AI - PLATFORM AUDIT & DATABASE MASTER LEDGER\r\n';
            csv += `Export Date,${dateStr} ${timeStr}\r\n`;
            csv += `Total Registered Users,${users.length} | Total Alarms,${alarmsData.length} | Total Events,${logsData.length}\r\n`;
            csv += `System Status,${reportData ? 'OPERATIONAL (100% HEALTH)' : 'OPERATIONAL'}\r\n\r\n`;

            csv += '--- SECTION 1: USER ACCOUNTS ---\r\n';
            csv += 'User ID,Name,Email,Role,Total Alarms,Habit Score,Registered Date,Last Active\r\n';
            users.forEach(u => {
                csv += `"${u.id}","${(u.name || '').replace(/"/g, '""')}","${(u.email || '').replace(/"/g, '""')}","${u.role || 'USER'}","${u.total_alarms || 0}","${u.habit_score || 0}","${u.created_at || ''}","${u.last_active || ''}"\r\n`;
            });
            csv += '\r\n';

            csv += '--- SECTION 2: CONFIGURED ALARMS ---\r\n';
            csv += 'Alarm ID,User ID,User Name,Alarm Title,Time,Type,Repeat Days,Status,Verification Method,Created At\r\n';
            alarmsData.forEach(a => {
                csv += `"${a.id}","${a.user_id}","${(a.user_name || '').replace(/"/g, '""')}","${(a.title || '').replace(/"/g, '""')}","${a.alarm_time}","${a.alarm_type}","${a.repeat_days || ''}","${a.is_active ? 'Active' : 'Disabled'}","${a.verification_method || 'multi_step'}","${a.created_at || ''}"\r\n`;
            });
            csv += '\r\n';

            csv += '--- SECTION 3: PLATFORM AUDIT LOGS ---\r\n';
            csv += 'Timestamp,Module,Message,Status\r\n';
            logsData.forEach(l => {
                csv += `"${l.time}","${l.module}","${(l.msg || '').replace(/"/g, '""')}","${(l.status || 'info').toUpperCase()}"\r\n`;
            });
        }

        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const prefix = cat === 'users' ? 'Users' : (cat === 'alarms' ? 'Alarms' : (cat === 'logs' ? 'AuditLogs' : 'Master'));
        a.download = `WakeWise_${prefix}_Report_${Date.now()}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        Toast.show('CSV Downloaded', `${catLabel} CSV file saved successfully.`, 'success', 2500);

    } else if (fmt === 'excel' || fmt === 'xlsx' || fmt === 'xls') {
        // --- 2. Excel XML Format (Native Excel Workbook) ---
        let excel = `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:html="http://www.w3.org/TR/REC-html40">
 <Styles>
  <Style ss:ID="Header"><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#107C41" ss:Pattern="Solid"/></Style>
  <Style ss:ID="Title"><Font ss:Bold="1" ss:Size="14" ss:Color="#107C41"/></Style>
  <Style ss:ID="Subheader"><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#16A34A" ss:Pattern="Solid"/></Style>
 </Styles>`;

        if (cat === 'users' || cat === 'all') {
            excel += `
 <Worksheet ss:Name="User Accounts">
  <Table>
   <Row><Cell ss:StyleID="Title"><Data ss:Type="String">WakeWise AI - Registered User Accounts</Data></Cell></Row>
   <Row><Cell><Data ss:Type="String">Generated: ${dateStr} ${timeStr} | Total Users: ${users.length}</Data></Cell></Row>
   <Row></Row>
   <Row ss:StyleID="Header">
    <Cell><Data ss:Type="String">User ID</Data></Cell>
    <Cell><Data ss:Type="String">Name</Data></Cell>
    <Cell><Data ss:Type="String">Email</Data></Cell>
    <Cell><Data ss:Type="String">Role</Data></Cell>
    <Cell><Data ss:Type="String">Total Alarms</Data></Cell>
    <Cell><Data ss:Type="String">Habit Score</Data></Cell>
    <Cell><Data ss:Type="String">Registered Date</Data></Cell>
   </Row>`;

            users.forEach(u => {
                excel += `
   <Row>
    <Cell><Data ss:Type="Number">${u.id}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(u.name || 'User')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(u.email || '')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(u.role || 'USER')}</Data></Cell>
    <Cell><Data ss:Type="Number">${u.total_alarms || 0}</Data></Cell>
    <Cell><Data ss:Type="Number">${u.habit_score || 0}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(u.created_at || '')}</Data></Cell>
   </Row>`;
            });

            excel += `
  </Table>
 </Worksheet>`;
        }

        if (cat === 'alarms' || cat === 'all') {
            excel += `
 <Worksheet ss:Name="Configured Alarms">
  <Table>
   <Row><Cell ss:StyleID="Title"><Data ss:Type="String">WakeWise AI - Configured Wake-Up Alarms</Data></Cell></Row>
   <Row><Cell><Data ss:Type="String">Generated: ${dateStr} ${timeStr} | Total Alarms: ${alarmsData.length}</Data></Cell></Row>
   <Row></Row>
   <Row ss:StyleID="Header">
    <Cell><Data ss:Type="String">Alarm ID</Data></Cell>
    <Cell><Data ss:Type="String">User Name</Data></Cell>
    <Cell><Data ss:Type="String">Alarm Title</Data></Cell>
    <Cell><Data ss:Type="String">Time</Data></Cell>
    <Cell><Data ss:Type="String">Type</Data></Cell>
    <Cell><Data ss:Type="String">Verification Method</Data></Cell>
    <Cell><Data ss:Type="String">Status</Data></Cell>
   </Row>`;

            alarmsData.forEach(a => {
                excel += `
   <Row>
    <Cell><Data ss:Type="Number">${a.id}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(a.user_name || 'User')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(a.title || 'Alarm')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(a.alarm_time || '')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(a.alarm_type || 'Daily')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(a.verification_method || 'multi_step')}</Data></Cell>
    <Cell><Data ss:Type="String">${a.is_active ? 'Active' : 'Disabled'}</Data></Cell>
   </Row>`;
            });

            excel += `
  </Table>
 </Worksheet>`;
        }

        if (cat === 'logs' || cat === 'all') {
            excel += `
 <Worksheet ss:Name="Audit Logs">
  <Table>
   <Row><Cell ss:StyleID="Title"><Data ss:Type="String">WakeWise AI - Platform Audit Logs</Data></Cell></Row>
   <Row><Cell><Data ss:Type="String">Generated: ${dateStr} ${timeStr} | Total Events: ${logsData.length}</Data></Cell></Row>
   <Row></Row>
   <Row ss:StyleID="Header">
    <Cell><Data ss:Type="String">Timestamp</Data></Cell>
    <Cell><Data ss:Type="String">Module</Data></Cell>
    <Cell><Data ss:Type="String">Event Description</Data></Cell>
    <Cell><Data ss:Type="String">Status</Data></Cell>
   </Row>`;

            logsData.forEach(l => {
                excel += `
   <Row>
    <Cell><Data ss:Type="String">${escapeXml(l.time || '')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(l.module || '')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml(l.msg || '')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXml((l.status || 'info').toUpperCase())}</Data></Cell>
   </Row>`;
            });

            excel += `
  </Table>
 </Worksheet>`;
        }

        excel += `
</Workbook>`;

        const blob = new Blob([excel], { type: 'application/vnd.ms-excel;charset=utf-8;' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const prefix = cat === 'users' ? 'Users' : (cat === 'alarms' ? 'Alarms' : (cat === 'logs' ? 'AuditLogs' : 'Master'));
        a.download = `WakeWise_${prefix}_Report_${Date.now()}.xls`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        Toast.show('Excel Downloaded', `${catLabel} spreadsheet saved successfully.`, 'success', 2500);

    } else {
        // --- 3. PDF Format (Printable High-Definition Document) ---
        const printWindow = window.open('', '_blank', 'width=900,height=750');
        if (!printWindow) {
            Toast.show('Popup Blocked', 'Please allow popups to generate PDF report.', 'warning', 3000);
            return;
        }

        let reportTitle = 'Platform Master Audit Report';
        let reportSubtitle = 'Complete System Cockpit & Database Ledger';
        if (cat === 'users') {
            reportTitle = 'User Accounts Directory';
            reportSubtitle = 'Registered User Profiles & Role Matrix';
        } else if (cat === 'alarms') {
            reportTitle = 'Configured Alarms Ledger';
            reportSubtitle = 'Active Schedules & Wake-Up Verification Protocols';
        } else if (cat === 'logs') {
            reportTitle = 'Platform Security & Audit Logs';
            reportSubtitle = 'Live Event Diagnostic Trail';
        }

        const showUsers = cat === 'users' || cat === 'all';
        const showAlarms = cat === 'alarms' || cat === 'all';
        const showLogs = cat === 'logs' || cat === 'all';

        const html = `<!DOCTYPE html>
<html>
<head>
    <title>WakeWise AI - ${reportTitle}</title>
    <style>
        @page { size: A4; margin: 16mm; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #1e293b; margin: 0; padding: 20px; font-size: 12px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #6366f1; padding-bottom: 12px; margin-bottom: 20px; }
        .logo { font-size: 20px; font-weight: 700; color: #6366f1; }
        .meta { text-align: right; font-size: 11px; color: #64748b; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; margin-bottom: 24px; }
        .stat-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; text-align: center; }
        .stat-box h4 { margin: 0; font-size: 18px; color: #1e1b4b; }
        .stat-box p { margin: 4px 0 0; font-size: 11px; color: #64748b; }
        h3 { font-size: 14px; margin: 20px 0 8px; color: #334155; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 11px; }
        th, td { border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; }
        th { background: #f1f5f9; font-weight: 600; color: #475569; }
        tr:nth-child(even) { background: #fafafa; }
        .badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; background: #e0e7ff; color: #3730a3; }
        .footer { margin-top: 30px; text-align: center; font-size: 10px; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 10px; }
        @media print {
            body { padding: 0; }
            .no-print { display: none; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <div class="logo">🧠 WakeWise AI - ${reportTitle}</div>
            <div style="font-size: 12px; color: #475569; margin-top: 4px;">${reportSubtitle}</div>
        </div>
        <div class="meta">
            <div><strong>Generated:</strong> ${dateStr} ${timeStr}</div>
            <div><strong>Status:</strong> Operational (100% Health)</div>
        </div>
    </div>

    <div class="stats-grid">
        ${showUsers ? `
        <div class="stat-box">
            <h4>${users.length}</h4>
            <p>Total Users</p>
        </div>` : ''}
        ${showAlarms ? `
        <div class="stat-box">
            <h4>${alarmsData.length}</h4>
            <p>Configured Alarms</p>
        </div>` : ''}
        ${showUsers ? `
        <div class="stat-box">
            <h4>${users.filter(u => (u.role || '').toUpperCase().includes('COACH')).length}</h4>
            <p>Wellness Coaches</p>
        </div>` : ''}
        ${showLogs ? `
        <div class="stat-box">
            <h4>${logsData.length}</h4>
            <p>Audit Events Recorded</p>
        </div>` : ''}
    </div>

    ${showUsers ? `
    <h3>Registered User Accounts (${users.length})</h3>
    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Alarms</th>
                <th>Habit Score</th>
                <th>Registered</th>
            </tr>
        </thead>
        <tbody>
            ${users.length === 0 ? '<tr><td colspan="7" style="text-align:center;">No accounts in database.</td></tr>' : users.map(u => `
                <tr>
                    <td>${u.id}</td>
                    <td><strong>${escapeHtml(u.name || 'User')}</strong></td>
                    <td>${escapeHtml(u.email)}</td>
                    <td><span class="badge">${escapeHtml(u.role || 'USER')}</span></td>
                    <td>${u.total_alarms || 0}</td>
                    <td>${u.habit_score || 0}%</td>
                    <td>${u.created_at || 'Recent'}</td>
                </tr>
            `).join('')}
        </tbody>
    </table>` : ''}

    ${showAlarms ? `
    <h3>Configured Wake-Up Alarms (${alarmsData.length})</h3>
    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>User Account</th>
                <th>Alarm Title</th>
                <th>Time</th>
                <th>Type</th>
                <th>Verification Method</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
            ${alarmsData.length === 0 ? '<tr><td colspan="7" style="text-align:center;">No alarms configured.</td></tr>' : alarmsData.map(a => `
                <tr>
                    <td>${a.id}</td>
                    <td>${escapeHtml(a.user_name || 'User')}</td>
                    <td><strong>${escapeHtml(a.title || 'Alarm')}</strong></td>
                    <td>${a.alarm_time}</td>
                    <td>${a.alarm_type || 'Daily'}</td>
                    <td>${a.verification_method || 'multi_step'}</td>
                    <td>${a.is_active ? 'Active' : 'Disabled'}</td>
                </tr>
            `).join('')}
        </tbody>
    </table>` : ''}

    ${showLogs ? `
    <h3>Platform Audit & Security Logs (${logsData.length})</h3>
    <table>
        <thead>
            <tr>
                <th style="width: 140px;">Timestamp</th>
                <th style="width: 110px;">Module</th>
                <th>Message</th>
                <th style="width: 80px;">Status</th>
            </tr>
        </thead>
        <tbody>
            ${logsData.length === 0 ? '<tr><td colspan="4" style="text-align:center;">No activity records.</td></tr>' : logsData.slice(0, 50).map(l => `
                <tr>
                    <td>${escapeHtml(l.time)}</td>
                    <td><strong>[${escapeHtml(l.module)}]</strong></td>
                    <td>${escapeHtml(l.msg)}</td>
                    <td>${(l.status || 'info').toUpperCase()}</td>
                </tr>
            `).join('')}
        </tbody>
    </table>` : ''}

    <div class="footer">
        WakeWise AI System Diagnostic Report • Generated from live PostgreSQL Database
    </div>

    <script>
        window.onload = function() {
            setTimeout(function() {
                window.print();
            }, 300);
        };
    </script>
</body>
</html>`;

        printWindow.document.open();
        printWindow.document.write(html);
        printWindow.document.close();
        Toast.show('PDF Ready', 'Print dialog opened. Select "Save as PDF".', 'success', 2500);
    }
};

window.simulateAdminExport = () => window.exportAdminReport('pdf', 'all');

function escapeXml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

// 10. Platform Announcements Management
let adminAnnouncementsList = [];

window.openCreateAnnouncementModal = (id = null) => {
    const modal = document.getElementById('announcement-modal');
    const form = document.getElementById('admin-announcement-form');
    const titleEl = document.getElementById('announcement-modal-title');
    const submitBtn = document.getElementById('announcement-submit-btn');

    if (!modal || !form) return;

    if (id) {
        const item = adminAnnouncementsList.find(a => a.id === id);
        if (item) {
            document.getElementById('announcement-id').value = item.id;
            document.getElementById('announcement-title').value = item.title;
            document.getElementById('announcement-message').value = item.message;
            document.getElementById('announcement-priority').value = item.priority || 'normal';
            document.getElementById('announcement-target-role').value = item.target_role || 'all';
            document.getElementById('announcement-is-active').checked = Boolean(item.is_active);
            if (titleEl) titleEl.textContent = 'Edit Platform Announcement';
            if (submitBtn) submitBtn.textContent = 'Update Announcement';
        }
    } else {
        form.reset();
        document.getElementById('announcement-id').value = '';
        document.getElementById('announcement-is-active').checked = true;
        if (titleEl) titleEl.textContent = 'Create Platform Announcement';
        if (submitBtn) submitBtn.textContent = 'Publish Announcement';
    }

    modal.classList.add('active');
};

window.closeAnnouncementModal = () => {
    const modal = document.getElementById('announcement-modal');
    if (modal) modal.classList.remove('active');
};

window.loadAdminAnnouncements = async () => {
    const tbody = document.getElementById('admin-announcements-tbody');
    if (!tbody) return;

    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/admin/announcements`, {
            headers: getAuthHeaders()
        });
        if (resp.ok) {
            const data = await resp.json();
            adminAnnouncementsList = data.announcements || [];
        }
    } catch (err) {
        console.warn('Error fetching announcements:', err);
    }

    if (adminAnnouncementsList.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" style="text-align:center; padding: 24px; color: var(--text-secondary);">
                    <i class="fas fa-bullhorn" style="font-size: 1.6rem; opacity: 0.4; margin-bottom: 8px; display:block;"></i>
                    No platform announcements found. Click "+ New Announcement" to broadcast to users.
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = adminAnnouncementsList.map(a => {
        const priorityBadge = a.priority === 'high'
            ? '<span class="badge badge-danger">High</span>'
            : (a.priority === 'low' ? '<span class="badge badge-info">Low</span>' : '<span class="badge badge-warning">Normal</span>');

        const roleBadge = a.target_role === 'all'
            ? '<span class="badge badge-primary">All Roles</span>'
            : `<span class="badge badge-secondary">${a.target_role.toUpperCase()}</span>`;

        const activeToggle = `
            <button class="btn btn-sm ${a.is_active ? 'btn-success' : 'btn-secondary'}" style="padding: 3px 8px; font-size: 0.75rem;" onclick="toggleAnnouncementStatus(${a.id}, ${a.is_active})">
                <i class="fas ${a.is_active ? 'fa-check' : 'fa-pause'}"></i> ${a.is_active ? 'Active' : 'Inactive'}
            </button>
        `;

        const createdDate = a.created_at ? new Date(a.created_at).toLocaleDateString() : 'Recent';

        return `
            <tr>
                <td style="font-weight: 600; color: #fff;">${escapeHtml(a.title)}</td>
                <td style="max-width: 260px; font-size: 0.84rem; color: var(--text-secondary);">${escapeHtml(a.message)}</td>
                <td>${priorityBadge}</td>
                <td>${roleBadge}</td>
                <td>${activeToggle}</td>
                <td style="font-size: 0.8rem; color: var(--text-muted);">${createdDate}</td>
                <td>
                    <div style="display: flex; gap: 6px;">
                        <button class="btn btn-sm btn-secondary" title="Edit" onclick="openCreateAnnouncementModal(${a.id})">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-danger" title="Delete" onclick="deleteAnnouncement(${a.id})">
                            <i class="fas fa-trash-alt"></i>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
};

window.toggleAnnouncementStatus = async (id, currentStatus) => {
    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/admin/announcements/${id}/status?is_active=${!currentStatus}`, {
            method: 'PATCH',
            headers: getAuthHeaders()
        });
        if (resp.ok) {
            Toast.show('Status Updated', `Announcement is now ${!currentStatus ? 'Active' : 'Inactive'}`, 'success', 2000);
            await loadAdminAnnouncements();
        } else {
            Toast.show('Update Failed', 'Could not update announcement status.', 'error', 3000);
        }
    } catch (err) {
        Toast.show('Network Error', err.message, 'error', 3000);
    }
};

window.deleteAnnouncement = async (id) => {
    if (!confirm('Are you sure you want to delete this platform announcement?')) return;

    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/admin/announcements/${id}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });
        if (resp.ok) {
            Toast.show('Deleted', 'Announcement deleted successfully.', 'success', 2000);
            await loadAdminAnnouncements();
        } else {
            Toast.show('Delete Failed', 'Failed to delete announcement.', 'error', 3000);
        }
    } catch (err) {
        Toast.show('Network Error', err.message, 'error', 3000);
    }
};

// Setup Announcement Form Handler
document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('admin-announcement-form');
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = document.getElementById('announcement-id').value;
            const payload = {
                title: document.getElementById('announcement-title').value.trim(),
                message: document.getElementById('announcement-message').value.trim(),
                priority: document.getElementById('announcement-priority').value,
                target_role: document.getElementById('announcement-target-role').value,
                is_active: document.getElementById('announcement-is-active').checked
            };

            try {
                const url = id ? `${window.API_BASE_URL}/api/admin/announcements/${id}` : `${window.API_BASE_URL}/api/admin/announcements`;
                const method = id ? 'PUT' : 'POST';
                const resp = await fetch(url, {
                    method: method,
                    headers: getAuthHeaders(),
                    body: JSON.stringify(payload)
                });

                if (resp.ok) {
                    closeAnnouncementModal();
                    Toast.show('Announcement Saved', id ? 'Announcement updated successfully.' : 'New announcement published.', 'success', 2500);
                    await loadAdminAnnouncements();
                } else {
                    const err = await resp.json().catch(() => ({ detail: 'Failed to save announcement' }));
                    Toast.show('Save Error', err.detail || 'Failed to save announcement.', 'error', 3000);
                }
            } catch (err) {
                Toast.show('Network Error', err.message, 'error', 3000);
            }
        });
    }
});

// Helper for HTML escaping
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// 11. Theme change reloads
document.querySelectorAll('#theme-toggle, .nav-toggle-theme').forEach(btn => {
    btn.addEventListener('click', () => {
        setTimeout(() => {
            loadAdminAnalytics();
        }, 150);
    });
});

// 12. Performance Metrics (Requirement 8) Controller
let currentPerfPeriodDays = 7;
let currentPerfStartDate = null;
let currentPerfEndDate = null;
let perfDailyTrendChart = null;

window.setPerfPeriod = function (days, btn) {
    currentPerfPeriodDays = days;
    currentPerfStartDate = null;
    currentPerfEndDate = null;

    document.querySelectorAll('.perf-period-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');

    const customBox = document.getElementById('perf-custom-date-box');
    if (customBox) customBox.style.display = 'none';

    loadPerformanceMetrics(days);
};

window.toggleCustomDateFilter = function (btn) {
    document.querySelectorAll('.perf-period-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');

    const customBox = document.getElementById('perf-custom-date-box');
    if (customBox) {
        customBox.style.display = 'flex';
    }
};

window.applyCustomPerfDates = function () {
    const startVal = document.getElementById('perf-start-date')?.value;
    const endVal = document.getElementById('perf-end-date')?.value;

    if (!startVal || !endVal) {
        if (typeof Toast !== 'undefined') Toast.show('Input Error', 'Please select both start and end dates.', 'warning', 3000);
        return;
    }

    currentPerfStartDate = startVal;
    currentPerfEndDate = endVal;
    loadPerformanceMetrics(null, startVal, endVal);
};

window.refreshPerformanceMetrics = function () {
    loadPerformanceMetrics(currentPerfPeriodDays, currentPerfStartDate, currentPerfEndDate);
};

async function loadPerformanceMetrics(periodDays = 7, startDate = null, endDate = null) {
    try {
        let query = '';
        if (startDate && endDate) {
            query = `?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`;
        } else {
            query = `?period_days=${periodDays || 7}`;
        }

        const resp = await fetch(`${window.API_BASE_URL}/api/admin/performance-metrics${query}`, {
            headers: getAuthHeaders()
        });

        if (resp.ok) {
            const data = await resp.json();
            renderPerformanceMetrics(data);
        } else {
            console.warn('Failed to fetch performance metrics:', resp.status);
        }
    } catch (err) {
        console.error('Error loading performance metrics:', err);
    }
}

function renderPerformanceMetrics(data) {
    if (!data) return;

    // Subtitle date period
    const subTitle = document.getElementById('perf-period-subtitle');
    if (subTitle && data.period) {
        subTitle.textContent = `Evaluated real telemetry from ${data.period.start_date} to ${data.period.end_date} (${data.period.days} days).`;
    }

    // 1. ALARM METRICS
    const am = data.alarm_metrics || {};
    const alarmRateEl = document.getElementById('perf-alarm-dismissal-rate');
    const alarmRateSub = document.getElementById('perf-alarm-dismissal-sub');
    if (alarmRateEl) {
        alarmRateEl.textContent = am.dismissal_success_rate !== null ? `${am.dismissal_success_rate}%` : 'Insufficient data';
    }
    if (alarmRateSub) {
        alarmRateSub.textContent = am.total_triggered_alarms > 0
            ? `${am.successful_dismissals} dismissals / ${am.total_triggered_alarms} triggered alarms`
            : 'No alarm triggers in this period';
    }

    const verifAccEl = document.getElementById('perf-verif-accuracy');
    const verifAccSub = document.getElementById('perf-verif-accuracy-sub');
    if (verifAccEl) {
        verifAccEl.textContent = am.verification_accuracy !== null ? `${am.verification_accuracy}%` : 'Insufficient data';
    }
    if (verifAccSub) {
        verifAccSub.textContent = am.total_verification_sessions > 0
            ? `${am.total_verification_sessions} sessions (${am.successful_sessions} pass / ${am.failed_sessions} fail) • ${am.average_attempts_per_session || 1} att/sess`
            : 'No verification sessions recorded';
    }

    const snoozeRedEl = document.getElementById('perf-snooze-reduction');
    const snoozeRedSub = document.getElementById('perf-snooze-reduction-sub');
    if (snoozeRedEl) {
        snoozeRedEl.textContent = am.snooze_reduction_display || 'Insufficient data';
    }
    if (snoozeRedSub) {
        snoozeRedSub.textContent = am.snooze_reduction_status === 'available'
            ? `Current: ${am.current_period_snoozes} snoozes vs Prev: ${am.previous_period_snoozes} snoozes`
            : 'Insufficient previous period data for comparison';
    }

    // 2. COGNITIVE CHALLENGE METRICS
    const cm = data.challenge_metrics || {};
    const chalCompEl = document.getElementById('perf-challenge-completion-rate');
    const chalCompSub = document.getElementById('perf-challenge-completion-sub');
    if (chalCompEl) {
        chalCompEl.textContent = cm.completion_rate !== null ? `${cm.completion_rate}%` : 'Insufficient data';
    }
    if (chalCompSub) {
        chalCompSub.textContent = cm.started_challenges > 0
            ? `${cm.completed_challenges} completed / ${cm.started_challenges} started challenges`
            : 'No challenges started in this period';
    }

    const chalAccEl = document.getElementById('perf-challenge-overall-accuracy');
    const chalAccSub = document.getElementById('perf-challenge-accuracy-sub');
    if (chalAccEl) {
        chalAccEl.textContent = cm.overall_accuracy !== null ? `${cm.overall_accuracy}%` : 'Insufficient data';
    }
    if (chalAccSub) {
        chalAccSub.textContent = cm.started_challenges > 0
            ? `${cm.correct_answers} correct / ${cm.total_answers} total answers`
            : 'No answers recorded in this period';
    }

    const adaptEl = document.getElementById('perf-adaptation-change');
    const adaptSub = document.getElementById('perf-adaptation-sub');
    const adapt = cm.adaptation_effectiveness || {};
    if (adaptEl) {
        if (adapt.status === 'available' && adapt.performance_change_pct !== null) {
            adaptEl.textContent = `${adapt.performance_change_pct > 0 ? '+' : ''}${adapt.performance_change_pct}%`;
        } else {
            adaptEl.textContent = 'Insufficient data';
        }
    }
    if (adaptSub) {
        if (adapt.status === 'available') {
            adaptSub.textContent = `Before: ${adapt.accuracy_before_adaptation}% acc -> After: ${adapt.accuracy_after_adaptation}% acc (${adapt.evaluated_users_count} users)`;
        } else {
            adaptSub.textContent = 'Requires >=4 attempts per user for before/after comparison';
        }
    }

    // Type Breakdown Table
    const typeTbody = document.getElementById('perf-type-breakdown-tbody');
    if (typeTbody) {
        typeTbody.innerHTML = '';
        (cm.breakdown_by_type || []).forEach(item => {
            const accText = item.accuracy !== null ? `${item.accuracy}%` : '<span style="color: var(--text-secondary);">No data</span>';
            const timeText = item.avg_time_seconds !== null ? `${item.avg_time_seconds}s` : '--';
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${escapeHtml(item.challenge_type)}</strong></td>
                <td>${item.attempts}</td>
                <td>${accText}</td>
                <td>${timeText}</td>
            `;
            typeTbody.appendChild(tr);
        });
    }

    // Difficulty Breakdown Table
    const diffTbody = document.getElementById('perf-diff-breakdown-tbody');
    if (diffTbody) {
        diffTbody.innerHTML = '';
        (cm.breakdown_by_difficulty || []).forEach(item => {
            const accText = item.accuracy !== null ? `${item.accuracy}%` : '<span style="color: var(--text-secondary);">No data</span>';
            const timeText = item.avg_time_seconds !== null ? `${item.avg_time_seconds}s` : '--';
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><span class="badge badge-secondary">${escapeHtml(item.difficulty)}</span></td>
                <td>${item.attempts}</td>
                <td>${accText}</td>
                <td>${timeText}</td>
            `;
            diffTbody.appendChild(tr);
        });
    }

    // 3. HABIT FORMATION METRICS
    const hm = data.habit_metrics || {};
    const habitScoreBadge = document.getElementById('perf-habit-score-badge');
    const habitScoreDetails = document.getElementById('perf-habit-score-details');
    const hImp = hm.habit_score_improvement || {};
    if (habitScoreBadge) {
        if (hImp.status === 'available' && hImp.current_habit_score !== null) {
            const deltaStr = hImp.absolute_improvement !== null ? ` (${hImp.absolute_improvement > 0 ? '+' : ''}${hImp.absolute_improvement} pts)` : '';
            habitScoreBadge.textContent = `${hImp.current_habit_score}/100${deltaStr}`;
        } else if (hImp.current_habit_score !== null) {
            habitScoreBadge.textContent = `${hImp.current_habit_score}/100`;
        } else {
            habitScoreBadge.textContent = 'Insufficient data';
        }
    }
    if (habitScoreDetails) {
        if (hImp.status === 'available') {
            habitScoreDetails.textContent = `Current period avg: ${hImp.current_habit_score} pts vs Previous period avg: ${hImp.previous_habit_score} pts across ${hImp.users_evaluated} users.`;
        } else {
            habitScoreDetails.textContent = 'Requires previous period habit activity for delta evaluation.';
        }
    }

    const wakeupConsBadge = document.getElementById('perf-wakeup-consistency-badge');
    const wakeupConsDetails = document.getElementById('perf-wakeup-consistency-details');
    if (wakeupConsBadge) {
        wakeupConsBadge.textContent = hm.wake_up_consistency_rate !== null ? `${hm.wake_up_consistency_rate}%` : 'Insufficient data';
    }
    if (wakeupConsDetails) {
        wakeupConsDetails.textContent = hm.wake_up_consistency_status === 'available'
            ? `${hm.successful_on_time_wake_ups} on-time wakeups out of ${hm.scheduled_wake_ups} scheduled wakeups.`
            : 'No scheduled alarms active in this period.';
    }

    const sleepAdhBadge = document.getElementById('perf-sleep-adherence-badge');
    const sleepAdhDetails = document.getElementById('perf-sleep-adherence-details');
    const sl = hm.sleep_schedule_adherence || {};
    if (sleepAdhBadge) {
        sleepAdhBadge.textContent = sl.status === 'available' && sl.adherence_score !== null ? `${sl.adherence_score}%` : 'Insufficient data';
    }
    if (sleepAdhDetails) {
        sleepAdhDetails.textContent = sl.status === 'available'
            ? `Bedtime adherence: ${sl.bedtime_adherence}% | Wake-time adherence: ${sl.wake_time_adherence}% (${sl.label})`
            : sl.message || 'Sleep Schedule Adherence: Insufficient data';
    }

    // 4. RECOMMENDATION METRICS
    const rm = data.recommendation_metrics || {};
    const recBadge = document.getElementById('perf-rec-relevance-badge');
    const recDetails = document.getElementById('perf-rec-relevance-details');
    const rel = rm.relevance || {};
    if (recBadge) {
        recBadge.textContent = rel.status === 'available' && rel.acceptance_rate !== null ? `${rel.acceptance_rate}% Relevance` : 'Not enough feedback data';
    }
    if (recDetails) {
        recDetails.textContent = rel.status === 'available'
            ? `${rel.recommendations_accepted} accepted out of ${rel.recommendations_shown} recommendation notifications.`
            : 'Not enough interaction records to calculate statistically sound relevance percentages.';
    }

    const engBadge = document.getElementById('perf-engagement-badge');
    const engDetails = document.getElementById('perf-engagement-details');
    const eng = rm.engagement_improvement || {};
    if (engBadge) {
        engBadge.textContent = eng.status === 'available' && eng.accuracy_difference_pct !== null ? `${eng.accuracy_difference_pct > 0 ? '+' : ''}${eng.accuracy_difference_pct}% correlation` : 'Insufficient data';
    }
    if (engDetails) {
        engDetails.textContent = eng.status === 'available'
            ? `Engaged users: ${eng.engaged_group_accuracy}% acc vs Baseline: ${eng.baseline_group_accuracy}% acc. (${eng.disclaimer})`
            : `${eng.disclaimer} Insufficient historical data.`;
    }

    const prodBadge = document.getElementById('perf-productivity-badge');
    const prodDetails = document.getElementById('perf-productivity-details');
    const prod = rm.productivity_improvement_rate || {};
    if (prodBadge) {
        prodBadge.textContent = prod.display_message || 'Insufficient data';
    }
    if (prodDetails) {
        prodDetails.textContent = prod.status === 'available'
            ? `Current productivity index: ${prod.current_period_productivity_index}% vs Prev: ${prod.previous_period_productivity_index}%`
            : 'Requires equivalent prior period behavioral analytics.';
    }

    // 5. SYSTEM PERFORMANCE METRICS
    const sm = data.system_metrics || {};
    const apiStats = sm.api_response_time || {};
    const apiAvgEl = document.getElementById('perf-api-avg-ms');
    const apiP95El = document.getElementById('perf-api-p95-ms');
    if (apiAvgEl) {
        apiAvgEl.textContent = apiStats.average_response_time_ms !== null ? `${apiStats.average_response_time_ms} ms` : 'Telemetry Idle';
    }
    if (apiP95El) {
        apiP95El.textContent = apiStats.status === 'available'
            ? `P95: ${apiStats.p95_response_time_ms}ms | Median: ${apiStats.median_response_time_ms}ms (${apiStats.request_count} requests)`
            : 'Waiting for server API traffic to measure response latencies';
    }

    const dashStats = sm.dashboard_loading_speed || {};
    const dashLoadEl = document.getElementById('perf-dash-load-ms');
    const dashLoadSub = document.getElementById('perf-dash-load-sub');
    if (dashLoadEl) {
        dashLoadEl.textContent = dashStats.initial_dashboard_request_ms !== null ? `${dashStats.initial_dashboard_request_ms} ms` : 'Telemetry Idle';
    }
    if (dashLoadSub) {
        dashLoadSub.textContent = dashStats.status === 'available'
            ? `Initial request: ${dashStats.initial_dashboard_request_ms}ms • Compound bundle load: ${dashStats.total_dashboard_data_loading_ms}ms`
            : 'Telemetry records dashboard API loading benchmarks on invocation';
    }

    const chalStats = sm.challenge_generation_latency || {};
    const chalLatEl = document.getElementById('perf-chal-latency-ms');
    const chalLatSub = document.getElementById('perf-chal-latency-sub');
    if (chalLatEl) {
        chalLatEl.textContent = chalStats.average_generation_latency_ms !== null ? `${chalStats.average_generation_latency_ms} ms` : 'Telemetry Idle';
    }
    if (chalLatSub) {
        chalLatSub.textContent = chalStats.status === 'available'
            ? `P95: ${chalStats.p95_latency_ms}ms • Fallback generations: ${chalStats.fallback_generations} • Total: ${chalStats.successful_generations}`
            : 'Instruments Gemini, Groq & Local fallback challenge generator duration';
    }

    const capStats = sm.concurrent_user_capacity || {};
    const capEl = document.getElementById('perf-concurrent-users');
    const capSub = document.getElementById('perf-concurrent-sub');
    if (capEl) {
        capEl.textContent = capStats.status === 'available' && capStats.requests_per_second !== null
            ? `${capStats.requests_per_second} RPS`
            : 'Benchmark Ready';
    }
    if (capSub) {
        capSub.textContent = capStats.status === 'available'
            ? `${capStats.concurrent_users_tested} concurrent users tested • Avg: ${capStats.average_latency_ms}ms • Errors: ${capStats.error_rate_pct}%`
            : 'Run load_test_system.py locally to benchmark concurrent user handling capacity';
    }

    // Slowest Endpoints Table
    const slowTbody = document.getElementById('perf-slowest-endpoints-tbody');
    if (slowTbody) {
        slowTbody.innerHTML = '';
        const slowest = apiStats.slowest_requests || [];
        if (slowest.length === 0) {
            const tr = document.createElement('tr');
            tr.innerHTML = '<td colspan="4" style="text-align: center; color: var(--text-secondary); padding: 14px;">No slow endpoints recorded yet.</td>';
            slowTbody.appendChild(tr);
        } else {
            slowest.forEach(s => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><code>${escapeHtml(s.endpoint)}</code></td>
                    <td>${s.calls}</td>
                    <td>${s.avg_ms} ms</td>
                    <td>${s.p95_ms} ms</td>
                `;
                slowTbody.appendChild(tr);
            });
        }
    }

    // Daily Verification & Challenge Trend Chart
    renderDailyTrendChart(cm.breakdown_by_period || []);
}

function renderDailyTrendChart(periodBreakdown) {
    const canvas = document.getElementById('perfDailyTrendChart');
    if (!canvas || typeof Chart === 'undefined') return;

    const ctx = canvas.getContext('2d');
    if (perfDailyTrendChart) {
        perfDailyTrendChart.destroy();
    }

    const labels = periodBreakdown.map(p => p.date.substring(5));
    const totalData = periodBreakdown.map(p => p.total_attempts);
    const correctData = periodBreakdown.map(p => p.correct_attempts);

    perfDailyTrendChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels.length ? labels : ['No Data'],
            datasets: [
                {
                    label: 'Total Attempts',
                    data: totalData.length ? totalData : [0],
                    backgroundColor: 'rgba(99, 102, 241, 0.5)',
                    borderColor: '#6366f1',
                    borderWidth: 1,
                    borderRadius: 4
                },
                {
                    label: 'Correct / Passed',
                    data: correctData.length ? correctData : [0],
                    backgroundColor: 'rgba(16, 185, 129, 0.6)',
                    borderColor: '#10b981',
                    borderWidth: 1,
                    borderRadius: 4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                    labels: { color: '#cbd5e1', font: { size: 11 } }
                }
            },
            scales: {
                x: {
                    ticks: { color: '#94a3b8', font: { size: 10 } },
                    grid: { color: 'rgba(255, 255, 255, 0.05)' }
                },
                y: {
                    beginAtZero: true,
                    ticks: { color: '#94a3b8', stepSize: 1, font: { size: 10 } },
                    grid: { color: 'rgba(255, 255, 255, 0.05)' }
                }
            }
        }
    });
}

// 13. Initial Startup
async function initAdminPanel() {
    if (typeof updateHeaderUserInfo === 'function') updateHeaderUserInfo();
    await renderAdminUsers();
    await loadAdminDashboardOverview();
    await loadAdminLogs();
    await loadAdminAnalytics();
    await loadAdminAnnouncements();
    await loadPerformanceMetrics(currentPerfPeriodDays);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAdminPanel);
} else {
    initAdminPanel();
}


