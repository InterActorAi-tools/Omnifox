import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// L5: the previous version read `globalThis.window?.APP_CONFIG?.API_URL`
// at Vite config evaluation time. Vite's config runs in Node where
// `window` is undefined, so this expression always evaluated to "" and
// the dev proxy silently pointed at an empty target. Source from the
// dev .env file via Vite's loadEnv helper instead. The variable name
// is intentionally distinct from the runtime VITE_API_URL used by the
// browser bundle - the dev proxy speaks to the backend HOST, the
// browser speaks via the proxy at /.
export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), "");
    const rawBackend = (env.VITE_DEV_BACKEND_URL || "").trim();

    const backend_url = (() => {
        if (!rawBackend) return "";
        const withProtocol = /^[a-zA-Z][a-zA-Z\d+\-.]*:\/\//.test(rawBackend)
            ? rawBackend
            : `https://${rawBackend}`;
        return new URL(withProtocol).origin;
    })();

    // M7: previously every proxy entry set `secure: false`, which
    // disables TLS verification for the dev-server-to-backend hop and
    // trains developers to ignore cert warnings. Default `secure: true`
    // means a self-signed cert on the dev backend will fail loudly -
    // fix the cert (or set VITE_DEV_BACKEND_URL to a plain-http local
    // backend) instead of silencing the warning.
    const proxyEntry = {
        target: backend_url,
        changeOrigin: true,
    };

    return {
        plugins: [react(), tailwindcss()],
        test: {
            environment: "jsdom",
            globals: true,
            setupFiles: ["./src/test/setup.js"],
            css: false,
        },
        // L4: strip every `console.*` call from the production bundle
        // so sentiment payloads, user history items, and other PII
        // never land in customers' devtools.
        esbuild: {
            drop: mode === "production" ? ["console", "debugger"] : [],
        },
        server: {
            proxy: {
                "/api": proxyEntry,
                "/auth": proxyEntry,
                "/process": proxyEntry,
                "/download": proxyEntry,
                "/progress": proxyEntry,
            },
            headers: {
                "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
            },
        },
    };
});
