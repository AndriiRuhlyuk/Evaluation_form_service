#!/usr/bin/env bash
# PreToolUse / Bash: вимагати підтвердження на shell-команди, здатні знищити
# або переписати файли міграцій Django.
#
# Навіщо окремий хук: правила Edit(**/migrations/*.py) покривають лише канал
# "інструмент пише у файл". Bash - окремий канал, де зіставлення йде по тексту
# команди. Правила Bash(...) працюють по префіксу, тому не ловлять шлях
# усередині команди - цей хук бачить команду цілком.
set -u

cmd=$(jq -r '.tool_input.command // ""' 2>/dev/null) || exit 0

ask() {
  jq -nc --arg r "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "ask",
      permissionDecisionReason: $r
    }
  }'
  exit 0
}

# git clean перевіряємо завжди: він знищує невідстежувані файли, навіть якщо
# слово "migrations" у команді не згадується (`git clean -fd`).
if printf '%s' "$cmd" | grep -qE '(^|[^[:alnum:]_-])git[[:space:]]+clean([[:space:]]|$)'; then
  ask "git clean знищує невідстежувані файли безслідно. У дереві є незакомічені міграції - відновити їх буде нізвідки."
fi

# Решта перевірок - лише для команд, що взагалі згадують міграції.
case "$cmd" in
  *migrations*) ;;
  *) exit 0 ;;
esac

if printf '%s' "$cmd" | grep -qE '(^|[^[:alnum:]_-])(rm|mv|shred|truncate|dd)[[:space:]]'; then
  ask "Команда видаляє або переміщує файли міграцій. Видалений файл розриває граф dependencies, а рядок у таблиці django_migrations лишається - це ламає всі manage.py команди, і у вас, і в CI."
fi

if printf '%s' "$cmd" | grep -qE '(^|[^[:alnum:]_-])git[[:space:]]+(checkout|restore|reset|stash)([[:space:]]|$)'; then
  ask "Команда відкочує стан файлів міграцій через git. Перевір, що незакомічені міграції не загубляться."
fi

if printf '%s' "$cmd" | grep -qE '(^|[^[:alnum:]_-])(find|xargs)[[:space:]].*(-delete|-exec[[:space:]]+rm)'; then
  ask "Масове видалення файлів у дереві, що містить міграції."
fi

if printf '%s' "$cmd" | grep -qE '>[[:space:]]*[^[:space:]]*migrations/'; then
  ask "Перенаправлення виводу у файл міграції затре його вміст."
fi

exit 0
