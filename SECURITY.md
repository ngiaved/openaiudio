# Security Policy

## Reporte de vulnerabilidades

OpenAIudio es software para eventos con red de confianza; no es un servicio
multi-tenant expuesto a internet. Aun así, cualquier falla que comprometa una
máquina o clave se toma en serio.

- **No** publiques la falla en issues públicos.
- Enviá un reporte por email a los mantenedores (ver `git log` / sección
  contribuidores) con: descripción, pasos para reproducir, impacto.
- Respuesta esperada: confirmación ≤ 72 h, y un fix planeado según severidad.

## Buenas prácticas

- **Nunca** committear `.env` ni claves (`.env` y `.venv/` están en gitignore).
- `GEMINI_API_KEY` solo en la máquina de producción, con rotación por evento.
- El servidor asume red local; detrás de un proxy se debe exponer con HTTPS:
  `X-Forwarded-*` (uvicorn `--proxy-headers`) y auth si el panel `/admin`
  queda accesible fuera de la red del evento.
- El micrófono del navegador solo se usa previo consentimiento explícito
  (`getUserMedia`), y el audio no se guarda en disco salvo que se habilite
  `OBS_OUT_DIR`.

## Alcance

Aplican a `app/` (backend) y `web/` (frontend) de la rama `main`.