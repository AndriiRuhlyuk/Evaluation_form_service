#!/usr/bin/env bash
#
# verify-tests.sh <app> <target_file>
#
# Доводить, що тести застосунку справді щось перевіряють, а не просто зеленіють.
# Робить три речі по черзі:
#   1. прогін тестів - має бути зелено на незміненому коді;
#   2. покриття цільового файлу через coverage.py, якщо він встановлений;
#   3. мутаційну перевірку - по черзі псує конструкції у цільовому файлі
#      і дивиться, чи тести це помічають. Кандидатів шукає mutate.py через
#      синтаксичне дерево, тому мутуються і багаторядкові вирази, і порівняння.
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

# Кандидатів шукає mutate.py через синтаксичне дерево: воно знає точні межі
# конструкції, тому багаторядковий `return (` замінюється цілком і файл лишається
# валідним Python. Пошук за шаблоном рядка цього не вміє.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MUTATOR="$SCRIPT_DIR/mutate.py"

if [[ ! -f "$MUTATOR" ]]; then
    echo "Немає $MUTATOR - мутаційна перевірка неможлива."
    exit 1
fi

# Якщо кандидатів більше за ліміт, беремо їх рівномірно по файлу, а не перші
# поспіль: інакше перевіримо лише початок модуля і не дізнаємось нічого про решту.
# Читаємо у масив без mapfile - він з'явився в bash 4, а /bin/bash на macOS це 3.2.
CANDIDATES=()
while IFS= read -r row; do
    CANDIDATES+=("$row")
done < <(python3 "$MUTATOR" list "$TARGET" | awk -v max="$MAX_MUTATIONS" '
    {rows[NR] = $0}
    END {
        step = (NR > max) ? NR / max : 1
        for (i = 1; i <= NR; i += step) print rows[int(i)]
    }')

if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
    echo "У $TARGET немає придатних конструкцій - мутувати нічого."
    exit 0
fi

TOTAL_FOUND=$(python3 "$MUTATOR" list "$TARGET" | wc -l | tr -d ' ')
echo "Кандидатів у файлі: $TOTAL_FOUND, перевіряємо: ${#CANDIDATES[@]}"

SURVIVED=()
SKIPPED=0
for ROW in "${CANDIDATES[@]}"; do
    # рядок має вигляд: <індекс>|<вид>|<рядок>|<фрагмент коду>
    IDX="${ROW%%|*}"
    REST="${ROW#*|}"
    KIND="${REST%%|*}"
    REST="${REST#*|}"
    LINE="${REST%%|*}"
    LABEL="${REST#*|}"

    python3 "$MUTATOR" apply "$TARGET" "$IDX"

    # Запобіжник. AST має гарантувати валідність, тож спрацювання тут означає
    # помилку мутатора, а не сигнал про якість тестів - і мовчки зарахувати
    # таку мутацію як "спіймано" було б обманом.
    if ! python3 -m py_compile "$TARGET" 2>/dev/null; then
        echo "  ПРОПУЩЕНО $KIND, рядок $LINE (мутація зламала синтаксис): $LABEL"
        SKIPPED=$((SKIPPED + 1))
        cp "$BACKUP" "$TARGET"
        continue
    fi

    if $RUN_TESTS >/dev/null 2>&1; then
        echo "  ВИЖИЛА  $KIND, рядок $LINE: $LABEL"
        SURVIVED+=("$KIND, рядок $LINE: $LABEL")
    else
        echo "  спіймано $KIND, рядок $LINE: $LABEL"
    fi
    cp "$BACKUP" "$TARGET"
done

echo
TESTED=$((${#CANDIDATES[@]} - SKIPPED))
if [[ $TESTED -eq 0 ]]; then
    echo "Жодної придатної мутації - усі $SKIPPED зламали синтаксис."
    echo "Це помилка мутатора: повідом про файл, на якому це сталося."
elif [[ ${#SURVIVED[@]} -eq 0 ]]; then
    echo "Усі $TESTED мутації спіймані - тести справді перевіряють цей код."
else
    echo "Вижило ${#SURVIVED[@]} з $TESTED. Ці рядки можна зламати непомітно:"
    printf '  - %s\n' "${SURVIVED[@]}"
    echo
    echo "Це не привід писати тест на кожен рядок. Це список для рішення:"
    echo "поведінка справді важлива - дописати тест; ні - лишити і сказати про це."
fi
