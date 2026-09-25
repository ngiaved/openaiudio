# ADR 0001 · Topología híbrida para transcripción y traducción simultánea

- Estado: **Aceptado** (v0.1)
- Fecha: 2026-09
- Categoría: Arquitectura del servidor

## Contexto

OpenAIudio transcribe y traduce en vivo charlas de una conferencia (varios
escenarios en paralelo). Necesitamos una topología que:

1. Genere el **original** con baja latencia y sin depender de GPU local.
2. Permita **traducir** a varios idiomas con proveedores distintos según el
   entorno (Gemini/AI Studio en la nube, Gemma vía Ollama completamente local).
3. Tolere cortes de red/cred). lámitos sin perder la charla.
4. Corra en una sola laptop de producción sin complicaciones de clusters.

## Opciones consideradas

### A. Todo por audio (solo Gemini Live)
Flujo de bytes de audio a la nube para el original y cada traducción (un
stream por idioma). Muy simple, máxima calidad de entonación, pero exige
conectividad estable y consumo alto de API.

### B. Todo por texto local (whisper + Gemma)
Original con `faster-whisper` local y traducción con Gemma vía Ollama. Offline
total, pero latencia y calidad dependientes del hardware de la laptop.

### C. Híbrida (elegida)
- El **original** siempre se genera desde audio (Gemini Live o whisper local).
- Las **traducciones** se generan por **audio** (Gemini Live, streaming) o por
  **texto** (modelo de texto Gemini o Gemma/Ollama), configurable por sesión.
- Modo `auto`: audio solo para el mock (demo); texto para Gemini y local (ver Nota abajo).

## Decisión

Se adopta la topología **C**. Cada sesión declara `provider` y
`translation_mode` (`audio | text | auto`); el orquestador (`app/store.py`)
decide la vía del original (siempre audio) y de cada traducción, y mantiene un
presupuesto de providers concurrentes (máximo por config) con promoción a
`live` cuando recibe audio y degradación a `idle` bajo el barrido de ociosidad.

## Consecuencias

Positivas:
- Un mismo servidor tolera señales en la nube y señales 100 % locales.
- `provider=auto` permite levantar la demonstra sin API key usando el `mock`.
- Latencia del original independiente de la traducción.

Negativas:
- Dos caminos de calidad distintos para traducción (audio vs texto).
- El proveedor por texto reintenta con backoff; la primera traducción de texto
  puede tardar más que la de audio en arrancar.

Nota sobre modo `auto` (revisada tras probar con API key real):
- El original con Gemini usa STT por **ventanas** (audio `generate_content` +
  texto), no Live streaming: los modelos `*-transcribe-live` son preview e
  inestables, y la vía por ventanas es robusta y barata.
- `auto` queda como: **audio** solo para el mock (demo); **texto** para
  Gemini (traducción) y local. La vía Live (audio) sigue disponible
  explícitamente con `TRANSLATION_MODE=audio` y `GEMINI_LIVE_MODEL`.