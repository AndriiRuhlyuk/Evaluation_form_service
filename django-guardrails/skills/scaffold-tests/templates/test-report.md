# Scaffold report: {app}

## Summary

Added `{test_file}` with {test_count} test(s) covering {one sentence on the behaviour}.
Baseline: `{green | red}`. flake8: `{0 findings | N findings}`.

## Tests written

- `{test_name}` - {why this test exists, not what it does}

## Mutation check

Command: `bash ${CLAUDE_PLUGIN_ROOT}/skills/scaffold-tests/scripts/verify-tests.sh --app {app} --target {target} --format json`

Candidates in file: {candidates_total}. Tested: {tested}. Caught: {caught}. Survived: {survived}. Skipped: {skipped}.

| line | kind | code | decision |
|---|---|---|---|
| {line} | {kind} | `{code}` | {test added / gap accepted because ...} |

{If skipped > 0: "Skipped {n} mutation(s) that broke the syntax - a mutator defect, not evidence about the tests."}
{If truncated: "Output was truncated; re-ran with --full."}

## Coverage

`{percent}%` of `{target}`, or `not measured - coverage.py absent in the container`.
Coverage says the tests touch the code; the mutation check above says whether they notice it breaking.

## Declared vs actual behaviour

- {location}: declared `{what the docstring / class promises}`, actual `{what the code does}`.
  Pinned by `{test_name}`. Not fixed - a behaviour change is the product owner's call.

{or: "No discrepancies found."}

## Deliberately not covered

- {case} - {why}
- {case} - {why}

## Registry

the target project's coverage registry (`.claude/rules/testing.md`) -> "The real baseline" updated with one line for `{test_file}`.

## Next step

{single concrete action, or "none - ready for review"}
