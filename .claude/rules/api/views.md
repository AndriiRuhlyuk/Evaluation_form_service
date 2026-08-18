---
description: Viewset conventions - slug lookup, the real URL shapes, defaults for new viewsets.
paths:
  - "**/views.py"
  - "**/urls.py"
---

# Viewsets and routing

## Lookup is by slug, not pk

`TemplateFormViewSet`, `WorkingFormViewSet` and `EvaluationFormViewSet` all set
`lookup_field = "slug"` (`template_form/views.py:122`, `working_form/views.py:78`,
`evaluation_form/views.py:141`). Their custom actions take `slug=None` or
`working_form_slug=None`, never `pk`. Reference-data viewsets still use `pk`.

## Real URL shapes

Taken from the URL resolver, not from docstrings - several docstrings claim hyphens where the
route actually has underscores. `working_form` passes an explicit `url_path` (hyphens);
`template_form` and `evaluation_form` do not, so DRF uses the method name verbatim.

```
/api/working-form/<slug>/{add-topic,approve,unapprove,clone,create-evaluation,restore-topic}/
/api/working-form/<working_form_slug>/topics/<pk>/{add-question,restore-item}/
/api/working-form/<working_form_slug>/{topics,items}/          # drf-nested-routers
/api/template-form/<slug>/{save_draft,publish,create_working_form}/     # underscores
/api/template-form/<form_topic__form_slug>/items/
/api/evaluation-form/evaluation-forms/<slug>/sync_crm/                  # underscore
/api/evaluation-form/{candidates,evaluation-feedbacks,evaluation-scores}/
/api/evaluation-form/evaluation-feedbacks/<pk>/submit/
/api/employees/{register,me,logout,token,token/refresh,token/verify}/
/api/{questions,topics,techstacks,projects}/<pk>/restore/
/api/topics/<pk>/recommended_questions/
/api/question-details/<pk>/     # plain function view, lives in template_form/services.py
```

Note `add-question` and `restore-item` hang off the **nested topics** route, not off the
working form itself.

## Working-form actions own the broadcast

`async_to_sync(channel_layer.group_send)` lives in `working_form/views.py` (lines 268, 340,
469, 553, 746, 910), never in the service it calls. Add an action that mutates a working form
without its broadcast and connected clients silently drift - there is no client-side
reconciliation. `domain/realtime.md` co-loads on this file and carries the event-type table.

## Defaults for a new viewset

JWT-only authentication, `PageNumberPagination` with page size 5, throttling anon 100/day and
user 300/day - all from `REST_FRAMEWORK` in `settings.py`, so a viewset that sets none of them
already behaves correctly. OpenAPI is served at `/api/schema/`, `/api/doc/swagger/` and
`/api/doc/redoc/` by drf-spectacular; a new action with no `@extend_schema` still appears
there, with an inferred and usually wrong response body.
