# OpenAIudio — hackathon submission

> Live transcription + simultaneous translation for conferences.
> Submission notes for Nerdearla.

## Nerdearla needs this

Live talks are mostly one-way: the speaker streams, the audience listens, and
**non-native speakers, hearing-impaired attendees and streaming viewers lose
context**. Most captioning tools are SaaS-per-seat, cloud-locked, expensive,
and require shipping audio out to a third party. Nerdearla needed something the
staff could run on **one venue laptop**, free, offline if the network dies,
multi-language, and controllable by a production team — captions that work for
live rooms *and* live streams.

**OpenAIudio** is that: a single self-contained server that transcribes talks
in real time, translates them simultaneously (ES→EN, PT, and more), feeds the
audience **and OBS/vMix overlays**, and exposes a production console — with zero
per-seat cost and no mandatory cloud.

## It does closed captions from live video/audio

- **Any live source:** capture the **microphone**, **system audio** (rides the
  same OS loopback the video mixer hears), or a **local file** to rehearse —
  from the broadcast console in the browser (MediaDevices → 16 kHz PCM16 over
  WebSocket).
- **Original language:** windowed streaming STT (Gemini `generateContent` with
  inline audio, or local `faster-whisper`, or any OpenAI-compatible
  inline-audio model).
- **Simultaneous translation:** text → text streaming per target language
  (cloud or local Gemma via Ollama).
- **Delivered where viewers are:** Web UI audience page, `WS /ws/audience`,
  plain-text feeds + `.live.txt` files for **OBS/vMix** text sources, and
  SRT/VTT/TXT export when the talk ends.
- **Production-grade control:** per-language state, audience counts and **live
  provider errors** in `/admin`; primary/fallback vendor switching; one
  transmitter per session enforced and explained in the GUI.

## How we built it

- **Single FastAPI process** that serves everything: REST/WS, captions pipeline
  and the built React SPA.
- **Hybrid topology:** original STT via windowed inline-audio (reliable, cheap,
  streamable — we validated the *preview* Gemini Live models and rejected them)
  and translations from the original's final text (one cheap hop per language).
- **Vendor-agnostic:** a vendor registry (Gemini, xAI, OpenAI, Anthropic, Groq,
  Mistral, DeepSeek, Together, OpenRouter, Azure, local, mock) lets each session
  pick a **primary + fallback** from the GUI; keys stay server-side, masked in
  the API.
- **Resilience by design:** active-provider budget, idle sweeper, NaN-guarded
  RMS energy gate to skip silence, retries with backoff, per-request timeouts,
  and a 30 s start-failure cooldown.
- **Deterministic mocking + 36 automated tests** so the whole e2e flow works
  offline and in CI.

## Challenges we ran into

- **Preview APIs are flaky.** Gemini `*-transcribe-live` / `*-live-translate-preview`
  would hang or abort; the default live-preview model doesn't even support text
  response. We pivoted to windowed `generateContent` STT — reliable and fully
  streamable.
- **Free-tier quota ≈ 20 requests/day per model.** Every request needed to
  count: RMS energy gating, backoff, timeouts, and honoring `Retry-After`.
- **Error spirals in production:** a misconfigured vendor model caused ~4 STT
  restarts per second (bankrupting the budget and spamming the audience).
  Root-cause + cooldown/fallback logic fixed it, now visible in `/admin`.
- **One transmitter per session:** two windows silently raced. Rewrote the audio
  pipeline from scratch (mic/system/file sources in browser) and made the
  rejection visible to the operator.
- **Platform audio quirks:** `getDisplayMedia` to capture system loopback (stop
  the video tracks!), device selection, resampling every source to a single
  16 kHz mono PCM contract.

## Accomplishments that we're proud of

- One laptop → captions for the room **and** the stream, all languages,
  without a cloud bill.
- **100% offline mode** (faster-whisper + Ollama Gemma) documented per OS in
  `docs/LOCAL_WHISPER.md`.
- 36 green tests with zero network, covering the real e2e path.
- Multi-vendor without lock-in: `PROVIDER=auto` still "just works", and custom
  vendors can be created from the GUI.
- Keys never leave the server; clean `git grep` proves `.env` and `data/` never
  shipped a secret.

## What we learned

- Ship for the **reliability of the boring path** (windowed STT, text→text
  translation) before the shiny one (Live).
- **Budget everything**: providers, connections, retries — a conference laptop
  is a tiny datacenter.
- Fail loud but *structured*: operators need the reason a language isn't live
  (bad key vs. quota vs. model name) — that shaped `/admin`.
- Deterministic tests + a mock provider make a realtime audio product actually
  testable in CI.

## What's next for OpenAIudio

- HLS/LL-HLS caption output for streaming platforms and PWA install for
  audience screens.
- Speaker diarization + per-speaker color coding in captions.
- Streaming glossary and term override at conference scale (live bilingual
  dictionary).
- Distributed ingest (stage audio → one box, transcodes → another) for
  multi-track rooms.
- Whisper GPU worker mode and automatic model-size selection by CPU/GPU.
- Live caption history + shareable highlights; export aligned with talk videos.

## Built with

**Backend** — Python 3.11+ · FastAPI · Uvicorn · httpx · pydantic · numpy ·
google-genai · faster-whisper (CTranslate2) · Ollama (gemma3) ·
OpenAI/Anthropic-compatible client adapters (xAI, OpenAI, Anthropic, Groq,
Mistral, DeepSeek, Together, OpenRouter, Azure OpenAI) · pytest + Starlette
TestClient · GitHub Actions (CI)

**Frontend** — React 19 · TypeScript (strict) · Vite 6 · Tailwind CSS v4 ·
React Router 7 · framer-motion · lucide-react · class-variance-authority/clsx ·
Web Audio API + MediaDevices (`getUserMedia`, `getDisplayMedia`)

**Protocols & integrations** — WebSockets (ingest/audience) · PCM16 audio ·
REST + OpenAPI docs · OBS/vMix text feeds · SRT/VTT/TXT export

**Platform** — macOS · Linux · Windows · optional NVIDIA CUDA (ctranslate2) ·
Apple Silicon (Metal) · Git + GitHub (PRs, CI)