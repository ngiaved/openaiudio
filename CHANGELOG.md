# Changelog

Todos los cambios notables de OpenAIudio quedan en este archivo, en formato
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado
[SemVer](https://semver.org/lang/es/).

## [Unreleased]

### Added
- Pipeline end-to-end de transcripción y traducción simultánea.
- Topología híbrida: original por audio; traducción por audio o texto,
  configurable por sesión (`audio | text | auto`).
- Providers: Gemini Live (audio), Gemini text (texto), faster-whisper +
  Gemma/Ollama (local), y `mock` (demos/CI).
- Archivos de subtítulos: buffers por (sesión, idioma), export SRT/VTT/TXT.
- Aplicación web React/Vite: vista de audiencia, consola de broadcast y panel
  de producción, servida por el propio FastAPI.
- REST/WS API: sesiones, glosario, ingestión de audio, audiencia, feeds
  (texto plano y archivos para OBS/vMix), healthz, status de producción.
- Tests de la API y del pipeline end-to-end con provider mock.
- Documentación: ADR-0001 (topología híbrida), ADR-0002 (stack frontend),
  guías de arquitectura y despliegue, seguridad, contribución, CoC.
- CI en GitHub Actions (backend + frontend) y Dependabot.
- Licencia Apache-2.0.

### Fixed
- Enrutado de WebSockets: la ingestión de audio vivía bajo `/api/`
  (`/api/ws/ingest/...`) por el prefijo del router; se movió a `/ws/ingest/...`
  con un router propio.
- `AudienceConn` no era hashable (TypeError al registrar audiencia).

## [0.1.0] - 2026-09

Primera versión con transmisión real de audio de navegador a servidor,
generación de subtítulos con el provider `mock` y vista de audiencia en vivo.

## [0.0.1] - 2026-09 · no publicado

Esqueleto inicial (estructura del repo, licencia, config base).