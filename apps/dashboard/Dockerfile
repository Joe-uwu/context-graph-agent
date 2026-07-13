# Cortex dashboard — a single-file static SPA served by nginx on :3000.
# No build step: index.html loads React from a CDN and talks to api-service over REST.
#   docker build -t cortex/dashboard apps/dashboard

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
EXPOSE 3000
