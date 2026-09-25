# Contribuyendo

¡Gracias por querés ayudar con OpenAIudio! Pedidos abiertos: más idiomas,
proveedores (Whisper.cpp, Deepgram, local streaming), accesibilidad, y
herramientas de operación para el evento.

## Setup local

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cd web && npm install && cd ..
.venv/bin/pytest tests/ -q
cd web && npm run build   # + npm run dev para HMR
```

## Convenciones

- **Commits**: [Conventional Commits](https://www.conventionalcommits.org/es/)
  (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `ci:`, `chore:`).
- **Versiones**: SemVer; cada cambio que toca comportamiento se anota en
  `CHANGELOG.md` bajo *Unreleased*.
- **Backend**: Python con tipado; cada nueva pieza de lógica lleva tests en
  `tests/`. Corre `.venv/bin/pytest tests/ -q` antes de abrir el PR.
- **Frontend**: TypeScript estricto; el CI corre `tsc --noEmit && vite build`.
  Nada de emojis en el código ni docs, salvo pedido explícito.
- **Idioma de las interfaces**: es/en (las labels de la web están en español).

## Decisiones de diseño

Cualquier decisión estructural se decide en un archivo bajo `docs/adr/`
(siguiendo [MADR](https://adr.github.io/)): contexto, opciones, decisión,
consecuencias. Discutí el ADR en el issue/PR antes de codificar lo grande.

## PRs

1. `feat/` o `fix/` corto desde `main`.
2. Tests verdes + build del front OK.
3. Changelog actualizado en *Unreleased*.
4. Un reviewer aprueba y mergea con squash.