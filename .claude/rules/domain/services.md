---
description: Service layer - transaction boundaries, which functions are deliberately not atomic, private helper convention.
paths:
  - "**/services.py"
---

# Services

This layer owns every mutation and every multi-model workflow. Three modules, ~1650 lines:
`template_form` (821), `working_form` (589), `evaluation_form` (231).

## The transaction boundary lives here, and it is uneven

Wrapped in `@transaction.atomic`:

| Module | Functions |
|---|---|
| `template_form` | `create_template_form`, `update_template_form`, `publish_template_form`, `clone_template_to_working` |
| `working_form` | `add_topic_to_working_form`, `add_question_to_topic`, `toggle_item_vote`, `toggle_topic_vote`, `clone_working_to_evaluation`, `clone_working_from_working` |

`check_and_complete_evaluation` (`evaluation_form/services.py:29`) is **also** atomic, but as a
context manager rather than a decorator, and it adds `select_for_update()` on the form row
because two interviewers can submit the last feedback at the same time. Grepping for
`@transaction.atomic` alone will tell you it is unprotected - it is not.

Not wrapped at all: `save_template_draft` (one JSONField write), `generate_html_report` and
`PeopleForceService` (no writes).

A new function that writes more than one row gets `@transaction.atomic`. A new function that
calls an external API keeps that call outside the block - holding a Postgres write lock across
an HTTP round trip to PeopleForce is how this service stalls under load.

Two things inside `check_and_complete_evaluation` are known debt, not style to copy: a bare
`print()` for the cleanup counters (`flake8` has no gate for it) and a commented-out
`transaction.on_commit(...)` for completion emails. Deferring side effects to `on_commit` is
the right pattern when you add one.

## Services never broadcast

`group_send` appears only in `working_form/views.py` and `working_form/consumers.py`, never in
a service. Keep it that way: the service returns its result, the view publishes it. A service
that broadcasts is unusable from the admin, from a management command and from a test.

## Private helpers are prefixed, and they are the real API

`template_form/services.py` is mostly `_`-prefixed helpers (`_ensure_tech_stacks`,
`_ensure_single_topic`, `_get_or_create_questions`, `_create_snapshots`,
`_synchronize_form_topics`, `_deactivate_removed_items`, `_reactivate_or_identify_new_items`,
`_process_newly_added_items`). Before writing a new one, grep - the operation you need usually
exists under a name you would not have guessed.

`populate_snapshot_from_question` is the single place snapshots are filled; add new snapshot
fields there, never at a call site.

## The documented exception

`get_question_details` (`template_form/services.py:698`) is a plain function **view** living in
this module, wired to `/api/question-details/<pk>/`. It is the only inversion of the layering
rule and it stays - do not "fix" it by moving it to `views.py` without checking the URL conf.
