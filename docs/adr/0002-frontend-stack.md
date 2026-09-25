# ADR 0002 · Stack del frontend

- Estado: **Aceptado** (v0.1)
- Fecha: 2026-09
- Categoría: Frontend

## Contexto

Tres pantallas en una sola SPA: **audiencia** (elige sesión + idioma y ve
subtítulos), **broadcast** (captura micrófono y transmite audio), y
**producción** (sesiones live, estados, audiencia). Debe verse moderna,
oscura y correr desde el propio servidor FastAPI (un solo puerto en la
laptop del evento), con web dev con HMR para desarrollo.

## Decisión

- **React 19 + Vite** con TypeScript estricto y `tsc --noEmit` en build.
- **Tailwind v4** (plugin `@tailwindcss/vite`, tema oscuro `ink`/`neon` en
  `src/index.css`).
- **shadcn-style** de forma ligera: componentes `ui/*` propios
  (`button`, `card`, `fields`), sin dependencia externa pesada.
- **framer-motion** para transiciones de los subtítulos.
- **lucide-react** para iconos.
- `vite.config.ts` proxya `/api`, `/ws`, `/feed` y `/healthz` al backend
  `:8000` en desarrollo.

## Consecuencias

Positivas:
- Build estático servido por FastAPI (`web/dist`) → cero infraestructura.
- Base de estilo consistente y fácil de extender.

Negativas:
- No se usa el generador de componentes shadcn CLI: los componentes se
  mantienen a mano (intencional, son pocos).
- La vista de audiencia depende de WebSocket; si el evento exige escalar, se
  puede colocar un reverse proxy/horizonte delante (ver ADR futuro).