# Multi-stage Next.js standalone build → minimal runtime serving on :3000.
FROM node:24-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:24-bookworm-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* vars are inlined into the client bundle at build time, so the
# browser-facing LiveKit WS URL must be present here (not just at runtime).
ARG NEXT_PUBLIC_LIVEKIT_URL=ws://localhost:7880
ARG NEXT_PUBLIC_REHEARSAL_MODEL_CHOICES=fast,better
ARG NEXT_PUBLIC_REHEARSAL_MODEL_LABELS=Fast,Better
ARG NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE=0
ENV NEXT_PUBLIC_LIVEKIT_URL=${NEXT_PUBLIC_LIVEKIT_URL}
ENV NEXT_PUBLIC_REHEARSAL_MODEL_CHOICES=${NEXT_PUBLIC_REHEARSAL_MODEL_CHOICES}
ENV NEXT_PUBLIC_REHEARSAL_MODEL_LABELS=${NEXT_PUBLIC_REHEARSAL_MODEL_LABELS}
ENV NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE=${NEXT_PUBLIC_REHEARSAL_EXPRESSIVE_AVAILABLE}
RUN npm run build

FROM node:24-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
# Standalone output bundles a self-contained server + only the deps it needs.
# F34: own the copied files as the built-in non-root `node` user so the runtime
# runs unprivileged (the Next standalone server needs no root).
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public
EXPOSE 3000
# F34: run as the non-root `node` user shipped in the base image.
USER node
# F34: liveness probe on the standalone server. Node's global fetch (24) avoids a
# curl dependency; a non-200 or a throw exits non-zero → unhealthy.
HEALTHCHECK --start-period=20s --interval=30s --timeout=5s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server.js"]
