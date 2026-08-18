---
description: Serializer traps - lazily validated Meta.fields, M2MListField, no mutations here.
paths:
  - "**/serializers.py"
---

# Serializers

## `Meta.fields` is validated lazily

`ModelSerializer.Meta.fields` is checked at first use, not at import. A name that no longer
exists on the model passes `python manage.py check` and only blows up as
`ImproperlyConfigured` when the endpoint or the schema is hit. `EmployeeSerializer` carried
`project` and `tech_stack` this way long after both fields were dropped from `Employee`.

**When you remove a model field, grep every `fields = (...)` tuple for its name.** The eight
serializer modules total ~2800 lines and `evaluation_form` plus `working_form` account for
1700 of them, so reading is not a substitute for grep.

## `M2MListField`

`working_form/custom_fields.py:5` subclasses `serializers.ListField` with an `IntegerField`
child, exposing a many-to-many relation as a flat list of ids instead of nested objects. Used
by `working_form/serializers.py:216-222` for `interviewers`, `approvers` and `recruiters`.
Reuse it rather than hand-rolling a `PrimaryKeyRelatedField(many=True)` - the write path
differs and the two shapes are not interchangeable for existing clients.

## No writes here

A serializer validates and shapes. Creating, cloning or cascading across models belongs in
`<app>/services.py`; `create()` and `update()` overrides that touch a second model are the
defect this rule exists to prevent.
