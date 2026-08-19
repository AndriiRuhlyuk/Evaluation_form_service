#!/usr/bin/env bash
#
# verify-tests.sh <app> <target_file>
#
# Доводить, що тести застосунку справді щось перевіряють, а не просто зеленіють.
# Робить три речі по черзі:
#   1. прогін тестів - має бути зелено на незміненому коді;
#   2. покриття цільового файлу через coverage.py, якщо він встановлений;
#   3. мутаційну перевірку - по черзі псує рядки `return` у цільовому файлі
#      і дивиться, чи тести це помічають.
#
# Мутація, яку тести НЕ помітили ("вижила"), означає прогалину в покритті:
# рядок можна зламати, і жоден тест не почервоніє.
#
# Файл відновлюється з копії у будь-якому разі - навіть якщо скрипт перервати
# по Ctrl+C. Копія робиться до першої зміни, git для відновлення не потрібен.

set -euo pipefail

APP="${1:-}"
TARGET="${2:-}"
MAX_MUTATIONS="${MAX_MUTATIONS:-5}"

if [[ -z "$APP" || -z "$TARGET" ]]; then
    echo "Використання: $0 <app> <target_file>"
    echo "Приклад:      $0 question question/views.py"
    exit 2
fi

if [[ ! -f "$TARGET" ]]; then
    echo "Немає такого файлу: $TARGET"
    exit 2
fi

# Команду прогону можна підмінити через TEST_CMD - потрібно для CI або коли
# Postgres підняли не через compose. За замовчуванням - топологія цього репо.
RUN_TESTS="${TEST_CMD:-docker-compose exec -T celery python manage.py test $APP}"

# ---------------------------------------------------------------- крок 1
# Тимчасові файли тримаємо поруч із ціллю, а не в /tmp: не залежимо від TMPDIR,
# а якщо скрипт уб'ють жорстко - копія лежить на видноті, а не губиться в системній теці.
BACKUP="${TARGET}.verify-backup"
BASE_LOG="${TARGET}.verify-log"

echo "== 1/3 базовий прогін =="
if ! $RUN_TESTS >"$BASE_LOG" 2>&1; then
    echo "ЗУПИНКА: тести червоні ще до мутацій. Спершу зелений прогін."
    tail -20 "$BASE_LOG"
    rm -f "$BASE_LOG"
    exit 1
fi
tail -3 "$BASE_LOG"
rm -f "$BASE_LOG"
echo

# ---------------------------------------------------------------- крок 2
echo "== 2/3 покриття =="
if docker-compose exec -T celery python -c "import coverage" 2>/dev/null; then
    docker-compose exec -T celery sh -c \
        "coverage run --source=$APP manage.py test $APP >/dev/null 2>&1; coverage report --include='$TARGET'"
else
    echo "coverage не встановлений - крок пропущено."
    echo "Щоб увімкнути: додай coverage у requirements.txt і перебудуй образ"
    echo "(docker-compose build celery), або разово:"
    echo "  docker-compose exec celery pip install coverage"
fi
echo

# ---------------------------------------------------------------- крок 3
echo "== 3/3 мутаційна перевірка (до $MAX_MUTATIONS мутацій) =="

cp "$TARGET" "$BACKUP"
# Відновлюємо файл за будь-якого виходу: успіх, помилка, Ctrl+C
trap 'cp "$BACKUP" "$TARGET"; rm -f "$BACKUP" "$BASE_LOG"' EXIT INT TERM

# Рядки виду `return <щось>` - саме вони несуть поведінку.
# `return` без значення і `return None` пропускаємо: псувати там нічого.
# Читаємо у масив без mapfile: він з'явився лише в bash 4, а /bin/bash на macOS - 3.2
LINES=()
while IFS= read -r ln; do
    LINES+=("$ln")
done < <(grep -n '^[[:space:]]*return [^N]' "$TARGET" | cut -d: -f1 | head -n "$MAX_MUTATIONS")

if [[ ${#LINES[@]} -eq 0 ]]; then
    echo "У $TARGET немає рядків return зі значенням - мутувати нічого."
    exit 0
fi

SURVIVED=()
SKIPPED=0
for LINE in "${LINES[@]}"; do
    python3 - "$TARGET" "$LINE" <<'PY'
import sys
path, line_no = sys.argv[1], int(sys.argv[2])
lines = open(path).readlines()
original = lines[line_no - 1]
indent = original[: len(original) - len(original.lstrip())]
lines[line_no - 1] = f"{indent}return None  # mutation\n"
open(path, "w").writelines(lines)
PY

    CODE_SNIPPET=$(sed -n "${LINE}p" "$BACKUP" | sed 's/^[[:space:]]*//' | cut -c1-50)

    # Багаторядковий вираз (`return (`) після заміни лишає хвіст без початку,
    # і файл перестає бути валідним Python. Тести тоді впадуть на SyntaxError,
    # а не на поведінці - це хибне "спіймано". Такі мутації пропускаємо.
    if ! python3 -m py_compile "$TARGET" 2>/dev/null; then
        echo "  пропущено рядок $LINE (багаторядковий): $CODE_SNIPPET"
        SKIPPED=$((SKIPPED + 1))
        cp "$BACKUP" "$TARGET"
        continue
    fi

    if $RUN_TESTS >/dev/null 2>&1; then
        echo "  ВИЖИЛА  рядок $LINE: $CODE_SNIPPET"
        SURVIVED+=("$LINE: $CODE_SNIPPET")
    else
        echo "  спіймано рядок $LINE: $CODE_SNIPPET"
    fi
    cp "$BACKUP" "$TARGET"
done

echo
TESTED=$((${#LINES[@]} - SKIPPED))
if [[ $TESTED -eq 0 ]]; then
    echo "Жодної придатної мутації: усі $SKIPPED кандидатів багаторядкові."
    echo "Візьми інший цільовий файл або підніми MAX_MUTATIONS."
elif [[ ${#SURVIVED[@]} -eq 0 ]]; then
    echo "Усі $TESTED мутації спіймані - тести справді перевіряють цей код."
else
    echo "Вижило ${#SURVIVED[@]} з $TESTED. Ці рядки можна зламати непомітно:"
    printf '  - %s\n' "${SURVIVED[@]}"
    echo
    echo "Це не привід писати тест на кожен рядок. Це список для рішення:"
    echo "поведінка справді важлива - дописати тест; ні - лишити і сказати про це."
fi
