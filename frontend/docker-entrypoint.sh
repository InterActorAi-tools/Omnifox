#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="/usr/share/nginx/html/config.js"

: "${API_URL:?API_URL must be set}"
GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-}"  # empty hides Google sign-in

escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

API_URL_ESCAPED=$(escape "$API_URL")
GOOGLE_CLIENT_ID_ESCAPED=$(escape "$GOOGLE_CLIENT_ID")

cat > "$CONFIG_FILE" <<EOF
window.APP_CONFIG = {
  "GOOGLE_CLIENT_ID": "${GOOGLE_CLIENT_ID_ESCAPED}",
  "API_URL": "${API_URL_ESCAPED}"
};
EOF

echo "Wrote runtime config to ${CONFIG_FILE}"

# H7: derive the Content-Security-Policy connect-src allowance from the
# deployed API host. Browsers compare connect-src against the request's
# origin (scheme + host + port), so we strip any path segment from
# $API_URL before injecting it.
#
# CSP directives explained:
#   default-src 'self'          - everything off-origin is rejected unless
#                                 explicitly allowed below.
#   script-src 'self' + Google  - app bundle + Google Identity Services.
#   connect-src 'self' + API    - XHR / SSE to /api on the same origin,
#                                 plus the deployed API host (when the
#                                 frontend and API are on different
#                                 subdomains), plus Google's OAuth
#                                 bootstrap endpoint.
#   frame-src https://accounts.google.com - the GIS iframe.
#   img-src 'self' data: + googleusercontent - inline SVG icons, the
#                                 qrcode.react canvas (data: URLs), and
#                                 the user.picture_url from Google login.
#   style-src 'self' 'unsafe-inline' - Tailwind / MUI / Chakra inject
#                                 <style> tags at runtime; tightening
#                                 needs migration to nonces/hashes.
#   font-src 'self' data:       - bundled fonts plus inline data: URIs
#                                 used by MUI/icon packs.
#   object-src 'none'           - no Flash/Java/embed plugin surface.
#   base-uri 'self'             - blocks <base href=evil>.
#   form-action 'self'          - posts only stay on-origin.
#   frame-ancestors 'none'      - same intent as X-Frame-Options: DENY.
#   upgrade-insecure-requests   - rewrite stray http:// asset refs.
CSP_API_ORIGIN=$(printf '%s' "$API_URL" | awk -F/ '{print $1"//"$3}')

export CSP_HEADER="default-src 'self'; script-src 'self' https://accounts.google.com https://apis.google.com; connect-src 'self' ${CSP_API_ORIGIN} https://accounts.google.com; frame-src https://accounts.google.com; img-src 'self' data: https://*.googleusercontent.com; style-src 'self' 'unsafe-inline'; font-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests"

echo "Computed CSP connect-src origin: ${CSP_API_ORIGIN}"

# Render the nginx site config from the template. We use envsubst with
# an explicit variable allowlist so nginx's own `$var` references
# (e.g. $uri, $http_host) are left untouched. The template is shipped
# under /etc/nginx/templates/; the rendered output goes into
# /etc/nginx/conf.d/default.conf where nginx expects it.
NGINX_TEMPLATE="/etc/nginx/omnifox-default.conf.template"
NGINX_CONF="/etc/nginx/conf.d/default.conf"

if [[ -f "$NGINX_TEMPLATE" ]]; then
  envsubst '${CSP_HEADER}' < "$NGINX_TEMPLATE" > "$NGINX_CONF"
  echo "Rendered nginx config to ${NGINX_CONF}"
fi
