import axios from "axios";

const getApiUrl = () => window.APP_CONFIG?.API_URL;

// H10: credentials now live in HttpOnly cookies set by the backend.
// We only cache the `user` payload client-side for UX (avatar, name,
// roles). The backend's /auth/logout clears the cookies; we just clear
// the local user cache.
export const clearAuthStorage = () => {
    localStorage.removeItem("user");
    // Best-effort cleanup of legacy localStorage entries left over from
    // pre-H10 sessions. A user upgrading across deploys will land here
    // once.
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
};

// H10: read the JS-readable XSRF-TOKEN cookie. Returns "" when not
// signed in (or when the deploy is still on a domain that hasn't set
// it yet) - callers only attach the header when the value is truthy.
const readCsrfCookie = () => {
    const match = document.cookie.match(/(?:^|;\s*)XSRF-TOKEN=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
};

// Create a single axios instance with interceptors.
// withCredentials:true is mandatory for the browser to send the
// HttpOnly auth cookies on cross-origin requests; same-origin would
// send them anyway, but staging and dev split the frontend / API
// hostnames.
const api = axios.create({
    baseURL: getApiUrl(),
    withCredentials: true,
    headers: {
        "Content-Type": "application/json",
    },
});

// On every request: refresh the base URL (config.js may load late) and
// attach the CSRF header for mutating methods. The backend rejects
// state-changing requests that present a cookie session but no
// matching X-CSRF-Token.
const MUTATING_METHODS = new Set(["post", "put", "patch", "delete"]);

api.interceptors.request.use(
    (config) => {
        const apiUrl = getApiUrl();
        if (apiUrl) {
            config.baseURL = apiUrl;
        }

        config.headers = config.headers ?? {};
        const method = (config.method || "get").toLowerCase();
        if (MUTATING_METHODS.has(method)) {
            const csrf = readCsrfCookie();
            if (csrf) {
                config.headers["X-CSRF-Token"] = csrf;
            }
        }
        return config;
    },
    (error) => Promise.reject(error)
);

// Auth endpoints report their own errors (wrong password, bad 2FA code,
// expired refresh). Sending them through the refresh/redirect logic below
// reloaded the login page and looped forever when /auth/refresh got 401.
const AUTH_ENDPOINTS = [
    "/auth/login",
    "/auth/register",
    "/auth/verify-2fa",
    "/auth/google",
    "/auth/refresh",
    "/auth/forgot-password",
    "/auth/reset-password",
];

// Share one in-flight refresh. The backend rotates refresh tokens and
// treats a replayed one as theft, so parallel refreshes after the access
// token expires would log the user out of every session.
let refreshPromise = null;
const refreshSession = () => {
    if (!refreshPromise) {
        refreshPromise = api.post("/auth/refresh", {}).finally(() => {
            refreshPromise = null;
        });
    }
    return refreshPromise;
};

// Handle 401 errors: try one refresh, then retry the original request.
// Both the refresh call and the retry rely on cookies - no localStorage
// reads needed.
api.interceptors.response.use(
    (response) => response,
    async (error) => {
        const originalRequest = error.config;
        const isAuthEndpoint = AUTH_ENDPOINTS.some((path) => originalRequest?.url?.startsWith(path));
        if (isAuthEndpoint) {
            return Promise.reject(error);
        }

        if (error.response?.status === 401 && originalRequest && !originalRequest._retry) {
            originalRequest._retry = true;

            try {
                // Empty-body refresh; the HttpOnly refresh_token cookie
                // carries the credential. The backend rotates and sets
                // fresh cookies on the response.
                await refreshSession();
                return api(originalRequest);
            } catch (refreshError) {
                clearAuthStorage();
                window.location.href = "/login";
                return Promise.reject(refreshError);
            }
        }

        // 401 (unauth) or 403 (CSRF / RBAC) - clear local cache and
        // redirect to login. The cookies themselves are cleared by
        // the backend on /auth/logout or by the browser on session
        // expiry.
        if (error.response?.status === 401 || error.response?.status === 403) {
            clearAuthStorage();
            window.location.href = "/login";
        }

        return Promise.reject(error);
    }
);

export const authService = {
    // Authentication
    async register(email, password, name, token) {
        const response = await api.post("/auth/register", { email, password, name, token });
        if (response.data?.user) {
            localStorage.setItem("user", JSON.stringify(response.data.user));
        }
        return response.data;
    },

    async getInviteDetails(token) {
        const response = await api.get(`/auth/invitation/${token}`);
        return response.data;
    },

    async login(email, password) {
        const response = await api.post("/auth/login", { email, password });
        if (response.data?.user) {
            localStorage.setItem("user", JSON.stringify(response.data.user));
        }
        return response.data;
    },

    async forgotPassword(email) {
        const response = await api.post("/auth/forgot-password", { email });
        return response.data;
    },

    async resetPassword(token, new_password) {
        const response = await api.post("/auth/reset-password", { token, new_password });
        return response.data;
    },

    async changePassword(current_password, new_password) {
        const response = await api.post("/users/me/change-password", {
            current_password,
            new_password,
        });
        return response.data;
    },

    async verify2FA(email, code) {
        const response = await api.post("/auth/verify-2fa", { email, code });
        if (response.data?.user) {
            localStorage.setItem("user", JSON.stringify(response.data.user));
        }
        return response.data;
    },

    async enable2FA() {
        const response = await api.post("/users/me/2fa/enable");
        return response.data;
    },

    async confirm2FA(code) {
        const response = await api.post("/users/me/2fa/confirm", { code });
        return response.data;
    },

    async disable2FA(password) {
        const response = await api.post("/users/me/2fa/disable", { password });
        return response.data;
    },

    // --- Admin Session Management ---
    async getAdminUserSessions(userId) {
        const response = await api.get(`/admin/users/${userId}/sessions`);
        return response.data;
    },

    async adminRevokeSession(userId, sessionId) {
        await api.delete(`/admin/users/${userId}/sessions/${sessionId}`);
    },

    async googleLogin(credential) {
        const response = await api.post("/auth/google", { credential });
        if (response.data?.user) {
            localStorage.setItem("user", JSON.stringify(response.data.user));
        }
        return response.data;
    },

    async refreshTokens() {
        // H10: cookies carry the credential. Empty-body POST is enough.
        await refreshSession();
    },

    async logout() {
        try {
            await api.post("/auth/logout");
        } catch (error) {
            console.error("Logout error:", error);
        } finally {
            clearAuthStorage();
        }
    },

    async logoutAllDevices() {
        await api.post("/users/me/logout-all");
        clearAuthStorage();
    },

    // User info
    async getCurrentUser() {
        const response = await api.get("/users/me");
        localStorage.setItem("user", JSON.stringify(response.data));
        return response.data;
    },

    getStoredUser() {
        const user = localStorage.getItem("user");
        return user ? JSON.parse(user) : null;
    },

    isAuthenticated() {
        // H10: we no longer have a token in JS we can inspect. The
        // cached `user` object is the best client-side signal that
        // the previous session is still alive; the real check happens
        // server-side when getCurrentUser fires. Any caller that needs
        // a hard answer should `await authService.getCurrentUser()`
        // and treat a 401 as not-authenticated.
        return !!localStorage.getItem("user");
    },

    // Sessions
    async getSessions() {
        const response = await api.get("/users/me/sessions");
        return response.data;
    },

    async deleteSession(sessionId) {
        await api.delete(`/users/me/sessions/${sessionId}`);
    },

    // Your data (GDPR)
    async deleteResult(filename) {
        await api.delete(`/users/me/results/${encodeURIComponent(filename)}`);
    },

    async deleteMyData(confirmEmail) {
        await api.post("/users/me/delete-data", { confirm_email: confirmEmail });
    },

    async deleteMyAccount(confirmEmail) {
        await api.post("/users/me/delete-account", { confirm_email: confirmEmail });
    },

    // Results (server-side history)
    async listResults() {
        const response = await api.get("/analysis");
        return response.data;
    },

    async getResult(filename) {
        const response = await api.get(`/analysis/${encodeURIComponent(filename)}`);
        return response.data;
    },

    // Chat about an analysis
    async getChat(filename) {
        const response = await api.get(`/analysis/${encodeURIComponent(filename)}/chat`);
        return response.data;
    },

    async sendChat(filename, message) {
        const response = await api.post(`/analysis/${encodeURIComponent(filename)}/chat`, { message });
        return response.data;
    },

    async applyProposal(filename, proposalId) {
        const response = await api.post(`/analysis/${encodeURIComponent(filename)}/proposals/${proposalId}/apply`);
        return response.data;
    },

    async dismissProposal(filename, proposalId) {
        await api.post(`/analysis/${encodeURIComponent(filename)}/proposals/${proposalId}/dismiss`);
    },

    // Activity
    async getActivity(limit = 50) {
        const response = await api.get(`/users/me/activity?limit=${limit}`);
        return response.data;
    },

    async getPendingInvitations() {
        const response = await api.get("/admin/invitations");
        return response.data;
    },
};

// Tells the History button to recount after a result is added or deleted.
export const RESULTS_CHANGED = "omnicat:results-changed";
export const notifyResultsChanged = (detail = {}) => window.dispatchEvent(new CustomEvent(RESULTS_CHANGED, { detail }));

// Download a result file through the shared client, so an expired access
// token is refreshed instead of failing. Returns null on success or a
// user-facing error message.
export const downloadFile = async (url, filename) => {
    try {
        const response = await api.get(url, { responseType: "blob" });
        const blobUrl = window.URL.createObjectURL(response.data);
        const link = document.createElement("a");
        link.href = blobUrl;
        link.download = filename || decodeURIComponent(url.split("/").pop());
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(blobUrl);
        return null;
    } catch (error) {
        if (error.response?.status === 404) {
            return "This file is no longer available. Results are kept for 30 days; run the analysis again to get a new file.";
        }
        return "Download failed. Please try again.";
    }
};

export default api;
