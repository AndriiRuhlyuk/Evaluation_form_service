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
- `template_form/tests.py`, `working_form/tests.py`, `evaluation_form/tests.py` - soft
  delete of the three form stages only (destroy endpoints, slug reservation, admin restore,
  the celery status task, destroy permissions)

Everything else is the untouched Django stub. A full `python manage.py test` therefore goes
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
