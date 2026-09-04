---
description: How gates are wired here - the two refusal layers and their order, why ask holds one entry, the three hooks that belong to this repo, which matrix to run after touching a gate.
paths:
  - ".claude/settings.json"
  - ".claude/hooks/**"
  - ".githooks/**"
  - ".claude/rules/**"
---

# Gates: what can refuse a command, and in which order

Two layers can refuse a Bash command and they are **not** interchangeable. A hook runs
first, and only `exit 2` stops the call outright - before permission rules are read.
Anything else a hook returns is advice: `deny` and `ask` are evaluated after, and a
matching `deny` wins.

Since `django-guardrails` 1.1.0 the `guard-migrations` branch for `git clean` exits 2, so
it decides first and in its own wording, and `Bash(git clean *)` under `deny` is never
consulted. **Keep the overlap anyway** - each layer covers a form the other misses.
`deny` matches by prefix, so `sudo git clean -fd` and `git -C <path> clean -fd` walk past
it, and the hook is the only guard left on them (it catches both since 1.1.0; the second
one used to escape *both* layers - ARCH-14).

Never relax a `deny` entry because "the hook covers it". Unless that branch exits 2, what
you get back is a prompt, and a prompt only stops anything in a session that honours
`ask` - which is exactly what this repo's sessions were found not to do, and why the
destructive branches were promoted out of `ask` in the first place (ARCH-13).

**Blocked means blocked.** You cannot wave an exit-2 gate through from the session.
Deleting a migration, or editing a committed one on purpose, is something you run
yourself in the terminal - and for a committed one the right move is usually a new
migration, not an edit.

## Why `permissions.ask` holds exactly one entry

`manage.py migrate`, kept as a reminder and honest about being nothing more. The other
three were not deleted but replaced by gates that hold:

- `docker-compose down` gave way to an exit-2 branch on the `-v` form - the one that
  drops the volume, and with it `django_migrations`.
- The two `Edit(**/migrations/**)` patterns gave way to `guard-migration-edits`, which
  blocks only a migration git **already tracks**.

That last distinction is the point. A committed migration is already in colleagues'
checkouts and applied somewhere, so editing it silently diverges schemas; an uncommitted
one is yours to edit, which is what writing a data migration by hand requires.

A rule that looks like protection and delivers none is worse than an absent rule. If you
find yourself adding one to `ask`, ask first whether the same thing can be decided from
the filesystem or from git instead.

## Quality gates live in `.githooks/pre-commit`, not in `PostToolUse`

`.githooks/pre-commit` runs `black` on staged files, `flake8` repo-wide, then the tests
inside whichever running compose service holds `manage.py` - the local interpreter cannot
reach the DB, because `.env` names the docker network. Wired by
`git config core.hooksPath .githooks`.

Running tests after every edit instead would spend ten red intermediate states on one plan
and push Claude into a micro-fix loop. That is the whole reason for the split.

## The four hooks that belong to *this* repo

Everything else you see firing comes from the plugins. `.claude/settings.json` keeps only
what is true here:

| Hook | What it does |
|---|---|
| `check-layout-drift.sh` | `SessionStart` + `PostToolUse`. When it speaks, fix **Project Layout** in `CLAUDE.md` **and write the comment** - an unannotated path is worse than no line at all. Indentation is a contract: exactly 4 characters per level; the tracked-filename whitelist is documented in the script itself. |
| `check-glossary-drift.sh` | `SessionStart` + `PostToolUse` on `Write\|Edit`, filtered to `CONTEXT.md` / `CONTEXT-MAP.md` by the path in the payload. Five checks: canon holding a stage-01 word, a delta whose feature shipped, the map disagreeing with the files on disk, the vendored `sdlc:fix-term` re-enabled by an `sdlc/` update, one term in two glossaries. **Reports, never blocks** - check 1 originally stood on `grep` and misfired on 4 of 11 real terms (`stage clone` lives as `clone_working_to_evaluation`), so it now reads the introducing commit instead. Backs the skill `fix-term-local`, which owns the write side. |
| `reinject-context.sh` | `SessionStart` with `matcher: compact`. Reprints repo state and invariants, because path-scoped rules are **not** re-injected after `/compact` - they reload the next time a matching file is opened. |
| `session-telemetry.py` | `SessionEnd`, `async`, counts into `.claude/telemetry.jsonl`. |
| `InstructionsLoaded` jq line | Appends one JSON line per rule load to `.claude/instructions.log` (gitignored): the rule file, the `trigger` file that matched, and the `globs` that did it. When a rule seems ignored, read this - `/memory` will not help, it lists the CLAUDE.md family only and never scans `.claude/rules/`. A missing line means the glob did not match, not that the rule was skipped. |

The rule index is built at session start, so a rule you just created does not activate in
the same session. Verify after `/clear`.

## After touching any gate, run its matrix

A mis-wired gate fails silently in both directions - it can stop biting, or start blocking
everything. Each plugin carries its own:

```
/django-guardrails:hooks-matrix
/drf-api-guard:hooks-matrix
/django-deploy-checklist:audit-matrix
```

The last one lives under `tests/`, not `hooks/`, because that plugin has no hooks and a
`hooks/` directory holding none would be a path that lies.

Changing a plugin gate is a two-repo cycle, and it is documented in the marketplace repo
(`AndriiRuhlyuk/evalforms-team-marketplace`), not here - the install is a cached copy, not
a link, so a push there does not reach this machine on its own. To try a change before
publishing, point a session at the worktree: `claude --plugin-dir <path>`.
