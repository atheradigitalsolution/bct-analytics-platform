# syntax=docker/dockerfile:1

# insight-portal - the BCT analytics dashboard.
#
# Multi-stage on the digest pinned in docs/agents/PLAN.md. A digest, not a tag: node:22-alpine moves
# and a tag would silently change the base of a signed image between two builds of the same commit.
#
# The runtime stage carries Next's standalone output and nothing else - no npm, no build toolchain,
# no node_modules tree the application does not import. There is no database driver in the image
# because there is none in the dependency tree: the portal reaches the warehouse only through the
# semantic API, and holds no credential that reaches Postgres.

FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# `npm ci` and not `npm install`: the lockfile is the input, so the image cannot drift from the tree
# that was scanned. Cache mount keeps rebuilds cheap without baking the cache into a layer.
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# A dedicated uid, distinct from the gateway's 10002 and the semantic API's 10003, so a process
# listing and an audit log can tell the three apart.
RUN addgroup -g 10004 -S portal && adduser -u 10004 -S -G portal portal

COPY --from=build --chown=root:root /app/.next/standalone ./
COPY --from=build --chown=root:root /app/.next/static ./.next/static
COPY --from=build --chown=root:root /app/public ./public

# Owned by root and readable by the runtime user, never writable by it: the process has no reason to
# modify its own code, and a read-only root filesystem in compose makes that structural rather than
# a matter of file modes alone.
USER 10004:10004

EXPOSE 3000

# JSON (exec) notation, not shell form: hadolint DL3025. Shell form wraps the probe in /bin/sh,
# so a hung probe leaves an extra process behind on every interval and the timeout signal goes to
# the shell rather than to node.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:' + (process.env.PORT || 3000) + '/healthz').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"]

CMD ["node", "server.js"]
