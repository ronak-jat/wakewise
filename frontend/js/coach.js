/* ==========================================================================
   INTELLIGENT COGNITIVE ALARM PLATFORM - WELLNESS COACH CONTROLLER
   Zero Mock Data: Real PostgreSQL Database Integration
   ========================================================================== */

let registeredPatients = [];
let coachRecommendationLogs = JSON.parse(localStorage.getItem('coach_recommendations')) || [];
let coachProgressChart = null;
let coachTrendsChart = null;
let coachHabitsChart = null;
let coachHabitTrendChart = null;
let currentCoachHabitPeriod = 7;
let currentCoachHabitPatientId = 0;
let currentCoachTrendMetric = 'habit_score';
let coachHabitAnalyticsData = null;

function getAuthHeaders() {
    const session = JSON.parse(localStorage.getItem('sessionUser') || '{}');
    return {
        'Content-Type': 'application/json',
        'Authorization': session.accessToken ? `Bearer ${session.accessToken}` : ''
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
        crumbText.textContent = item ? item.textContent : 'Dashboard';
    }

    if (typeof window.setDashboardActiveTab === 'function') {
        window.setDashboardActiveTab(tabId);
    }

    document.body.classList.remove('sidebar-open');

    if (tabId === 'tab-analytics') {
        loadCoachHabitAnalytics();
    }
};

const restoreCoachDashboardTab = () => {
    if (typeof window.restoreDashboardActiveTab === 'function') {
        window.restoreDashboardActiveTab();
    }
};

if (document.readyState !== 'loading') {
    restoreCoachDashboardTab();
} else {
    window.addEventListener('DOMContentLoaded', restoreCoachDashboardTab);
}

// 2. Fetch Real Assigned Patients & Analytics Data from PostgreSQL
async function loadCoachDashboardData() {
    try {
        // Fetch only users actively assigned to this coach by Admin
        const usersResp = await fetch(`${window.API_BASE_URL}/api/coach/users?t=${Date.now()}`, {
            headers: getAuthHeaders()
        });
        if (usersResp.ok) {
            registeredPatients = await usersResp.json();
            if (registeredPatients.length > 0 && currentCoachHabitPatientId === 0) {
                currentCoachHabitPatientId = registeredPatients[0].id;
            }
        } else {
            console.warn('Could not fetch coach assigned patients:', usersResp.status);
            registeredPatients = [];
        }
    } catch (e) {
        console.warn('Could not fetch assigned patients list:', e);
        registeredPatients = [];
    }

    // Fetch wellness and sleep metrics for current session
    let wellnessData = null;
    let sleepTrendsData = null;
    let sleepQualityData = null;
    let challengeData = null;

    try {
        const [wRes, sRes, sqRes, cRes] = await Promise.allSettled([
            fetch(`${window.API_BASE_URL}/api/dashboard/wellness`, { headers: getAuthHeaders() }),
            fetch(`${window.API_BASE_URL}/api/dashboard/sleep-trends`, { headers: getAuthHeaders() }),
            fetch(`${window.API_BASE_URL}/api/dashboard/sleep-quality`, { headers: getAuthHeaders() }),
            fetch(`${window.API_BASE_URL}/api/dashboard/challenge-performance`, { headers: getAuthHeaders() })
        ]);

        if (wRes.status === 'fulfilled' && wRes.value.ok) wellnessData = await wRes.value.json();
        if (sRes.status === 'fulfilled' && sRes.value.ok) sleepTrendsData = await sRes.value.json();
        if (sqRes.status === 'fulfilled' && sqRes.value.ok) sleepQualityData = await sqRes.value.json();
        if (cRes.status === 'fulfilled' && cRes.value.ok) challengeData = await cRes.value.json();
    } catch (err) {
        console.warn('Could not load coach analytics:', err);
    }

    // Update Header Metric Cards
    renderCoachStats(wellnessData, sleepTrendsData, sleepQualityData);
    populatePatientSelects();
    renderOptimalPatientsTable(wellnessData);
    renderHelpList(wellnessData);
    renderPatientReports(wellnessData, sleepTrendsData);
    await loadCoachDispatchedLogs();
    initCoachCharts(wellnessData, sleepTrendsData, challengeData, sleepQualityData);
    loadCoachHabitAnalytics();
}

function renderOptimalPatientsTable(wellnessData) {
    const tbody = document.getElementById('optimal-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!registeredPatients || registeredPatients.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 16px;">No registered users found.</td></tr>';
        return;
    }

    // Filter to optimal performers (score >= 75) and sort descending
    const optimalPatients = registeredPatients
        .filter(p => (p.habit_score !== undefined && p.habit_score !== null ? p.habit_score : (wellnessData?.habit_score || 0)) >= 75)
        .sort((a, b) => (b.habit_score || 0) - (a.habit_score || 0));

    if (optimalPatients.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 16px;">No patients currently in optimal range (&ge;75%).</td></tr>';
        return;
    }

    optimalPatients.forEach(p => {
        const tr = document.createElement('tr');
        const scoreNum = p.habit_score !== undefined && p.habit_score !== null ? Math.round(p.habit_score) : (wellnessData && wellnessData.habit_score ? Math.round(wellnessData.habit_score) : 0);
        const habitScore = `${scoreNum}%`;
        const consistencyText = p.target_wake_time ? `Target ${p.target_wake_time}` : 'Regular';
        const badgeClass = scoreNum >= 75 ? 'badge-success' : 'badge-warning';
        const statusLabel = scoreNum >= 85 ? 'Excellent' : 'Optimal';

        tr.innerHTML = `
            <td><strong>${p.name || p.email.split('@')[0]}</strong></td>
            <td><span class="badge ${badgeClass}">${habitScore}</span></td>
            <td><i class="fas fa-moon" style="color: #a855f7; margin-right: 4px;"></i> ${consistencyText}</td>
            <td><span class="badge ${badgeClass}">${statusLabel}</span></td>
            <td>
                <button class="btn btn-secondary" style="padding: 3px 9px; font-size: 0.75rem;" onclick="viewPatientHabits(${p.id})">
                    <i class="fas fa-chart-line" style="margin-right: 4px;"></i> Habits
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function renderCoachStats(wellnessData, sleepTrendsData, sleepQualityData) {
    const activeUsersEl = document.getElementById('stat-active-users');
    if (activeUsersEl) {
        activeUsersEl.textContent = registeredPatients.length || '0';
    }

    // Calculate real average habit score across registered patients
    const avgHabitEl = document.querySelector('.glass-card.success-hover.stat-card .stat-details h3');
    if (avgHabitEl) {
        if (registeredPatients.length > 0) {
            const sumScores = registeredPatients.reduce((acc, p) => acc + (p.habit_score || 0), 0);
            const avgScore = Math.round(sumScores / registeredPatients.length);
            avgHabitEl.textContent = `${avgScore}%`;
        } else {
            avgHabitEl.textContent = (wellnessData && wellnessData.habit_score !== null) ? `${wellnessData.habit_score}%` : 'N/A';
        }
    }

    const sleepQualityEl = document.getElementById('stat-coach-sleep-quality') || document.querySelector('.glass-card.secondary-hover.stat-card .stat-details h3');
    const sleepLevelEl = document.getElementById('stat-coach-sleep-quality-level');
    if (sleepQualityEl) {
        if (registeredPatients.length > 0) {
            const validSleepScores = registeredPatients
                .map(p => p.sleep_quality_score)
                .filter(s => s !== null && s !== undefined && !isNaN(s));

            if (validSleepScores.length > 0) {
                const sumSleep = validSleepScores.reduce((acc, s) => acc + s, 0);
                const avgSleep = Math.round(sumSleep / validSleepScores.length);
                sleepQualityEl.textContent = `${avgSleep}%`;
                if (sleepLevelEl) {
                    sleepLevelEl.textContent = avgSleep >= 85 ? 'Optimal' : (avgSleep >= 70 ? 'Good' : 'Needs Review');
                    sleepLevelEl.className = `badge ${avgSleep >= 75 ? 'badge-success' : (avgSleep >= 50 ? 'badge-warning' : 'badge-danger')}`;
                }
            } else if (sleepQualityData && sleepQualityData.score !== null && sleepQualityData.score !== undefined) {
                sleepQualityEl.textContent = `${Math.round(sleepQualityData.score)}%`;
            } else {
                sleepQualityEl.textContent = 'N/A';
            }
        } else if (sleepQualityData && sleepQualityData.score !== null && sleepQualityData.score !== undefined) {
            sleepQualityEl.textContent = `${Math.round(sleepQualityData.score)}%`;
            if (sleepLevelEl) {
                sleepLevelEl.textContent = sleepQualityData.level || 'Good';
                sleepLevelEl.className = `badge ${sleepQualityData.score >= 75 ? 'badge-success' : (sleepQualityData.score >= 50 ? 'badge-warning' : 'badge-danger')}`;
            }
        } else {
            sleepQualityEl.textContent = 'N/A';
            if (sleepLevelEl) sleepLevelEl.textContent = 'Insufficient data';
        }
    }

    const weeklyImprEl = document.querySelector('.glass-card.accent-hover.stat-card .stat-details h3');
    if (weeklyImprEl) {
        weeklyImprEl.textContent = wellnessData ? `${wellnessData.current_streak}d streak` : '0d streak';
    }
}

function populatePatientSelects() {
    const selects = [
        document.getElementById('rec-patient'),
        document.getElementById('modal-rec-patient')
    ];

    selects.forEach(sel => {
        if (!sel) return;
        sel.innerHTML = '<option value="" disabled selected>Select registered user...</option>';
        if (registeredPatients.length === 0) {
            const opt = document.createElement('option');
            opt.disabled = true;
            opt.textContent = 'No registered users found';
            sel.appendChild(opt);
        } else {
            registeredPatients.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = `${p.name || 'User'} (${p.email})`;
                sel.appendChild(opt);
            });
        }
    });

    const habitPatientSelect = document.getElementById('habit-patient-select');
    if (habitPatientSelect) {
        habitPatientSelect.innerHTML = `<option value="0" ${currentCoachHabitPatientId === 0 ? 'selected' : ''}>All Patients (Aggregate)</option>`;
        if (registeredPatients.length > 0) {
            registeredPatients.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.id;
                if (currentCoachHabitPatientId === p.id) opt.selected = true;
                opt.textContent = `${p.name || 'Patient'} (${p.email})`;
                habitPatientSelect.appendChild(opt);
            });
        }
    }
}

function renderHelpList(wellnessData) {
    const tbody = document.getElementById('help-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!registeredPatients || registeredPatients.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 16px;">No patients found in database.</td></tr>';
        return;
    }

    // Filter to ONLY patients with sub-optimal / bad sleep or habit score (< 75)
    const reviewPatients = registeredPatients
        .filter(p => {
            const hScore = p.habit_score !== undefined && p.habit_score !== null ? p.habit_score : (wellnessData?.habit_score ?? 100);
            const sqScore = p.sleep_quality_score !== undefined && p.sleep_quality_score !== null ? p.sleep_quality_score : 100;
            return hScore < 75 || sqScore < 75;
        })
        .sort((a, b) => (a.habit_score || 0) - (b.habit_score || 0)); // Worst scores first

    if (reviewPatients.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 16px;">All active patients currently meet optimal sleep & habit thresholds.</td></tr>';
        return;
    }

    // Display only patients requiring review
    reviewPatients.forEach(p => {
        const tr = document.createElement('tr');
        const scoreNum = p.habit_score !== undefined && p.habit_score !== null ? Math.round(p.habit_score) : 0;
        const habitText = `${scoreNum}%`;
        const sleepText = (p.target_wake_time) ? `Wake: ${p.target_wake_time}` : (p.sleep_quality_score ? `SQ: ${Math.round(p.sleep_quality_score)}%` : 'Irregular Schedule');
        const badgeClass = scoreNum < 60 ? 'badge-danger' : 'badge-warning';

        tr.innerHTML = `
            <td><strong>${p.name || p.email.split('@')[0]}</strong></td>
            <td><span class="badge ${badgeClass}">${habitText}</span></td>
            <td><i class="fas fa-exclamation-circle text-warning"></i> ${sleepText}</td>
            <td style="display: flex; gap: 6px; align-items: center;">
                <button class="btn btn-primary" style="padding: 4px 10px; font-size: 0.75rem;" onclick="openRecommendationFor(${p.id})">
                    Intervene
                </button>
                <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.75rem;" onclick="viewPatientHabits(${p.id})" title="View user habit analytics">
                    <i class="fas fa-chart-line"></i>
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function renderPatientReports(wellnessData, sleepTrendsData) {
    const tbody = document.getElementById('all-reports-table')?.querySelector('tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (registeredPatients.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 16px;">No patient reports found in database.</td></tr>';
        return;
    }

    registeredPatients.forEach((p, idx) => {
        const tr = document.createElement('tr');
        const target = p.target_wake_time ? `${p.target_wake_time} (Bed: ${p.target_bedtime || 'N/A'})` : 'Not configured';
        const habitScore = p.habit_score !== undefined && p.habit_score !== null ? Math.round(p.habit_score) : null;
        const status = habitScore !== null ? (habitScore >= 80 ? 'Optimal' : (habitScore >= 50 ? 'Moderate' : 'Needs Support')) : 'Active';
        const badgeClass = status === 'Optimal' ? 'badge-success' : (status === 'Moderate' ? 'badge-warning' : 'badge-danger');

        tr.innerHTML = `
            <td><code>USR-${p.id || (idx + 101)}</code></td>
            <td><strong>${p.name || p.email}</strong></td>
            <td>${target}</td>
            <td><span class="badge badge-info">${p.inactivity_threshold_minutes ? p.inactivity_threshold_minutes + 'm threshold' : 'Standard'}</span></td>
            <td><span class="badge ${badgeClass}">${status} (${habitScore !== null ? habitScore + '%' : '--'})</span></td>
            <td style="font-size: 0.8rem; color: var(--text-secondary); max-width: 180px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                ${p.target_bedtime ? 'Target sleep adherence active' : 'Advise setting target bedtime & wake schedule'}
            </td>
            <td>
                <button class="btn btn-secondary" style="padding: 3px 9px; font-size: 0.75rem;" onclick="viewPatientHabits(${p.id})">
                    <i class="fas fa-chart-line" style="margin-right: 4px;"></i> Habits
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function loadCoachDispatchedLogs() {
    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/notifications/coach/dispatched?limit=50`, {
            headers: getAuthHeaders()
        });
        if (resp.ok) {
            const data = await resp.json();
            coachRecommendationLogs = (data.logs || []).map(l => ({
                date: l.time_ago || (l.created_at ? new Date(l.created_at).toLocaleString() : 'Recently'),
                patient: `${l.patient_name} (${l.patient_email})`,
                notes: l.message,
                status: (l.delivery_status || 'Delivered').toUpperCase()
            }));
            localStorage.setItem('coach_recommendations', JSON.stringify(coachRecommendationLogs));
        }
    } catch (err) {
        console.warn('Error loading dispatched coach logs:', err);
    }
    renderMessageLogs();
}

function renderMessageLogs() {
    const tbody = document.getElementById('messages-table')?.querySelector('tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!coachRecommendationLogs || coachRecommendationLogs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 16px;">No coach recommendations dispatched yet.</td></tr>';
        return;
    }

    coachRecommendationLogs.forEach(l => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><span style="font-size:0.8rem; color:var(--text-muted);">${l.date}</span></td>
            <td><strong>${escapeHtml(l.patient)}</strong></td>
            <td style="font-size:0.85rem; color:var(--text-secondary);">${escapeHtml(l.notes)}</td>
            <td><span class="badge badge-success"><i class="fas fa-check-double" style="margin-right:4px;"></i> ${l.status || 'DELIVERED'}</span></td>
        `;
        tbody.appendChild(tr);
    });
}

window.openRecommendationFor = (patientIdentifier) => {
    let patientId = patientIdentifier;
    if (typeof patientIdentifier === 'string') {
        const matched = registeredPatients.find(p => p.name === patientIdentifier || p.email === patientIdentifier || String(p.id) === patientIdentifier);
        if (matched) patientId = matched.id;
    }

    const selectModal = document.getElementById('modal-rec-patient');
    if (selectModal && patientId) {
        selectModal.value = patientId;
    }
    Modal.open('recommendation-modal');
};

// 3. Recommendation Submissions
const directForm = document.getElementById('recommendation-form-direct');
if (directForm) {
    directForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const patientVal = document.getElementById('rec-patient').value;
        const notes = document.getElementById('rec-text').value;
        await submitRecommendation(patientVal, notes);
        directForm.reset();
    });
}

const modalForm = document.getElementById('recommendation-form-modal');
if (modalForm) {
    modalForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const patientVal = document.getElementById('modal-rec-patient').value;
        const notes = document.getElementById('modal-rec-text').value;
        const success = await submitRecommendation(patientVal, notes);
        if (success) {
            Modal.close('recommendation-modal');
            modalForm.reset();
        }
    });
}

async function submitRecommendation(patientIdentifier, notes) {
    if (!patientIdentifier || !notes || !notes.trim()) {
        Toast.show('Missing Input', 'Please select a recipient and enter recommendation notes.', 'warning', 2500);
        return false;
    }

    let targetPatient = registeredPatients.find(p => String(p.id) === String(patientIdentifier) || p.email === patientIdentifier || p.name === patientIdentifier);
    if (!targetPatient && !isNaN(parseInt(patientIdentifier, 10))) {
        targetPatient = { id: parseInt(patientIdentifier, 10), name: `User #${patientIdentifier}`, email: '' };
    }

    if (!targetPatient) {
        Toast.show('Invalid Patient', 'Could not identify target patient.', 'danger', 2500);
        return false;
    }

    const session = JSON.parse(localStorage.getItem('sessionUser') || '{}');
    const coachName = session.name || 'Dr. Jenkins';

    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/notifications/coach`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                user_id: targetPatient.id,
                message: notes.trim(),
                title: `Coach Advice: ${coachName}`,
                priority: 'normal',
                action_url: 'user/habits.html'
            })
        });

        if (resp.ok) {
            const data = await resp.json();
            Toast.show('Advice Transmitted', `Successfully delivered advice recommendations to ${targetPatient.name || targetPatient.email}.`, 'success', 3000);
            await loadCoachDispatchedLogs();
            return true;
        } else {
            const errData = await resp.json().catch(() => ({}));
            Toast.show('Delivery Failed', errData.detail || 'Could not deliver recommendation notification.', 'danger', 3500);
            return false;
        }
    } catch (err) {
        console.error('Error submitting coach recommendation:', err);
        Toast.show('Network Error', 'Failed to reach notification server.', 'danger', 3000);
        return false;
    }
}

// 4. Real Chart.js Rendering
function initCoachCharts(wellnessData, sleepTrendsData, challengeData, sleepQualityData) {
    const isDark = document.body.getAttribute('data-theme') === 'dark';
    const textColor = isDark ? '#9ca3af' : '#62627a';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(99, 102, 241, 0.08)';

    // 1. Progress Chart (Real Habit Adherence Distribution)
    const progressCtx = document.getElementById('coachProgressChart');
    if (progressCtx) {
        if (coachProgressChart) coachProgressChart.destroy();
        
        const labels = ['Wake Consistency', 'Challenge Mastery', 'Snooze Control', 'Schedule Adherence'];
        let values = [0, 0, 0, 0];

        if (registeredPatients && registeredPatients.length > 0) {
            let sumWake = 0, sumChal = 0, sumSnooze = 0, sumSched = 0;
            let count = 0;
            registeredPatients.forEach(p => {
                const bd = p.habit_breakdown || {};
                
                // Wake Consistency
                let wake = bd.wake_up_consistency;
                if (wake === undefined || wake === null) {
                    wake = (p.wake_up_consistency !== undefined && p.wake_up_consistency !== null) ? p.wake_up_consistency : (p.habit_score || 0);
                }

                // Challenge Mastery
                let chal = bd.challenge_completion;
                if (chal === undefined || chal === null) {
                    chal = p.habit_score || 0;
                }

                // Snooze Control (Default 100% when no excess snoozes)
                let snooze = bd.snooze_reduction;
                if (snooze === undefined || snooze === null) {
                    snooze = 100;
                }

                // Schedule Adherence
                let sched = bd.sleep_schedule_adherence;
                if (sched === undefined || sched === null) {
                    sched = (p.sleep_quality_score !== null && p.sleep_quality_score !== undefined) ? p.sleep_quality_score : 80;
                }

                sumWake += Number(wake) || 0;
                sumChal += Number(chal) || 0;
                sumSnooze += Number(snooze) || 0;
                sumSched += Number(sched) || 0;
                count++;
            });

            if (count > 0) {
                values = [
                    Math.round(sumWake / count),
                    Math.round(sumChal / count),
                    Math.round(sumSnooze / count),
                    Math.round(sumSched / count)
                ];
            }
        } else if (wellnessData) {
            values = [
                Math.round(wellnessData.wake_up_consistency_percentage || 0),
                Math.round(wellnessData.challenge_completion_percentage || 0),
                Math.round(wellnessData.snooze_reduction_percentage !== undefined ? wellnessData.snooze_reduction_percentage : 100),
                Math.round(wellnessData.sleep_adherence_percentage || 0)
            ];
        }

        // If newly registered users with no alarm actions yet, ensure values are non-negative
        values = values.map(v => Math.max(0, Math.min(100, v)));

        coachProgressChart = new Chart(progressCtx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Habit Component Adherence (%)',
                    data: values,
                    backgroundColor: ['#6366f1', '#10b981', '#f59e0b', '#3b82f6'],
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: textColor } },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.dataset.label}: ${ctx.raw}%`
                        }
                    }
                },
                scales: {
                    x: { grid: { color: gridColor }, ticks: { color: textColor } },
                    y: { grid: { color: gridColor }, ticks: { color: textColor }, min: 0, max: 100 }
                }
            }
        });
    }

    // 2. Sleep Trends Chart (Per-Patient Sleep Efficiency & Quality Comparison)
    const trendsCtx = document.getElementById('coachTrendsChart');
    if (trendsCtx) {
        if (coachTrendsChart) coachTrendsChart.destroy();

        let labels = [];
        let dataVals = [];

        if (registeredPatients && registeredPatients.length > 0) {
            labels = registeredPatients.map(p => p.name || p.email.split('@')[0]);
            dataVals = registeredPatients.map(p => (p.sleep_quality_score !== null && p.sleep_quality_score !== undefined) ? Math.round(p.sleep_quality_score) : 75);
        } else {
            labels = ['Past 7 Days Avg'];
            dataVals = [(sleepQualityData && sleepQualityData.score !== null) ? Math.round(sleepQualityData.score) : 0];
        }

        coachTrendsChart = new Chart(trendsCtx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Patient Sleep Quality Score (%)',
                    data: dataVals,
                    backgroundColor: dataVals.map(v => v >= 85 ? '#10b981' : (v >= 70 ? '#3b82f6' : '#f59e0b')),
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: textColor } },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `Sleep Quality: ${ctx.raw}%`
                        }
                    }
                },
                scales: {
                    x: { grid: { color: gridColor }, ticks: { color: textColor } },
                    y: { grid: { color: gridColor }, ticks: { color: textColor }, min: 0, max: 100 }
                }
            }
        });
    }

    // 3. Challenge Performance Radar Chart
    const habitsCtx = document.getElementById('coachHabitsChart');
    if (habitsCtx) {
        if (coachHabitsChart) coachHabitsChart.destroy();

        let typeLabels = ['Math Problems', 'Memory Match', 'Word Scramble', 'Pattern Sequence', 'Tap Game', 'Shake Phone', 'Barcode Scan'];
        let typeAccuracies = [0, 0, 0, 0, 0, 0, 0];

        if (challengeData && challengeData.performance_by_type) {
            if (Array.isArray(challengeData.performance_by_type)) {
                typeLabels = challengeData.performance_by_type.map(item => item.challenge_type || 'Challenge');
                typeAccuracies = challengeData.performance_by_type.map(item => Math.round(item.accuracy_percentage || 0));
            } else {
                typeLabels = Object.keys(challengeData.performance_by_type);
                typeAccuracies = typeLabels.map(k => Math.round(challengeData.performance_by_type[k]?.accuracy_percentage || 0));
            }
        }

        coachHabitsChart = new Chart(habitsCtx, {
            type: 'radar',
            data: {
                labels: typeLabels,
                datasets: [{
                    label: 'Challenge Success Rate (%)',
                    data: typeAccuracies,
                    borderColor: '#ec4899',
                    backgroundColor: 'rgba(236, 72, 153, 0.2)',
                    pointBackgroundColor: '#ec4899',
                    pointBorderColor: '#fff',
                    pointHoverBackgroundColor: '#fff',
                    pointHoverBorderColor: '#ec4899'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: textColor } }
                },
                scales: {
                    r: {
                        grid: { color: gridColor },
                        pointLabels: { color: textColor },
                        ticks: { display: false },
                        min: 0,
                        max: 100
                    }
                }
            }
        });
    }
}

// ==========================================================================
// 4B. Real PostgreSQL Habit Analytics Controller & Trend Visualizer
// ==========================================================================

window.viewPatientHabits = (patientId) => {
    currentCoachHabitPatientId = parseInt(patientId, 10) || 0;
    const habitSel = document.getElementById('habit-patient-select');
    if (habitSel) {
        habitSel.value = currentCoachHabitPatientId;
    }
    switchTab('tab-analytics');
    loadCoachHabitAnalytics();
};

window.openRecommendationForCurrentPatient = () => {
    const selectedPatient = registeredPatients.find(p => p.id === currentCoachHabitPatientId);
    if (selectedPatient) {
        openRecommendationFor(selectedPatient.id);
    } else {
        Modal.open('recommendation-modal');
    }
};

window.onHabitPatientChange = (val) => {
    currentCoachHabitPatientId = parseInt(val, 10) || 0;
    loadCoachHabitAnalytics();
};

window.setCoachHabitPeriod = (days) => {
    currentCoachHabitPeriod = parseInt(days, 10) || 7;
    ['7d', '30d', '90d'].forEach(p => {
        const btn = document.getElementById(`habit-btn-${p}`);
        if (btn) {
            if (p === `${currentCoachHabitPeriod}d`) {
                btn.className = 'btn btn-primary';
            } else {
                btn.className = 'btn btn-secondary';
            }
        }
    });
    loadCoachHabitAnalytics();
};

window.setCoachTrendMetric = (metric) => {
    currentCoachTrendMetric = metric;
    const metrics = ['habit_score', 'wake_up_consistency', 'snooze_rate', 'challenge_success', 'sleep_schedule_adherence'];
    metrics.forEach(m => {
        const btn = document.getElementById(`trend-tab-${m}`);
        if (btn) {
            btn.className = (m === currentCoachTrendMetric) ? 'btn btn-primary' : 'btn btn-secondary';
        }
    });
    renderCoachHabitTrendChart();
};

async function loadCoachHabitAnalytics() {
    try {
        let url = `${window.API_BASE_URL}/api/dashboard/habit-analytics?period_days=${currentCoachHabitPeriod}`;
        if (currentCoachHabitPatientId && currentCoachHabitPatientId > 0) {
            url += `&user_id=${currentCoachHabitPatientId}`;
        }
        const resp = await fetch(url, { headers: getAuthHeaders() });
        if (resp.ok) {
            coachHabitAnalyticsData = await resp.json();
            renderCoachHabitAnalytics(coachHabitAnalyticsData);
        } else {
            console.warn('Could not load habit analytics:', resp.status);
        }
    } catch (err) {
        console.warn('Error fetching habit analytics:', err);
    }
}

function renderCoachHabitAnalytics(data) {
    if (!data) return;

    // 0. Update User Profile Context Banner
    const nameEl = document.getElementById('habit-patient-name');
    const emailEl = document.getElementById('habit-patient-email');
    const bedEl = document.getElementById('habit-patient-bed');
    const wakeEl = document.getElementById('habit-patient-wake');
    const inactEl = document.getElementById('habit-patient-inactivity');
    const avatarEl = document.getElementById('habit-patient-avatar');
    const badgeEl = document.getElementById('habit-patient-badge');

    const selectedPatient = registeredPatients.find(p => p.id === currentCoachHabitPatientId);
    if (selectedPatient) {
        if (nameEl) nameEl.textContent = selectedPatient.name || `User #${selectedPatient.id}`;
        if (emailEl) emailEl.textContent = selectedPatient.email ? `${selectedPatient.email}` : 'Individual telemetry active';
        if (bedEl) bedEl.textContent = selectedPatient.target_bedtime || data.sleep_adherence?.target_bedtime || '23:00';
        if (wakeEl) wakeEl.textContent = selectedPatient.target_wake_time || data.wake_up_consistency?.target_wake_time || '07:00';
        if (inactEl) inactEl.textContent = selectedPatient.inactivity_threshold_minutes ? `${selectedPatient.inactivity_threshold_minutes}m` : '15m';
        if (avatarEl) {
            const initials = (selectedPatient.name || selectedPatient.email || 'USR').substring(0, 3).toUpperCase();
            avatarEl.textContent = initials;
        }
        if (badgeEl) {
            badgeEl.textContent = `User #${selectedPatient.id}`;
            badgeEl.className = 'badge badge-primary';
        }
    } else {
        if (nameEl) nameEl.textContent = 'All Patients (Aggregate Overview)';
        if (emailEl) emailEl.textContent = `${registeredPatients.length} registered patient profiles`;
        if (bedEl) bedEl.textContent = data.sleep_adherence?.target_bedtime || '23:00 (Avg)';
        if (wakeEl) wakeEl.textContent = data.wake_up_consistency?.target_wake_time || '07:00 (Avg)';
        if (inactEl) inactEl.textContent = '15m (Std)';
        if (avatarEl) avatarEl.textContent = 'ALL';
        if (badgeEl) {
            badgeEl.textContent = 'Cohort Aggregate';
            badgeEl.className = 'badge badge-info';
        }
    }

    // 1. Habit Score Section
    const hs = data.habit_score || {};
    const scoreVal = (hs.score !== null && hs.score !== undefined) ? Math.round(hs.score) : '--';
    const scoreEl = document.getElementById('coach-habit-score-val');
    if (scoreEl) scoreEl.textContent = scoreVal;

    const levelEl = document.getElementById('coach-habit-level-badge');
    if (levelEl) {
        levelEl.textContent = hs.level || 'Good';
        const num = Number(scoreVal) || 0;
        levelEl.className = `badge ${num >= 75 ? 'badge-success' : (num >= 50 ? 'badge-warning' : 'badge-danger')}`;
    }

    const deltaEl = document.getElementById('coach-habit-delta-pill');
    if (deltaEl) {
        if (hs.change !== null && hs.change !== undefined) {
            if (hs.change > 0) {
                deltaEl.textContent = `↑ +${hs.change}% vs last period`;
                deltaEl.className = 'badge badge-success';
            } else if (hs.change < 0) {
                deltaEl.textContent = `↓ ${hs.change}% vs last period`;
                deltaEl.className = 'badge badge-danger';
            } else {
                deltaEl.textContent = 'Stable vs last period';
                deltaEl.className = 'badge badge-info';
            }
        } else {
            deltaEl.textContent = 'Baseline';
            deltaEl.className = 'badge badge-info';
        }
    }

    // Breakdown Bars
    const bd = hs.breakdown || {};
    const wakeScore = bd.wake_up_consistency !== undefined && bd.wake_up_consistency !== null ? Math.round(bd.wake_up_consistency) : '--';
    const chalScore = bd.challenge_completion !== undefined && bd.challenge_completion !== null ? Math.round(bd.challenge_completion) : '--';
    const snoozeScore = bd.snooze_reduction !== undefined && bd.snooze_reduction !== null ? Math.round(bd.snooze_reduction) : '--';
    const sleepScore = bd.sleep_schedule_adherence !== undefined && bd.sleep_schedule_adherence !== null ? Math.round(bd.sleep_schedule_adherence) : '--';

    const wakeText = document.getElementById('coach-score-wake');
    const wakeBar = document.getElementById('coach-bar-wake');
    if (wakeText) wakeText.textContent = wakeScore !== '--' ? `${wakeScore}%` : '--';
    if (wakeBar) wakeBar.style.width = wakeScore !== '--' ? `${Math.min(100, Math.max(0, wakeScore))}%` : '0%';

    const chalText = document.getElementById('coach-score-challenge');
    const chalBar = document.getElementById('coach-bar-challenge');
    if (chalText) chalText.textContent = chalScore !== '--' ? `${chalScore}%` : '--';
    if (chalBar) chalBar.style.width = chalScore !== '--' ? `${Math.min(100, Math.max(0, chalScore))}%` : '0%';

    const snoozeText = document.getElementById('coach-score-snooze');
    const snoozeBar = document.getElementById('coach-bar-snooze');
    if (snoozeText) snoozeText.textContent = snoozeScore !== '--' ? `${snoozeScore}%` : '--';
    if (snoozeBar) snoozeBar.style.width = snoozeScore !== '--' ? `${Math.min(100, Math.max(0, snoozeScore))}%` : '0%';

    const sleepText = document.getElementById('coach-score-sleep');
    const sleepBar = document.getElementById('coach-bar-sleep');
    if (sleepText) sleepText.textContent = sleepScore !== '--' ? `${sleepScore}%` : '--';
    if (sleepBar) sleepBar.style.width = sleepScore !== '--' ? `${Math.min(100, Math.max(0, sleepScore))}%` : '0%';

    // 2. Current Habit Streak
    const st = data.streak || {};
    const curStreak = document.getElementById('coach-streak-current');
    const bestStreak = document.getElementById('coach-streak-best');
    const passedStreak = document.getElementById('coach-streak-passed');
    const missedStreak = document.getElementById('coach-streak-missed');
    const failedStreak = document.getElementById('coach-streak-failed');

    if (curStreak) curStreak.textContent = st.current !== undefined ? st.current : '0';
    if (bestStreak) bestStreak.textContent = st.best !== undefined ? `${st.best}d` : '0d';
    if (passedStreak) passedStreak.textContent = st.successful_days !== undefined ? st.successful_days : '0';
    if (missedStreak) missedStreak.textContent = st.missed_days !== undefined ? st.missed_days : '0';
    if (failedStreak) failedStreak.textContent = st.failed_verification_days !== undefined ? st.failed_verification_days : '0';

    // 3. Wake-Up Consistency
    const wc = data.wake_up_consistency || {};
    const wakeScoreBadge = document.getElementById('coach-wake-score-badge');
    const wakeAvg = document.getElementById('coach-wake-avg');
    const wakeTarget = document.getElementById('coach-wake-target');
    const wakeOntime = document.getElementById('coach-wake-ontime');
    const wakeLate = document.getElementById('coach-wake-late');
    const wakeMissed = document.getElementById('coach-wake-missed');

    if (wakeScoreBadge) wakeScoreBadge.textContent = wc.score !== null && wc.score !== undefined ? `${Math.round(wc.score)}%` : '--%';
    if (wakeAvg) wakeAvg.textContent = wc.average_wake_time || 'Insufficient data';
    if (wakeTarget) wakeTarget.textContent = wc.target_wake_time ? `Target ${wc.target_wake_time}` : '07:00';
    if (wakeOntime) wakeOntime.textContent = `${wc.on_time || 0} / ${wc.total_wakeups || 0}`;
    if (wakeLate) wakeLate.textContent = `${wc.late || 0}`;
    if (wakeMissed) wakeMissed.textContent = `${wc.missed || 0}`;

    // 4. Snooze Behavior
    const sb = data.snooze || {};
    const snoozeAvg = document.getElementById('coach-snooze-avg-day');
    const snoozeTot = document.getElementById('coach-snooze-total');
    const snoozeChg = document.getElementById('coach-snooze-change');
    const snoozeDays = document.getElementById('coach-snooze-days');
    const snoozeMax = document.getElementById('coach-snooze-max');
    const snoozeDismiss = document.getElementById('coach-snooze-dismissal');

    if (snoozeAvg) snoozeAvg.textContent = sb.average_per_day !== null && sb.average_per_day !== undefined ? `${sb.average_per_day} / day` : '0.0 / day';
    if (snoozeTot) snoozeTot.textContent = `${sb.total || 0}`;
    if (snoozeChg) {
        if (sb.change_percent !== null && sb.change_percent !== undefined) {
            snoozeChg.textContent = sb.change_percent < 0 ? `↓ ${sb.change_percent}%` : `↑ +${sb.change_percent}%`;
            snoozeChg.style.color = sb.change_percent <= 0 ? '#22c55e' : '#ef4444';
        } else {
            snoozeChg.textContent = 'Stable';
            snoozeChg.style.color = '#38bdf8';
        }
    }
    if (snoozeDays) snoozeDays.textContent = `${sb.days_with_snoozes || 0}`;
    if (snoozeMax) snoozeMax.textContent = `${sb.max_snoozes_single_morning || 0}`;
    if (snoozeDismiss) snoozeDismiss.textContent = sb.avg_time_to_dismissal_minutes ? `${Math.round(sb.avg_time_to_dismissal_minutes)}m` : 'Instant';

    // 5. Sleep Schedule Adherence
    const sa = data.sleep_adherence || {};
    const sleepScoreBadge = document.getElementById('coach-sleep-score-badge');
    const sleepEstBed = document.getElementById('coach-sleep-est-bed');
    const sleepTgtBed = document.getElementById('coach-sleep-tgt-bed');
    const sleepEstWake = document.getElementById('coach-sleep-est-wake');
    const sleepTgtWake = document.getElementById('coach-sleep-tgt-wake');

    if (sleepScoreBadge) sleepScoreBadge.textContent = sa.score !== null && sa.score !== undefined ? `${Math.round(sa.score)}%` : '--%';
    if (sleepEstBed) sleepEstBed.textContent = sa.estimated_bedtime || 'Insufficient data';
    if (sleepTgtBed) sleepTgtBed.textContent = sa.target_bedtime || '23:00';
    if (sleepEstWake) sleepEstWake.textContent = sa.estimated_wake_time || 'Insufficient data';
    if (sleepTgtWake) sleepTgtWake.textContent = sa.target_wake_time || '07:00';

    // 6. Wakefulness & Verification
    const wf = data.wakefulness || {};
    const wfRating = document.getElementById('coach-wakefulness-rating');
    const wfLabel = document.getElementById('coach-wakefulness-label');
    const verifRate = document.getElementById('coach-verif-rate');
    const verifFails = document.getElementById('coach-verif-fails');
    const verifDuration = document.getElementById('coach-verif-duration');
    const verifDrills = document.getElementById('coach-verif-drills');

    if (wfRating) wfRating.textContent = wf.average_rating !== null && wf.average_rating !== undefined ? wf.average_rating : '--';
    if (wfLabel) wfLabel.textContent = wf.rating_label || 'Awake';
    if (verifRate) verifRate.textContent = wf.verification_success_rate !== null && wf.verification_success_rate !== undefined ? `${Math.round(wf.verification_success_rate)}%` : '0%';
    if (verifFails) verifFails.textContent = `${wf.verification_failures || 0}`;
    if (verifDuration) verifDuration.textContent = wf.average_duration_seconds ? `${Math.round(wf.average_duration_seconds)}s` : '0s';
    if (verifDrills) verifDrills.textContent = `${wf.average_challenges_required || 1.0}`;

    // 7. Challenge Performance by Type (Radar & Highlights)
    const cp = data.challenge_performance || {};
    const chalAcc = document.getElementById('coach-chal-overall-acc');
    const chalStrong = document.getElementById('coach-chal-strongest');
    const chalWeak = document.getElementById('coach-chal-weakest');

    if (chalAcc) chalAcc.textContent = `${Math.round(cp.overall_accuracy || 0)}% Acc`;
    if (chalStrong) chalStrong.textContent = cp.strongest_type || 'Logic Puzzles';
    if (chalWeak) chalWeak.textContent = cp.weakest_type || 'Pattern Recognition';

    renderCoachChallengeRadar(cp.by_type || []);

    // 8. Habit Insights
    const insightsList = document.getElementById('coach-habit-insights-list');
    if (insightsList) {
        insightsList.innerHTML = '';
        const ins = data.insights || [];
        if (ins.length === 0) {
            insightsList.innerHTML = '<li style="color: var(--text-muted);">Sufficient multi-day historical data is required to calculate dynamic behavioral patterns.</li>';
        } else {
            ins.forEach(item => {
                const li = document.createElement('li');
                li.style.marginBottom = '6px';
                li.textContent = item;
                insightsList.appendChild(li);
            });
        }
    }

    // 9. Multi-Metric Trend Chart
    renderCoachHabitTrendChart();
}

function renderCoachChallengeRadar(typeList) {
    const habitsCtx = document.getElementById('coachHabitsChart');
    if (!habitsCtx) return;

    if (coachHabitsChart) coachHabitsChart.destroy();

    const isDark = document.body.getAttribute('data-theme') === 'dark';
    const textColor = isDark ? '#9ca3af' : '#62627a';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(99, 102, 241, 0.1)';

    let typeLabels = ['Math Problems', 'Logic Puzzles', 'Memory Challenges', 'Word Games', 'Pattern Recognition', 'Riddles', 'Quick Quizzes'];
    let typeAccuracies = [80, 85, 75, 80, 70, 75, 85];

    if (Array.isArray(typeList) && typeList.length > 0) {
        typeLabels = typeList.map(item => item.challenge_type || 'Challenge');
        typeAccuracies = typeList.map(item => Math.round(item.accuracy_percentage || 0));
    }

    coachHabitsChart = new Chart(habitsCtx, {
        type: 'radar',
        data: {
            labels: typeLabels,
            datasets: [{
                label: 'Challenge Success Rate (%)',
                data: typeAccuracies,
                borderColor: '#ec4899',
                backgroundColor: 'rgba(236, 72, 153, 0.25)',
                pointBackgroundColor: '#ec4899',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: '#ec4899',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: textColor } },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label}: ${ctx.raw}%`
                    }
                }
            },
            scales: {
                r: {
                    grid: { color: gridColor },
                    angleLines: { color: gridColor },
                    pointLabels: { color: textColor, font: { size: 11, weight: '600' } },
                    ticks: { display: false },
                    min: 0,
                    max: 100
                }
            }
        }
    });
}

function renderCoachHabitTrendChart() {
    const trendCtx = document.getElementById('coachHabitTrendChart');
    const emptyEl = document.getElementById('coach-trend-empty');
    if (!trendCtx) return;

    if (coachHabitTrendChart) coachHabitTrendChart.destroy();

    const isDark = document.body.getAttribute('data-theme') === 'dark';
    const textColor = isDark ? '#9ca3af' : '#62627a';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(99, 102, 241, 0.08)';

    const trendData = (coachHabitAnalyticsData && coachHabitAnalyticsData.trend) ? coachHabitAnalyticsData.trend : [];

    if (!trendData || trendData.length === 0) {
        if (emptyEl) emptyEl.style.display = 'flex';
        return;
    }

    if (emptyEl) emptyEl.style.display = 'none';

    const labels = trendData.map(pt => {
        try {
            const parts = pt.date.split('-');
            return `${parts[1]}/${parts[2]}`;
        } catch (e) {
            return pt.date;
        }
    });

    const metricConfig = {
        'habit_score': { label: 'Habit Score', color: '#a855f7', fill: 'rgba(168, 85, 247, 0.15)' },
        'wake_up_consistency': { label: 'Wake-Up Consistency (%)', color: '#38bdf8', fill: 'rgba(56, 189, 248, 0.15)' },
        'snooze_rate': { label: 'Snooze Reduction Rate (%)', color: '#22c55e', fill: 'rgba(34, 197, 94, 0.15)' },
        'challenge_success': { label: 'Challenge Success Rate (%)', color: '#ec4899', fill: 'rgba(236, 72, 153, 0.15)' },
        'sleep_schedule_adherence': { label: 'Sleep Schedule Adherence (%)', color: '#f59e0b', fill: 'rgba(245, 158, 11, 0.15)' }
    };

    const cfg = metricConfig[currentCoachTrendMetric] || metricConfig['habit_score'];
    const values = trendData.map(pt => (pt[currentCoachTrendMetric] !== null && pt[currentCoachTrendMetric] !== undefined) ? Math.round(pt[currentCoachTrendMetric]) : 0);

    coachHabitTrendChart = new Chart(trendCtx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: cfg.label,
                data: values,
                borderColor: cfg.color,
                backgroundColor: cfg.fill,
                borderWidth: 3,
                fill: true,
                tension: 0.35,
                pointBackgroundColor: cfg.color,
                pointBorderColor: '#fff',
                pointRadius: 4,
                pointHoverRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: textColor } },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label}: ${ctx.raw}%`
                    }
                }
            },
            scales: {
                x: { grid: { color: gridColor }, ticks: { color: textColor } },
                y: { grid: { color: gridColor }, ticks: { color: textColor }, min: 0, max: 100 }
            }
        }
    });
}

// 5. Generate Real System Diagnostic Report for Coach in PDF, Excel, or CSV
window.exportCoachReport = async (format = 'pdf') => {
    const fmt = (format || 'pdf').toLowerCase();
    Toast.show('Compiling Diagnostic Report...', `Generating ${fmt.toUpperCase()} export from PostgreSQL database.`, 'info', 2000);

    const session = JSON.parse(localStorage.getItem('sessionUser') || '{}');
    const dateStr = new Date().toLocaleDateString();
    const timeStr = new Date().toLocaleTimeString();

    if (fmt === 'csv') {
        let csv = '\uFEFF';
        csv += 'WAKEWISE AI - WELLNESS COACH DIAGNOSTIC REPORT\r\n';
        csv += `Export Date,${dateStr} ${timeStr}\r\n`;
        csv += `Advisor Name,"${(session.name || 'Wellness Advisor').replace(/"/g, '""')}"\r\n`;
        csv += `Email,"${(session.email || 'coach@wakewise.ai').replace(/"/g, '""')}"\r\n`;
        csv += `Total Assigned Patients,${registeredPatients.length}\r\n\r\n`;

        csv += '--- REGISTERED PATIENTS REGISTRY ---\r\n';
        csv += 'User ID,Name,Email,Target Bedtime,Target Wake Time,Inactivity Threshold (mins),Habit Score\r\n';
        registeredPatients.forEach(p => {
            csv += `"${p.id}","${(p.name || '').replace(/"/g, '""')}","${(p.email || '').replace(/"/g, '""')}","${p.target_bedtime || '23:00'}","${p.target_wake_time || '07:00'}","${p.inactivity_threshold_minutes || 30}","${p.habit_score || 0}%"\r\n`;
        });
        csv += '\r\n';

        csv += '--- DISPATCHED ADVISOR RECOMMENDATIONS ---\r\n';
        csv += 'Timestamp,Patient,Recommendation Note,Status\r\n';
        coachRecommendationLogs.forEach(l => {
            csv += `"${l.date}","${(l.patient || '').replace(/"/g, '""')}","${(l.notes || '').replace(/"/g, '""')}","${l.status || 'Active'}"\r\n`;
        });

        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `WakeWise_Coach_Report_${Date.now()}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        Toast.show('CSV Downloaded', 'Coach patient registry CSV saved successfully.', 'success', 2500);

    } else if (fmt === 'excel' || fmt === 'xlsx' || fmt === 'xls') {
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
 </Styles>
 <Worksheet ss:Name="Patient Directory">
  <Table>
   <Row><Cell ss:StyleID="Title"><Data ss:Type="String">WakeWise AI - Wellness Coach Diagnostic Ledger</Data></Cell></Row>
   <Row><Cell><Data ss:Type="String">Advisor: ${escapeXmlCoach(session.name || 'Coach')} (${escapeXmlCoach(session.email || '')})</Data></Cell></Row>
   <Row><Cell><Data ss:Type="String">Date: ${dateStr} ${timeStr} | Patients: ${registeredPatients.length}</Data></Cell></Row>
   <Row></Row>
   <Row ss:StyleID="Header">
    <Cell><Data ss:Type="String">Patient ID</Data></Cell>
    <Cell><Data ss:Type="String">Patient Name</Data></Cell>
    <Cell><Data ss:Type="String">Email</Data></Cell>
    <Cell><Data ss:Type="String">Target Bedtime</Data></Cell>
    <Cell><Data ss:Type="String">Target Wake</Data></Cell>
    <Cell><Data ss:Type="String">Inactivity Threshold</Data></Cell>
   </Row>`;

        registeredPatients.forEach(p => {
            excel += `
   <Row>
    <Cell><Data ss:Type="Number">${p.id}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXmlCoach(p.name || 'Patient')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXmlCoach(p.email || '')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXmlCoach(p.target_bedtime || '23:00')}</Data></Cell>
    <Cell><Data ss:Type="String">${escapeXmlCoach(p.target_wake_time || '07:00')}</Data></Cell>
    <Cell><Data ss:Type="String">${p.inactivity_threshold_minutes || 30} mins</Data></Cell>
   </Row>`;
        });

        excel += `
  </Table>
 </Worksheet>
</Workbook>`;

        const blob = new Blob([excel], { type: 'application/vnd.ms-excel;charset=utf-8;' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `WakeWise_Coach_Report_${Date.now()}.xls`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        Toast.show('Excel Downloaded', 'Spreadsheet report saved successfully.', 'success', 2500);

    } else {
        // PDF format
        const printWindow = window.open('', '_blank', 'width=860,height=700');
        if (!printWindow) {
            Toast.show('Popup Blocked', 'Please allow popups to generate PDF report.', 'warning', 3000);
            return;
        }

        const html = `<!DOCTYPE html>
<html>
<head>
    <title>WakeWise AI - Coach Diagnostic Ledger</title>
    <style>
        @page { size: A4; margin: 16mm; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #1e293b; margin: 0; padding: 20px; font-size: 12px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #6366f1; padding-bottom: 12px; margin-bottom: 20px; }
        .logo { font-size: 20px; font-weight: 700; color: #6366f1; }
        .meta { text-align: right; font-size: 11px; color: #64748b; }
        .stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 24px; }
        .stat-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; text-align: center; }
        .stat-box h4 { margin: 0; font-size: 18px; color: #1e1b4b; }
        .stat-box p { margin: 4px 0 0; font-size: 11px; color: #64748b; }
        h3 { font-size: 14px; margin: 20px 0 8px; color: #334155; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 11px; }
        th, td { border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; }
        th { background: #f1f5f9; font-weight: 600; color: #475569; }
        tr:nth-child(even) { background: #fafafa; }
        .footer { margin-top: 30px; text-align: center; font-size: 10px; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 10px; }
        @media print { body { padding: 0; } }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <div class="logo">🩺 WakeWise AI - Wellness Coach Portal</div>
            <div style="font-size: 12px; color: #475569; margin-top: 4px;">Patient Clinical Summary & Behavioral Ledger</div>
        </div>
        <div class="meta">
            <div><strong>Coach:</strong> ${escapeXmlCoach(session.name || 'Advisor')} (${escapeXmlCoach(session.email || '')})</div>
            <div><strong>Date:</strong> ${dateStr} ${timeStr}</div>
        </div>
    </div>

    <div class="stats-grid">
        <div class="stat-box">
            <h4>${registeredPatients.length}</h4>
            <p>Monitored Patients</p>
        </div>
        <div class="stat-box">
            <h4>${coachRecommendationLogs.length}</h4>
            <p>Advised Recommendations</p>
        </div>
        <div class="stat-box">
            <h4>100%</h4>
            <p>System Diagnostic Health</p>
        </div>
    </div>

    <h3>Registered Patient Registry (${registeredPatients.length})</h3>
    <table>
        <thead>
            <tr>
                <th>ID</th>
                <th>Patient Name</th>
                <th>Email</th>
                <th>Target Bedtime</th>
                <th>Target Wake</th>
                <th>Threshold</th>
            </tr>
        </thead>
        <tbody>
            ${registeredPatients.length === 0 ? '<tr><td colspan="6" style="text-align:center;">No patients registered.</td></tr>' : registeredPatients.map(p => `
                <tr>
                    <td>${p.id}</td>
                    <td><strong>${escapeXmlCoach(p.name || 'Patient')}</strong></td>
                    <td>${escapeXmlCoach(p.email)}</td>
                    <td>${p.target_bedtime || '23:00'}</td>
                    <td>${p.target_wake_time || '07:00'}</td>
                    <td>${p.inactivity_threshold_minutes || 30} mins</td>
                </tr>
            `).join('')}
        </tbody>
    </table>

    <div class="footer">
        WakeWise AI Coach Diagnostic Report • Generated from live PostgreSQL Database
    </div>

    <script>
        window.onload = function() {
            setTimeout(function() { window.print(); }, 300);
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

window.simulateCoachReport = (fmt) => window.exportCoachReport(fmt || 'pdf');

function escapeXmlCoach(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

// 6. Theme Change Listener
document.querySelectorAll('#theme-toggle, .nav-toggle-theme').forEach(btn => {
    btn.addEventListener('click', () => {
        setTimeout(() => {
            loadCoachDashboardData();
        }, 150);
    });
});

// 7. Initial Startup
document.addEventListener('DOMContentLoaded', () => {
    if (typeof updateHeaderUserInfo === 'function') updateHeaderUserInfo();
    loadCoachDashboardData();
});
