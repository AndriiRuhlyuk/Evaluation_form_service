---
description: The twelve permission classes, the missing global default, JWT and role model.
paths:
  - "**/permissions.py"
---

# Access control

## There is no global default - set it on every viewset

`REST_FRAMEWORK` in `settings.py` defines authentication, pagination and throttling but **no**
`DEFAULT_PERMISSION_CLASSES`. DRF then falls back to `AllowAny`. A viewset that forgets
`permission_classes` is publicly writable and nothing in `manage.py check`, `flake8` or the
schema will say so.

## The inventory

Role- **and** participation-based, one `permissions.py` per app:

| App | Classes |
|---|---|
| `working_form` | `CanInteractWithWorkingForm`, `CanEditWorkingForm`, `IsRecruiter`, `CanCreateEvaluationForm` |
| `evaluation_form` | `CanScoreOrFeedback`, `CanCreateScore` |
| `template_form` | `IsManagerOrSuperuser` |
| `employee` | `IsAdminUserOrReadOnly` |
| `question`, `topic`, `techstack`, `project` | `IsEmployee`, duplicated verbatim in each of the four |

`IsRecruiter` lives in `working_form/permissions.py` but is imported by
`evaluation_form/views.py` and `template_form/views.py` - do not move or rename it without
checking both. The four `IsEmployee` copies are genuine duplicates: change one and the other
three keep the old behaviour.

`CanScoreOrFeedback.has_object_permission` is one of the four functions `setup.cfg` names as
too complex to enable a `max-complexity` gate. Splitting it is welcome; growing it is not.

## Auth model

`AUTH_USER_MODEL = employee.Employee` - email login, no username. Roles are HIRING_MANAGER,
MANAGER, RECRUITER, INTERVIEWER; levels run JUNIOR through HEAD. simplejwt is the only
authentication class: access token 360 min, refresh 1 day, rotation with blacklist.

Django admin access is a separate mechanism - `employee/admin_mixins.py:ManagerPermissionMixin`,
covered in `api/admin.md`.