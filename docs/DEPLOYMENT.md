# Guía de despliegue (conferencia)

Guía paso a paso para levantar OpenAIudio en la laptop de producción de un
evento. Requisito: Python 3.11+ y Node 20+ (solo para buildear el front).

## 1) Instalar el backend

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## 2) Configurar credenciales

```bash
cp .env.example .env
# editar .env: al menos GEMINI_API_KEY si se usa la nube
```

Si **no** hay key, `PROVIDER=auto` cae en el provider `mock` (útil para
ensayar el flujo completo sin internet).

## 3) Buildear el frontend (una vez)

```bash
cd web
npm install
npm run build
cd ..
```

El build queda en `web/dist` y FastAPI lo sirve solo.

## 4) Correr

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Web: `http://localhost:8000` · API docs: `http://localhost:8000/docs`
· Health: `http://localhost:8000/healthz`

Desde otra notebook del evento se entra por la IP de la máquina
(`http://192.168.x.x:8000`); asegurar que el firewall de macOS permita la
conexión entrante en el puerto 8000.

## 5) Operar durante la charla

1. **Producción** → `http://…:8000/admin`: ver sesiones, estados, audiencia.
2. **Broadcast** → `http://…:8000/broadcast` desde la laptop del escenario:
   crear la sesión, elegir idiomas y presionar **Transmitir**. Conceder el
   permiso de micrófono.
3. **Audiencia** → `http://…:8000`: elegir sesión e idioma en cada pantalla.

### OBS / vMix

- Overlay de texto plano: `GET http://host:8000/feed/{session_id}/live?lang=es`
  (o el archivo `data/{session_id}.{lang}.live.txt` si se configura
  `OBS_OUT_DIR`). Bajar cada X segundos y mostrarlo en un texto fuente.
- Subtítulos finales: exportar en `POST`/`GET
  /api/sessions/{id}/export?fmt=srt` al terminar.

## 6) Modo 100 % local

Instalar Ollama con `gemma3:4b` (`ollama pull gemma3:4b`), `faster-whisper`,
y fijar `PROVIDER=local`. La traducción sale por texto vía Gemma.

## Puesta a punto del evento

- Health check automatizado: `curl -fsS http://localhost:8000/healthz`.
- Probar 5 min antes: crear sesión con `mock`, transmitir 10 s, abrir la vista
  de audiencia por Wi-Fi del evento y verificar subtítulos.
- Recomendado `MAX_PROVIDERS` acorde a los idiomas: 1 original + N
  traducciones por escenario, por práctico subir a 2× como margen.
- Tener a mano la key de fallback y un cable de red como plan B.