---
paths:
  - "evaluation_form_service/settings.py"
  - "evaluation_form_service/celery.py"
  - "evaluation_form_service/asgi.py"
  - "docker-compose.yaml"
  - "Dockerfile"
---

# Environment variables and local-run gotchas

## Every variable is read without a default

All of them come from a bare `os.getenv()` in `settings.py` - the only exception is
`DJANGO_DEBUG`. A missing key does not fail loudly: it leaks in as `None` and surfaces much
later, as an unreadable `SECRET_KEY` or a psycopg connection to a database literally named
`None`.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django signing key |
| `DJANGO_DEBUG` | compared against the string `"True"` - `true` or `1` silently mean production |
| `POSTGRES_DB` / `USER` / `PASSWORD` / `HOST` / `PORT` | psycopg 3 connection; `HOST` is `db` in compose, `localhost` outside |
| `CELERY_BROKER_URL` | Redis URL the worker publishes to |
| `CELERY_RESULT_BACKEND` | where task results land |
| `PEOPLEFORCE_API_KEY` | CRM auth, used by `PeopleForceService` |
| `PEOPLEFORCE_API_URL` | CRM base URL |
| `PGDATA` | read by `docker-compose.yaml` only (`my_db:$PGDATA`), never by Django - omit it and the db volume mounts wrong |

`Read(**/.env.*)` is denied, so `.env.sample` is unreadable to you as well. This table is the
only copy you get.

## Running outside Docker

- `CHANNEL_LAYERS` hardcodes Redis to `("redis", 6379)`, the compose service name. Outside
  Docker, override it or alias `redis` in `/etc/hosts`, or every WebSocket connection fails.
- `MEDIA_URL` reaches `urlpatterns` only when `DEBUG` **and** `debug_toolbar` are active, so
  generated reports are not served in a `DEBUG=False` local run.
- `ALLOWED_HOSTS` is hardcoded to `127.0.0.1`/`localhost`, and `AllowedHostsOriginValidator`
  wraps the WebSocket router, so a non-local Origin is rejected before auth runs.
- `runserver` is ASGI-served because `daphne` sits first in `INSTALLED_APPS`, but exercising
  WebSockets properly needs the explicit `daphne evaluation_form_service.asgi:application`.

## Compose topology

Six services: `evaluation_form` (Daphne :8000), `db` (postgres:16-alpine), `redis`,
`celery`, `celery-beat` (DatabaseScheduler, so periodic tasks live in the DB, not in code),
`flower` (:5555). Every one of them runs `wait_for_db` first - that management command lives
in the `techstack` app, not in the project package.
