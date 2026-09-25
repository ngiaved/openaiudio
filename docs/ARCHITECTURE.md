# Architecture

> Technical overview of how OpenAIudio works. To run the project in
> production, see [DEPLOYMENT.md](DEPLOYMENT.md).

## Pieces

```
browser (broadcaster) ── gUM + PCM16 16 kHz ──▶  WS /ws/ingest/{id}
browser (audience) ─────────────────────────▶  WS /ws/audience/{id}?lang=
OBS / vMix ──────────────────────────────────▶  GET /feed/{id}/live?lang=
                                                    (and .live.txt files on disk)
command line ───────────────────────────────▶  REST /api/sessions* + /healthz
```

A single **FastAPI** process (`app/`) that:

1. Receives audio from the broadcaster (`app/routers/sessions.py` → `ingest`).
2. Converts it to `float32` mono 16 kHz (`app/audio.py`) and pushes it to the
   orchestrator.
3. `app/store.py` decides, per session, which providers to bring up (original +
   translations) under an **active-provider budget** and feeds them audio or
   text according to each target's pathway.
4. Captions (`app/captions.py`) are assembled into per-(session, language)
   buffers that emit events to the audience and to feeds.
5. The audience receives a `snapshot` on connect, then `caption`
   (partial/final) and `state` events.

## Topology (ADR-0001)

- **Original**: always via audio.
- **Translation**: via audio (Gemini Live, experimental) or text
  (any cloud text model / Gemma via Ollama), depending on
  `translation_mode` (`audio | text | auto`) and the provider.
- Each session can declare a **primary and a fallback vendor** (selectable in
  the `/broadcast` GUI). On a fatal provider error (bad/missing model, invalid
  key) the session switches to the fallback automatically; on non-fatal ones
  (rate-limit/quota) it only stops and waits. A start failure enters a 30 s
  cooldown to avoid error spirals — see `Store._try_fallback` and
  `Target.cooldown_until` in `app/store.py`.

## Vendors

`app/vendors.py` keeps a registry: built-in vendors (gemini, xai, openai,
anthropic, groq, mistral, deepseek, together, openrouter, azure_openai, local,
mock) plus user-created ones persisted to `data/vendors.json`. Every vendor
reads its API key from the environment and is auto-disabled without one;
`ENABLED_VENDORS` gates whole vendors. Custom vendors share the same features
and are created/tested from the `/vendors` page.

| Vendor | Protocol | Original (STT) | Translation |
| --- | --- | --- | --- |
| `gemini` | gemini | Gemini Live (audio) / windowed | Gemini text / live (audio) |
| `xai`, `openai`, `anthropic`, `groq`, `mistral`, `deepseek`, `together`, `openrouter`, `azure_openai` | openai (or anthropic) | inline-audio chat STT | chat text |
| `local` | local | faster-whisper | Gemma via Ollama (text) — see [LOCAL_WHISPER.md](LOCAL_WHISPER.md) |
| `mock` | mock | fake (periodic) | fake — demos and CI |

Per-target state machine: `warming → live ↔ idle`, retries with backoff, and
per-language audience counts. If a target has no listeners and exceeds the idle
timeout, the sweeper pauses it to free the budget.

## Public API

- `GET /api/sessions` · `POST /api/sessions` · `GET|DELETE /api/sessions/{id}`
- `POST /api/sessions/{id}/glossary` · `POST /api/sessions/{id}/switch` (fallback)
- `GET /api/sessions/{id}/export?lang=&fmt=srt|vtt|txt`
- `GET /api/languages`
- `GET /api/vendors` · `POST|PUT|DELETE /api/vendors/{id}` · `POST /api/vendors/{id}/test`
- `GET /healthz` · admin: `GET /admin/status` (see `app/routers/admin.py`)
- `WS /ws/ingest/{id}` · `WS /ws/audience/{id}?lang=`
- `GET /feed/{id}/live?lang=` (plain text) + OBS output on disk

## Frontend

A React/Vite SPA in `web/` (ADR-0002) served by FastAPI from `web/dist`. It has
four routes: `/` (pick a session), `/broadcast` (vendor + audio-source
selection, one transmitter per session), `/admin` (per-target state, live
provider errors and audience counts), `/vendors` (manage model vendors), and
`/:sid[/:lang]` for the direct audience view.

## Configuration

Everything comes from environment variables (`.env.example`). Values are
resolved in `app/config.py`. `PROVIDER=auto` picks `gemini` when
`GEMINI_API_KEY` is set, otherwise `mock`. Keys are only read from the env /
the `/vendors` page (never committed; `.env` and `data/` are gitignored).
For the fully-offline setup, see [LOCAL_WHISPER.md](LOCAL_WHISPER.md).