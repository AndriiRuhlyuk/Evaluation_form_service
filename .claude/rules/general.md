---
description: Baseline for every Python change - layering, query discipline, comment language, verification order.
paths:
  - "**/*.py"
---

# Baseline for any code change

Loads whenever you open a `.py` file, so it is deliberately short. Subsystem detail lives in
the other rules and co-loads by its own glob.

## Layering

`views.py` stays thin → `services.py` owns mutations, multi-model workflows and the
transaction boundary → `permissions.py` owns access rules. A mutation written inside a view or
a serializer is the single most common defect in this repo.

One deliberate exception: `get_question_details` is a plain function view living in
`template_form/services.py`, wired to `/api/question-details/<pk>/`.

## Order of work

1. **Locate the stage.** Template, working, or evaluation? Touching two means two tasks.
2. **Write the service function** in `<app>/services.py`, with `@transaction.atomic` if it
   writes more than one row.
3. **Wire the view** as a thin `@action` or viewset method, permission class from
   `<app>/permissions.py`.
4. **Broadcast if it mutates a working form.** The `group_send` call belongs in the view, not
   in the service - see `domain/realtime.md` for the event table.
5. **Add a test.** No safety net exists; prioritise `services.py`, `permissions.py`, the
   consumer.
6. **Verify** in this order: `black .` rewrites, then `flake8` reports, then
   `python manage.py test`.

## Query discipline

Never call `.count()` on anything reachable from a list endpoint. Use
`working_form/utils.py: prefetch_count()` - it reads the prefetch cache when one is populated
and only falls back to `COUNT(*)` otherwise. A bare `.count()` re-queries per row and turns
one list request into N. The managers in `working_form/models.py` lean hard on
`prefetch_related` and annotation chains, so the cache is usually there.

## Language

Code and identifiers in English. Docstrings and comments mix English and Ukrainian - match the
file you are editing rather than converting it.

## Baseline to diff against

`flake8` must exit with zero findings. Any output at all is a regression introduced by your
diff, not pre-existing noise. Config is `setup.cfg`; `*/migrations/*` is excluded there, and
`asgi.py` has a deliberate `E402` exemption.
