/* ==========================================================================
   INTELLIGENT COGNITIVE ALARM PLATFORM - NOTIFICATION & REMINDER CONTROLLER
   Requirement 11: Real-time Notification Center, Multi-Channel Preferences
   (Email, SMS, Both, Disabled), Category Matrix, History Audit & Report Delivery.
   ========================================================================== */

// API Base URL is globally initialized by config.js

let activeNotificationsList = [];
let activeNotifCategory = 'all';
let isUnreadFilterActive = false;
let currentSearchQuery = '';

// Preference state cache
let currentNotificationPrefs = null;
let currentProviderStatus = { email_configured: false, sms_configured: false };
let currentUserPhone = '';

function getNotifAuthHeaders() {
    let token = '';
    try {
        const session = JSON.parse(localStorage.getItem('sessionUser') || '{}');
        token = session.accessToken || session.token || localStorage.getItem('token') || localStorage.getItem('accessToken') || '';
    } catch (_) {}

    return {
        'Content-Type': 'application/json',
        'Authorization': token ? `Bearer ${token}` : ''
    };
}

// ==========================================================================
// 1. Unread Count Poller & Badge Updater
// ==========================================================================
async function updateNotificationBadge() {
    const badgeEl = document.getElementById('notif-badge');
    if (!badgeEl) return;

    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/notifications/unread-count`, {
            headers: getNotifAuthHeaders()
        });
        if (resp.ok) {
            const data = await resp.json();
            const count = data.unread_count || 0;
            if (count > 0) {
                badgeEl.textContent = count > 99 ? '99+' : count;
                badgeEl.style.display = 'inline-flex';
                badgeEl.classList.add('has-unread');
            } else {
                badgeEl.textContent = '0';
                badgeEl.style.display = 'none';
                badgeEl.classList.remove('has-unread');
            }
        }
    } catch (e) {
        console.debug('Badge poll note:', e);
    }
}

// ==========================================================================
// 2. Fetch User Notifications
// ==========================================================================
async function fetchUserNotifications(type = null, unreadOnly = false) {
    try {
        let url = `${window.API_BASE_URL}/api/notifications/?limit=50`;
        if (type && type !== 'all') {
            url += `&type=${encodeURIComponent(type)}`;
        }
        if (unreadOnly) {
            url += `&unread_only=true`;
        }

        const resp = await fetch(url, {
            headers: getNotifAuthHeaders()
        });

        if (resp.ok) {
            const data = await resp.json();
            activeNotificationsList = data.notifications || [];
            updateNotificationBadge();
            return activeNotificationsList;
        }
    } catch (err) {
        console.error('Error fetching notifications:', err);
    }
    return [];
}

// ==========================================================================
// 3. Dropdown Menu Trigger & Populator
// ==========================================================================
window.toggleNotificationDropdown = async (e) => {
    if (e) e.stopPropagation();
    const dropdown = document.getElementById('notif-dropdown');
    if (!dropdown) return;

    const isVisible = dropdown.classList.contains('show');
    // Close other dropdowns
    document.querySelectorAll('.dropdown-menu.show').forEach(d => d.classList.remove('show'));

    if (!isVisible) {
        dropdown.classList.add('show');
        await renderNotificationDropdown();
    } else {
        dropdown.classList.remove('show');
    }
};

async function renderNotificationDropdown() {
    const listContainer = document.getElementById('notif-dropdown-list');
    if (!listContainer) return;

    listContainer.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);"><i class="fas fa-circle-notch fa-spin"></i> Loading...</div>';
    const notifs = await fetchUserNotifications();

    if (!notifs || notifs.length === 0) {
        listContainer.innerHTML = `
            <div style="padding: 30px 16px; text-align: center; color: var(--text-muted);">
                <i class="fas fa-bell-slash" style="font-size: 1.8rem; opacity: 0.5; margin-bottom: 8px;"></i>
                <p style="margin: 0; font-size: 0.85rem;">No notifications right now.</p>
            </div>
        `;
        return;
    }

    listContainer.innerHTML = '';
    notifs.slice(0, 5).forEach(n => {
        const item = document.createElement('div');
        item.className = `notif-item ${n.is_read ? '' : 'unread'}`;
        item.onclick = () => handleNotificationClick(n);

        const iconClass = getCategoryIcon(n.type);
        item.innerHTML = `
            <div class="notif-icon-circle ${n.type}">
                <i class="${iconClass}"></i>
            </div>
            <div class="notif-item-body">
                <div class="notif-item-title">
                    <span>${escapeHtml(n.title)}</span>
                    <span class="notif-item-time">${n.time_ago || 'Recently'}</span>
                </div>
                <p class="notif-item-msg">${escapeHtml(n.message)}</p>
            </div>
        `;
        listContainer.appendChild(item);
    });
}

// ==========================================================================
// 4. Full Notification Center Renderer
// ==========================================================================
window.renderNotificationCenter = async () => {
    const centerList = document.getElementById('full-notifications-list') || document.getElementById('notif-center-list');
    if (!centerList) return;

    centerList.innerHTML = '<div style="padding: 40px; text-align: center; color: var(--text-muted);"><i class="fas fa-circle-notch fa-spin" style="font-size: 1.5rem;"></i><p style="margin-top: 10px;">Evaluating latest platform events & reminders...</p></div>';

    const notifs = await fetchUserNotifications(activeNotifCategory, isUnreadFilterActive);
    
    // Filter by search query if any
    let filtered = notifs;
    if (currentSearchQuery) {
        const q = currentSearchQuery.toLowerCase();
        filtered = filtered.filter(n => 
            (n.title && n.title.toLowerCase().includes(q)) || 
            (n.message && n.message.toLowerCase().includes(q)) ||
            (n.type && n.type.toLowerCase().includes(q))
        );
    }

    if (!filtered || filtered.length === 0) {
        centerList.innerHTML = `
            <div class="glass-card" style="padding: 50px 20px; text-align: center; color: var(--text-muted);">
                <i class="fas fa-bell-slash" style="font-size: 2.5rem; color: var(--text-muted); opacity: 0.4; margin-bottom: 16px;"></i>
                <h3 style="margin-bottom: 6px; font-size: 1.15rem; color: var(--text-primary);">No Notifications Found</h3>
                <p style="font-size: 0.85rem; max-width: 380px; margin: 0 auto; color: var(--text-secondary);">
                    ${isUnreadFilterActive ? 'You have read all your notifications!' : 'Your notification stream is completely up to date.'}
                </p>
            </div>
        `;
        return;
    }

    centerList.innerHTML = '';
    filtered.forEach(n => {
        const card = document.createElement('div');
        card.className = `notif-center-card priority-${n.priority || 'normal'} ${n.is_read ? '' : 'unread'}`;

        const iconClass = getCategoryIcon(n.type);
        const categoryLabel = getCategoryLabel(n.type);
        const channelBadges = getChannelBadgesHtml(n);

        card.innerHTML = `
            <div class="notif-icon-circle ${n.type}" style="width: 44px; height: 44px; font-size: 1.2rem;">
                <i class="${iconClass}"></i>
            </div>
            <div class="notif-center-body">
                <div class="notif-center-header">
                    <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <h4 class="notif-center-title">${escapeHtml(n.title)}</h4>
                        <span class="badge ${getCategoryBadgeClass(n.type)}">${categoryLabel}</span>
                        ${channelBadges}
                        ${n.priority && n.priority !== 'normal' ? `<span class="badge ${n.priority === 'urgent' ? 'badge-danger' : 'badge-warning'}">${n.priority.toUpperCase()}</span>` : ''}
                    </div>
                    <span style="font-size: 0.8rem; color: var(--text-muted);"><i class="fas fa-clock"></i> ${n.time_ago || 'Recently'}</span>
                </div>
                <p class="notif-center-msg">${escapeHtml(n.message)}</p>
                <div class="notif-center-actions">
                    ${n.action_url ? `<button class="btn btn-primary" style="padding: 4px 12px; font-size: 0.78rem;" onclick="handleNotificationAction('${n.action_url}', ${n.id})"><i class="fas fa-arrow-right"></i> Open Feature</button>` : ''}
                    ${!n.is_read ? `<button class="btn btn-secondary" style="padding: 4px 10px; font-size: 0.78rem;" onclick="markNotificationAsRead(${n.id})"><i class="fas fa-check"></i> Mark as Read</button>` : ''}
                    <button class="table-action-btn delete-btn" style="width: 28px; height: 28px;" onclick="deleteNotificationItem(${n.id})" title="Dismiss"><i class="fas fa-trash-alt"></i></button>
                </div>
            </div>
        `;
        centerList.appendChild(card);
    });
};

function getChannelBadgesHtml(n) {
    let badges = '<span class="badge chan-badge-inapp"><i class="fas fa-bell"></i> In-App</span>';
    if (n.delivery_channel === 'email' || n.delivery_channel === 'both' || n.email_status === 'delivered') {
        badges += ' <span class="badge chan-badge-email"><i class="fas fa-envelope"></i> Email</span>';
    }
    if (n.delivery_channel === 'sms' || n.delivery_channel === 'both' || n.sms_status === 'delivered') {
        badges += ' <span class="badge chan-badge-sms"><i class="fas fa-sms"></i> SMS</span>';
    }
    return badges;
}

// ==========================================================================
// 5. Filter Chips & Search
// ==========================================================================
window.setNotificationFilter = (category, btnEl) => {
    activeNotifCategory = category;
    document.querySelectorAll('.notif-filter-chips .notif-chip, .notif-filter-chip').forEach(c => c.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');
    renderNotificationCenter();
};

window.toggleUnreadOnlyFilter = (checkboxEl) => {
    isUnreadFilterActive = checkboxEl.checked;
    renderNotificationCenter();
};

window.filterNotificationCenterSearch = (query) => {
    currentSearchQuery = (query || '').trim();
    renderNotificationCenter();
};

// ==========================================================================
// 6. Action Handlers
// ==========================================================================
window.handleNotificationClick = async (notif) => {
    if (!notif.is_read) {
        await markNotificationAsRead(notif.id, false);
    }
    const dropdown = document.getElementById('notif-dropdown');
    if (dropdown) dropdown.classList.remove('show');

    if (notif.action_url) {
        handleNotificationAction(notif.action_url, notif.id);
    } else {
        if (typeof window.switchTab === 'function') {
            window.switchTab('tab-notifications');
        } else if (!window.location.pathname.includes('notifications.html')) {
            window.location.href = 'notifications.html';
        }
    }
};

window.handleNotificationAction = async (url, notifId) => {
    if (notifId) {
        await markNotificationAsRead(notifId, false);
    }

    if (url.includes('tab-') || url.includes('#')) {
        const tabId = url.split('#')[1] || url;
        if (typeof window.switchTab === 'function') {
            const mappedTab = tabId.startsWith('tab-') ? tabId : `tab-${tabId}`;
            window.switchTab(mappedTab);
            return;
        }
    }

    // Direct page navigation
    window.location.href = url;
};

window.markNotificationAsRead = async (notifId, refresh = true) => {
    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/notifications/${notifId}/read`, {
            method: 'PATCH',
            headers: getNotifAuthHeaders()
        });
        if (resp.ok) {
            updateNotificationBadge();
            if (refresh) renderNotificationCenter();
        }
    } catch (e) {
        console.error('Mark read error:', e);
    }
};

window.markAllNotificationsRead = async () => {
    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/notifications/read-all`, {
            method: 'PATCH',
            headers: getNotifAuthHeaders()
        });
        if (resp.ok) {
            if (typeof Toast !== 'undefined') {
                Toast.show('Notifications Updated', 'All notifications marked as read.', 'success', 2000);
            }
            updateNotificationBadge();
            renderNotificationCenter();
            const dropdown = document.getElementById('notif-dropdown');
            if (dropdown && dropdown.classList.contains('show')) {
                renderNotificationDropdown();
            }
        }
    } catch (e) {
        console.error('Mark all read error:', e);
    }
};

window.clearAllReadNotifications = async () => {
    if (!confirm('Clear all read notifications from your view?')) return;

    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/notifications/clear-all`, {
            method: 'DELETE',
            headers: getNotifAuthHeaders()
        });
        if (resp.ok) {
            if (typeof Toast !== 'undefined') {
                Toast.show('Cleaned Up', 'Read notifications cleared.', 'info', 2000);
            }
            updateNotificationBadge();
            renderNotificationCenter();
        }
    } catch (e) {
        console.error('Clear read error:', e);
    }
};

window.deleteNotificationItem = async (notifId) => {
    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/notifications/${notifId}`, {
            method: 'DELETE',
            headers: getNotifAuthHeaders()
        });
        if (resp.ok) {
            updateNotificationBadge();
            renderNotificationCenter();
        }
    } catch (e) {
        console.error('Delete notification error:', e);
    }
};

// ==========================================================================
// 7. MULTI-CHANNEL PREFERENCES & MATRIX CONTROLLER
// ==========================================================================
window.fetchDeliveryProviderStatus = async () => {
    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/notifications/providers`, {
            headers: getNotifAuthHeaders()
        });
        if (resp.ok) {
            currentProviderStatus = await resp.json();
            updateProviderStatusUI();
        }
    } catch (e) {
        console.debug('Provider status note:', e);
    }
};

function updateProviderStatusUI() {
    const banner = document.getElementById('provider-status-banner');
    if (!banner) return;
    banner.style.display = 'none';
    banner.innerHTML = '';
}

window.openNotificationPreferencesModal = async () => {
    const modal = document.getElementById('notification-preferences-modal');
    if (!modal) return;

    await fetchDeliveryProviderStatus();
    await loadNotificationPreferencesIntoModal();

    if (typeof Modal !== 'undefined') {
        Modal.open('notification-preferences-modal');
    } else {
        modal.classList.add('active');
    }
};

async function loadNotificationPreferencesIntoModal() {
    try {
        // Fetch preferences
        const resp = await fetch(`${window.API_BASE_URL}/api/notifications/preferences`, {
            headers: getNotifAuthHeaders()
        });

        // Also fetch user profile for phone number
        const userResp = await fetch(`${window.API_BASE_URL}/api/auth/me`, {
            headers: getNotifAuthHeaders()
        });

        if (userResp.ok) {
            const user = await userResp.json();
            currentUserPhone = user.phone_number || '';
            const phoneInput = document.getElementById('pref-phone-input');
            if (phoneInput) phoneInput.value = currentUserPhone;
            updatePhoneStatusBadge(currentUserPhone);
        }

        if (resp.ok) {
            const data = await resp.json();
            currentNotificationPrefs = data;

            // Global channel buttons
            setGlobalChannelPillUI(data.preferred_channel || 'email');

            // Category Matrix Toggles
            const setCheck = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.checked = !!val;
            };

            setCheck('pref-bedtime-email', data.bedtime_email);
            setCheck('pref-bedtime-sms', data.bedtime_sms);
            setCheck('pref-wakeup-email', data.wakeup_email);
            setCheck('pref-wakeup-sms', data.wakeup_sms);
            setCheck('pref-habit-email', data.habit_email);
            setCheck('pref-habit-sms', data.habit_sms);
            setCheck('pref-challenge-email', data.challenge_email);
            setCheck('pref-challenge-sms', data.challenge_sms);
            setCheck('pref-progress-email', data.progress_email);
            setCheck('pref-progress-sms', data.progress_sms);
            setCheck('pref-announcement-email', data.announcement_email);
            setCheck('pref-announcement-sms', data.announcement_sms);

            // Legacy fallbacks for backward compatibility
            setCheck('pref-bedtime', data.bedtime_reminders);
            setCheck('pref-wakeup', data.wake_up_reminders);
            setCheck('pref-habit', data.habit_alerts);
            setCheck('pref-challenge', data.challenge_reminders);
            setCheck('pref-progress', data.progress_notifications);
            setCheck('pref-announcement', data.platform_announcements);

            // Lead times
            const setSelect = (id, val) => {
                const el = document.getElementById(id);
                if (el && val !== undefined && val !== null) el.value = val;
            };
            setSelect('pref-bedtime-lead', data.bedtime_lead_minutes || 30);
            setSelect('pref-wakeup-lead', data.wakeup_lead_minutes || 10);

            // Browser push toggle
            setCheck('pref-browser', data.browser_notifications_enabled);

            // Check SMS phone guidance
            evaluatePhoneGuidanceAlert();
        }
    } catch (e) {
        console.error('Error loading preferences:', e);
    }
}

window.selectGlobalChannel = (channel) => {
    setGlobalChannelPillUI(channel);

    const isEmail = channel === 'email' || channel === 'both';
    const isSms = channel === 'sms' || channel === 'both';
    const isAllOff = channel === 'disabled';

    const matrixCategories = ['bedtime', 'wakeup', 'habit', 'challenge', 'progress', 'announcement'];
    matrixCategories.forEach(cat => {
        const emailEl = document.getElementById(`pref-${cat}-email`);
        const smsEl = document.getElementById(`pref-${cat}-sms`);
        const legacyEl = document.getElementById(`pref-${cat}`);

        if (emailEl) emailEl.checked = isAllOff ? false : isEmail;
        if (smsEl) smsEl.checked = isAllOff ? false : isSms;
        if (legacyEl) legacyEl.checked = !isAllOff;
    });

    evaluatePhoneGuidanceAlert();
};

function setGlobalChannelPillUI(channel) {
    document.querySelectorAll('.channel-pill-btn').forEach(btn => {
        if (btn.dataset.channel === channel) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}

function updatePhoneStatusBadge(phone) {
    const badge = document.getElementById('pref-phone-status-badge');
    if (!badge) return;

    if (phone && phone.trim().length >= 10) {
        badge.className = 'phone-status-badge badge-configured';
        badge.innerHTML = '<i class="fas fa-check-circle"></i> Configured';
    } else {
        badge.className = 'phone-status-badge badge-missing';
        badge.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Not Configured';
    }
}

function evaluatePhoneGuidanceAlert() {
    const alertBox = document.getElementById('phone-guidance-alert');
    if (!alertBox) return;

    const phoneInput = document.getElementById('pref-phone-input');
    const phone = (phoneInput?.value || currentUserPhone || '').trim();

    // Check if any SMS checkbox is active or global channel is SMS/Both
    const activeChannelBtn = document.querySelector('.channel-pill-btn.active');
    const globalChannel = activeChannelBtn ? activeChannelBtn.dataset.channel : 'email';

    let hasSmsEnabled = globalChannel === 'sms' || globalChannel === 'both';
    const smsToggles = ['pref-bedtime-sms', 'pref-wakeup-sms', 'pref-habit-sms', 'pref-challenge-sms', 'pref-progress-sms', 'pref-announcement-sms'];
    smsToggles.forEach(id => {
        const el = document.getElementById(id);
        if (el && el.checked) hasSmsEnabled = true;
    });

    if (hasSmsEnabled && (!phone || phone.length < 10)) {
        alertBox.style.display = 'block';
    } else {
        alertBox.style.display = 'none';
    }
}

// Attach live listener on phone input and SMS toggles
document.addEventListener('DOMContentLoaded', () => {
    const phoneInput = document.getElementById('pref-phone-input');
    if (phoneInput) {
        phoneInput.addEventListener('input', (e) => {
            updatePhoneStatusBadge(e.target.value);
            evaluatePhoneGuidanceAlert();
        });
    }

    const modalBody = document.querySelector('#notification-preferences-modal .modal-body');
    if (modalBody) {
        modalBody.addEventListener('change', () => {
            evaluatePhoneGuidanceAlert();
        });
    }
});

window.saveNotificationPreferences = async (e) => {
    if (e) e.preventDefault();

    const getCheck = (id) => {
        const el = document.getElementById(id);
        return el ? el.checked : true;
    };

    const activeChannelBtn = document.querySelector('.channel-pill-btn.active');
    const preferredChannel = activeChannelBtn ? activeChannelBtn.dataset.channel : 'email';

    const phoneInput = document.getElementById('pref-phone-input');
    const phoneVal = phoneInput ? phoneInput.value.trim() : currentUserPhone;

    // Validate phone if SMS is preferred or enabled
    const bedtimeSms = getCheck('pref-bedtime-sms');
    const wakeupSms = getCheck('pref-wakeup-sms');
    const habitSms = getCheck('pref-habit-sms');
    const challengeSms = getCheck('pref-challenge-sms');
    const progressSms = getCheck('pref-progress-sms');
    const announcementSms = getCheck('pref-announcement-sms');

    const anySmsActive = bedtimeSms || wakeupSms || habitSms || challengeSms || progressSms || announcementSms || preferredChannel === 'sms' || preferredChannel === 'both';

    if (anySmsActive && phoneVal) {
        const cleaned = phoneVal.replace(/[\s\-\(\)]/g, '');
        const phoneRegex = /^\+?[0-9]{10,15}$/;
        if (!phoneRegex.test(cleaned)) {
            if (typeof Toast !== 'undefined') {
                Toast.show('Invalid Phone Number', 'Please enter a valid 10-15 digit phone number (e.g., +1234567890).', 'warning', 3500);
            } else {
                alert('Please enter a valid 10-15 digit phone number.');
            }
            return;
        }
    }

    // 1. If phone changed, update user profile first
    if (phoneVal !== currentUserPhone) {
        try {
            await fetch(`${window.API_BASE_URL}/api/auth/profile`, {
                method: 'PUT',
                headers: getNotifAuthHeaders(),
                body: JSON.stringify({ phone_number: phoneVal })
            });
            currentUserPhone = phoneVal;
        } catch (err) {
            console.warn('Could not update phone in profile:', err);
        }
    }

    const payload = {
        preferred_channel: preferredChannel,
        phone_number: phoneVal || null,
        bedtime_reminders: getCheck('pref-bedtime') || getCheck('pref-bedtime-email') || getCheck('pref-bedtime-sms'),
        bedtime_email: getCheck('pref-bedtime-email'),
        bedtime_sms: bedtimeSms,
        wake_up_reminders: getCheck('pref-wakeup') || getCheck('pref-wakeup-email') || getCheck('pref-wakeup-sms'),
        wakeup_email: getCheck('pref-wakeup-email'),
        wakeup_sms: wakeupSms,
        habit_alerts: getCheck('pref-habit') || getCheck('pref-habit-email') || getCheck('pref-habit-sms'),
        habit_email: getCheck('pref-habit-email'),
        habit_sms: habitSms,
        challenge_reminders: getCheck('pref-challenge') || getCheck('pref-challenge-email') || getCheck('pref-challenge-sms'),
        challenge_email: getCheck('pref-challenge-email'),
        challenge_sms: challengeSms,
        progress_notifications: getCheck('pref-progress') || getCheck('pref-progress-email') || getCheck('pref-progress-sms'),
        progress_email: getCheck('pref-progress-email'),
        progress_sms: progressSms,
        platform_announcements: getCheck('pref-announcement') || getCheck('pref-announcement-email') || getCheck('pref-announcement-sms'),
        announcement_email: getCheck('pref-announcement-email'),
        announcement_sms: announcementSms,
        browser_notifications_enabled: getCheck('pref-browser'),
        bedtime_lead_minutes: parseInt(document.getElementById('pref-bedtime-lead')?.value || 30),
        wakeup_lead_minutes: parseInt(document.getElementById('pref-wakeup-lead')?.value || 10)
    };

    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/notifications/preferences`, {
            method: 'PUT',
            headers: getNotifAuthHeaders(),
            body: JSON.stringify(payload)
        });

        if (resp.ok) {
            const updated = await resp.json();
            currentNotificationPrefs = updated;

            if (typeof Toast !== 'undefined') {
                Toast.show('Preferences Saved', 'Delivery matrix and notification channels updated.', 'success', 2500);
            }
            if (typeof Modal !== 'undefined') {
                Modal.close('notification-preferences-modal');
            } else {
                document.getElementById('notification-preferences-modal')?.classList.remove('active');
            }
            renderNotificationCenter();
        } else {
            const errData = await resp.json().catch(() => ({}));
            const msg = errData.detail || 'Failed to save preferences.';
            if (typeof Toast !== 'undefined') {
                Toast.show('Error', msg, 'danger', 3000);
            }
        }
    } catch (err) {
        console.error('Error saving preferences:', err);
    }
};

// ==========================================================================
// 8. NOTIFICATION DELIVERY HISTORY AUDIT LOG
// ==========================================================================
let currentHistoryChannel = 'all';
let currentHistoryStatus = 'all';
let currentHistoryPage = 1;

window.renderNotificationHistory = async (page = 1) => {
    const historyContainer = document.getElementById('notif-history-table-body') || document.getElementById('notif-history-list');
    if (!historyContainer) return;

    currentHistoryPage = page;
    historyContainer.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 24px; color: var(--text-muted);"><i class="fas fa-circle-notch fa-spin"></i> Loading delivery audit history...</td></tr>';

    try {
        let url = `${window.API_BASE_URL}/api/notifications/history?page=${page}&limit=20`;
        if (currentHistoryChannel && currentHistoryChannel !== 'all') {
            url += `&channel=${encodeURIComponent(currentHistoryChannel)}`;
        }
        if (currentHistoryStatus && currentHistoryStatus !== 'all') {
            url += `&status=${encodeURIComponent(currentHistoryStatus)}`;
        }

        const resp = await fetch(url, { headers: getNotifAuthHeaders() });
        if (resp.ok) {
            const data = await resp.json();
            const items = data.history || [];

            if (items.length === 0) {
                historyContainer.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 30px; color: var(--text-muted);"><i class="fas fa-history" style="font-size: 1.5rem; opacity: 0.4; margin-bottom: 6px;"></i><p style="margin:0;">No delivery history logs found matching current filters.</p></td></tr>';
                return;
            }

            historyContainer.innerHTML = '';
            items.forEach(h => {
                const tr = document.createElement('tr');
                const statusBadge = getDeliveryStatusBadgeHtml(h.delivery_status, h.email_status, h.sms_status);
                const channelBadge = getHistoryChannelBadgeHtml(h.delivery_channel);
                const categoryLabel = getCategoryLabel(h.type);

                tr.innerHTML = `
                    <td>
                        <span class="badge ${getCategoryBadgeClass(h.type)}">${categoryLabel}</span>
                    </td>
                    <td>
                        <div style="font-weight: 600; color: var(--text-primary); font-size: 0.88rem;">${escapeHtml(h.title)}</div>
                        <div style="font-size: 0.78rem; color: var(--text-secondary); max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(h.message)}</div>
                    </td>
                    <td>${channelBadge}</td>
                    <td style="font-size: 0.8rem; color: var(--text-secondary); white-space: nowrap;">
                        <i class="fas fa-clock" style="margin-right: 4px; font-size: 0.75rem;"></i>${h.time_ago || (h.created_at ? new Date(h.created_at).toLocaleString() : 'Recently')}
                    </td>
                    <td>${statusBadge}</td>
                `;
                historyContainer.appendChild(tr);
            });
        }
    } catch (e) {
        console.error('Error rendering history:', e);
        historyContainer.innerHTML = '<tr><td colspan="5" style="text-align:center; color: #f87171; padding: 20px;">Failed to load delivery history.</td></tr>';
    }
};

window.filterHistoryChannel = (channel, btnEl) => {
    currentHistoryChannel = channel;
    document.querySelectorAll('.history-channel-btn').forEach(b => b.classList.remove('active'));
    if (btnEl) btnEl.classList.add('active');
    renderNotificationHistory(1);
};

window.filterHistoryStatus = (status, selectEl) => {
    currentHistoryStatus = selectEl.value;
    renderNotificationHistory(1);
};

function getHistoryChannelBadgeHtml(channel) {
    switch (channel) {
        case 'email': return '<span class="badge chan-badge-email"><i class="fas fa-envelope"></i> Email</span>';
        case 'sms': return '<span class="badge chan-badge-sms"><i class="fas fa-sms"></i> SMS</span>';
        case 'both': return '<span class="badge chan-badge-email"><i class="fas fa-envelope"></i> Email</span> <span class="badge chan-badge-sms"><i class="fas fa-sms"></i> SMS</span>';
        default: return '<span class="badge chan-badge-inapp"><i class="fas fa-bell"></i> In-App</span>';
    }
}

function getDeliveryStatusBadgeHtml(deliveryStatus, emailStatus, smsStatus) {
    const status = deliveryStatus || 'delivered';
    switch (status) {
        case 'delivered':
        case 'sent':
            return '<span class="delivery-status-pill status-delivered"><i class="fas fa-check-circle"></i> Delivered</span>';
        case 'unconfigured':
            return '<span class="delivery-status-pill status-unconfigured" title="Audit mode: Provider credentials not set in env"><i class="fas fa-info-circle"></i> In-App / Logged</span>';
        case 'no_phone':
            return '<span class="delivery-status-pill status-no-phone" title="SMS skipped: No phone number configured"><i class="fas fa-exclamation-circle"></i> No Phone</span>';
        case 'failed':
            return '<span class="delivery-status-pill status-failed"><i class="fas fa-times-circle"></i> Failed</span>';
        default:
            return `<span class="delivery-status-pill status-delivered">${status}</span>`;
    }
}

// ==========================================================================
// 9. SCHEDULED REPORT DELIVERY DISPATCHER
// ==========================================================================
window.scheduleReportDelivery = async (e) => {
    if (e) e.preventDefault();

    const activeChannelPill = document.querySelector('#report-channel-pills .channel-pill-btn.active');
    const channel = activeChannelPill ? activeChannelPill.dataset.channel : 'email';

    const freqEl = document.getElementById('report-frequency-select');
    const frequency = freqEl ? freqEl.value : 'weekly';

    const typeEl = document.getElementById('report-type-select');
    const reportType = typeEl ? typeEl.value : 'summary';

    const submitBtn = document.getElementById('schedule-report-btn');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Scheduling...';
    }

    try {
        const resp = await fetch(`${window.API_BASE_URL}/api/notifications/reports/schedule`, {
            method: 'POST',
            headers: getNotifAuthHeaders(),
            body: JSON.stringify({
                report_type: reportType,
                frequency: frequency,
                delivery_channel: channel
            })
        });

        if (resp.ok) {
            const data = await resp.json();
            if (typeof Toast !== 'undefined') {
                Toast.show('Report Scheduled', data.message || `Automated ${frequency} report active via ${channel.toUpperCase()}.`, 'success', 3500);
            } else {
                alert(`Report scheduled successfully! Next delivery: ${data.next_delivery_formatted || 'Scheduled'}`);
            }

            // Update badge / notification center
            updateNotificationBadge();
            if (typeof renderNotificationCenter === 'function') renderNotificationCenter();
        } else {
            const errData = await resp.json().catch(() => ({}));
            const msg = errData.detail || 'Could not schedule automated report.';
            if (typeof Toast !== 'undefined') {
                Toast.show('Scheduling Failed', msg, 'danger', 3500);
            } else {
                alert(msg);
            }
        }
    } catch (err) {
        console.error('Error scheduling report:', err);
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-calendar-check" style="margin-right: 6px;"></i> Schedule Automated Report';
        }
    }
};

window.selectReportChannel = (channel) => {
    document.querySelectorAll('#report-channel-pills .channel-pill-btn').forEach(btn => {
        if (btn.dataset.channel === channel) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
};

// ==========================================================================
// 10. Request Browser Push Permission
// ==========================================================================
window.requestBrowserPushPermission = async () => {
    if (!('Notification' in window)) {
        if (typeof Toast !== 'undefined') {
            Toast.show('Unsupported', 'Browser desktop notifications are not supported on this device.', 'warning', 3000);
        }
        return;
    }

    try {
        const permission = await Notification.requestPermission();
        const checkbox = document.getElementById('pref-browser');

        if (permission === 'granted') {
            if (checkbox) checkbox.checked = true;
            if (typeof Toast !== 'undefined') {
                Toast.show('Permission Granted', 'Desktop push notifications enabled for WakeWise alarms & reminders.', 'success', 3000);
            }
            new Notification('WakeWise AI Notifications Enabled', {
                body: 'You will receive bedtime, alarm, and habit reminders.',
                icon: '/assets/logo.png'
            });
        } else {
            if (checkbox) checkbox.checked = false;
            if (typeof Toast !== 'undefined') {
                Toast.show('Permission Denied', 'Browser notification permission was not granted. In-app notifications will continue working normally.', 'info', 3500);
            }
        }
    } catch (e) {
        console.error('Permission request error:', e);
    }
};

// ==========================================================================
// Helper UI Formatters
// ==========================================================================
function getCategoryIcon(type) {
    switch (type) {
        case 'bedtime': return 'fas fa-moon';
        case 'wake_up': return 'fas fa-sun';
        case 'habit_alert': return 'fas fa-chart-line';
        case 'challenge':
        case 'challenge_reminder': return 'fas fa-brain';
        case 'progress': return 'fas fa-award';
        case 'platform_announcement':
        case 'announcement': return 'fas fa-bullhorn';
        case 'coach_recommendation':
        case 'coach': return 'fas fa-comment-medical';
        case 'report_delivery': return 'fas fa-file-alt';
        default: return 'fas fa-bell';
    }
}

function getCategoryLabel(type) {
    switch (type) {
        case 'bedtime': return 'Bedtime';
        case 'wake_up': return 'Wake-Up';
        case 'habit_alert': return 'Habit Alert';
        case 'challenge':
        case 'challenge_reminder': return 'Challenge';
        case 'progress': return 'Progress';
        case 'platform_announcement':
        case 'announcement': return 'Announcement';
        case 'coach_recommendation':
        case 'coach': return 'Coach Advice';
        case 'report_delivery': return 'Report';
        default: return 'Reminder';
    }
}

function getCategoryBadgeClass(type) {
    switch (type) {
        case 'bedtime': return 'badge-secondary';
        case 'wake_up': return 'badge-warning';
        case 'habit_alert': return 'badge-danger';
        case 'challenge':
        case 'challenge_reminder': return 'badge-info';
        case 'progress': return 'badge-success';
        case 'platform_announcement':
        case 'announcement': return 'badge-primary';
        case 'coach_recommendation':
        case 'coach': return 'badge-success';
        case 'report_delivery': return 'badge-info';
        default: return 'badge-info';
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;')
                      .replace(/</g, '&lt;')
                      .replace(/>/g, '&gt;')
                      .replace(/"/g, '&quot;')
                      .replace(/'/g, '&#039;');
}

// Global click to close dropdown when clicked outside
document.addEventListener('click', (e) => {
    const dropdown = document.getElementById('notif-dropdown');
    const trigger = document.getElementById('notif-trigger');
    if (dropdown && dropdown.classList.contains('show')) {
        if (!dropdown.contains(e.target) && (!trigger || !trigger.contains(e.target))) {
            dropdown.classList.remove('show');
        }
    }
});

// Auto-initialize when loaded
function initNotificationsModule() {
    updateNotificationBadge();
    fetchDeliveryProviderStatus();
    
    // Poll badge counter every 30 seconds
    setInterval(updateNotificationBadge, 30000);

    // Setup chip listeners if present
    document.querySelectorAll('.notif-filter-chips .notif-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            const filter = chip.dataset.filter || 'all';
            if (filter === 'unread') {
                isUnreadFilterActive = true;
                activeNotifCategory = 'all';
            } else {
                isUnreadFilterActive = false;
                activeNotifCategory = filter;
            }
            document.querySelectorAll('.notif-filter-chips .notif-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            renderNotificationCenter();
        });
    });

    const searchInput = document.getElementById('notif-center-search');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            filterNotificationCenterSearch(e.target.value);
        });
    }

    // Connect preferences modal buttons
    const openPrefsBtn = document.getElementById('notif-center-prefs-btn');
    if (openPrefsBtn) openPrefsBtn.onclick = openNotificationPreferencesModal;

    const navOpenPrefsBtn = document.getElementById('notif-open-prefs-btn');
    if (navOpenPrefsBtn) navOpenPrefsBtn.onclick = openNotificationPreferencesModal;

    const notifTrigger = document.getElementById('notif-trigger');
    if (notifTrigger) notifTrigger.onclick = toggleNotificationDropdown;

    const markAllBtn = document.getElementById('notif-center-mark-all-btn');
    if (markAllBtn) markAllBtn.onclick = markAllNotificationsRead;

    const navMarkAllBtn = document.getElementById('notif-mark-all-read-btn');
    if (navMarkAllBtn) navMarkAllBtn.onclick = markAllNotificationsRead;

    const clearAllBtn = document.getElementById('notif-center-clear-all-btn');
    if (clearAllBtn) clearAllBtn.onclick = clearAllReadNotifications;

    const prefsForm = document.getElementById('notification-preferences-form');
    if (prefsForm) prefsForm.onsubmit = saveNotificationPreferences;

    const prefsCloseBtn = document.getElementById('notif-prefs-close-btn');
    if (prefsCloseBtn) {
        prefsCloseBtn.onclick = () => {
            if (typeof Modal !== 'undefined') Modal.close('notification-preferences-modal');
            else document.getElementById('notification-preferences-modal')?.classList.remove('active');
        };
    }
    const prefsCancelBtn = document.getElementById('notif-prefs-cancel-btn');
    if (prefsCancelBtn) {
        prefsCancelBtn.onclick = () => {
            if (typeof Modal !== 'undefined') Modal.close('notification-preferences-modal');
            else document.getElementById('notification-preferences-modal')?.classList.remove('active');
        };
    }

    const pushReqBtn = document.getElementById('notif-request-permission-btn');
    if (pushReqBtn) pushReqBtn.onclick = requestBrowserPushPermission;

    // If on a page with full notifications list, render it
    if (document.getElementById('full-notifications-list') || document.getElementById('notif-center-list')) {
        renderNotificationCenter();
    }

    // If on a page with notification history table, render it
    if (document.getElementById('notif-history-table-body')) {
        renderNotificationHistory();
    }

    // Connect report schedule form if present
    const reportForm = document.getElementById('report-delivery-form');
    if (reportForm) {
        reportForm.onsubmit = scheduleReportDelivery;
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNotificationsModule);
} else {
    initNotificationsModule();
}
