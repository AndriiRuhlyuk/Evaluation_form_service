---
name: scaffold-tests
description: Use when adding or extending tests in this Django/DRF repo - writing a tests file for an app, covering services.py, permissions.py or the WebSocket consumer, raising coverage, or answering "are these tests actually any good". Scaffolds the file under this repo's conventions (APITestCase, literal slug URLs, status plus DB-row assertions, all_objects for soft delete), then proves the tests bite by running an AST-based mutation check against the module under test, and updates the coverage registry in .claude/rules/testing.md. Trigger whenever the user asks for tests, more coverage, a test review, or names an app or module to cover - even when they never say the word "scaffold".
argument-hint: '[app-or-module-path, e.g. question or project/views.py]'
allowed-tools: Read, Grep, Glob, Write, Edit, TodoWrite, Agent, Task, Bash(python3:*), Bash(uv run:*), Bash(bash:*), Bash(docker-compose:*), Bash(.venv/bin/black:*), Bash(.venv/bin/flake8:*), Bash(git:*), Bash(grep:*), Bash(sort:*), Bash(tr:*), Bash(echo:*)
---

# scaffold-tests

Goal: land one test file that fails when the code under test breaks, and prove it - so the
next green run means something. In this repo a green suite is nearly meaningless (see
`.claude/rules/testing.md`), which is why the mutation check below is not optional.

## Repo state, resolved at load time

- Requested target: $ARGUMENTS
- Current branch: !`git branch --show-current 2>/dev/null || echo unknown`
- Compose services up: !`docker-compose ps --services --filter status=running 2>/dev/null | tr '\n' ' ' | grep . || echo "none - the database is down"`
- Test inventory (`<file>:<count of def test_>`):

!`grep -rc "def test_" --include="tests*.py" --exclude-dir=.venv . 2>/dev/null | sort -t: -k2 -rn | grep . || echo "no test files found"`

These three lines were executed once, before you started reading. They are already resolved
text, not commands you can re-run - if you need fresher numbers, call the tool yourself.

## No argument given

If no target is named above, do not invent one and do not pick one yourself. The inventory
above is per **file**; sum the counts per app directory to get the table below, and mark every
app whose total is `0`. An app absent from the inventory has no test file at all - list it
with `0`. Then stop with one question.

```
app              tests   file
--------------------------------------------
question           23    question/tests/tests_questions.py
working_form        8    working_form/tests/tests_working_forms.py
employee            0    (none)

-> Which app should I cover?
```

Go no further until the user answers.

## Workflow

Use this checklist literally. Create one todo per step and mark each done before moving on.

- [ ] **Step 1: Probe the environment.** Run exactly:

  ```bash
  python3 .claude/skills/scaffold-tests/scripts/preflight.py --app <app> --target <module> --format text
  ```

  Read the exit code, not the prose: `0` means proceed; `1` means at least one check is
  `blocked` - name which one, surface its `detail` and `fix` verbatim, and stop (a blocked
  `compose` or `database` makes every later step impossible; a blocked `app`, `layout` or
  `target` means the target itself is wrong); `2` means you passed a bad flag - fix the
  command and retry once. If `docker-compose` is missing entirely, pass `--no-docker` and tell
  the user that steps 6 and 7 will need `TEST_CMD` pointed at a reachable Postgres.
  The probe writes nothing, so re-running it after a fix is free.

- [ ] **Step 2: Read the code before writing about it.** Read the module under test plus its
  neighbours in the same app: `models.py`, `views.py`, `services.py`, `permissions.py`, and
  `urls.py` for the real paths. Tests are written from the code, not from assumptions about
  the code. If the expected behaviour is still unclear after reading, ask one question and
  wait - a guessed expectation produces a test that pins a bug.

- [ ] **Step 3: Load the conventions.** Read `.claude/skills/scaffold-tests/references/conventions.md`
  now. Every path in this file is written from the repo root, which is your working
  directory - a bare `references/conventions.md` resolves to nothing there. It holds the
  assertion rules, the file-placement rule, and the cover-first order. Do not write the first
  assertion before reading it; the defaults in your head are from other projects.

- [ ] **Step 4: Check the behaviour is not already covered.** Run:

  ```bash
  grep -rn "def test_" --include="tests*.py" --exclude-dir=.venv .
  ```

  Three tests about one behaviour are worse than one: they manufacture the appearance of
  coverage and all fail together on a single change. If another app already covers it, say so
  and do not duplicate.

- [ ] **Step 5: Write the tests.** Destination comes from the probe's `destination` check.
  Cover at minimum: the happy path, one permission denial, one boundary (nonexistent id,
  repeated action, empty list). Normal TDD is inverted here because the code already exists -
  the mutation check in step 7 is what proves each test can actually fail.

- [ ] **Step 6: Run and format.** In this order, because `black` rewrites and `flake8` only
  reports:

  ```bash
  docker-compose exec -T celery python manage.py test <app>
  .venv/bin/black <app>
  .venv/bin/flake8
  ```

  The `.venv/bin/` prefix is not optional: a bare `black` is not on PATH here, and a bare
  `flake8` resolves to an unrelated system install that never reads this repo's `setup.cfg`.
  Linting with that binary measures the wrong thing and reports a clean run you cannot trust.

  `flake8` must print nothing. Any output is a regression introduced by your diff, not
  pre-existing noise. Fix it before step 7 - mutating a file that already fails lint gives an
  unreadable result.

- [ ] **Step 7: Prove the tests bite.** Run exactly:

  ```bash
  bash .claude/skills/scaffold-tests/scripts/verify-tests.sh --app <app> --target <module> --format json
  ```

  Do not modify the command and do not substitute your own judgement for it. Exit codes, as
  produced by exactly the command above (`--dry-run` and `--help` also exit `0` without
  running anything, which is why the command is fixed):
  `0` every mutation was caught, you are done with this step; `1` at least one mutation
  survived, go to step 8; `3` the suite was already red before any mutation - stop and fix the
  tests, nothing downstream carries signal until it is green; `2` the check could not run at
  all - read the stderr lines, fix the named cause and re-run. The exit-2 causes are: a bad
  flag value, a target whose path carries characters that cannot be passed to a shell, a
  target or directory that is not writable, an unreadable or non-Python target, a target with
  no mutable construct (point `--target` at the module holding the logic), enumeration or
  apply failure, and every candidate breaking the syntax (a mutator defect - report the file
  it happened on). Never report `2` as a pass: it
  means zero mutations were executed, which says nothing about the tests. Exit `130` means the
  run was interrupted; the file was restored, but nothing was measured. Exit `4` is the one
  that needs you to act on the working tree first: the restore failed, the target still holds
  mutated source, and the backup path is printed on stderr - copy it back before anything else.
  If the JSON says `"truncated": true`, re-run with `--full` before reporting counts.

- [ ] **Step 8: Validation loop.** While `survived` is non-empty: read
  `.claude/skills/scaffold-tests/references/mutation-guide.md`, decide per survivor (write a test / accept the gap with a
  stated reason / flag it as dead code), apply the decision, then re-run step 7. Repeat until
  `survived` is empty or every remaining survivor has an explicit accepted reason. Never close
  this loop by asserting the mutated behaviour - that blesses the break instead of detecting
  it.

- [ ] **Step 9: Independent review.** Dispatch one subagent with a clean context - it has not
  seen this conversation, which is the point - and give it exactly this task: "Read <test
  file> and <module under test>. Do not read anything else about how they were produced. List
  every assertion that would still pass if the module were broken, every test whose name does
  not match what it asserts, and every use of `Model.objects` where soft-deleted rows make the
  assertion vacuous. Return findings only, no praise."

  Then handle the reply as findings, not as verdicts: reproduce each one first (run the test,
  read the line it names). Reproduced -> fix it and return to step 7, because the fix changes
  the code the mutation check ran against. Not reproduced -> say so with the evidence that
  refutes it. A finding you neither reproduced nor refuted is still open; do not close step 9
  while one remains.

- [ ] **Step 10: Update the registry.** Add the new file to the "The real baseline" section of
  `.claude/rules/testing.md` with one line saying what it covers. A registry that has drifted
  from reality is worse than no registry, because it is trusted.

- [ ] **Step 11: Report, do not commit.** Fill in `.claude/skills/scaffold-tests/templates/test-report.md` section by
  section. Do not invent findings the scripts did not produce, and do not drop a section -
  "No discrepancies found" is a result. Then show `git diff --stat` and hand over ready-to-run
  branch and commit commands for the user to execute. Never commit or push yourself. Branch
  from `develop` per README (`feature/*`); the message format is
  `Add: <app> test coverage for <what>`.

## Gotchas

- **The database lives in Docker.** A local `manage.py test` cannot reach it and there is no
  SQLite fallback in `settings.py` - a missing `POSTGRES_*` fails the run before any assertion
  is reached. Always go through `docker-compose exec -T celery`, or set `TEST_CMD`.

- **`tests.py` next to `tests/` is unresolvable.** Python cannot decide whether `<app>.tests`
  is a module or a package, and one of them silently disappears. The probe checks this; if it
  reports a collision, fix the layout before writing anything.

- **`startapp` stubs read as coverage.** A file containing only `# Create your tests here.`
  looks like a covered app in any file listing. If the probe reports stubs, offer to delete
  them in the same commit.

- **Soft delete makes assertions vacuous.** `Model.objects` filters deleted rows out, so
  `assertEqual(qs.count(), 0)` passes whether the delete worked or the queryset was empty all
  along. Read through `Model.all_objects` when the point is that the row still exists.

- **A skipped mutation is not a caught one.** When a mutation breaks the syntax the suite fails
  on `SyntaxError`, which looks identical to a real catch from the outside. The script reports
  `skipped` separately - never fold it into `caught`.

- **`uv` is optional here.** Both scripts are stdlib-only and carry a PEP 723 header, so
  `uv run` works if it is installed and `python3` works if it is not. If `uv run` reports
  `command not found`, switch to `python3` rather than installing anything.

- **The load-time commands at the top are frozen.** They ran once. After you create a test
  file, the inventory above is stale - re-grep rather than quoting it.

- **`mutate.py apply` rewrites tracked source in place.** It keeps no backup of its own; only
  `verify-tests.sh` takes one. Run it directly with `--dry-run`. It refuses to apply a second
  `return` mutation over its own marker, but comparisons leave no marker and are not guarded -
  applying one twice yields `not (not (a == b))`, which is a no-op nothing detects.

- **A `return` sharing its line with a header is never mutated.** In `def f(): return 1` and
  `if x: return 5` the return is skipped, because the mutator replaces a whole node with one
  line and would delete the header sitting on it. A comparison on that same line is still
  mutated, so such a file is partly covered, not uncovered. Multi-line comparisons are skipped
  too. A module written in one-line style can therefore reach "all mutations caught" while its
  returns were never touched - say so in the report rather than letting the number stand alone.

- **`candidates_total` counts constructs, not lines.** `return x == 1` is two candidates, a
  return and a comparison on the same line. Do not read the number as a count of statements.

- **Exit code 2 from `verify-tests.sh` is not a pass.** It means no mutation ran at all. The
  script fails closed on purpose, because reporting "nothing survived" without executing a
  single mutation would defeat the only guarantee this skill offers.

## Bundled files, and when to open them

Nothing below enters context until you reference it. Open each one at the step that names it.
Paths are written from the repo root, which is where you are running - a bare
`references/conventions.md` resolves to nothing there.

| Path | Open it when |
|---|---|
| `.claude/skills/scaffold-tests/references/conventions.md` | step 3, before the first assertion |
| `.claude/skills/scaffold-tests/references/mutation-guide.md` | step 8, or whenever a survivor needs a decision |
| `.claude/skills/scaffold-tests/templates/test-report.md` | step 11, to shape the final answer |
| `.claude/skills/scaffold-tests/scripts/preflight.py` | run at step 1; read only if its output is confusing |
| `.claude/skills/scaffold-tests/scripts/verify-tests.sh` | run at step 7; read only to change its contract |
| `.claude/skills/scaffold-tests/scripts/mutate.py` | called by `verify-tests.sh`; run directly only with `--dry-run` |

Every script answers `--help` with its flags, exit codes and two examples. Read that before
guessing at an invocation. `mutate.py` hides its flags behind the `list` and `apply`
subcommands, so its top-level `--help` lists them in the epilog rather than as options.
