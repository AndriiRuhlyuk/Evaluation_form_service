# CLAUDE.md

Django REST Framework service for technical-interview evaluation forms. This file is the
router: it carries what every session needs. Detail that only matters inside one subsystem
lives in `.claude/rules/` and loads when you open matching files.

**Tradeoff:** this file records pitfalls and reasons, not description; it omits what you can
read off the code. If a line here contradicts the code, the code wins - fix the line.

## 1. Commands

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

`.env` must define `SECRET_KEY`, `DJANGO_DEBUG`, `POSTGRES_DB/USER/PASSWORD/HOST/PORT`,
`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `PEOPLEFORCE_API_KEY`, `PEOPLEFORCE_API_URL`.
`Read(**/.env.*)` is denied, so `.env.sample` is unreadable too - this list is the only copy.

**Baselines to diff against.** `flake8` must exit clean - zero findings. Any output at all is
a regression introduced by your diff. Tests are the opposite: only two real ones exist
(`topic/tests/tests_topics.py`, `techstack/tests/tests_techstacks.py`) and every other
`tests.py` is an empty stub, so a green test run proves almost nothing.

## 2. Architecture

Four apps form one pipeline. Each stage is a **clone** of the previous one, never an FK to
it, so an earlier stage can change without rewriting history already captured downstream.

```
question + topic + techstack   question bank
  → TemplateForm    reusable blueprint, draft/publish
  → WorkingForm     per-vacancy copy, collaborative voting + approval
  → EvaluationForm  per-candidate snapshot, scores + feedback + report
```

Clone functions, the highest bug density in the repo (`grep -rn "def clone_"` - line numbers
here rot faster than anything else in this file):
- `clone_template_to_working()` in `template_form/services.py`
- `clone_working_to_evaluation()`, `clone_working_from_working()` in `working_form/services.py`

Supporting apps: `employee` (custom user model + JWT endpoints), `project` (vacancy reference
data).

Layering: `views.py` stays thin → `services.py` owns mutations and multi-model workflows →
`permissions.py` owns access rules. One deliberate exception: `get_question_details` is a
plain function view inside `template_form/services.py`, wired to `/api/question-details/<pk>/`.

## 3. Hard rules

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

## 4. Workflow

1. **Locate the stage.** Template, working, or evaluation? Touching two means two tasks.
2. **Write the service function.** Logic and transaction boundary in `<app>/services.py`.
3. **Wire the view.** Thin `@action` or viewset method, permission class from `<app>/permissions.py`.
4. **Broadcast if it mutates a working form.** `async_to_sync(channel_layer.group_send)` to
   `form_<id>`. Skip it and connected clients silently drift - never leave a mutation unbroadcast.
5. **Add a test.** No safety net exists; prioritise `services.py`, `permissions.py`, the consumer.
6. **Verify.** `black . && flake8 && python manage.py test`, compared against the §1 baselines.

## 5. Conventions

- Code and identifiers in English. Docstrings and comments mix English and Ukrainian - match
  the file you are editing. Planning docs (`Progress.md`, `docs/orchestration/*`) are Ukrainian.
- Git flow and commit prefixes: see `README.md` → "Git Workflow". Not restated here.
- Planning artifacts: `Features_list.json` (registry with `done` flags), `Progress.md` (roadmap),
  `docs/orchestration/` (per-feature plans). `.claude/settings.json` points `plansDirectory` at
  `docs/plans`, which plan mode creates on demand.

## 6. Local-run gotchas

- `CHANNEL_LAYERS` hardcodes Redis to `("redis", 6379)`, the compose service name. Outside Docker,
  override it or alias `redis` in `/etc/hosts`, or every WebSocket connection fails.
- `MEDIA_URL` reaches `urlpatterns` only when `DEBUG` **and** `debug_toolbar` are active, so
  generated reports are not served in a `DEBUG=False` local run.
- `ALLOWED_HOSTS` is hardcoded to `127.0.0.1`/`localhost`, and `AllowedHostsOriginValidator` wraps
  the WebSocket router, so a non-local Origin is rejected before auth runs.

## 7. Path-specific rules

Detail loads automatically from `.claude/rules/` when you open matching files:

| Rule | Loads for | Covers |
|---|---|---|
| `forms-lifecycle.md` | `template_form/**`, `working_form/**`, `evaluation_form/**` | snapshots, cloning, draft/publish, the two quorum rules, soft delete |
| `drf-api.md` | `**/views.py`, `**/serializers.py`, `**/permissions.py` | real URL shapes, slug lookup, permission classes, query discipline |
| `realtime.md` | consumer, middleware, routing, `asgi.py` | ASGI wiring, WebSocket auth, the broadcast contract |
| `reporting-crm.md` | `evaluation_form/services.py`, `tasks.py`, `templates/reports/**` | completion flow, report generation, PeopleForce sync |

Path-scoped rules are **not** re-injected after `/compact`; they reload the next time you open a
matching file. Anything that must survive compaction belongs in this file, not in a rule.
