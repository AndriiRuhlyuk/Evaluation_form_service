# Test conventions of this repo

Read this before writing the first assertion. The reference files to copy the shape from are
`working_form/tests/tests_working_forms.py` and `question/tests/tests_questions.py`. Follow them rather than habits
carried over from other projects - a test that looks foreign is a test nobody maintains.

## Structure

- `APITestCase` from `rest_framework.test`, not a bare `django.test.TestCase`. The DRF class
  gives you a client that speaks JSON and understands authentication; the bare one does not.
- `setUpTestData` for anything shared across the class. It runs once and wraps the rows in a
  transaction that is rolled back per test, so it is dramatically cheaper than `setUp`.
- `setUp` only for the one object each test is going to corrupt. Putting a mutated object in
  `setUpTestData` leaks state between tests and produces failures that depend on test order.

## Assertions

- Every test checks two things: the HTTP status **and** the state of the row in the database.
  A test that only looks at the response code misses half the bugs, because a view can return
  204 while writing nothing.
- For soft delete, read through `Model.all_objects`. `Model.objects` filters deleted rows out,
  so the assertion passes against an empty result and the test is green for the wrong reason.
- Use `prefetch_count()` from `working_form/utils.py` expectations in mind: list endpoints must
  not trigger a per-row `COUNT(*)`. If you are testing a list endpoint, `assertNumQueries` is
  a legitimate assertion here.

## URLs

Write the real path as a string: `f"/api/working-form/{obj.slug}/"`, **not** `reverse()`.
Lookup in this repo goes by `slug`, and a literal string shows at a glance what is being
tested. `reverse()` hides the shape and keeps passing when the URL changes underneath.

## Naming and comments

- `test_<what we do>_<what we expect>`, e.g. `test_second_delete_returns_404`.
- A comment explains **why** the test exists, not what the line does. `# guards the 400 branch
  that was reported as a 500 in #42` earns its place; `# create a question` does not.
- Comment language follows the neighbouring file. Do not convert a Ukrainian file to English
  or the other way around.

## What to cover, in this order

The priority comes from `.claude/rules/testing.md`. Deviate only with a stated reason.

1. `services.py` - transaction boundaries and the three `clone_*` functions carry the highest
   bug density in the repo. A broken clone silently corrupts every downstream stage.
2. `permissions.py` - access depends on the role **and** on participation in the form, so a
   wrong answer here is a data leak rather than a 500.
3. `working_form/consumers.py` - needs Channels' `WebsocketCommunicator`; nothing in the HTTP
   test client reaches it, which is why it is still uncovered.

A minimum useful pass covers three cases: the happy path, a permission denial, and one
boundary (nonexistent id, repeated action, empty list).

## Where the file goes

Every app here keeps its tests in a `tests/` package - no flat `<app>/tests.py` module is
left in the repo. A new file goes to `<app>/tests/tests_<topic>.py`, named after the plural
of what it covers (`tests_projects.py`, `tests_questions.py`). If the package does not exist
yet, create it together with its `__init__.py`; do not fall back to a flat module.

Never create `<app>/tests.py` next to an `<app>/tests/` directory. Python cannot decide whether
`<app>.tests` is a module or a package, and one of them disappears without a diagnostic.

## Reporting a discrepancy

When the declared behaviour differs from the actual one - a docstring promising something the
code does not do, a permission class declared but never reached, identical actions returning
different codes in different apps - pin the **actual** behaviour with a test and name the test
so it says this out loud, e.g. `test_is_employee_is_declared_but_never_applied`.

Whoever eventually fixes the code then gets a red test and has to make a conscious decision,
instead of learning about the change from a bug report. Do not quietly fix the discrepancy
yourself: a behaviour change is the product owner's call.
