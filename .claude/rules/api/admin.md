---
description: Django admin surface - unfold theme, the unevenly applied permission mixin, nested_admin is dead weight.
paths:
  - "**/admin.py"
  - "employee/admin_mixins.py"
---

# Django admin

## unfold, and the ordering it demands

Admin classes subclass `unfold.admin.ModelAdmin` (plus `TabularInline` / `StackedInline` from
the same module), not `django.contrib.admin.ModelAdmin`. `"unfold"` and its `contrib.*` apps
must stay **before** `django.contrib.admin` in `INSTALLED_APPS` or the templates resolve to
stock Django and the theme silently disappears.

Two admins deliberately opt out: `employee/admin.py` extends `DjangoUserAdmin` (it needs the
password-change plumbing) and `project/admin.py` uses plain `admin.ModelAdmin`. Both therefore
render in the stock theme.

## `ManagerPermissionMixin` is applied unevenly

`employee/admin_mixins.py:ManagerPermissionMixin` grants write access to managers and
superusers and read-only to everyone else authenticated. It is mixed into `TopicAdmin`,
`TechStackAdmin` and every writable admin in `template_form/admin.py` - but **not** into
`QuestionAdmin`, `EmployeeAdmin` or `ProjectAdmin`. There any staff user with the model
permission can write. Treat that as an open question, not as settled design: adding the mixin
is a behaviour change for existing staff accounts, so raise it rather than fixing it silently.

The `ReadOnly*` proxy admins in `template_form/admin.py:318,386` skip the mixin on purpose -
they deny writes structurally instead.

## `nested_admin` is installed but unused

`"nested_admin"` sits in `INSTALLED_APPS` and `/_nested_admin/` is routed in
`evaluation_form_service/urls.py:56`, yet no `admin.py` imports it - every inline comes from
`unfold.admin` and `unfold.contrib.inlines`. Removing the app and the route would be safe
today; assume neither is load-bearing until something actually imports `nested_admin`.

## Admin calls services, like views do

`template_form/admin.py:17` imports `populate_snapshot_from_question` and `SNAPSHOT_FIELDS`
from `template_form/services.py`. Keep that direction - snapshot logic must not be reimplemented
inside a `save_model` or a formset.

`evaluation_form/admin.py` and `working_form/admin.py` are one-line stubs: the two most complex
stages have no admin surface at all, which is why bugs there only surface through the API.