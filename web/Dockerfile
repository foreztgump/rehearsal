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
ENV NEXT_PUBLIC_LIVEKIT_URL=${NEXT_PUBLIC_LIVEKIT_URL}
ENV NEXT_PUBLIC_REHEARSAL_MODEL_CHOICES=${NEXT_PUBLIC_REHEARSAL_MODEL_CHOICES}
ENV NEXT_PUBLIC_REHEARSAL_MODEL_LABELS=${NEXT_PUBLIC_REHEARSAL_MODEL_LABELS}
RUN npm run build

FROM node:24-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
# Standalone output bundles a self-contained server + only the deps it needs.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
