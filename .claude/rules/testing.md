---
description: What a green test run does and does not prove here, and what to cover first.
paths:
  - "**/tests.py"
  - "**/tests/*.py"
---

# Tests: the suite is almost empty, treat green with suspicion

## The real baseline

Test files with assertions:

- `topic/tests/tests_topics.py`
- `techstack/tests/tests_techstacks.py`
- `question/tests/tests_questions.py` - the whole `QuestionViewSet` contract: author stamped
  by `perform_create`, `is_active` soft delete (second DELETE returns **204**, not 404, and
  a deleted question is hidden from `list` yet still retrievable by pk), the `restore`
  action including its 400-on-already-active branch, `?is_active=false`, and the fact that
  `IsEmployee` is declared in `permission_classes` but never reached because
  `get_permissions()` is overridden
- `project/tests/tests_projects.py` - the whole `ProjectViewSet` contract, mutation-checked at 16/16 on
  `project/views.py`. Pins three discrepancies rather than fixing them: read actions get an
  **empty** permission list and write actions `AllowAny`, so `list`, `retrieve`, `create`
  and `PATCH` all answer anonymous clients (the question endpoints answer 401); a
  form-encoded `POST`/`PUT` that omits `is_active` sets it to **False** via DRF's
  `default_empty_html`, so the same body creates an invisible project over multipart and a
  visible one over JSON; and the `restore` payload nests the project under a `topic` key
- `template_form/tests/tests_template_forms.py`, `working_form/tests/tests_working_forms.py`,
  `evaluation_form/tests/tests_evaluation_forms.py` - soft delete of the three form stages
  only (destroy endpoints, slug reservation, admin restore, the celery status task, destroy
  permissions)

## Layout is a `tests/` package everywhere

Every app keeps its tests in `<app>/tests/` with an `__init__.py`, one file per concern named
`tests_<plural>.py`. There are no flat `<app>/tests.py` modules left and no startapp stubs -
`employee` simply has no test file, which is the honest way to show it has no tests. Adding a
flat `<app>/tests.py` next to the package makes `<app>.tests` ambiguous for Python and one of
the two silently disappears, so the scaffold-tests preflight blocks on it.

Everything else is untested. A full `python manage.py test` therefore goes
green while the three `clone_*` functions, most permission classes and the WebSocket
consumer are still uncovered. Never cite a green run as evidence that a change is safe -
say which test you added and what it exercises.

## Cover in this order

1. `services.py` - the transaction boundaries and the three clone functions carry the highest
   bug density in the repo.
2. `permissions.py` - access is role **and** participation based, so a wrong answer is a data
   leak rather than a 500.
3. `working_form/consumers.py` - needs `daphne` or Channels' `WebsocketCommunicator`; nothing
   in the HTTP test client reaches it.

## Running

```bash
python manage.py test working_form          # one app
python manage.py test topic.tests.tests_topics.TopicAPITests.test_list   # one method
```

Tests need a reachable Postgres (`python manage.py wait_for_db` first) - there is no SQLite
fallback in `settings.py`, so a missing `POSTGRES_*` env var fails the run before any
assertion is reached.
