---
paths:
  - "**/views.py"
  - "**/serializers.py"
  - "**/permissions.py"
---

# DRF surface: routing, lookup, permissions, query discipline

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

## Permission classes

Role- **and** participation-based, one `permissions.py` per app:

- `working_form`: `CanInteractWithWorkingForm`, `CanEditWorkingForm`, `CanCreateEvaluationForm`, `IsRecruiter`
- `evaluation_form`: `CanScoreOrFeedback`, `CanCreateScore`
- `template_form`: `IsManagerOrSuperuser`
- `employee`: `IsAdminUserOrReadOnly`
- `question`, `topic`, `techstack`, `project`: `IsEmployee`, duplicated verbatim in each app

`IsRecruiter` lives in `working_form/permissions.py` but is also imported by
`evaluation_form/views.py` and `template_form/views.py` - do not move it without checking both.

Auth: `AUTH_USER_MODEL = employee.Employee` (email login, no username; roles HIRING_MANAGER /
MANAGER / RECRUITER / INTERVIEWER, levels JUNIOR→HEAD). JWT via simplejwt is the only default
authentication class: access 360 min, refresh 1 day, rotation plus blacklist. Django admin
permissions come from `employee/admin_mixins.py: ManagerPermissionMixin` - managers and
superusers get full access, other authenticated users read-only.

## Query discipline

Models and serializers here lean on heavy `prefetch_related` and annotation chains (see the
managers in `working_form/models.py`). Use `working_form/utils.py: prefetch_count()` instead
of `.count()` on anything reachable from a list endpoint: it reads the prefetch cache when
one is populated and only falls back to `COUNT(*)` otherwise. A bare `.count()` re-queries
per row and turns one list request into N.

## Defaults for new viewsets

JWT-only auth, `PageNumberPagination` with page size 5, throttling anon 100/day and user
300/day. Admin uses django-unfold plus nested_admin, so `/_nested_admin/` must stay routed or
nested inlines break. OpenAPI lives at `/api/schema/`, `/api/doc/swagger/`, `/api/doc/redoc/`.

`ModelSerializer.Meta.fields` is validated lazily, at first use rather than at import, so a
name that no longer exists on the model passes `manage.py check` and only blows up as
`ImproperlyConfigured` when the endpoint or the schema is hit. `EmployeeSerializer` carried
`project` and `tech_stack` this way after both fields were dropped from `Employee`. When you
remove a model field, grep every `fields = (...)` tuple for its name.
