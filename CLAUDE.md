# CLAUDE.md

**Tradeoff:** this file records pitfalls and reasons, not description; it omits what you can
read off the code. If a line here contradicts the code, the code wins - fix the line. Detail
that only matters inside one subsystem lives in `.claude/rules/` and loads when you open
matching files.

## Overview

Django REST Framework service for technical-interview evaluation forms. A recruiter builds a
question blueprint, a hiring team fills it collaboratively in real time for one vacancy, and
each candidate gets a frozen snapshot of it that carries scores, feedback, a generated HTML
report, and a note pushed back to the PeopleForce CRM.

Single Django project, no frontend in this repo - the API is consumed over REST plus one
WebSocket channel.

## Tech Stack

- **Runtime:** Python 3.13, Django 5.2.6, Django REST Framework 3.16.1
- **Database:** PostgreSQL 16 via psycopg 3 (`psycopg[binary]`)
- **Realtime:** Channels 4.3.1 + Daphne 4.2.1 (ASGI), `channels_redis` over Redis
- **Async jobs:** Celery 5.5.3 + `django-celery-beat` (DB scheduler), Flower for monitoring
- **Auth:** `djangorestframework-simplejwt` - email login, no username
- **API surface:** drf-spectacular (OpenAPI), django-filter, drf-nested-routers
- **Admin:** django-unfold + django-nested-admin + django-debug-toolbar
- **Tooling:** black, flake8, whitenoise
- **Infrastructure:** Docker Compose (web, db, redis, celery, celery-beat, flower)

## Project Layout

Migrations, `__pycache__`, `staticfiles/` and `media/` are omitted - they carry no signal.

```
evaluation_form_service/
├── evaluation_form_service/   # Django project package
│   ├── settings.py            # daphne first in INSTALLED_APPS, unfold before django.contrib.admin
│   ├── asgi.py                # ProtocolTypeRouter: HTTP + WebSocket behind AllowedHostsOriginValidator
│   ├── celery.py              # Celery app, autodiscover_tasks()
│   └── urls.py                # root router, /api/schema/, /api/doc/swagger/, /_nested_admin/
├── question/                  # question bank
├── topic/                     # topics, /api/topics/<pk>/recommended_questions/
├── techstack/                 # tech stacks + `wait_for_db` management command
├── project/                   # vacancy reference data
├── employee/                  # AUTH_USER_MODEL, JWT endpoints
│   └── admin_mixins.py        # ManagerPermissionMixin - who may write in django admin
├── template_form/             # STAGE 1: reusable blueprint, draft/publish
│   └── services.py            # clone_template_to_working(), get_question_details()
├── working_form/              # STAGE 2: per-vacancy copy, collaborative voting + approval
│   ├── consumers.py           # WebSocket consumer, group `form_<id>`
│   ├── middleware.py          # JwtAuthMiddleware - JWT auth for the WS handshake
│   ├── routing.py             # websocket_urlpatterns, wired into asgi.py
│   ├── services.py            # clone_working_to_evaluation(), clone_working_from_working()
│   └── utils.py               # prefetch_count() - use instead of .count()
├── evaluation_form/           # STAGE 3: per-candidate snapshot, scores + feedback + report
│   ├── services.py            # check_and_complete_evaluation(), generate_html_report(), PeopleForceService
│   └── tasks.py               # Celery: update_evaluation_statuses (the only task)
├── templates/reports/         # evaluation_report.html - rendered by generate_html_report()
├── fixtures/                  # initial_data.json
├── docs/orchestration/        # per-feature plans (Ukrainian)
└── .claude/rules/             # path-scoped rules, auto-loaded by glob
```

## Commands

Tooling lives in `.venv/`. Activate it or prefix with `.venv/bin/`. Two hooks in
`.claude/settings.json` act on you: `PostToolUse` runs `.venv/bin/black` on every `.py` you
write, and `PreToolUse` (`guard-migrations.sh`) turns any migration-touching command, or any
`git clean`, into a permission prompt.

```bash
docker-compose up --build      # Postgres, Redis, Daphne :8000, Celery worker/beat, Flower :5555

python manage.py wait_for_db   # custom command, lives in the techstack app
python manage.py migrate
python manage.py createsuperuser   # email + password, no username
python manage.py runserver         # ASGI-served (daphne is first in INSTALLED_APPS)
daphne evaluation_form_service.asgi:application   # explicit ASGI, needed to exercise WebSockets

python manage.py showmigrations    # ALWAYS run before makemigrations
python manage.py makemigrations <app>

python manage.py test              # all
python manage.py test working_form # one app, or a dotted path down to one method

black .   # format first: black rewrites, flake8 only reports
flake8    # config in setup.cfg

python manage.py loaddata fixtures/initial_data.json
```

**Baselines to diff against.** `flake8` must exit clean - zero findings. Any output at all is
a regression introduced by your diff. Tests are the opposite: only two real ones exist
(`topic/tests/tests_topics.py`, `techstack/tests/tests_techstacks.py`) and every other
`tests.py` is an empty stub, so a green test run proves almost nothing.

## Architecture

Four apps form one pipeline. Each stage is a **clone** of the previous one, never an FK to
it, so an earlier stage can change without rewriting history already captured downstream.

```
question + topic + techstack   question bank
  → TemplateForm    reusable blueprint, draft/publish
  → WorkingForm     per-vacancy copy, collaborative voting + approval
  → EvaluationForm  per-candidate snapshot, scores + feedback + report
```

Clone functions, the highest bug density in the repo (`grep -rn "def clone_"` - line numbers
rot faster than anything else in this file):
- `clone_template_to_working()` in `template_form/services.py`
- `clone_working_to_evaluation()`, `clone_working_from_working()` in `working_form/services.py`

Supporting apps: `employee` (custom user model + JWT endpoints), `project` (vacancy reference
data).

Layering: `views.py` stays thin → `services.py` owns mutations and multi-model workflows →
`permissions.py` owns access rules. One deliberate exception: `get_question_details` is a
plain function view inside `template_form/services.py`, wired to `/api/question-details/<pk>/`.

## Hard Rules

**NEVER:**
- Put a mutation or a multi-model workflow in a view or serializer. It belongs in `services.py`.
- Call `.count()` on anything reachable from a list endpoint. Use `working_form/utils.py: prefetch_count()`.
- Use `all_objects` on a `template_form` model. It does not exist there and raises `AttributeError`.
- Add a stage or a snapshot field before reading all three clone functions.

**ALWAYS:**
- Run `showmigrations` before `makemigrations`. Feature branches here carry uncommitted migrations,
  so a new one can silently stack on someone else's unmerged state.
- Name the manager explicitly when the model has soft delete. Three different flags exist and
  one of them behaves differently per app.

## Workflow

1. **Locate the stage.** Template, working, or evaluation? Touching two means two tasks.
2. **Write the service function.** Logic and transaction boundary in `<app>/services.py`.
3. **Wire the view.** Thin `@action` or viewset method, permission class from `<app>/permissions.py`.
4. **Broadcast if it mutates a working form.** `async_to_sync(channel_layer.group_send)` to
   `form_<id>`. Skip it and connected clients silently drift - never leave a mutation unbroadcast.
5. **Add a test.** No safety net exists; prioritise `services.py`, `permissions.py`, the consumer.
6. **Verify.** `black . && flake8 && python manage.py test`, compared against the Commands baselines.

## Environment Variables

All of them are read with a bare `os.getenv()` in `settings.py` - **no defaults except
`DJANGO_DEBUG`**. A missing key does not fall back, it surfaces later as `None` deep inside
Django (unreadable `SECRET_KEY` error, or a psycopg connection to database `None`).

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django signing key |
| `DJANGO_DEBUG` | compared against the string `"True"`; anything else means production mode |
| `POSTGRES_DB` / `USER` / `PASSWORD` / `HOST` / `PORT` | psycopg 3 connection; `HOST` is `db` in compose, `localhost` outside |
| `CELERY_BROKER_URL` | Redis URL the worker publishes to |
| `CELERY_RESULT_BACKEND` | where task results land |
| `PEOPLEFORCE_API_KEY` | CRM auth, used by `PeopleForceService` |
| `PEOPLEFORCE_API_URL` | CRM base URL |
| `PGDATA` | read by `docker-compose.yaml` only (`my_db:$PGDATA`), never by Django - omit it and the db volume mounts wrong |

`Read(**/.env.*)` is denied, so `.env.sample` is unreadable to you too - this table is the
only copy you get.

## Local-run Gotchas

- `CHANNEL_LAYERS` hardcodes Redis to `("redis", 6379)`, the compose service name. Outside Docker,
  override it or alias `redis` in `/etc/hosts`, or every WebSocket connection fails.
- `MEDIA_URL` reaches `urlpatterns` only when `DEBUG` **and** `debug_toolbar` are active, so
  generated reports are not served in a `DEBUG=False` local run.
- `ALLOWED_HOSTS` is hardcoded to `127.0.0.1`/`localhost`, and `AllowedHostsOriginValidator` wraps
  the WebSocket router, so a non-local Origin is rejected before auth runs.

## Documentation

Everything lives in the repo and is versioned with the code - there is no external vault.

| Artifact | Holds |
|---|---|
| `README.md` | setup instructions and the Git Workflow (branch naming, commit prefixes) |
| `Progress.md` | roadmap, Ukrainian |
| `Features_list.json` | feature registry with `done` flags |
| `docs/orchestration/` | per-feature implementation plans, Ukrainian |
| `docs/plans/` | created on demand by plan mode (`plansDirectory` in `.claude/settings.json`) |

## Conventions

- Code and identifiers in English. Docstrings and comments mix English and Ukrainian - match
  the file you are editing. Planning docs are Ukrainian.
- Git flow and commit prefixes: see `README.md` → "Git Workflow". Not restated here.

## Path-specific Rules

Detail loads automatically from `.claude/rules/` when you open matching files:

| Rule | Loads for | Covers |
|---|---|---|
| `forms-lifecycle.md` | `template_form/**`, `working_form/**`, `evaluation_form/**` | snapshots, cloning, draft/publish, the two quorum rules, soft delete |
| `drf-api.md` | `**/views.py`, `**/serializers.py`, `**/permissions.py` | real URL shapes, slug lookup, permission classes, query discipline |
| `realtime.md` | consumer, middleware, routing, `asgi.py` | ASGI wiring, WebSocket auth, the broadcast contract |
| `reporting-crm.md` | `evaluation_form/services.py`, `tasks.py`, `templates/reports/**` | completion flow, report generation, PeopleForce sync |

Path-scoped rules are **not** re-injected after `/compact`; they reload the next time you open a
matching file. Anything that must survive compaction belongs in this file, not in a rule.

## Compact Instructions

When compacting, always preserve:

- Which pipeline stage the current task touches, and why that one.
- Any uncommitted migration you created or noticed - `guard-migrations.sh` prompts are easy to
  lose, and a forgotten migration silently stacks on the next one.
- File paths modified in this session, with the service function names touched.
- The last `flake8` result and whether it was clean, since a clean baseline is the only
  regression signal this repo has.
- Whether a working-form mutation still needs its `group_send` broadcast.
