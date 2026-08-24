#!/usr/bin/env bash
# PostToolUse / Bash: підсвітити руйнівні операції у щойно згенерованих
# міграціях, поки їх ще не застосували через migrate.
#
# RemoveField/DeleteModel компілюються в DROP COLUMN / DROP TABLE - дані
# зникають незворотно. Rename* на Postgres бере ACCESS EXCLUSIVE блокування,
# тобто зупиняє читання і запис таблиці на час операції.
#
# Звуження до makemigrations живе ТУТ, а не в hooks.json. У standalone-версії
# його робило поле "if" конфігурації; у плагіні на нього покладатись не можна -
# самодостатній скрипт працює однаково незалежно від того, як його підключили.
set -u

payload=$(cat 2>/dev/null) || payload=""
cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // ""' 2>/dev/null) || cmd=""
case "$cmd" in
  *makemigrations*) ;;
  *) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0

files=""
while IFS= read -r line; do
  # porcelain-формат: XY<пробіл>шлях; для перейменувань "R  old -> new"
  # береться частина після останнього пробілу, тобто новий шлях.
  path=${line##* }
  [ -f "$path" ] && files="${files}${path}"$'\n'
done < <(git status --porcelain -- '*/migrations/*.py' 2>/dev/null)

[ -n "$files" ] || exit 0

hits=$(printf '%s' "$files" | while IFS= read -r f; do
  [ -n "$f" ] || continue
  grep -lE 'RemoveField|DeleteModel|RenameField|RenameModel|AlterModelTable|AlterUniqueTogether' "$f" 2>/dev/null
done)

[ -n "$hits" ] || exit 0

jq -nc --arg f "$hits" '{
  hookSpecificOutput: {
    hookEventName: "PostToolUse",
    additionalContext: ("УВАГА: незакомічені міграції містять потенційно руйнівні операції (DROP COLUMN / DROP TABLE / перейменування з блокуванням таблиці). Перш ніж пропонувати migrate, покажи користувачу вміст цих файлів і поясни наслідки для даних:\n" + $f)
  }
}'
