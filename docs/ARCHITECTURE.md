# Arquitectura

> Resumen técnico de cómo funciona OpenAIudio. Para reproducir el proyecto en
> producción, ver [DEPLOYMENT.md](DEPLOYMENT.md).

## Piezas

```
browser (broadcaster) ── gUM + PCM16 16 kHz ──▶  WS /ws/ingest/{id}
browser (audiencia) ─────────────────────────▶  WS /ws/audience/{id}?lang=
OBS / vMix ──────────────────────────────────▶  GET /feed/{id}/live?lang=
                                                   (y archivos .live.txt en disco)
línea de comandos ───────────────────────────▶  REST /api/sessions* + /healthz
```

Un solo proceso **FastAPI** (módulo `app/`) que:

1. Recibe audio del broadcaster (`app/routers/sessions.py` → `ingest`).
2. Lo convierte a `float32` mono 16 kHz (`app/audio.py`) y lo empuja al
   orquestador.
3. `app/store.py` decide por sesión qué proveedores levantar (original +
   traducciones) bajo un **presupuesto de providers activos** y les entrega
   audio o texto según la vía.
4. Los subtítulos (`app/captions.py`) se ensamblan en buffers por
   (sesión, idioma) que emiten eventos a la audiencia y feeds.
5. La audiencia recibe un `snapshot` al conectarse y luego eventos
   `caption` (partial/final) y `state`.

## Topología (ADR-0001)

- **Original**: siempre por audio.
- **Traducción**: por audio (Gemini Live) o texto (Gemini text / Gemma/Ollama),
  según `translation_mode` (`audio | text | auto`) y el proveedor.

## Providers

| Provider | Original | Traducción | Uso |
| --- | --- | --- | --- |
| `gemini` | Gemini Live (audio) | Gemini Live (audio) o Gemini text | nube, calidad |
| `local` | faster-whisper | Gemma vía Ollama (texto) | 100 % offline |
| `mock` | fake (por periodo) | fake | demos y CI |

Vista de estados por target: `warming → live ↔ idle`, re-intentos con backoff,
y conteo de audiencia por idioma. Si un target no tiene oyentes y supera el
tiempo de ociosidad, el barrido (`sweeper`) lo pausa para liberar el presupuesto.

## API pública

- `GET /api/sessions` · `POST /api/sessions` · `GET|DELETE /api/sessions/{id}`
- `POST /api/sessions/{id}/glossary`
- `GET /api/sessions/{id}/export?lang=&fmt=srt|vtt|txt`
- `GET /api/languages`
- `GET /healthz` · admin: `GET /admin/status` (ver `app/routers/admin.py`)
- `WS /ws/ingest/{id}` · `WS /ws/audience/{id}?lang=`
- `GET /feed/{id}/live?lang=` (plain text) + salida OBS en disco

## Frontend

Una SPA React/Vite en `web/` (ADR-0002) servida por FastAPI desde
`web/dist`. Tiene tres rutas: `/` (elegir sesión), `/broadcast`,
`/admin`, y `/:sid[/:lang]` para la vista de audiencia directa.

## Configuración

Todo sale de variables de entorno (`.env.example`). Los valores se resuelven
en `app/config.py`. `PROVIDER=auto` elige `gemini` si hay `GEMINI_API_KEY`,
si no `mock`.