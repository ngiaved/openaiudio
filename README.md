# OpenAIudio

Transcripción y **traducción simultánea open source** para conferencias:
varias sesiones en paralelo, subtítulos en vivo para la audiencia, consola de
broadcast y panel para el equipo de producción.

- **Original siempre por audio** (Gemini Live o `faster-whisper` local).
- **Traducciones por audio o texto** (Gemini / Gemma vía Ollama), configurable
  por sesión (`audio | text | auto`). Ver [ADR-0001](docs/adr/0001-hybrid-topology.md).
- Un solo binario/servidor: la SPA (React/Vite) la sirve el propio FastAPI.
- Sin API key arranca en modo `mock` para demos y CI.
- Licencia **Apache-2.0**. Hecho para [Nerdearla](https://nerdear.la).

## Requisitos

- Python 3.11+ · Node 20+ (para buildear el front)
- Opcional: `GEMINI_API_KEY` (AI Studio) para la nube · `ollama` en el modo local

## Arranque rápido

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env        # y editar (o dejarlo sin key → provider mock)

cd web && npm install && npm run build && cd ..
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abrí `http://localhost:8000` (audiencia), `/broadcast` (transmitir) y
`/admin` (producción). Docs de la API en `/docs`.

## Uso en la conferencia

Seguí la [Guía de despliegue](docs/DEPLOYMENT.md):
1. **Producción** crea la sesión desde `/broadcast` y transmite.
2. La **audiencia** entra por `/` y elige sesión e idioma.
3. OBS/vMix consumen `/feed/{id}/live?lang=` o archivos `.live.txt`.

## Arquitectura

- `store.py`: orquestador (presupuesto de providers, estados, barrido).
- `providers/`: `gemini`, `local` (whisper + Ollama), `mock`.
- `captions.py`: buffers y export SRT/VTT/TXT.
- `routers/`: REST/WS ingest+audience/feed/admin.
- Más en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Desarrollo

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/           # pipeline end-to-end con provider mock
cd web && npm run dev             # Vite :5173 con proxy al backend :8000
```

Ver [CONTRIBUTING.md](CONTRIBUTING.md) y el [CHANGELOG.md](CHANGELOG.md).

## Configuración

Todas las opciones se documentan en `.env.example`
(`PROVIDER`, `GEMINI_MODEL`, `TRANSLATION_MODE`, `MAX_PROVIDERS`,
`MAX_SESSIONS`, `IDLE_TIMEOUT_SEC`, `OBS_OUT_DIR`, `WHISPER_MODEL`,
`OLLAMA_URL`, `OLLAMA_MODEL`, `HOST`, `PORT`, …).

## Seguridad

Reportá vulnerabilidades siguiendo [SECURITY.md](SECURITY.md). Este proyecto
**no** pretende ser un servicio multi-tenant expuesto a internet; se asume red
de confianza dentro del evento y se recomienda usarlo tras un proxy con HTTPS.

## Licencia

[Apache License 2.0](LICENSE). © 2026 OpenAIudio contributors.