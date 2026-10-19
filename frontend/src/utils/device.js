// Turn a stored user-agent string into a readable label, e.g. "Chrome on Windows".
export const describeDevice = (userAgent = "") => {
    const ua = userAgent || "";
    const browser = /Edg\//.test(ua) ? "Edge"
        : /OPR\//.test(ua) ? "Opera"
        : /Firefox\//.test(ua) ? "Firefox"
        : /Chrome\//.test(ua) ? "Chrome"
        : /Safari\//.test(ua) ? "Safari"
        : null;
    const os = /Windows/.test(ua) ? "Windows"
        : /iPhone|iPad/.test(ua) ? "iOS"
        : /Android/.test(ua) ? "Android"
        : /Mac OS X/.test(ua) ? "macOS"
        : /Linux/.test(ua) ? "Linux"
        : null;
    if (browser && os) return `${browser} on ${os}`;
    return browser || os || "Unknown device";
};
