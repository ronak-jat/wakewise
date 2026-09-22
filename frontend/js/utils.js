/* ==========================================================================
   INTELLIGENT COGNITIVE ALARM PLATFORM - UTILITIES AND INTERFACE CONTROLLER
   ========================================================================== */

// Global Alarm State Safe Initialization
if (typeof window.currentRingingAlarm === 'undefined') {
    window.currentRingingAlarm = null;
}
if (typeof window.isWakeUpVerified === 'undefined') {
    window.isWakeUpVerified = false;
}

// Toast Notifications System
class ToastManager {
    constructor() {
        this.wrapper = document.getElementById('toast-wrapper');
        if (!this.wrapper) {
            this.wrapper = document.createElement('div');
            this.wrapper.id = 'toast-wrapper';
            document.body.appendChild(this.wrapper);
        }
    }

    /**
     * Display a sleek toast reminder
     * @param {string} title 
     * @param {string} message 
     * @param {'success' | 'warning' | 'danger' | 'info'} type 
     * @param {number} duration 
     */
    clearAll() {
        if (!this.wrapper) return;
        const toasts = this.wrapper.querySelectorAll('.toast-message');
        toasts.forEach(t => t.remove());
    }

    show(title, message, type = 'info', duration = 4000) {
        this.clearAll(); // Clear any previous active toast notifications
        const toast = document.createElement('div');
        toast.className = `toast-message toast-${type}`;
        
        let iconClass = 'fa-info-circle';
        if (type === 'success') iconClass = 'fa-check-circle';
        if (type === 'warning') iconClass = 'fa-exclamation-triangle';
        if (type === 'danger') iconClass = 'fa-exclamation-circle';

        toast.innerHTML = `
            <div class="toast-icon">
                <i class="fas ${iconClass}"></i>
            </div>
            <div class="toast-body">
                <div class="toast-title">${title}</div>
                <div class="toast-desc">${message}</div>
            </div>
            <div class="toast-close">
                <i class="fas fa-times"></i>
            </div>
        `;

        this.wrapper.appendChild(toast);

        // Force a layout reflow for animation
        toast.offsetHeight;

        // Slide in
        toast.classList.add('show');

        // Setup Close Handler
        const closeBtn = toast.querySelector('.toast-close');
        closeBtn.addEventListener('click', () => this.dismiss(toast));

        // Auto Dismiss
        const timeoutId = setTimeout(() => {
            this.dismiss(toast);
        }, duration);

        toast.dataset.timeoutId = timeoutId;
    }

    dismiss(toast) {
        if (toast.classList.contains('show')) {
            toast.classList.remove('show');
            clearTimeout(Number(toast.dataset.timeoutId));
            
            // Wait for CSS slide transition to finish before removing
            toast.addEventListener('transitionend', () => {
                toast.remove();
            });
        }
    }
}

// Global Instant of Toast Notifications
const Toast = new ToastManager();

const setDashboardActiveTab = (tabId) => {
    if (!tabId) return;
    localStorage.setItem(`${window.location.pathname}-active-tab`, tabId);
};

const restoreDashboardActiveTab = () => {
    const savedTab = localStorage.getItem(`${window.location.pathname}-active-tab`);
    if (savedTab && typeof window.switchTab === 'function') {
        if (document.getElementById(savedTab)) {
            switchTab(savedTab);
        }
    }
};

window.setDashboardActiveTab = setDashboardActiveTab;
window.restoreDashboardActiveTab = restoreDashboardActiveTab;

// Core UI Handlers
document.addEventListener('DOMContentLoaded', () => {
    // 1. Theme Handler (Light/Dark Mode toggle)
    const initTheme = () => {
        const savedTheme = localStorage.getItem('app-theme') || 'dark';
        document.body.setAttribute('data-theme', savedTheme);
        updateThemeToggles(savedTheme);
    };

    const toggleTheme = () => {
        const currentTheme = document.body.getAttribute('data-theme') || 'dark';
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.body.setAttribute('data-theme', newTheme);
        localStorage.setItem('app-theme', newTheme);
        updateThemeToggles(newTheme);
        Toast.show('Theme Updated', `Switched to ${newTheme} mode successfully.`, 'info', 2000);
    };

    const updateThemeToggles = (theme) => {
        const themeBtnIcons = document.querySelectorAll('.nav-toggle-theme i, #theme-toggle i');
        themeBtnIcons.forEach(icon => {
            if (theme === 'light') {
                icon.className = 'fas fa-moon';
            } else {
                icon.className = 'fas fa-sun';
            }
        });
    };

    // Attach theme toggle events
    const themeBtn = document.getElementById('theme-toggle') || document.querySelector('.nav-toggle-theme');
    if (themeBtn) {
        themeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            toggleTheme();
        });
    }

    initTheme();

    const ensureSidebarToggleExists = () => {
        document.querySelectorAll('.db-sidebar').forEach(sidebar => {
            if (!sidebar.querySelector('#sidebar-toggle')) {
                const brand = sidebar.querySelector('.sidebar-brand');
                if (!brand) return;

                const toggle = document.createElement('button');
                toggle.id = 'sidebar-toggle';
                toggle.className = 'sidebar-toggle-btn';
                toggle.title = 'Toggle Sidebar';
                toggle.innerHTML = '<i class="fas fa-bars"></i>';
                brand.appendChild(toggle);
            }
        });
    };

    ensureSidebarToggleExists();

    // 2. Sidebar Collapse Handler
    const sidebarToggle = document.getElementById('sidebar-toggle');
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', (e) => {
            e.preventDefault();
            document.body.classList.toggle('sidebar-collapsed');
            
            // Save state
            const isCollapsed = document.body.classList.contains('sidebar-collapsed');
            localStorage.setItem('sidebar-collapsed', isCollapsed ? 'true' : 'false');
        });
    }

    // Mobile Hamburger Menu toggle drawer
    const mobileToggle = document.getElementById('mobile-nav-toggle');
    if (mobileToggle) {
        mobileToggle.addEventListener('click', (e) => {
            e.preventDefault();
            document.body.classList.toggle('sidebar-open');
        });
    }

    const restoreSidebarState = () => {
        const savedCollapse = localStorage.getItem('sidebar-collapsed');
        if (savedCollapse === 'true') {
            document.body.classList.add('sidebar-collapsed');
        }
    };

    // Global switchTab implementation
    window.switchTab = (tabId) => {
        if (!tabId) return;

        let targetId = tabId;
        if (!document.getElementById(targetId) && document.getElementById(`tab-${tabId}`)) {
            targetId = `tab-${tabId}`;
        }

        const sections = document.querySelectorAll('.tab-content-section');
        if (sections.length > 0) {
            sections.forEach(sec => sec.classList.remove('active'));
            const activeSection = document.getElementById(targetId);
            if (activeSection) {
                activeSection.classList.add('active');
            }
        }

        document.querySelectorAll('.sidebar-menu-item').forEach(item => {
            item.classList.remove('active');
            const itemTab = item.dataset.tab;
            if (itemTab === targetId || itemTab === tabId || itemTab === targetId.replace('tab-', '')) {
                item.classList.add('active');
            }
        });

        const crumbText = document.getElementById('breadcrumb-current');
        if (crumbText) {
            const activeItemSpan = document.querySelector(`.sidebar-menu-item.active span`);
            if (activeItemSpan && activeItemSpan.textContent) {
                crumbText.textContent = activeItemSpan.textContent.trim();
            }
        }

        const cleanHash = targetId.replace('tab-', '');
        if (window.history && window.history.replaceState) {
            window.history.replaceState(null, null, `#${cleanHash}`);
        }

        if (typeof window.setDashboardActiveTab === 'function') {
            window.setDashboardActiveTab(targetId);
        }

        document.body.classList.remove('sidebar-open');
    };

    const syncBreadcrumbFromActiveMenu = () => {
        const crumbText = document.getElementById('breadcrumb-current');
        const activeItem = document.querySelector('.sidebar-menu-item.active');
        if (crumbText && activeItem) {
            const activeLabel = activeItem.querySelector('span')?.textContent?.trim();
            if (activeLabel) {
                crumbText.textContent = activeLabel;
            }
        }
    };

    const setDashboardActiveTab = (tabId) => {
        if (!tabId) return;
        localStorage.setItem(`${window.location.pathname}-active-tab`, tabId);
    };

    const restoreDashboardActiveTab = () => {
        const hash = window.location.hash.replace('#', '').trim();
        if (hash) {
            let tabId = hash;
            if (!document.getElementById(tabId) && document.getElementById(`tab-${hash}`)) {
                tabId = `tab-${hash}`;
            }
            if (document.getElementById(tabId)) {
                switchTab(tabId);
                return;
            }
        }

        const savedTab = localStorage.getItem(`${window.location.pathname}-active-tab`);
        if (savedTab && typeof window.switchTab === 'function') {
            if (document.getElementById(savedTab)) {
                switchTab(savedTab);
            }
        }
    };
    window.restoreDashboardActiveTab = restoreDashboardActiveTab;
    window.setDashboardActiveTab = setDashboardActiveTab;

    const highlightMenuItemForPage = () => {
        const currentPath = window.location.pathname.split('/').pop();
        if (!currentPath) return;

        document.querySelectorAll('.sidebar-menu-item').forEach(item => {
            const link = item.querySelector('a[href]');
            if (!link) return;
            const linkHref = link.getAttribute('href').split('/').pop();
            if (linkHref && linkHref.replace(/#.*/, '') === currentPath) {
                document.querySelectorAll('.sidebar-menu-item.active').forEach(active => active.classList.remove('active'));
                item.classList.add('active');
            }
        });

        syncBreadcrumbFromActiveMenu();
    };

    const bindSidebarNavigation = () => {
        document.querySelectorAll('.sidebar-menu-item').forEach(item => {
            const tabId = item.dataset.tab;
            const anchor = item.querySelector('a');
            
            const handleNavigation = (e) => {
                if (tabId && document.getElementById(tabId.startsWith('tab-') ? tabId : `tab-${tabId}`)) {
                    e.preventDefault();
                    switchTab(tabId);
                } else if (anchor) {
                    const href = anchor.getAttribute('href');
                    if (href && href !== '#' && !href.startsWith('javascript:')) {
                        // Allow standard link navigation if referencing a different HTML page
                        return;
                    }
                    e.preventDefault();
                }
            };

            if (anchor) {
                anchor.addEventListener('click', handleNavigation);
            } else {
                item.addEventListener('click', handleNavigation);
            }
        });
    };

    // Restore any saved preferences and then initialize sidebars
    restoreSidebarState();
    highlightMenuItemForPage();
    bindSidebarNavigation();
    restoreDashboardActiveTab();
    syncBreadcrumbFromActiveMenu();

    window.addEventListener('hashchange', restoreDashboardActiveTab);

    // Close mobile menu when clicking outside
    document.addEventListener('click', (e) => {
        if (document.body.classList.contains('sidebar-open')) {
            const sidebar = document.querySelector('.db-sidebar');
            const toggle = document.getElementById('mobile-nav-toggle');
            if (sidebar && !sidebar.contains(e.target) && toggle && !toggle.contains(e.target)) {
                document.body.classList.remove('sidebar-open');
            }
        }
    });

    // 3. Profile Dropdown Toggle
    const profileTrigger = document.getElementById('profile-trigger');
    const dropdownMenu = document.getElementById('profile-dropdown');
    if (profileTrigger && dropdownMenu) {
        profileTrigger.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdownMenu.classList.toggle('show');
        });

        document.addEventListener('click', () => {
            dropdownMenu.classList.remove('show');
        });
    }

    // 4. Live Date & Time updates
    const timeDisplay = document.querySelector('.db-time-widget .time');
    const dateDisplay = document.querySelector('.db-time-widget .date');
    if (timeDisplay || dateDisplay) {
        const updateTime = () => {
            const now = new Date();
            if (timeDisplay) {
                timeDisplay.textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            }
            if (dateDisplay) {
                const options = { weekday: 'long', year: 'numeric', month: 'short', day: 'numeric' };
                dateDisplay.textContent = now.toLocaleDateString('en-US', options);
            }
        };
        updateTime();
        setInterval(updateTime, 1000);
    }

    // 5. Dynamic Greeting update based on hour
    const greetingText = document.getElementById('greeting-text');
    if (greetingText) {
        const getGreeting = () => {
            const hour = new Date().getHours();
            if (hour < 12) return 'Good Morning';
            if (hour < 18) return 'Good Afternoon';
            return 'Good Evening';
        };
        
        // Fetch current user from localStorage
        const sessionUser = JSON.parse(localStorage.getItem('sessionUser') || '{}');
        const username = sessionUser.name || 'User';
        greetingText.innerHTML = `${getGreeting()}, <span class="grad-text">${username}</span>!`;
    }

    // 6. Global Loader Mask handler
    const loaderMask = document.getElementById('loader-mask');
    if (loaderMask) {
        // Fade out loader after slight delay
        setTimeout(() => {
            loaderMask.classList.add('hide');
        }, 600);
    }
});

// Custom Modal Controllers
const Modal = {
    open(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('show');
            document.body.style.overflow = 'hidden';
        }
    },
    close(modalId) {
        // Prevent bypassing challenge modal while alarm is actively ringing
        if (modalId === 'challenge-modal' && window.currentRingingAlarm && window.isWakeUpVerified !== true) {
            console.warn("🔒 Wake-Up Verification in progress. Modal dismissal blocked.");
            return;
        }

        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('show');
            document.body.style.overflow = '';
        }

        if (modalId === 'challenge-modal' && window.isWakeUpVerified === true && typeof window.stopAlarmSound === 'function') {
            window.stopAlarmSound();
        }
    }
};

// Wire up general close modal clicks
document.addEventListener('DOMContentLoaded', () => {
    const closeButtons = document.querySelectorAll('.modal-close-btn, .modal-cancel-btn');
    closeButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            const modal = e.target.closest('.modal-overlay');
            if (modal) {
                if (modal.id === 'challenge-modal' && window.currentRingingAlarm && window.isWakeUpVerified !== true) {
                    return;
                }
                Modal.close(modal.id);
            }
        });
    });

    const overlays = document.querySelectorAll('.modal-overlay');
    overlays.forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                if (overlay.id === 'challenge-modal') {
                    // Force user to solve cognitive challenge to close modal
                    return;
                }
                Modal.close(overlay.id);
            }
        });
    });

    // Prevent ESC key from bypassing active wake-up verification
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && window.currentRingingAlarm && window.isWakeUpVerified !== true) {
            e.preventDefault();
            e.stopPropagation();
        }
    });
});

// Web Audio Alarm Tone Synthesizer (Fallback tone generator)
window.playAlarmSynthTone = function(soundType = 'Radar') {
    try {
        const AudioCtxClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtxClass) return;
        if (!window._alarmAudioCtx) {
            window._alarmAudioCtx = new AudioCtxClass();
        }
        if (window._alarmAudioCtx.state === 'suspended') {
            window._alarmAudioCtx.resume();
        }

        const osc = window._alarmAudioCtx.createOscillator();
        const gain = window._alarmAudioCtx.createGain();
        osc.connect(gain);
        gain.connect(window._alarmAudioCtx.destination);

        const now = window._alarmAudioCtx.currentTime;
        if (soundType === 'Chimes') {
            osc.type = 'sine';
            osc.frequency.setValueAtTime(523.25, now);
            osc.frequency.setValueAtTime(659.25, now + 0.2);
            osc.frequency.setValueAtTime(783.99, now + 0.4);
        } else if (soundType === 'Forest Bird') {
            osc.type = 'sine';
            osc.frequency.setValueAtTime(1200, now);
            osc.frequency.setValueAtTime(1600, now + 0.1);
            osc.frequency.setValueAtTime(1400, now + 0.25);
        } else if (soundType === 'WakeUp Dj') {
            osc.type = 'sawtooth';
            osc.frequency.setValueAtTime(440, now);
            osc.frequency.setValueAtTime(880, now + 0.15);
        } else {
            osc.type = 'square';
            osc.frequency.setValueAtTime(800, now);
            osc.frequency.setValueAtTime(1000, now + 0.2);
        }

        gain.gain.setValueAtTime(0.4, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
        osc.start(now);
        osc.stop(now + 0.6);
    } catch (e) {
        console.error('Synth tone error:', e);
    }
};

// Unlock browser HTML5 audio element & AudioContext on user click or touch interaction
document.addEventListener('click', () => {
    if (window._alarmAudioCtx && window._alarmAudioCtx.state === 'suspended') {
        window._alarmAudioCtx.resume();
    }
    const audio = document.getElementById('alarm-audio');
    if (audio && audio.paused && audio.currentTime > 0) {
        audio.play().catch(() => {});
    }
}, { once: false });
