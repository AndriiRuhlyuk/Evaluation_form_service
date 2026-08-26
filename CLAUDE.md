# CLAUDE.md

**Tradeoff:** this file records pitfalls and reasons, not description; it omits what you can
read off the code. If a line here contradicts the code, the code wins - fix the line. Detail
that only matters inside one subsystem lives in `.claude/rules/` and loads when you open
matching files.

## Overview

Django REST Framework service for technical-interview evaluation forms. A recruiter builds a
question blueprint, a hiring team fills it collaboratively in real time for one vacancy, and
each candidate gets a frozen snapshot carrying scores, feedback, an HTML report, and a note
pushed to the PeopleForce CRM. No frontend here - REST plus one WebSocket channel.

## Tech Stack

Library versions live in `requirements.txt` and are deliberately not restated here: a number
copied into this file is a place to drift that nothing checks.

- **Core:** Python 3.13, Django, DRF, PostgreSQL 16 via psycopg 3
- **Realtime:** Channels + Daphne (ASGI), `channels_redis` over Redis
- **Async jobs:** Celery + `django-celery-beat` (DB scheduler), Flower
- **API surface:** simplejwt (email login), drf-spectacular, django-filter, drf-nested-routers
- **Admin and tooling:** django-unfold, nested_admin, debug-toolbar, black, flake8, whitenoise
- **Infrastructure:** Docker Compose - web, db, redis, celery, celery-beat, flower

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
│   ├── custom_fields.py       # M2MListField - M2M as a flat list of ids, used by serializers.py
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
├── .githooks/                 # the pre-commit quality gate - what it runs and why: gates.md
└── .claude/                   # rules/ by layer + the three hooks that know about *this* repo
```

`check-layout-drift.sh` verifies this tree against the real structure. Indentation is a
contract - exactly 4 characters per level; the tracked-filename whitelist is in the script.

## Commands

Tooling lives in `.venv/`. Activate it or prefix with `.venv/bin/`.

```bash
docker-compose up --build      # Postgres, Redis, Daphne :8000, Celery worker/beat, Flower :5555
python manage.py wait_for_db   # custom command, lives in the techstack app
python manage.py migrate
python manage.py runserver         # ASGI-served (daphne is first in INSTALLED_APPS)
daphne evaluation_form_service.asgi:application   # explicit ASGI, needed to exercise WebSockets
python manage.py showmigrations    # ALWAYS run before makemigrations
python manage.py makemigrations <app>
python manage.py test working_form # one app, or a dotted path down to one method
black .   # format first: black rewrites, flake8 only reports
flake8    # config in setup.cfg
```

**Baseline to diff against.** `flake8` must exit clean - zero findings. Any output at all is a
regression introduced by your diff. The test suite is the opposite of a signal; `testing.md`
explains why a green run proves almost nothing here.

## Gates and Plugins

Three plugins from `AndriiRuhlyuk/evalforms-team-marketplace`, declared in the **committed**
`.claude/settings.json`. What each one blocks is in that plugin's README; how to install and
update it is in the marketplace README. Neither is restated here.

- **`django-guardrails`** - the gates that would hold in any Django repo: writing to `.env` or
  a key file, a secret-shaped literal, `group_send` in a `services.py`, editing a migration git
  already tracks, and any command that would destroy migrations.
- **`drf-api-guard`** - an API class declaring neither `permission_classes` nor
  `get_permissions()`, and `fields = "__all__"` in a serializer `Meta`.
- **`django-deploy-checklist`** - no hooks at all; it answers `/deploy-check` with four static
  release invariants, so nothing of it fires while you write.

**Declaring is not installing**, and the failure is silent: a fresh clone reports `No plugins
installed`, raises no error, and is indistinguishable from a healthy one. The invariant to read
is `claude plugin list` - **exactly one** entry per plugin, each at `Scope: project`. A second
entry means a stale marketplace is still registered and every gate runs twice.

The two refusal layers and their order, why `permissions.ask` holds one entry, which matrix to
run after touching a gate: `.claude/rules/infra/gates.md`, loaded by `.claude/settings.json`.

## Architecture

Four apps form one pipeline. Each stage is a **clone** of the previous one, never an FK to
it, so an earlier stage can change without rewriting history already captured downstream.

```
question + topic + techstack   question bank
  → TemplateForm    reusable blueprint, draft/publish
  → WorkingForm     per-vacancy copy, collaborative voting + approval
  → EvaluationForm  per-candidate snapshot, scores + feedback + report
```

The three `clone_*` functions carry the highest bug density in the repo - the tree above names
the two files holding them. `template_form/models.py` additionally holds the abstract bases
(`BaseForm`, `BaseFormItems`) all three stages inherit, so it is shared foundation, not stage one.

**First question on any task: which stage?** Touching two stages means two tasks. Everything
below that - layering, transactions, query discipline, verification order - lives in
`general.md` and loads the moment you open a `.py` file.

## Environment

`.env` must define `SECRET_KEY`, `DJANGO_DEBUG`, `POSTGRES_DB/USER/PASSWORD/HOST/PORT`,
`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `PEOPLEFORCE_API_KEY`, `PEOPLEFORCE_API_URL`,
`PGDATA`. Only `DJANGO_DEBUG` has a default, and `Read(**/.env.*)` is denied so `.env.sample`
is unreadable - `local-setup.md` says what each one breaks when missing.

## Docs and Conventions

Everything is versioned with the code; there is no external vault. `README.md` holds setup and
the Git Workflow (branch naming, commit prefixes - not restated here). `Progress.md` is the
roadmap, `Features_list.json` the feature registry with `done` flags, `docs/orchestration/`
the per-feature plans; plan mode creates `docs/plans/` on demand. Planning docs are Ukrainian;
the code-comment convention lives in `general.md`.

## Path-specific Rules

Every rule in `.claude/rules/` is path-scoped - **nothing there loads unconditionally**. The
directory is scanned recursively, so folders (`api`, `data`, `domain`, `infra`, `integrations`)
are organisation for humans; only `paths:` decides what enters context. What a rule covers is
its own `description:` and what triggers it is its own `paths:` - neither is mirrored here,
because a copied glob is a place to drift that nothing checks. To see the set:
`find .claude/rules -name '*.md' -exec head -6 {} +` - `**` needs zsh or bash `globstar` and
silently returns a short list without either. Two load on nearly everything - `general.md` on any `.py`,
`workflow.md` on `.py` and `docs/plans/**`; the rest are one subsystem each.

Rules are **not** re-injected after `/compact`; they reload the next time you open a matching
file, so anything that must survive compaction belongs here, not in a rule. The rule index is
built at session start: a rule created mid-session activates only after `/clear`. When one
seems ignored, read `.claude/instructions.log` - `/memory` lists the CLAUDE.md family only.

## Compact Instructions

When compacting, always preserve: which pipeline stage the task touches; any uncommitted
migration you created or noticed (a forgotten one silently stacks on the next); file paths
modified this session with the service function names; the last `flake8` result, since a clean
baseline is the only regression signal here; and whether a working-form mutation still owes
its `group_send` broadcast.
