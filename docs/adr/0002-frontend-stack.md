# ADR 0002 · Frontend stack

- Status: **Accepted** (v0.1)
- Date: 2026-09
- Category: Frontend

## Context

Three screens in a single SPA: **audience** (picks a session + language and
sees captions), **broadcast** (captures the microphone and streams audio), and
**production** (live sessions, states, audience). It must look modern and dark,
run from the FastAPI server itself (one port on the venue laptop), and provide
a dev server with HMR for development.

## Decision

- **React 19 + Vite** with strict TypeScript and `tsc --noEmit` in the build.
- **Tailwind v4** (`@tailwindcss/vite` plugin, dark `ink`/`neon` theme in
  `src/index.css`).
- A light **shadcn-style** approach: our own `ui/*` components
  (`button`, `card`, `fields`), no heavy external dependency.
- **framer-motion** for caption transitions.
- **lucide-react** for icons.
- `vite.config.ts` proxies `/api`, `/ws`, `/feed` and `/healthz` to the
  backend on `:8000` in development.

## Consequences

Positive:
- Static build served by FastAPI (`web/dist`) → zero infrastructure.
- Consistent, easy-to-extend style base.

Negative:
- The shadcn component generator CLI is not used: components are maintained by
  hand (intentional; there are few).
- The audience view depends on WebSockets; if the event needs to scale, a
  reverse proxy/horizon can be placed in front (see a future ADR).