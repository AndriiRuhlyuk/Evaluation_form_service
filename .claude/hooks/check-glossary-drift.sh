#!/usr/bin/env bash
# SessionStart / PostToolUse: звірити глосарії між собою, з кодом і з реєстром фіч.
#
# Навіщо: інваріант "канон тримає лише покрите кодом" тримає скіл fix-term-local,
# а людина з редактором - ні. Саме так шість спекулятивних термінів опинилися в
# кореневому CONTEXT.md разом з тими, що покриті кодом, і ніщо їх не розрізняє.
#
# Скрипт лише ЧИТАЄ і лише звітує. Він НЕ блокує: перевірка 1 стоїть на grep, а
# grep бреше в обидва боки - дає сорок влучань на report через generate_html_report
# і нуль на "обґрунтована відмова", яка в коді живе як decision='refuse'. Гейт на
# ненадійній евристиці бере репо в заручники, як це вже зробив flake8 на sdlc/.
#
# Мовчить, коли чисто: хук друкує в контекст на кожному спрацюванні.
#
# Завжди exit 0: ненульовий код у PostToolUse трактується як збій інструменту.
set -u

event="${1:-PostToolUse}"

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd) || exit 0
cd "$root" || exit 0

command -v jq >/dev/null 2>&1 || exit 0

# PostToolUse смикається на кожному Write/Edit. Нас обходять лише глосарії, тож
# усе інше відсіюємо тут, до будь-якої роботи.
if [ "$event" = "PostToolUse" ]; then
  payload=$(cat 2>/dev/null) || exit 0
  fp=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // ""' 2>/dev/null)
  case "$fp" in
    *CONTEXT.md|*CONTEXT-MAP.md) ;;
    *) exit 0 ;;
  esac
fi

APPS="employee evaluation_form working_form template_form question topic techstack project"
CANON="CONTEXT.md"
MAP="CONTEXT-MAP.md"
findings=""

add() { findings="${findings}$1
"; }

# Імена термінів із блоку "## Glossary" одного файлу.
# Рядок має форму "- термін - визначення...", розділювач саме " - " з пробілами,
# тому "inter-rater agreement" не ріжеться навпіл.
terms_of() {
  awk '
    /^## Glossary/ { inside = 1; next }
    /^## / { inside = 0 }
    inside && /^- / {
      line = substr($0, 3)
      p = index(line, " - ")
      print (p > 0 ? substr(line, 1, p - 1) : line)
    }
  ' "$1" 2>/dev/null
}

glossaries=""
[ -f "$CANON" ] && glossaries="$CANON"
for f in docs/features/*/CONTEXT.md; do
  [ -f "$f" ] && glossaries="$glossaries $f"
done
gloss_count=$(printf '%s\n' $glossaries | grep -c . || true)

# --- 1. Канон містить слово зі стадії 01 ------------------------------------
# Сигнал - git, не grep. Перевірялося на живих даних: grep дав 11 влучань, з яких
# 4 хибні (stage clone живе як clone_working_to_evaluation, question bank як
# class Question, CRM sync як PeopleForce, aggregated decision як aggregated).
# Коміт, що ввів рядок, розрізняє точно: слово зі стадії 01 прийшло з брифа, а не
# з коду. Термін без коміту - незакомічена правка, і тоді мовчимо: людина в роботі.
if [ -f "$CANON" ]; then
  early=""
  while IFS= read -r t; do
    [ -n "$t" ] || continue
    subj=$(git log -S"$t" --format='%s' -- "$CANON" 2>/dev/null | tail -1)
    case "$subj" in
      01:*|*"idea for"*) early="$early $t," ;;
    esac
  done <<EOF
$(terms_of "$CANON")
EOF
  if [ -n "$early" ]; then
    add "Канон містить слова зі стадії 01 - їх увів коміт брифа, не коміт коду:${early%,}"
    add "  Канон тримає покрите кодом; місце пропозиції - docs/features/<slug>/CONTEXT.md."
  fi
fi

# --- 2. Дельта пережила шип -------------------------------------------------
for f in docs/features/*/CONTEXT.md; do
  [ -f "$f" ] || continue
  slug=$(basename "$(dirname "$f")")
  brief="docs/features/$slug/idea-brief.md"
  [ -f "$brief" ] || continue
  ids=$(awk '/^ticket:/ { print; exit }' "$brief" | grep -oE '[A-Z]+-[0-9]+' || true)
  for id in $ids; do
    done_flag=$(jq -r --arg i "$id" \
      '[.. | objects | select(.id? == $i)] | .[0].done // "absent"' \
      Features_list.json 2>/dev/null)
    if [ "$done_flag" = "true" ]; then
      add "Дельта пережила шип - $id має done: true, а терміни ще лежать у $f."
      add "  Час підвищити їх у канон і прибрати дельту."
    fi
  done
done

# --- 3. Мапа відповідає файлам ----------------------------------------------
if [ "$gloss_count" -gt 1 ] && [ ! -f "$MAP" ]; then
  add "Глосаріїв $gloss_count, а CONTEXT-MAP.md немає - мапа має зʼявитися з другим глосарієм."
fi
if [ "$gloss_count" -le 1 ] && [ -f "$MAP" ]; then
  add "Глосарій один, а CONTEXT-MAP.md існує - зайва мапа перемикає вендорний sdlc:fix-term у запис по теках коду."
fi
if [ -f "$MAP" ]; then
  linked=$(grep -oE '\]\(\./[^)]+\)' "$MAP" 2>/dev/null | sed 's/^](\.\///; s/)$//' || true)
  for l in $linked; do
    [ -f "$l" ] || add "CONTEXT-MAP.md посилається на $l, якого немає."
  done
  for g in $glossaries; do
    printf '%s\n' $linked | grep -qx "$g" || add "Глосарій $g не має рядка в CONTEXT-MAP.md."
  done
fi

# --- 4. Вендорний fix-term лишається вимкненим ------------------------------
# Оновлення sdlc/ повертає SKILL.md мовчки, і тоді два скіли пишуть глосарії
# за різними правилами.
if [ -f "sdlc/plugin/skills/fix-term/SKILL.md" ]; then
  add "Вендорний sdlc:fix-term знову увімкнений - оновлення sdlc/ повернуло SKILL.md."
  add "  Перейменуй його на SKILL.md.example: цей скіл пише глосарії за іншим правилом адреси."
fi

# --- 5. Слово живе в одному файлі -------------------------------------------
if [ "$gloss_count" -gt 1 ]; then
  dupes=$(for g in $glossaries; do terms_of "$g"; done | sort | uniq -d || true)
  if [ -n "$dupes" ]; then
    add "Термін стоїть більш ніж в одному глосарії: $(printf '%s' "$dupes" | tr '\n' ',' | sed 's/,$//')"
    add "  Одне слово - один файл; обери власника і прибери другий запис."
  fi
fi

[ -n "$findings" ] || exit 0

jq -nc --arg e "$event" --arg c "Звірка глосаріїв:
$findings" '{
  hookSpecificOutput: {
    hookEventName: $e,
    additionalContext: $c
  }
}'
exit 0
