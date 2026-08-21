#!/usr/bin/env bash
# Матриця PASS/FAIL для хуків цього репо: bash .claude/hooks/test-hooks.sh
#
# Навіщо: хук, привʼязаний до Claude без ізольованого прогону, мовчить двома
# способами - або не спрацьовує там, де мав, або блокує все підряд. Обидва
# видно тільки у живій сесії, коли вже пізно. Тут кожен скрипт годується
# синтетичним payload через stdin, і перевіряється рівно exit code.
#
# Три категорії кейсів на кожен хук:
#   positive - має заблокувати (exit 2)
#   negative - має пропустити (exit 0)
#   edge     - порожній/кривий payload не має крашити хук (exit 0)
set -u

cd "$(dirname "$0")/../.." || exit 1

PY=.venv/bin/python
[ -x "$PY" ] || PY=python3

pass=0
fail=0

# run_case <назва> <очікуваний код> <команда> <payload>
run_case() {
  local name="$1" expect="$2" cmd="$3" payload="$4" actual

  printf '%s' "$payload" | $cmd >/dev/null 2>&1
  actual=$?

  if [ "$actual" = "$expect" ]; then
    printf '  \033[32mPASS\033[0m  %-52s exit %s\n' "$name" "$actual"
    pass=$((pass + 1))
  else
    printf '  \033[31mFAIL\033[0m  %-52s exit %s (очікували %s)\n' \
      "$name" "$actual" "$expect"
    fail=$((fail + 1))
  fi
}

SECRETS="$PY .claude/hooks/protect-secrets.py"
LAYERING="$PY .claude/hooks/guard-layering.py"
TELEMETRY="$PY .claude/hooks/session-telemetry.py"
REINJECT="bash .claude/hooks/reinject-context.sh"

echo
echo "protect-secrets.py  (PreToolUse, exit 2 = заблоковано)"

run_case "positive: Write у .env" 2 "$SECRETS" \
  '{"tool_name":"Write","tool_input":{"file_path":"/repo/.env","content":"X=1"}}'

run_case "positive: Write у server.pem" 2 "$SECRETS" \
  '{"tool_name":"Write","tool_input":{"file_path":"/repo/server.pem","content":"x"}}'

run_case "positive: Edit у .env.production" 2 "$SECRETS" \
  '{"tool_name":"Edit","tool_input":{"file_path":".env.production","new_string":"A=1"}}'

run_case "positive: AWS key у коді" 2 "$SECRETS" \
  '{"tool_name":"Write","tool_input":{"file_path":"a/settings.py","content":"KEY = \"AKIA3KLMNOPQRSTUVWXY\"\n"}}'

# Канонічний ключ AWS із доків містить слово EXAMPLE. Глушник плейсхолдерів
# не має його рятувати: форма справжня, отже блокуємо.
run_case "positive: AWS doc-key попри слово EXAMPLE" 2 "$SECRETS" \
  '{"tool_name":"Write","tool_input":{"file_path":"a/settings.py","content":"KEY = \"AKIAIOSFODNN7EXAMPLE\"\n"}}'

run_case "positive: Postgres URL із паролем" 2 "$SECRETS" \
  '{"tool_name":"Write","tool_input":{"file_path":"a/db.py","content":"DSN = \"postgresql://admin:hunter2@db:5432/app\"\n"}}'

run_case "positive: SECRET_KEY літералом" 2 "$SECRETS" \
  '{"tool_name":"Write","tool_input":{"file_path":"a/settings.py","content":"SECRET_KEY = \"django-insecure-9f2ba7c1d4e8\"\n"}}'

run_case "positive: секрет у MultiEdit" 2 "$SECRETS" \
  '{"tool_name":"MultiEdit","tool_input":{"file_path":"a/x.py","edits":[{"old_string":"a","new_string":"b"},{"old_string":"c","new_string":"t = \"ghp_abcdefghijklmnopqrstuvwxyz0123456789\""}]}}'

run_case "negative: .env.sample дозволений" 0 "$SECRETS" \
  '{"tool_name":"Write","tool_input":{"file_path":"/repo/.env.sample","content":"POSTGRES_DB="}}'

run_case "negative: звичайний .py" 0 "$SECRETS" \
  '{"tool_name":"Write","tool_input":{"file_path":"working_form/views.py","content":"def get(self):\n    return None\n"}}'

run_case "negative: os.getenv замість літерала" 0 "$SECRETS" \
  '{"tool_name":"Write","tool_input":{"file_path":"a/settings.py","content":"SECRET_KEY = os.getenv(\"SECRET_KEY\")\n"}}'

run_case "negative: плейсхолдер, не секрет" 0 "$SECRETS" \
  '{"tool_name":"Write","tool_input":{"file_path":".env.sample","content":"PEOPLEFORCE_API_KEY=your-api-key-here\n"}}'

run_case "edge: порожній stdin" 0 "$SECRETS" ''
run_case "edge: невалідний JSON" 0 "$SECRETS" 'not json at all {{{'
run_case "edge: JSON без tool_input" 0 "$SECRETS" '{"tool_name":"Write"}'
run_case "edge: tool_input не обʼєкт" 0 "$SECRETS" '{"tool_name":"Write","tool_input":"oops"}'
run_case "edge: file_path відсутній" 0 "$SECRETS" '{"tool_name":"Write","tool_input":{"content":"x"}}'
run_case "edge: file_path = null" 0 "$SECRETS" '{"tool_name":"Write","tool_input":{"file_path":null}}'

echo
echo "guard-layering.py  (PreToolUse, exit 2 = заблоковано)"

run_case "positive: group_send у services.py" 2 "$LAYERING" \
  '{"tool_name":"Edit","tool_input":{"file_path":"working_form/services.py","new_string":"    async_to_sync(layer.group_send)(f\"form_{pk}\", payload)\n"}}'

run_case "positive: import channels у services.py" 2 "$LAYERING" \
  '{"tool_name":"Write","tool_input":{"file_path":"template_form/services.py","content":"from channels.layers import get_channel_layer\n"}}'

run_case "positive: get_channel_layer() у services.py" 2 "$LAYERING" \
  '{"tool_name":"Edit","tool_input":{"file_path":"evaluation_form/services.py","new_string":"layer = get_channel_layer()\n"}}'

run_case "negative: group_send у views.py дозволений" 0 "$LAYERING" \
  '{"tool_name":"Edit","tool_input":{"file_path":"working_form/views.py","new_string":"async_to_sync(layer.group_send)(group, payload)\n"}}'

run_case "negative: group_send у consumers.py дозволений" 0 "$LAYERING" \
  '{"tool_name":"Edit","tool_input":{"file_path":"working_form/consumers.py","new_string":"await self.channel_layer.group_send(g, m)\n"}}'

run_case "negative: звичайний services.py" 0 "$LAYERING" \
  '{"tool_name":"Edit","tool_input":{"file_path":"working_form/services.py","new_string":"with transaction.atomic():\n    form.save()\n"}}'

run_case "negative: коментар про group_send" 0 "$LAYERING" \
  '{"tool_name":"Edit","tool_input":{"file_path":"working_form/services.py","new_string":"# group_send робить view, не цей модуль\n"}}'

run_case "edge: порожній stdin" 0 "$LAYERING" ''
run_case "edge: невалідний JSON" 0 "$LAYERING" '{"broken'
run_case "edge: шлях без services.py" 0 "$LAYERING" \
  '{"tool_name":"Edit","tool_input":{"file_path":"README.md","new_string":"group_send"}}'

echo
echo "session-telemetry.py  (SessionEnd, async - завжди exit 0)"

run_case "negative: валідний payload" 0 "$TELEMETRY" \
  '{"session_id":"abcd1234-test","cwd":"/tmp","reason":"clear","transcript_path":"/nonexistent.jsonl"}'

run_case "edge: порожній stdin" 0 "$TELEMETRY" ''
run_case "edge: невалідний JSON" 0 "$TELEMETRY" 'xxx'
run_case "edge: transcript_path відсутній" 0 "$TELEMETRY" '{"session_id":"x","cwd":"/tmp"}'

echo
echo "reinject-context.sh  (SessionStart, stdout -> context, завжди exit 0)"

run_case "negative: звичайний запуск" 0 "$REINJECT" \
  '{"hook_event_name":"SessionStart","source":"compact"}'

run_case "edge: порожній stdin" 0 "$REINJECT" ''

echo
printf 'Разом: \033[32m%s PASS\033[0m, \033[31m%s FAIL\033[0m\n' "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1
