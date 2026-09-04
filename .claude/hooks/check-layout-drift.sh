#!/usr/bin/env bash
# SessionStart / PostToolUse: звірити ASCII-дерево в секції "## Project Layout"
# файлу CLAUDE.md з реальною структурою проєкту.
#
# Навіщо: дерево в CLAUDE.md рукописне, і гниє воно тихо - битий шлях не дає
# помилки, він просто веде агента хибним слідом. Скрипт лише ЧИТАЄ: він
# знаходить розбіжність і вливає її в контекст, а коментар до нового модуля
# пише модель (shell не вміє пояснити, що робить routing.py).
#
# Мовчить, коли все збігається: хук друкує в контекст на кожному спрацюванні,
# тож "все ок" × 40 інструментів за сесію - чистий шум.
#
# Завжди exit 0: ненульовий код у PostToolUse трактується як збій інструменту,
# а нам потрібне повідомлення, а не помилка.
set -u

event="${1:-PostToolUse}"

# Хук може стартувати з будь-якого cwd - прив'язуємось до розташування скрипта.
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd) || exit 0
cd "$root" || exit 0

md="CLAUDE.md"
[ -f "$md" ] || exit 0

# Імена, поява яких означає нову можливість у стеку, а не рутинний файл апки.
# models/views/serializers/admin/apps/urls/permissions/tests є в кожній апці за
# визначенням - їхня згадка в дереві не несе інформації.
WHITELIST="services.py consumers.py middleware.py routing.py tasks.py utils.py custom_fields.py admin_mixins.py signals.py managers.py"

# Те, що не версіонується, у дереві не описують - воно нічого не каже про проєкт.
# .superpowers - скретч-журнал subagent-driven-development, живе лише поки триває фіча.
# sdlc - сторонній SDLC-тулкіт, гітігнорований разом з усім вмістом (.gitignore: /sdlc/).
# pocock - чужі скіли як еталон форми, гітігноровані так само (.gitignore: /pocock/).
IGNORE_DIRS="^(\.git|\.venv|\.idea|\.superpowers|sdlc|pocock|__pycache__|staticfiles|media|reports|node_modules|htmlcov)$"

emit() {
  jq -nc --arg e "$event" --arg c "$1" '{
    hookSpecificOutput: {
      hookEventName: $e,
      additionalContext: $c
    }
  }'
  exit 0
}

# --- 1. Витягти ```-блок із секції "## Project Layout" ---------------------
block=$(awk '
  /^## Project Layout/ { inside = 1; next }
  inside && /^## /      { exit }
  inside && /^```/      { fence++; if (fence == 1) next; else exit }
  inside && fence == 1  { print }
' "$md")

[ -n "$block" ] || exit 0

# --- 2. Розпарсити дерево в повні шляхи ------------------------------------
# Відступ 4 символи = 1 рівень. "│" замінюємо на пробіл, щоб рахувати довжину
# в байтах незалежно від локалі (│ у UTF-8 займає 3 байти, пробіл - 1).
expected=""
badformat=""
declare -a stack
while IFS= read -r line; do
  case "$line" in
    *'├── '*|*'└── '*) ;;
    *) continue ;;
  esac

  indent=$(printf '%s' "$line" | sed -e 's/├── .*$//' -e 's/└── .*$//' -e 's/│/ /g')

  # Відступ, не кратний 4, підіймає рядок на хибний рівень, і всі наступні
  # рядки чіпляються під нього - один зламаний символ дає каскад фальшивих
  # шляхів. Ловимо це прямо, інакше діагностика бреше про причину.
  if [ $(( ${#indent} % 4 )) -ne 0 ]; then
    badformat="${badformat}  ${line}"$'\n'
    continue
  fi

  depth=$(( ${#indent} / 4 + 1 ))

  name=$(printf '%s' "$line" \
    | sed -e 's/^.*├── //' -e 's/^.*└── //' -e 's/[[:space:]].*$//' -e 's#/$##')
  [ -n "$name" ] || continue

  stack[$depth]="$name"
  full=""
  i=1
  while [ "$i" -le "$depth" ]; do
    full="${full}${stack[$i]}/"
    i=$((i + 1))
  done
  expected="${expected}${full%/}"$'\n'
done <<< "$block"

expected=$(printf '%s' "$expected" | sed '/^$/d')

if [ -n "$badformat" ]; then
  emit "У дереві ## Project Layout файлу CLAUDE.md зламаний відступ - він має бути рівно 4 символи на рівень («│   » або 4 пробіли). Рядки з некратним відступом:

${badformat}
Полагодь їх. До того звірка структури неповна: рядок на хибному рівні тягне за собою всі наступні."
fi

# Дерево, що не парситься, небезпечніше за дерево застаріле: детектор мовчав би,
# вдаючи, що розбіжностей нема.
count=$(printf '%s\n' "$expected" | grep -c . || true)
if [ "$count" -lt 10 ]; then
  emit "Не вдалося розпарсити дерево в секції ## Project Layout файлу CLAUDE.md (знайдено $count шляхів, очікується щонайменше 10). Формат зламано: відступ має бути рівно 4 символи на рівень, маркери «├── » і «└── ». Полагодь блок, інакше звірка структури не працює."
fi

# --- 3. Зібрати розбіжності -------------------------------------------------
stale=""
while IFS= read -r p; do
  [ -n "$p" ] || continue
  [ -e "$p" ] || stale="${stale}  - ${p}  (у дереві, немає на диску)"$'\n'
done <<< "$expected"

missing=""

# 3a. Директорії 1-го рівня. Директорія вважається присутньою, якщо будь-який
# шлях у дереві дорівнює їй або починається з "<dir>/" - бо `docs` показана
# в дереві як `docs/orchestration/`.
for d in $(find . -maxdepth 1 -type d ! -name '.' | sed 's#^\./##' | sort); do
  printf '%s\n' "$d" | grep -qE "$IGNORE_DIRS" && continue
  if ! printf '%s\n' "$expected" | grep -qE "^${d}(/|$)"; then
    missing="${missing}  + ${d}/  (директорія на диску, немає в дереві)"$'\n'
  fi
done

# 3b. Whitelist-файли всередині директорій 1-го рівня.
for d in $(find . -maxdepth 1 -type d ! -name '.' | sed 's#^\./##' | sort); do
  printf '%s\n' "$d" | grep -qE "$IGNORE_DIRS" && continue
  for f in $WHITELIST; do
    [ -f "$d/$f" ] || continue
    if ! printf '%s\n' "$expected" | grep -qxF "$d/$f"; then
      missing="${missing}  + ${d}/${f}  (на диску, немає в дереві)"$'\n'
    fi
  done
done

[ -n "$stale$missing" ] || exit 0

emit "Дерево в секції ## Project Layout файлу CLAUDE.md розійшлося зі структурою проєкту:

${missing}${stale}
Онови секцію: додай або прибери рядок, дотримуючись формату (відступ 4 символи на рівень). Для кожного доданого шляху напиши коментар праворуч - що модуль РОБИТЬ, а не як він називається; ім'я файлу вже видно зі шляху. Якщо шлях не вартий згадки в дереві, скажи про це користувачу замість того, щоб додавати рядок мовчки."
