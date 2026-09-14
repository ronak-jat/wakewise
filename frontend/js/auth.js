/* ==========================================================================
   INTELLIGENT COGNITIVE ALARM PLATFORM - FASTAPI & DATABASE AUTH CONTROLLER
   ========================================================================== */

// Automatically capture OAuth tokens/session redirected from backend
(function handleOAuthRedirectParams() {
    if (typeof window === 'undefined' || !window.location) return;
    try {
        const urlParams = new URLSearchParams(window.location.search);
        const token = urlParams.get('token');
        const sessionEncoded = urlParams.get('session');

        if (token && sessionEncoded) {
            const userObj = JSON.parse(decodeURIComponent(sessionEncoded));
            localStorage.setItem('sessionUser', JSON.stringify(userObj));
            urlParams.delete('token');
            urlParams.delete('session');
            const cleanSearch = urlParams.toString() ? `?${urlParams.toString()}` : '';
            window.history.replaceState({}, document.title, window.location.pathname + cleanSearch + window.location.hash);
        } else if (token) {
            const existing = JSON.parse(localStorage.getItem('sessionUser') || '{}');
            existing.accessToken = token;
            localStorage.setItem('sessionUser', JSON.stringify(existing));
            urlParams.delete('token');
            const cleanSearch = urlParams.toString() ? `?${urlParams.toString()}` : '';
            window.history.replaceState({}, document.title, window.location.pathname + cleanSearch + window.location.hash);
        }
    } catch (e) {
        console.warn('OAuth redirect URL parsing note:', e);
    }
})();

// Access centralized API Base URL from config.js
function getApiBaseUrl() {
    if (typeof window !== 'undefined' && window.API_BASE_URL !== undefined) {
        return window.API_BASE_URL;
    }
    return '';
}



function getRelativePath(targetPath) {
    const pathname = window.location.pathname;
    const isSubfolder = pathname.includes('/user/') || pathname.includes('/admin/') || pathname.includes('/coach/');

    if (targetPath === 'login.html') {
        return isSubfolder ? '../login.html' : 'login.html';
    }

    if (targetPath === 'dashboard-user.html') {
        if (pathname.includes('/user/')) return 'dashboard-user.html';
        return isSubfolder ? '../user/dashboard-user.html' : 'user/dashboard-user.html';
    }
    if (targetPath === 'dashboard-coach.html') {
        if (pathname.includes('/coach/')) return 'dashboard-coach.html';
        return isSubfolder ? '../coach/dashboard-coach.html' : 'coach/dashboard-coach.html';
    }
    if (targetPath === 'dashboard-admin.html') {
        if (pathname.includes('/admin/')) return 'dashboard-admin.html';
        return isSubfolder ? '../admin/dashboard-admin.html' : 'admin/dashboard-admin.html';
    }
    return targetPath;
}

/**
 * Validates session and roles to prevent unauthorized dashboard navigation
 * @param {string} requiredRole ('user' | 'coach' | 'admin')
 */
function protectPage(requiredRole) {
    const sessionUser = JSON.parse(localStorage.getItem('sessionUser'));

    if (!sessionUser || !sessionUser.accessToken) {
        // No active session or missing token, redirect to login page
        window.location.href = getRelativePath('login.html');
        return;
    }

    const userRole = (sessionUser.role || '').toLowerCase();
    const targetRole = (requiredRole || '').toLowerCase();

    if (userRole !== targetRole) {
        // User role does not match page requirements, redirect to correct dashboard
        if (userRole === 'user') {
            window.location.href = getRelativePath('dashboard-user.html');
        } else if (userRole === 'coach') {
            window.location.href = getRelativePath('dashboard-coach.html');
        } else if (userRole === 'admin') {
            window.location.href = getRelativePath('dashboard-admin.html');
        } else {
            window.location.href = getRelativePath('login.html');
        }
    }
}

/**
 * Login User via FastAPI & Database Backend API
 * Endpoint: POST /api/auth/login
 * @param {string} email 
 * @param {string} password 
 * @returns {Promise<{success: boolean, user?: object, token?: string, message: string}>}
 */
async function attemptLoginAsync(email, password) {
    try {
        const endpoint = `${window.API_BASE_URL}/api/auth/login`;
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                email: email.trim().toLowerCase(),
                password: password
            })
        });

        let data;
        try {
            data = await response.json();
        } catch (e) {
            data = { detail: `Server error (${response.status} ${response.statusText})` };
        }

        if (!response.ok) {
            return {
                success: false,
                message: data.detail || 'Invalid email or password.'
            };
        }

        const user = data.user;
        // Store authenticated session token and user info from Database
        localStorage.setItem('sessionUser', JSON.stringify({
            id: user.id,
            email: user.email,
            name: user.name,
            role: user.role.toLowerCase(),
            accessToken: data.access_token,
            provider: user.provider || 'LOCAL',
            loggedInAt: new Date().toISOString()
        }));

        return {
            success: true,
            user: user,
            token: data.access_token,
            message: `Logged in successfully as ${user.name}!`
        };
    } catch (error) {
        console.error('Database API Login Error:', error);
        return {
            success: false,
            message: `Could not connect to backend endpoint (${window.API_BASE_URL || window.location.origin}/api/auth/login). Verify backend server is running.`
        };
    }
}

/**
 * Register User via FastAPI & Database Backend API
 * Endpoint: POST /api/auth/register
 * @param {string} name 
 * @param {string} email 
 * @param {string} password 
 * @param {string} role ('USER' | 'Wellness Coach' | 'Administrator')
 * @param {string} provider ('LOCAL' | 'GOOGLE')
 * @returns {Promise<{success: boolean, data?: object, message: string}>}
 */
async function registerUserAsync(name, email, password, role = 'USER', provider = 'LOCAL') {
    try {
        const endpoint = `${window.API_BASE_URL}/api/auth/register`;
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: name.trim(),
                email: email.trim().toLowerCase(),
                password: password,
                role: role.toUpperCase(),
                provider: provider
            })
        });

        let data;
        try {
            data = await response.json();
        } catch (e) {
            data = { detail: `Server error (${response.status} ${response.statusText})` };
        }

        if (!response.ok) {
            return {
                success: false,
                message: data.detail || 'Registration failed.'
            };
        }

        return {
            success: true,
            data: data.data,
            message: data.message || 'User registered in Database successfully!'
        };
    } catch (error) {
        console.error('Database API Registration Error:', error);
        return {
            success: false,
            message: `Could not connect to backend endpoint (${window.API_BASE_URL || window.location.origin}/api/auth/register). Verify backend server is running.`
        };
    }
}

/**
 * Login/Register User via Google OAuth API
 * Endpoint: POST /api/auth/google
 * @param {object} googleData { token?: string, email?: string, name?: string, role?: string }
 * @returns {Promise<{success: boolean, user?: object, token?: string, message: string}>}
 */
async function loginWithGoogleAsync(googleData) {
    try {
        const endpoint = `${window.API_BASE_URL}/api/auth/google`;
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(googleData)
        });

        let data;
        try {
            data = await response.json();
        } catch (e) {
            data = { detail: `Server endpoint error (${response.status} ${response.statusText}). Please restart uvicorn server.` };
        }

        if (!response.ok) {
            return {
                success: false,
                message: data.detail || 'Google OAuth authentication failed.'
            };
        }

        const user = data.user;
        localStorage.setItem('sessionUser', JSON.stringify({
            id: user.id,
            email: user.email,
            name: user.name,
            role: user.role.toLowerCase(),
            accessToken: data.access_token,
            provider: 'GOOGLE',
            loggedInAt: new Date().toISOString()
        }));

        return {
            success: true,
            user: user,
            token: data.access_token,
            message: `Authenticated with Google as ${user.name}!`
        };
    } catch (error) {
        console.error('Google OAuth API Error:', error);
        return {
            success: false,
            message: `Could not connect to Google OAuth backend endpoint (${window.API_BASE_URL || window.location.origin}/api/auth/google). Verify backend server is running.`
        };
    }
}

/**
 * Trigger logout and clean session data
 */
function logout() {
    localStorage.removeItem('sessionUser');
    window.location.href = getRelativePath('login.html');
}

/**
 * Helper to compute name initials for WhatsApp DP avatar
 */
function getInitials(name) {
    if (!name) return 'U';
    const parts = name.trim().split(' ');
    if (parts.length >= 2 && parts[0] && parts[1]) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return name.slice(0, 2).toUpperCase();
}

/**
 * Generates avatar HTML: Uploaded Custom Image OR WhatsApp DP Style Initials Avatar
 */
function renderAvatarHTML(name, avatarUrl, isLarge = false) {
    if (avatarUrl) {
        return `<img src="${avatarUrl}" alt="Avatar" style="${isLarge ? 'width: 90px; height: 90px; border-radius: 50%; object-fit: cover;' : 'width: 32px; height: 32px; border-radius: 50%; object-fit: cover;'}">`;
    }
    const initials = getInitials(name);
    return `<div class="${isLarge ? 'whatsapp-dp-avatar-large' : 'whatsapp-dp-avatar'}">${initials}</div>`;
}

/**
 * Synchronizes the logged-in user's avatar, name & email across navbar and dashboard greetings
 */
function updateHeaderUserInfo() {
    const sessionUser = JSON.parse(localStorage.getItem('sessionUser') || '{}');
    const name = sessionUser.name || (sessionUser.email ? sessionUser.email.split('@')[0] : 'User');
    const customAvatar = sessionUser.avatar || localStorage.getItem('user_avatar_' + (sessionUser.email || 'guest'));

    // 1. Navbar Avatar Slot
    const avatarSlot = document.getElementById('nav-avatar-slot');
    if (avatarSlot) {
        avatarSlot.innerHTML = renderAvatarHTML(name, customAvatar, false);
    }

    // 2. Profile Preview Avatar (if present in Profile tab)
    const profileAvatarContainer = document.getElementById('profile-avatar-preview-container');
    if (profileAvatarContainer) {
        profileAvatarContainer.innerHTML = renderAvatarHTML(name, customAvatar, true);
    }

    // 3. Navbar Username
    const navUsername = document.getElementById('nav-username');
    if (navUsername) {
        navUsername.textContent = name;
    }

    // 4. Greeting Header
    const greetingText = document.getElementById('greeting-text');
    if (greetingText) {
        const hour = new Date().getHours();
        const timeGreeting = hour < 12 ? 'Good Morning' : (hour < 18 ? 'Good Afternoon' : 'Good Evening');
        const role = (sessionUser.role || '').toLowerCase();

        if (role === 'admin') {
            greetingText.innerHTML = `System Cockpit, <span class="grad-text">${name}</span>`;
        } else if (role === 'coach') {
            greetingText.innerHTML = `Welcome, <span class="grad-text">${name}</span>`;
        } else {
            greetingText.innerHTML = `${timeGreeting}, <span class="grad-text">${name}</span>!`;
        }
    }

    // 5. User Profile Form inputs (if present)
    const profileNameInput = document.getElementById('profile-name');
    if (profileNameInput) {
        profileNameInput.value = name;
    }

    const profileEmailInput = document.getElementById('profile-email');
    if (profileEmailInput && sessionUser.email) {
        profileEmailInput.value = sessionUser.email;
    }

    const bedtimeInput = document.getElementById('profile-bedtime-target');
    if (bedtimeInput && sessionUser.target_bedtime) {
        bedtimeInput.value = sessionUser.target_bedtime;
    }

    const wakeInput = document.getElementById('profile-wake-target');
    if (wakeInput && sessionUser.target_wake_time) {
        wakeInput.value = sessionUser.target_wake_time;
    }

    const thresholdInput = document.getElementById('profile-inactivity-threshold');
    if (thresholdInput && sessionUser.inactivity_threshold_minutes) {
        thresholdInput.value = sessionUser.inactivity_threshold_minutes;
    }
}

/**
 * Binds Profile Picture Uploader File Input and Action Listeners
 */
function bindAvatarUploadListeners() {
    const picInput = document.getElementById('profile-pic-input');
    const changeBtn = document.getElementById('change-avatar-btn');
    const removeBtn = document.getElementById('remove-avatar-btn');

    if (changeBtn && picInput) {
        changeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            picInput.click();
        });
    }

    if (picInput) {
        picInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file) return;

            if (file.size > 4 * 1024 * 1024) {
                if (typeof Toast !== 'undefined') Toast.show('File Too Large', 'Please select an image smaller than 4MB.', 'warning');
                return;
            }

            const reader = new FileReader();
            reader.onload = function (event) {
                const base64Url = event.target.result;
                const sessionUser = JSON.parse(localStorage.getItem('sessionUser') || '{}');
                sessionUser.avatar = base64Url;
                localStorage.setItem('sessionUser', JSON.stringify(sessionUser));
                if (sessionUser.email) {
                    localStorage.setItem('user_avatar_' + sessionUser.email, base64Url);
                }
                updateHeaderUserInfo();
                if (typeof Toast !== 'undefined') Toast.show('Profile Picture Updated', 'Your custom profile picture has been saved.', 'success');
            };
            reader.readAsDataURL(file);
        });
    }

    if (removeBtn) {
        removeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            const sessionUser = JSON.parse(localStorage.getItem('sessionUser') || '{}');
            delete sessionUser.avatar;
            localStorage.setItem('sessionUser', JSON.stringify(sessionUser));
            if (sessionUser.email) {
                localStorage.removeItem('user_avatar_' + sessionUser.email);
            }
            updateHeaderUserInfo();
            if (typeof Toast !== 'undefined') Toast.show('Avatar Reset', 'Reverted to WhatsApp DP style initials avatar.', 'info');
        });
    }
}

// Bind Logout modal, user info, and avatar listeners on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    updateHeaderUserInfo();
    bindAvatarUploadListeners();

    const addLogoutModal = () => {
        if (document.getElementById('logout-modal')) return;

        const logoutModalHTML = `
            <div id="logout-modal" class="modal-overlay">
                <div class="modal-container" style="max-width: 400px;">
                    <div class="modal-header">
                        <h3>Confirm Logout</h3>
                        <button class="modal-close-btn"><i class="fas fa-times"></i></button>
                    </div>
                    <div class="modal-body">
                        <p>Are you sure you want to end your current dashboard session?</p>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary modal-cancel-btn">Cancel</button>
                        <button id="confirm-logout-btn" class="btn btn-danger">Logout</button>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', logoutModalHTML);

        const confirmBtn = document.getElementById('confirm-logout-btn');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', () => {
                logout();
            });
        }

        const closeBtn = document.querySelector('#logout-modal .modal-close-btn');
        const cancelBtn = document.querySelector('#logout-modal .modal-cancel-btn');
        if (closeBtn) closeBtn.addEventListener('click', () => Modal.close('logout-modal'));
        if (cancelBtn) cancelBtn.addEventListener('click', () => Modal.close('logout-modal'));
    };

    const logoutTriggers = document.querySelectorAll('.logout-trigger, #logout-btn');
    if (logoutTriggers.length > 0) {
        addLogoutModal();
        logoutTriggers.forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                if (typeof Modal !== 'undefined') {
                    Modal.open('logout-modal');
                } else {
                    if (confirm("Are you sure you want to logout?")) logout();
                }
            });
        });
    }
});
