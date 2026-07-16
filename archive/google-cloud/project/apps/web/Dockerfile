FROM node:24-alpine AS dependencies
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages/shared-types/package.json ./packages/shared-types/package.json
COPY packages/ui/package.json ./packages/ui/package.json
RUN pnpm install --frozen-lockfile

FROM dependencies AS builder
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/src ./apps/web/src
COPY apps/web/public ./apps/web/public
COPY apps/web/eslint.config.mjs apps/web/next-env.d.ts apps/web/next.config.ts apps/web/tsconfig.json ./apps/web/
COPY packages/shared-types/src ./packages/shared-types/src
COPY packages/ui/src ./packages/ui/src
RUN corepack enable && pnpm --filter @all-rise/web build

FROM dependencies AS validation
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/src ./apps/web/src
COPY apps/web/public ./apps/web/public
COPY apps/web/eslint.config.mjs apps/web/next-env.d.ts apps/web/next.config.ts apps/web/tsconfig.json ./apps/web/
COPY packages/shared-types/src ./packages/shared-types/src
COPY packages/ui/src ./packages/ui/src
RUN pnpm --filter @all-rise/web typecheck \
    && pnpm --filter @all-rise/web lint \
    && pnpm --filter @all-rise/web test

FROM node:24-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
COPY --from=builder --chown=node:node /app/apps/web/.next/standalone ./
COPY --from=builder --chown=node:node /app/apps/web/.next/static ./apps/web/.next/static
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
