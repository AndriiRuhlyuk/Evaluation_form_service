---
description: Migration discipline - inspect state before generating, five uncommitted files in this branch, what the hooks do.
paths:
  - "**/migrations/*.py"
---

# Migrations

## `showmigrations` before `makemigrations`, every time

Feature branches in this repo carry migration files that were never committed. Generating a
new one without looking first silently stacks it on somebody else's unmerged state, and the
dependency graph then only resolves on your machine.

```bash
python manage.py showmigrations      # read the state first
python manage.py makemigrations <app>
```

As of the `feature/evaluation-form-improvement` branch, five migrations are untracked:
`employee/0002_alter_employee_level`, `template_form/0002_add_draft_fields`,
`template_form/0003_alter_templateformtopic_unique_together_and_more`,
`working_form/0002_workingform_is_deleted_alter_workingform_project`,
`working_form/0003_alter_workingformtopic_unique_together_and_more`. Two of them alter
`unique_together`, which Postgres implements by dropping and recreating a constraint under an
`ACCESS EXCLUSIVE` lock - never present those as routine.

## Abstract bases fan out

`BaseForm` and `BaseFormItems` live in `template_form/models.py` but are inherited by
`working_form` and `evaluation_form` models. One field added there produces three migrations,
in three apps, that must be applied together.

## What the hooks already do for you

- `Edit(**/migrations/*.py)` is set to `ask` in `.claude/settings.json` - editing a migration
  always prompts.
- `guard-migrations.sh` (PreToolUse/Bash) prompts on any shell command mentioning migrations,
  and on `git clean` unconditionally, because untracked migrations cannot be recovered.
- `check-new-migrations.sh` (PostToolUse) reports destructive operations after
  `makemigrations` runs.

Both live in the `django-guardrails` plugin, not in `.claude/`. The plugin comes from the
`evalforms-team-marketplace` marketplace declared in the committed `.claude/settings.json`, but
the install is still per machine - on a checkout where the offer was declined, neither fires and
nothing says so.

A prompt from these is a question, not an obstacle - answer it by showing the file contents and
the data consequences before proposing `migrate`.

## Style tools skip this directory

`setup.cfg` excludes `*/migrations/*` from `flake8`, and the `black` hook fires on Write/Edit
only - a file produced by `makemigrations` goes through neither. Read generated migrations
instead of trusting the gate to have looked at them.
