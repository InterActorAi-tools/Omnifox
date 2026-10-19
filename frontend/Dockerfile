ARG NODE_VERSION=22
ARG NGINX_VERSION=1.27-alpine

FROM node:${NODE_VERSION}-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build


FROM nginx:${NGINX_VERSION} AS runtime

RUN apk add --no-cache bash

COPY --from=build /app/dist /usr/share/nginx/html
# H7: ship the nginx config as a template stored OUTSIDE
# /etc/nginx/templates/ so the base image's own 20-envsubst step does
# not race us. Our entrypoint envsubsts ${CSP_HEADER} (composed from
# $API_URL) into /etc/nginx/conf.d/default.conf at container start.
COPY default.conf.template /etc/nginx/omnifox-default.conf.template
COPY docker-entrypoint.sh /docker-entrypoint.d/40-app-config.sh
RUN chmod +x /docker-entrypoint.d/40-app-config.sh

ENV API_URL="" \
    GOOGLE_CLIENT_ID=""

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
