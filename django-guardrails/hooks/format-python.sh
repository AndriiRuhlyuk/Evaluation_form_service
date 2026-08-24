#!/usr/bin/env bash
# PostToolUse / Write|Edit|MultiEdit: прогнати black по щойно записаному .py.
#
# Навіщо окремий скрипт, а не однорядковий inline-хук у hooks.json: inline-версія
# жила у settings.json і хардкодила `.venv/bin/black`, тобто мовчки нічого не
# робила в будь-якому репо, де venv лежить інакше. У плагіні той самий рядок
# мусить працювати всюди, тому пошук інтерпретатора винесено в код.
#
# Два різні корені в одному хуку: сам скрипт належить ПЛАГІНУ
# (${CLAUDE_PLUGIN_ROOT}), а black - ЦІЛЬОВОМУ ПРОЄКТУ ($CLAUDE_PROJECT_DIR).
# Плутанина між ними - головна пастка конвертації standalone -> plugin.
#
# Форматування ніколи не блокує: exit 0 за будь-яких обставин.
set -u

path=$(jq -r '.tool_response.filePath // .tool_input.file_path // ""' 2>/dev/null) || exit 0
case "$path" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "$path" ] || exit 0

project="${CLAUDE_PROJECT_DIR:-.}"

if [ -x "$project/.venv/bin/black" ]; then
  "$project/.venv/bin/black" -q "$path" 2>/dev/null
elif command -v black >/dev/null 2>&1; then
  black -q "$path" 2>/dev/null
fi

exit 0
