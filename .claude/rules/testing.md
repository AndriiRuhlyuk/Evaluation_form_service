---
description: What a green test run does and does not prove here, and what to cover first.
paths:
  - "**/tests.py"
  - "**/tests/*.py"
---

# Tests: the suite is almost empty, treat green with suspicion

## The real baseline

Only two test files contain assertions:

- `topic/tests/tests_topics.py`
- `techstack/tests/tests_techstacks.py`

Every other `tests.py` is the untouched Django stub. A full `python manage.py test` therefore
goes green while the three `clone_*` functions, every permission class and the WebSocket
consumer are completely uncovered. Never cite a green run as evidence that a change is safe -
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
