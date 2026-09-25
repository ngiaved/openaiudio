# Security Policy

## Reporting vulnerabilities

OpenAIudio is software for events on a trusted network; it is not a
multi-tenant service exposed to the internet. Even so, any flaw that could
compromise a machine or a key is taken seriously.

- **Do not** file the issue in public issue trackers.
- Email a report to the maintainers (see `git log` / contributing section)
  with: description, reproduction steps, impact.
- Expected response: confirmation ≤ 72 h, and a fix planned by severity.

## Best practices

- **Never** commit `.env` or keys (`.env` and `.venv/` are gitignored).
- Keep `GEMINI_API_KEY` only on the production machine, rotated per event.
- The server assumes a local network; when exposed behind a proxy, use HTTPS:
  `X-Forwarded-*` (uvicorn `--proxy-headers`) and auth if the `/admin` panel
  is reachable outside the event network.
- The browser microphone is only used after explicit consent
  (`getUserMedia`), and audio is never written to disk unless `OBS_OUT_DIR`
  is enabled.

## Scope

Applies to `app/` (backend) and `web/` (frontend) on the `main` branch.