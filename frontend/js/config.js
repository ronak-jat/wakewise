/**
 * WakeWise AI - Intelligent Cognitive Alarm Platform
 * Central API & Environment Configuration
 * 
 * Single source of truth for backend API base URL and client settings.
 */
(function (global) {
    // 1. Check for manual runtime override (e.g. from window or localStorage)
    const storedOverride = (function () {
        try {
            return global.localStorage ? (global.localStorage.getItem('WAKEWISE_API_BASE_URL') || global.localStorage.getItem('API_BASE_URL')) : null;
        } catch (e) {
            return null;
        }
    })();

    const runtimeOverride = global.WAKEWISE_API_BASE_URL || storedOverride;

    if (runtimeOverride && typeof runtimeOverride === 'string' && runtimeOverride.trim()) {
        global.API_BASE_URL = runtimeOverride.trim().replace(/\/+$/, '');
    } else {
        // 2. Environment Auto-Detection
        const loc = global.location;
        const hostname = (loc && loc.hostname) ? loc.hostname.toLowerCase() : '';
        const isLocal = !hostname ||
            hostname === 'localhost' ||
            hostname === '127.0.0.1' ||
            hostname === '[::1]' ||
            (loc && loc.protocol === 'file:');

        if (isLocal) {
            // If served directly from FastAPI on port 8000, use relative paths
            if (loc && loc.port === '8000') {
                global.API_BASE_URL = '';
            } else {
                global.API_BASE_URL = 'http://127.0.0.1:8000';
            }
        } else {
            // Production deployment (e.g. Vercel)
            global.API_BASE_URL = 'https://web-production-de20d.up.railway.app';
        }
    }

    // Single centralized getter for backward compatibility
    global.getApiBaseUrl = function () {
        return global.API_BASE_URL;
    };

    // Google OAuth Client ID fallback
    if (!global.GOOGLE_CLIENT_ID) {
        global.GOOGLE_CLIENT_ID = '1057786367809-mb9h4k6bjvcld420dpijgl6a038pcdjc.apps.googleusercontent.com';
    }

    // Optional background sync of public config from backend if reachable
    if (typeof global.fetch === 'function') {
        const configUrl = (global.API_BASE_URL ? global.API_BASE_URL : '') + '/api/auth/config';
        global.fetch(configUrl, { method: 'GET' })
            .then(function (res) { return res.ok ? res.json() : null; })
            .then(function (cfg) {
                if (cfg && cfg.google_client_id) {
                    global.GOOGLE_CLIENT_ID = cfg.google_client_id;
                }
            })
            .catch(function () {
                // Silently fallback to defaults when backend is initializing or offline
            });
    }
})(typeof window !== 'undefined' ? window : this);