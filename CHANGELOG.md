# Changelog

All notable changes to OpenAIudio are documented in this file, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[SemVer](https://semver.org/).

## [Unreleased]

### Added
- End-to-end simultaneous transcription and translation pipeline.
- Hybrid topology: original always via audio; translations via audio or text,
  configurable per session (`audio | text | auto`).
- Providers: Gemini Live (audio), Gemini text (text), faster-whisper +
  Gemma/Ollama (local), and `mock` (demos/CI).
- Caption files: per-(session, language) buffers, SRT/VTT/TXT export.
- React/Vite web app: audience view, broadcast console and production panel,
  served by FastAPI itself.
- REST/WS API: sessions, glossary, audio ingest, audience, feeds (plain text
  and files for OBS/vMix), healthz, production status.
- API and end-to-end pipeline tests with the mock provider.
- Documentation: ADR-0001 (hybrid topology), ADR-0002 (frontend stack),
  architecture and deployment guides, security, contribution, CoC.
- GitHub Actions CI (backend + frontend) and Dependabot.
- Apache-2.0 license.

### Fixed
- WebSocket routing: audio ingest lived under `/api/`
  (`/api/ws/ingest/...`) because of the router prefix; moved to
  `/ws/ingest/...` with its own router.
- `AudienceConn` was not hashable (TypeError when registering an audience).

## [0.1.0] - 2026-09

First release with real audio streaming from browser to server, caption
generation with the `mock` provider and a live audience view.

## [0.0.1] - 2026-09 · unpublished

Initial skeleton (repo structure, license, base config).