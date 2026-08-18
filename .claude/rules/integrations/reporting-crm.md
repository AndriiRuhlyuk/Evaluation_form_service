---
description: Completion flow, HTML report generation, the Celery status task and the PeopleForce push.
paths:
  - "evaluation_form/services.py"
  - "evaluation_form/tasks.py"
  - "templates/reports/**"
---

# Completion, reporting and PeopleForce sync

## Completion flow

1. An interviewer calls `submit` on their own `EvaluationFeedback`
   (`/api/evaluation-form/evaluation-feedbacks/<pk>/submit/`). The view refuses unless every
   item is either scored or flagged "lacks expertise".
2. `check_and_complete_evaluation(form_id)` (`evaluation_form/services.py:29`) runs under
   `transaction.atomic` with `select_for_update`. When no unsubmitted feedback remains it
   prunes unscored items and then empty topics, and sets status `COMPLETED`.
   This prune is a **hard delete** - the only place in the codebase that bypasses soft delete.

## The report is not generated on completion

`generate_html_report(form)` (`evaluation_form/services.py:84`) renders
`templates/reports/evaluation_report.html` into `EvaluationForm.report_file`
(`upload_to="reports/%Y/%m/"`).

It has exactly one caller: the `sync_crm` action at `evaluation_form/views.py:447`. A
completed form therefore has **no report file at all** until someone triggers CRM sync. If
you need a report outside that path, call `generate_html_report` explicitly - do not assume
completion produced one.

Reports are served from `MEDIA_URL`, which is only wired into `urlpatterns` when `DEBUG` and
`debug_toolbar` are both active, so report links are dead in a `DEBUG=False` local run.

## PeopleForce sync

`PeopleForceService` (`evaluation_form/services.py:129`) posts a note containing the decision
summary and the report URL. The candidate id is parsed out of `Candidate.pf_link` by
`extract_candidate_id()`, which tries `/candidates/<id>` or `/applicants/<id>` first and falls
back to a trailing `/<id>`; anything else raises. A changed PeopleForce URL format breaks sync
here first.

The final decision string is computed in the view, not the service: all interviewers voting
`next_step` yields `"Move Forward"`, anything else yields `"Mixed/Refuse"`.

`sync_crm` is restricted to `IsRecruiter`.

## Scheduled task

Celery with django-celery-beat (DB scheduler). `evaluation_form/tasks.py:14
update_evaluation_statuses` flips `PENDING` → `IN_PROGRESS` for forms whose
`interview_datetime` falls within `INTERVIEW_PENDING_THRESHOLD` (1 hour,
`evaluation_form/models.py:20`). Email notifications are TODOs only - nothing sends mail yet.
