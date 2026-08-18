---
description: Model layer - abstract bases shared across stages, manager selection, reference-data soft delete.
paths:
  - "**/models.py"
---

# Models

## `template_form/models.py` is the shared foundation, not one stage

`BaseForm` (line 10) and `BaseFormItems` (line 177) are abstract and inherited across the
pipeline: `TemplateForm`, `WorkingForm` and `EvaluationForm` all extend `BaseForm`;
`TemplateFormItems` and `WorkingFormItem` extend `BaseFormItems`. A field added to either base
lands in three tables and needs a migration in three apps. `domain/forms-lifecycle.md`
co-loads here and covers the snapshot fields those bases carry.

## Always name the manager explicitly

Three soft-delete flags exist and they do not behave alike. The full table is in
`domain/forms-lifecycle.md`, which only loads for the three form apps - the half that matters
in the reference-data apps is below.

## Reference data: `is_active` is filtered in the view, not the manager

`Question`, `Topic`, `TechStack` and `Project` each carry a plain `is_active` BooleanField with
the **default manager**. Nothing filters it at the model layer. The hiding happens in each
viewset's `get_queryset()` (`question/views.py:181`, `project/views.py:123`), which applies
`is_active=True` unless the request passes an explicit `?is_active=` override, and `destroy()`
sets the flag instead of deleting.

The consequence: a service function, an admin page, a management command or a shell query sees
soft-deleted rows. Filter `is_active=True` by hand outside the viewset, and never assume
`Model.objects` is already clean.

`employee.Employee.is_active` is Django's standard auth flag (login enabled or disabled) and
has nothing to do with this convention. `Employee` is `AUTH_USER_MODEL` with
`CustomUserManager` (`employee/models.py:5`) - email login, no username.

## `all_objects` exists in exactly one app

Only `working_form` defines it (`WorkingForm`, `WorkingFormTopic`, `WorkingFormItem`).
`WorkingForm.all_objects` is also what slug uniqueness checks read
(`working_form/models.py:247,280`), so a soft-deleted form still reserves its slug. On any
`template_form` model `all_objects` raises `AttributeError`.

## Managers here are query-heavy by design

`WorkingFormTopicManager` and `WorkingFormItemManager` return annotated querysets
(`get_annotated_list()`). Anything that then calls `.count()` discards that work - use
`working_form/utils.py: prefetch_count()`.
