# Reading the mutation check

Read this when `verify-tests.sh` reports at least one survivor, or when you are unsure what a
result means.

## The three outcomes

| Field in the JSON | Meaning | What to do |
|---|---|---|
| `caught` | the mutation was applied and the suite turned red | nothing, this is the good case |
| `survived` | the line was broken and no test noticed | decide per line, see below |
| `skipped` | applying the mutation produced invalid Python | mutator defect, not a signal |

`skipped` is the trap. A skipped mutation makes the suite fail on a `SyntaxError`, which looks
identical to "the tests caught it" from the outside. The script separates the two on purpose,
and reporting a skipped mutation as evidence of good tests would be a lie. If `skipped` is
non-zero, say which file it happened on so the mutator can be fixed.

## What to do with a survivor

A survivor is not automatically a missing test. It is a question with three legitimate answers:

1. **The behaviour matters** - write the test. This is the common case for `services.py` and
   `permissions.py`.
2. **The behaviour is genuinely untestable at this layer** - say so explicitly. Example: a
   `return` inside a `__str__` used only by the admin.
3. **The line is dead** - the more interesting finding. A `return` no caller depends on may be
   unreachable code rather than an untested one. Report it, do not delete it silently.

Never respond to a survivor by writing an assertion that pins the mutated form. The point is to
detect the break, not to bless it.

## Coverage and mutations answer different questions

`coverage` tells you whether the tests **touch** a line. Mutation tells you whether they
**notice** when that line breaks. A file at 100% coverage can catch zero mutations, and that
file is the dangerous one: the number manufactures confidence that nothing supports.

This is why the coverage step is informational and never blocks, while a survivor always
demands a stated decision.

## What is never mutated

The candidate list is narrower than "every line", and a clean run only speaks about what was
actually in it:

- `return` sharing its line with the header (`def f(): return 1`, `if x: return 5`). The
  mutator replaces a whole node with one line, so mutating these would delete the header. A
  comparison on that same line is still a candidate - the exclusion is per construct, not per
  line.
- multi-line comparisons, because the replacement works on column offsets within one line.
- everything that is neither a `return` with a value nor a comparison: arithmetic, `and`/`or`,
  constants, boundary values.

So "all mutations caught" means the tests notice these two classes of break in this file. It
does not mean the module is proven. When `candidates_total` looks small next to the amount of
logic in the file, say so in the report rather than letting the number speak for itself.

## Tuning the run

- `--max-mutations N` (default 5). Candidates are sampled evenly across the file, not taken
  from the top, so raising the number widens the sample rather than digging deeper into the
  first function.
- `--full` lists every survivor; by default only the first three appear and `truncated` is
  `true`. Do not report "3 survivors" when `truncated` is `true` - re-run with `--full`.
- `--kinds` on `mutate.py` restricts the mutation types. `compare` only applies to
  single-line comparisons, because the replacement works on column offsets.
- `TEST_CMD` replaces the runner entirely, which is how the same script works in CI or against
  a Postgres started outside compose.
