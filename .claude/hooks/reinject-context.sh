#!/usr/bin/env bash
# SessionStart / matcher=compact: повернути в контекст те, що compact з'їдає.
#
# Навіщо: CLAUDE.md прямо фіксує, що правила з .claude/rules/ НЕ переінжектяться
# після /compact - вони підвантажаться аж коли Claude наступного разу відкриє
# файл, що збігається з paths. Між compact і тим моментом агент працює без
# інваріантів проєкту і встигає їх порушити.
#
# Контракт SessionStart: stdout при exit 0 стає контекстом Claude (для решти
# подій stdout ігнорується). Тому тут друкуємо, а не логуємо.
#
# Друкуємо тільки те, що compact губить: живий стан репозиторію і жменю
# інваріантів. Переказувати сюди CLAUDE.md сенсу немає - він переживає compact.
set -u

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0

echo "## Стан репозиторію після compact"
echo

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) && echo "Гілка: ${branch}"

echo
echo "Останні коміти:"
git log --oneline -5 2>/dev/null || echo "  (не git-репозиторій)"

# Незакомічена міграція - найдорожча втрата після compact: забута міграція
# мовчки нашаровується на наступну, і граф dependencies розходиться з базою.
pending_migrations=$(git status --porcelain -- '*/migrations/*.py' 2>/dev/null)
echo
if [ -n "$pending_migrations" ]; then
  echo "УВАГА, незакомічені міграції:"
  printf '%s\n' "$pending_migrations" | sed 's/^/  /'
else
  echo "Незакомічених міграцій немає."
fi

changed=$(git status --porcelain 2>/dev/null | grep -vE '/migrations/' | head -15)
echo
if [ -n "$changed" ]; then
  echo "Змінені файли:"
  printf '%s\n' "$changed" | sed 's/^/  /'
else
  echo "Робоче дерево чисте."
fi

# flake8 - єдиний регресійний сигнал у цьому репо (тести зелені майже завжди).
# Ганяємо його тут, щоб після compact агент знав фактичний baseline, а не
# пам'ятав вигаданий. timeout, щоб повільний диск не тримав старт сесії.
echo
if [ -x .venv/bin/flake8 ]; then
  flake8_out=$(timeout 60 .venv/bin/flake8 2>&1)
  if [ -z "$flake8_out" ]; then
    echo "flake8: чисто. Будь-який новий рядок у виводі - регресія твого діфа."
  else
    echo "flake8: $(printf '%s\n' "$flake8_out" | wc -l | tr -d ' ') знахідок ДО твоїх змін:"
    printf '%s\n' "$flake8_out" | head -10 | sed 's/^/  /'
  fi
else
  echo "flake8: .venv не активований, baseline невідомий."
fi

cat <<'INVARIANTS'

## Інваріанти, які compact губить разом із .claude/rules/

- Стадії pipeline (TemplateForm -> WorkingForm -> EvaluationForm) зв'язані
  клонуванням, а не FK. Не додавай FK на попередню стадію.
- services.py ніколи не робить broadcast. group_send() живе у working_form/
  views.py і consumers.py. Це стереже хук guard-layering.py на PreToolUse.
- Кожна мутація working_form винна свій group_send у group form_<id>.
- Рахуй через prefetch_count() з working_form/utils.py, не через .count() -
  інакше кожен виклик іде окремим запитом повз prefetch.
- python manage.py showmigrations ЗАВЖДИ перед makemigrations.
- .env недоступний на читання і закритий на запис хуком protect-secrets.py.
INVARIANTS

exit 0
