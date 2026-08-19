#!/usr/bin/env bash
#
# verify-tests.sh --app <app> --target <file> [options]
#
# Proves that an app's tests actually check something instead of merely going
# green. Three steps, in order:
#   1. baseline run    - must be green on unmodified code, otherwise nothing
#                        that follows carries any signal;
#   2. coverage        - which lines the tests touch (skipped when coverage.py
#                        is absent, never fatal);
#   3. mutation check  - breaks constructs in the target file one at a time and
#                        watches whether the tests notice. Candidates come from
#                        mutate.py via the syntax tree, so multi-line
#                        expressions and comparisons are mutated correctly.
#
# A mutation the tests did NOT notice ("survived") marks a gap: that line can be
# broken and no test turns red.
#
# The target file is restored from a copy on every exit path, including Ctrl+C.
# The copy is taken before the first modification; git is not involved. If the
# restore itself fails, the copy is KEPT and the script exits 4 - losing the
# backup would leave the mutated source as the only version of the file.
#
# JSON summary on stdout, progress log on stderr.
# Exit: 0 no survivors, 1 survivors present, 3 baseline red, 130 interrupted,
#       2 the check could not run (bad flags, unwritable target or directory, no
#         mutable construct, enumeration or apply failed) - never read 2 as
#         "tests are fine",
#       4 RESTORE FAILED - recover the backup named on stderr first.

set -euo pipefail

APP=""
TARGET=""
MAX_MUTATIONS="${MAX_MUTATIONS:-5}"
FORMAT="json"
FULL=0
DRY_RUN=0
SURVIVOR_PREVIEW=3

usage() {
    cat <<'EOF'
verify-tests.sh --app <app> --target <file> [options]

Runs the suite, measures coverage, then mutates the target file to prove the
tests catch regressions.

Options:
  --app <name>        Django app whose tests to run (required)
  --target <path>     module to mutate, repo-relative (required)
  --max-mutations <n> how many candidates to test (default 5, env MAX_MUTATIONS)
  --format json|text  stdout shape (default json)
  --full              list every survivor instead of the first 3
  --dry-run           print the mutation plan, run no tests, change no files
  -h, --help          this text

Env:
  TEST_CMD  overrides the test command
            (default: docker-compose exec -T celery python manage.py test <app>)

Exit: 0 no survivors, 1 survivors present, 3 baseline red, 130 interrupted,
      2 the check could not run (bad flags, unwritable target or directory, no
        mutable construct, enumeration or apply failed) - never read 2 as
        "tests are fine",
      4 RESTORE FAILED - the target still holds mutated source, the backup was
        kept, recover it before doing anything else.

Examples:
  bash verify-tests.sh --app question --target question/views.py
  bash verify-tests.sh --app topic --target topic/services.py --full --format text
EOF
}

# A flag whose value is missing must be a usage error (exit 2). Without this
# check `shift 2` fails under `set -e` and the script exits 1 - the code the
# caller is told means "survivors present", i.e. a typo would be read as a real
# finding.
need_value() {
    if [[ $2 -lt 2 ]]; then
        echo "$1 requires a value (see --help)" >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app) need_value "$1" $#; APP="$2"; shift 2 ;;
        --target) need_value "$1" $#; TARGET="$2"; shift 2 ;;
        --max-mutations) need_value "$1" $#; MAX_MUTATIONS="$2"; shift 2 ;;
        --format) need_value "$1" $#; FORMAT="$2"; shift 2 ;;
        --full) FULL=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
done

if [[ -z "$APP" || -z "$TARGET" ]]; then
    echo "--app and --target are both required (see --help)" >&2
    exit 2
fi
if [[ ! -f "$TARGET" ]]; then
    echo "no such file: $TARGET" >&2
    exit 2
fi
# $APP is interpolated into the default test command and executed through
# `bash -c`, so anything but a Python identifier is a shell injection.
if ! [[ "$APP" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "--app must be a Django app label (letters, digits, underscore), got: $APP" >&2
    exit 2
fi
# $TARGET reaches a container shell inside single quotes in the coverage step, so
# a quote or a dollar in the path would close them and execute the remainder.
if ! [[ "$TARGET" =~ ^[A-Za-z0-9._/-]+$ ]]; then
    echo "--target may only contain letters, digits, dot, underscore, dash and" >&2
    echo "slash - it is interpolated into a shell command. Got: $TARGET" >&2
    exit 2
fi
# This script rewrites the target in place and keeps its backup in the same
# directory. Without both being writable it cannot work, and finding that out
# halfway through means an unrestorable file.
if [[ ! -w "$TARGET" ]]; then
    echo "target is not writable: $TARGET" >&2
    echo "The mutation check rewrites it in place and restores it afterwards." >&2
    exit 2
fi
TARGET_DIR="$(dirname "$TARGET")"
if [[ ! -w "$TARGET_DIR" ]]; then
    echo "directory is not writable: $TARGET_DIR" >&2
    echo "The backup and log files are written next to the target on purpose," >&2
    echo "so that a hard kill leaves them in plain sight." >&2
    exit 2
fi
if [[ "$FORMAT" != "json" && "$FORMAT" != "text" ]]; then
    echo "--format must be json or text, got: $FORMAT" >&2
    exit 2
fi
# An unvalidated value here is worse than a wrong one: 0 divides by zero inside
# the sampling awk, and a non-number silently disables the cap and runs the full
# suite once per candidate.
if ! [[ "$MAX_MUTATIONS" =~ ^[0-9]+$ ]] || [[ "$MAX_MUTATIONS" -lt 1 ]]; then
    echo "--max-mutations must be a positive integer, got: $MAX_MUTATIONS" >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MUTATOR="$SCRIPT_DIR/mutate.py"
if [[ ! -f "$MUTATOR" ]]; then
    echo "missing $MUTATOR - the mutation check cannot run" >&2
    exit 2
fi

# The runner is overridable so the same script works in CI or against a Postgres
# started outside compose. The default matches this repo's topology.
RUN_TESTS="${TEST_CMD:-docker-compose exec -T celery python manage.py test $APP}"

# Run through `bash -c` rather than expanding $RUN_TESTS unquoted: an override
# like TEST_CMD='python3 -c "import x"' would otherwise be split on spaces and
# the quotes passed through literally, turning a fine command into a red
# baseline that looks like a test failure.
run_tests() {
    bash -c "$RUN_TESTS"
}

json_escape() {
    # Backslash first, then quote, then the control characters a 60-char source
    # excerpt can realistically carry. A raw tab in the output is invalid JSON,
    # and the consumer of this stdout is a parser, not a human.
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g' \
        | tr -d '\r\n'
}

# Temp files live next to the target rather than in /tmp: no dependency on
# TMPDIR, and if the script is killed hard the backup sits in plain sight
# instead of disappearing into a system directory.
BACKUP="${TARGET}.verify-backup"
BASE_LOG="${TARGET}.verify-log"
LIST_ERR="${TARGET}.verify-list-err"

restore() {
    rm -f "$BASE_LOG" "$LIST_ERR"

    # No backup means either it was never taken (an early exit before the
    # mutation loop) or a previous restore already consumed it. Both are
    # success: the target was never left mutated.
    [[ -f "$BACKUP" ]] || return 0

    # Target already identical to the backup - nothing was written, or the
    # write failed. Saying "still holds mutated source" here would send the
    # reader hunting for damage that does not exist.
    if cmp -s "$BACKUP" "$TARGET"; then
        rm -f "$BACKUP"
        return 0
    fi

    # Deleting the backup after a FAILED restore would leave the mutated source
    # as the only copy of the file. The backup is the last line of defence, so
    # it is removed only once the restore is known to have succeeded.
    if cp "$BACKUP" "$TARGET" 2>/dev/null; then
        rm -f "$BACKUP"
        return 0
    fi

    echo "" >&2
    echo "RESTORE FAILED. $TARGET holds mutated source and the copy back failed." >&2
    echo "The backup was kept. Make the target writable, then run:" >&2
    echo "  chmod u+w '$TARGET' && cp '$BACKUP' '$TARGET' && rm '$BACKUP'" >&2
    return 1
}

# Installed before the first temp file is written, not before the first
# mutation: a kill during the baseline run - the longest step by far - would
# otherwise leave the log behind with no diagnostic.
# The INT/TERM handler clears the EXIT trap first. Without that, `exit 130`
# re-enters restore(), which finds the backup already consumed, and the exit
# status of the trap replaces 130 - an interrupted run would report as a
# restore failure.
trap 'restore || exit 4' EXIT
trap 'trap - EXIT; restore; exit 130' INT TERM

# Enumeration must fail closed. Swallowing the mutator's stderr here and
# continuing with an empty list would let the script report "nothing survived"
# without ever running a mutation - the one thing this script exists to prevent.
if ! LIST_OUT=$(python3 "$MUTATOR" list "$TARGET" --format tsv 2>"$LIST_ERR"); then
    echo "STOP: could not enumerate mutation candidates in $TARGET" >&2
    cat "$LIST_ERR" >&2
    rm -f "$LIST_ERR"
    exit 2
fi
rm -f "$LIST_ERR"

if [[ -z "$LIST_OUT" ]]; then
    TOTAL_FOUND=0
else
    TOTAL_FOUND=$(printf '%s\n' "$LIST_OUT" | wc -l | tr -d ' ')
fi

if [[ "$TOTAL_FOUND" -eq 0 ]]; then
    # Not a success: the check proved nothing about the tests. Exiting 0 here
    # would be read as "every mutation was caught".
    echo "STOP: $TARGET has no mutable construct (no return with a value, no" >&2
    echo "single-line comparison). This check cannot say anything about the" >&2
    echo "tests - point --target at the module that holds the logic." >&2
    exit 2
fi

# Candidates are sampled evenly across the file rather than taken from the top:
# testing only the first N would tell us nothing about the rest of the module.
# Read into an array without mapfile - that arrived in bash 4, and /bin/bash on
# macOS is still 3.2.
CANDIDATES=()
while IFS= read -r row; do
    [[ -n "$row" ]] && CANDIDATES+=("$row")
done < <(printf '%s\n' "$LIST_OUT" | awk -v max="$MAX_MUTATIONS" '
    {rows[NR] = $0}
    END {
        step = (NR > max) ? NR / max : 1
        for (i = 1; i <= NR; i += step) print rows[int(i)]
    }')

if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
    echo "STOP: $TOTAL_FOUND candidate(s) found but sampling produced none." >&2
    echo "That is a defect in this script, not a statement about the tests." >&2
    exit 2
fi

if [[ $DRY_RUN -eq 1 ]]; then
    echo "dry run: no tests executed, no files changed" >&2
    if [[ "$FORMAT" == "json" ]]; then
        printf '{"dry_run":true,"target":"%s","app":"%s","test_command":"%s","candidates_total":%s,"planned":[' \
            "$(json_escape "$TARGET")" "$(json_escape "$APP")" \
            "$(json_escape "$RUN_TESTS")" "$TOTAL_FOUND"
        SEP=""
        for ROW in "${CANDIDATES[@]}"; do
            IDX="${ROW%%|*}"; REST="${ROW#*|}"
            KIND="${REST%%|*}"; REST="${REST#*|}"
            LINE="${REST%%|*}"; LABEL="${REST#*|}"
            printf '%s{"index":%s,"kind":"%s","line":%s,"code":"%s"}' \
                "$SEP" "$IDX" "$(json_escape "$KIND")" "$LINE" "$(json_escape "$LABEL")"
            SEP=","
        done
        printf ']}\n'
    else
        echo "would run: $RUN_TESTS"
        printf '%s\n' "${CANDIDATES[@]}"
    fi
    exit 0
fi

# ---------------------------------------------------------------- step 1
echo "== 1/3 baseline run ==" >&2
if ! run_tests >"$BASE_LOG" 2>&1; then
    echo "STOP: the suite is red before any mutation. Fix that first." >&2
    tail -20 "$BASE_LOG" >&2
    rm -f "$BASE_LOG"
    if [[ "$FORMAT" == "json" ]]; then
        printf '{"target":"%s","app":"%s","baseline":"red","survivors":[]}\n' \
            "$(json_escape "$TARGET")" "$(json_escape "$APP")"
    else
        echo "baseline red"
    fi
    exit 3
fi
tail -3 "$BASE_LOG" >&2
rm -f "$BASE_LOG"

# ---------------------------------------------------------------- step 2
echo "== 2/3 coverage ==" >&2
COVERAGE_PERCENT="null"
COVERAGE_AVAILABLE="false"
# The coverage probe is hardcoded to this repo's container. When the runner has
# been redirected, or docker is not installed at all, saying "coverage.py not
# installed" would name the wrong cause and hand out a fix that cannot work.
if [[ -n "${TEST_CMD:-}" ]]; then
    echo "coverage skipped: TEST_CMD is set, so the container topology is unknown." >&2
elif ! command -v docker-compose >/dev/null 2>&1; then
    echo "coverage skipped: docker-compose is not on PATH." >&2
elif docker-compose exec -T celery python -c "import coverage" 2>/dev/null; then
    COVERAGE_AVAILABLE="true"
    COVERAGE_OUT=$(docker-compose exec -T celery sh -c \
        "coverage run --source=$APP manage.py test $APP >/dev/null 2>&1; coverage report --include='$TARGET'" 2>&1 || true)
    echo "$COVERAGE_OUT" >&2
    PERCENT=$(printf '%s' "$COVERAGE_OUT" | awk '/%/ {gsub("%","",$NF); last=$NF} END {print last}')
    [[ -n "$PERCENT" ]] && COVERAGE_PERCENT="$PERCENT"
else
    echo "coverage.py not installed - step skipped." >&2
    echo "To enable: add coverage to requirements.txt and rebuild (docker-compose build celery)," >&2
    echo "or once-off: docker-compose exec celery pip install coverage" >&2
fi

# ---------------------------------------------------------------- step 3
echo "== 3/3 mutation check (up to $MAX_MUTATIONS mutations) ==" >&2
echo "candidates in file: $TOTAL_FOUND, testing: ${#CANDIDATES[@]}" >&2

# The traps are already installed; this is what gives them something to restore.
cp "$TARGET" "$BACKUP"

SURVIVED=()
SKIPPED=0
CAUGHT=0
for ROW in "${CANDIDATES[@]}"; do
    # row shape: <index>|<kind>|<line>|<code excerpt>
    IDX="${ROW%%|*}"; REST="${ROW#*|}"
    KIND="${REST%%|*}"; REST="${REST#*|}"
    LINE="${REST%%|*}"; LABEL="${REST#*|}"

    # --force because this loop keeps its own backup: the marker guard exists to
    # protect a human running mutate.py by hand, and without it a target whose
    # source merely contains the text "# mutation" would abort the whole run.
    # Unguarded under `set -e` this would kill the script with exit 1 - the code
    # that means "survivors present" - after running zero mutations.
    if ! python3 "$MUTATOR" apply "$TARGET" "$IDX" --force >/dev/null; then
        echo "STOP: could not apply mutation $IDX to $TARGET (see the error above)." >&2
        echo "No conclusion about the tests can be drawn from a partial run." >&2
        exit 2
    fi

    # Safety net. The AST is supposed to guarantee validity, so a hit here means
    # a mutator defect, not a signal about test quality - silently scoring such
    # a mutation as "caught" would be a lie.
    # ast.parse rather than py_compile: the latter drops a __pycache__ next to
    # the target on every single mutation, which the restore step does not clean.
    if ! python3 -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" \
        "$TARGET" 2>/dev/null; then
        echo "  SKIPPED $KIND, line $LINE (mutation broke the syntax): $LABEL" >&2
        SKIPPED=$((SKIPPED + 1))
        cp "$BACKUP" "$TARGET"
        continue
    fi

    if run_tests >/dev/null 2>&1; then
        echo "  SURVIVED $KIND, line $LINE: $LABEL" >&2
        SURVIVED+=("$KIND|$LINE|$LABEL")
    else
        echo "  caught   $KIND, line $LINE: $LABEL" >&2
        CAUGHT=$((CAUGHT + 1))
    fi
    cp "$BACKUP" "$TARGET"
done

TESTED=$((${#CANDIDATES[@]} - SKIPPED))

LIMIT=${#SURVIVED[@]}
TRUNCATED="false"
if [[ $FULL -eq 0 && ${#SURVIVED[@]} -gt $SURVIVOR_PREVIEW ]]; then
    LIMIT=$SURVIVOR_PREVIEW
    TRUNCATED="true"
fi

if [[ "$FORMAT" == "json" ]]; then
    printf '{"target":"%s","app":"%s","baseline":"green","coverage":{"available":%s,"percent":%s},' \
        "$(json_escape "$TARGET")" "$(json_escape "$APP")" \
        "$COVERAGE_AVAILABLE" "$COVERAGE_PERCENT"
    printf '"candidates_total":%s,"tested":%s,"caught":%s,"skipped":%s,"survived":%s,"truncated":%s,"survivors":[' \
        "$TOTAL_FOUND" "$TESTED" "$CAUGHT" "$SKIPPED" "${#SURVIVED[@]}" "$TRUNCATED"
    SEP=""
    for ((i = 0; i < LIMIT; i++)); do
        ROW="${SURVIVED[$i]}"
        KIND="${ROW%%|*}"; REST="${ROW#*|}"
        LINE="${REST%%|*}"; LABEL="${REST#*|}"
        printf '%s{"kind":"%s","line":%s,"code":"%s"}' \
            "$SEP" "$(json_escape "$KIND")" "$LINE" "$(json_escape "$LABEL")"
        SEP=","
    done
    printf ']}\n'
else
    if [[ $TESTED -eq 0 ]]; then
        echo "No usable mutation - all $SKIPPED broke the syntax."
        echo "That is a mutator defect: report the file it happened on."
    elif [[ ${#SURVIVED[@]} -eq 0 ]]; then
        echo "All $TESTED mutations caught - the tests do check this code."
    else
        echo "Survived ${#SURVIVED[@]} of $TESTED. These lines can be broken unnoticed:"
        for ((i = 0; i < LIMIT; i++)); do
            ROW="${SURVIVED[$i]}"
            KIND="${ROW%%|*}"; REST="${ROW#*|}"
            LINE="${REST%%|*}"; LABEL="${REST#*|}"
            printf '  - line %s (%s): %s\n' "$LINE" "$KIND" "$LABEL"
        done
        [[ "$TRUNCATED" == "true" ]] && echo "  ... truncated, pass --full for all"
    fi
fi

# An empty survivor list is only good news when something was actually tested.
# With every candidate skipped, `survived == 0` says nothing at all, and exit 0
# would be read as "every mutation was caught".
if [[ $TESTED -eq 0 ]]; then
    echo "STOP: 0 of ${#CANDIDATES[@]} mutations ran - all of them broke the syntax." >&2
    echo "That is a mutator defect. No conclusion about the tests can be drawn." >&2
    exit 2
fi

[[ ${#SURVIVED[@]} -eq 0 ]] && exit 0
exit 1
