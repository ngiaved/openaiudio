# Deployment guide (conference)

Step-by-step guide to run OpenAIudio on an event's production laptop.
Requirements: Python 3.11+ and Node 20+ (only to build the frontend).

## 1) Install the backend

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## 2) Configure credentials

```bash
cp .env.example .env
# edit .env: at minimum GEMINI_API_KEY if you use the cloud
```

If there is **no** key, `PROVIDER=auto` falls back to the `mock` provider
(useful for rehearsing the whole flow without internet).

### Which Gemini model to use

For the cloud provider to work, `GEMINI_MODEL` and `GEMINI_TEXT_MODEL` must
both be set to a text-capable model that exists on your Google AI Studio
account:

- `GEMINI_MODEL=gemini-3.8-flash` — used for the **original** captions
  (windowed STT: inline audio → generated text).
- `GEMINI_TEXT_MODEL=gemini-3.8-flash` — used for **translations** (text → text).
  If unset, it defaults to `GEMINI_MODEL`.
- `GEMINI_LIVE_MODEL=gemini-3.5-transcribe-live` — **only** needed for the
  experimental `TRANSLATION_MODE=audio` path. Ignored otherwise.

If the model name is wrong or not available on the key, every request fails
with an invalid-model error and no captions are produced. Free-tier keys have a
small daily quota (≈20 requests/day per model); a paid/Billing-enabled key is
recommended for a real event.

## 3) Build the frontend (once)

```bash
cd web
npm install
npm run build
cd ..
```

The build lives in `web/dist` and FastAPI serves it by itself.

## 4) Run

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Web: `http://localhost:8000` · API docs: `http://localhost:8000/docs`
· Health: `http://localhost:8000/healthz`

From another laptop in the venue, browse to the machine's IP
(`http://192.168.x.x:8000`); make sure the macOS firewall allows inbound
connections on port 8000.

## 5) Operate during the talk

1. **Production** → `http://…:8000/admin`: watch sessions, states, audience.
2. **Broadcast** → `http://…:8000/broadcast` from the stage laptop: create the
   session, pick languages and press **Transmit**. Grant the microphone
   permission.
3. **Audience** → `http://…:8000`: pick a session and language on each screen.

### OBS / vMix

- Plain-text overlay: `GET http://host:8000/feed/{session_id}/live?lang=en`
  (or the file `data/{session_id}.{lang}.live.txt` when `OBS_OUT_DIR` is set).
  Poll every few seconds and show it in a text source.
- Final captions: export with `POST`/`GET
  /api/sessions/{id}/export?fmt=srt` when the talk ends.

## 6) Fully local mode

Install Ollama with `gemma3:4b` (`ollama pull gemma3:4b`), `faster-whisper`,
and set `PROVIDER=local`. Translation then runs via text through Gemma.

## Event readiness checklist

- Automated health check: `curl -fsS http://localhost:8000/healthz`.
- Test 5 minutes ahead: create a session with `mock`, broadcast for 10 s, open
  the audience view on the venue Wi-Fi and verify captions appear.
- Recommended `MAX_PROVIDERS` to match the languages: 1 original + N
  translations per stage; practically, scale to 2× as margin.
- Keep a fallback key and a network cable handy as plan B.