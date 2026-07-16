# Shared types

`openapi.json` is exported from the FastAPI application and `src/openapi.ts` is generated with
`pnpm --filter @all-rise/shared-types generate`. `src/index.ts` contains stable aliases consumed
by the web application; frontend code must not duplicate backend response shapes.
