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

- **Core:** Python 3.13, Django 5.2.6, DRF 3.16.1, PostgreSQL 16 via psycopg 3
- **Realtime:** Channels 4.3.1 + Daphne 4.2.1 (ASGI), `channels_redis` over Redis
- **Async jobs:** Celery 5.5.3 + `django-celery-beat` (DB scheduler), Flower
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
├── .githooks/                 # one quality gate before every commit: black on staged, flake8 repo-wide, tests when Postgres answers; wired by `git config core.hooksPath .githooks`
└── .claude/                   # rules/ by layer (api, data, domain, infra, integrations) + hooks/ (only the three that know about *this* repo)
```

`check-layout-drift.sh` verifies this tree against the real structure. Indentation is a
contract - exactly 4 characters per level; the tracked-filename whitelist is documented in
the script itself.

## Commands

Tooling lives in `.venv/`. Activate it or prefix with `.venv/bin/`. Two hook sources act on you.
The **plugin** holds every gate that would hold in any Django repo; three **block** with exit 2,
and the stderr says what to do instead: writing to `.env` or any key file, a secret-shaped
literal into a tracked file, `group_send`/`channel_layer` into a `services.py`. Non-blocking
there: `black` on each `.py` written, a prompt on any migration-touching command or `git clean`,
a destructive-operation report on a new migration. It no longer lives here: it is published as
`django-guardrails@evalforms-team-marketplace` (repo `AndriiRuhlyuk/evalforms-team-marketplace`),
and both the marketplace and the enabled plugin are declared in the **committed**
`.claude/settings.json` - so a fresh clone is offered the install on first session and stays
**ungated until that offer is accepted**. The install itself is a per-machine cache under
`~/.claude/plugins/cache/`, which is why `claude plugin list` must show version `1.0.0` and
exactly one `django-guardrails`; a second one means a stale marketplace is still registered and
every gate runs twice. `.claude/settings.json` keeps beyond that only what is true of *this* repo: an
`InstructionsLoaded` logger (see Path-specific Rules); a `matcher: compact` hook re-printing
repo state and invariants after `/compact`; an `async` `SessionEnd` counter into
`.claude/telemetry.jsonl`; and `check-layout-drift.sh` - when it speaks, fix **Project Layout**
and **write the comment**, an unannotated path being worse than no line at all.

Quality gates live in `.githooks/pre-commit`, **not** in `PostToolUse` - running tests after
every edit would spend ten red intermediate states on one plan and push Claude into a
micro-fix loop. `/django-guardrails:hooks-matrix` re-runs the PASS/FAIL matrix for every plugin
gate - run it after touching any, since a mis-wired gate fails silently. Changing a gate is now a
two-repo cycle: edit it in the marketplace worktree, bump both versions there (its own CI checks
they match), push, then `claude plugin marketplace update evalforms-team-marketplace` here - the
install is a cached copy, not a link, so nothing changes until that update runs. To try a change
before publishing, point a session at the worktree with `claude --plugin-dir <path>`.

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
(`BaseForm`, `BaseFormItems`) that all three stages inherit, so it is shared foundation rather
than stage one.

**First question on any task: which stage?** Touching two stages means two tasks. Everything
below that - layering, transactions, query discipline, verification order - lives in
`general.md` and loads the moment you open a `.py` file.

## Environment

`.env` must define `SECRET_KEY`, `DJANGO_DEBUG`, `POSTGRES_DB/USER/PASSWORD/HOST/PORT`,
`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `PEOPLEFORCE_API_KEY`, `PEOPLEFORCE_API_URL`,
`PGDATA`. None has a default except `DJANGO_DEBUG`, and `Read(**/.env.*)` is denied so
`.env.sample` is unreadable - `local-setup.md` explains what each one breaks when missing.

## Docs and Conventions

Everything is versioned with the code; there is no external vault. `README.md` holds setup and
the Git Workflow (branch naming, commit prefixes - not restated here). `Progress.md` is the
roadmap, `Features_list.json` the feature registry with `done` flags, `docs/orchestration/`
the per-feature plans; plan mode creates `docs/plans/` on demand. Planning docs are Ukrainian;
the code-comment convention lives in `general.md`.

## Path-specific Rules

Every rule in `.claude/rules/` is path-scoped - **nothing there loads unconditionally**. The
directory is scanned recursively, so the folders below are organisation for humans; only
`paths:` decides what enters context.

| Rule | Loads for | Covers |
|---|---|---|
| `general.md` | `**/*.py` | layering, order of work, query discipline, comment language, verification |
| `workflow.md` | `**/*.py`, `docs/plans/**` | TDD via `superpowers:test-driven-development`, always offer `superpowers:subagent-driven-development` for plans |
| `api/views.md` | `**/views.py`, `**/urls.py` | slug lookup, real URL shapes, viewset defaults, who owns the broadcast |
| `api/serializers.md` | `**/serializers.py` | lazily validated `Meta.fields`, `M2MListField`, no writes here |
| `api/permissions.md` | `**/permissions.py` | the twelve classes, the missing global default, JWT and roles |
| `api/admin.md` | `**/admin.py`, `admin_mixins.py` | unfold ordering, the unevenly applied mixin, `nested_admin` is unused |
| `data/models.md` | `**/models.py` | shared abstract bases, manager selection, `is_active` filtered in views |
| `data/migrations.md` | `**/migrations/*.py` | `showmigrations` first, the uncommitted five, what the hooks do |
| `domain/forms-lifecycle.md` | `template_form/**`, `working_form/**`, `evaluation_form/**` | snapshots, cloning, draft/publish, the two quorum rules, soft delete |
| `domain/services.md` | `**/services.py` | transaction boundaries, services never broadcast, private helpers |
| `domain/realtime.md` | consumer, middleware, routing, `working_form/views.py`, `asgi.py` | ASGI wiring, WebSocket auth, the broadcast contract |
| `integrations/reporting-crm.md` | `evaluation_form/services.py`, `tasks.py`, `templates/reports/**` | completion flow, report generation, PeopleForce sync |
| `infra/local-setup.md` | `settings.py`, `celery.py`, `asgi.py`, `docker-compose.yaml`, `Dockerfile` | every env var and what it breaks, compose topology |
| `testing.md` | `**/tests.py`, `**/tests/*.py` | why green proves nothing, what to cover first |

Path-scoped rules are **not** re-injected after `/compact`; they reload the next time you open a
matching file. Anything that must survive compaction belongs in this file, not in a rule.

When a rule seems ignored, `/memory` will not help - it lists the CLAUDE.md family only and
never scans `.claude/rules/`. Use `.claude/instructions.log` instead (gitignored, one JSON line
per load): it records the rule file, the `trigger` file that matched and the `globs` that did
it. An expected line missing there means the glob did not match, not that the rule was skipped.

## Compact Instructions

When compacting, always preserve: which pipeline stage the task touches; any uncommitted
migration you created or noticed (a forgotten one silently stacks on the next); file paths
modified this session with the service function names; the last `flake8` result, since a clean
baseline is the only regression signal here; and whether a working-form mutation still owes
its `group_send` broadcast.
