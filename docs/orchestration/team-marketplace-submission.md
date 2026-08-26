# Урок 6, складний рівень: team-marketplace на GitHub

**Репозиторій:** https://github.com/AndriiRuhlyuk/evalforms-team-marketplace (public)
**Зелений CI:** https://github.com/AndriiRuhlyuk/evalforms-team-marketplace/actions/runs/32945761419
**Плагінів у маркетплейсі:** 3 - `django-guardrails@1.2.0`, `drf-api-guard@1.0.0`,
`django-deploy-checklist@1.0.1`
**Споживач:** приватний `AndriiRuhlyuk/Evaluation_form_service` (Django 5.2 + DRF, Channels,
Celery), де всі три встановлені на `Scope: project`.

Нижче - відтворювана послідовність. Кожен крок має команду і **перевірку**, бо в цій задачі
майже всі помилки мовчазні: успішний вивід команди не доводить, що вона щось зробила.

---

## Крок 0. Передумови

```bash
claude --version          # CLI має бути в PATH
gh auth status            # для створення репо і читання CI
```

---

## Крок 1. Публічний репозиторій із безпечним іменем

Ім'я не може починатися з `anthropic-`, `claude-code-`, `official-` - це зарезервовані
простори імен, і валідатор такий маркетплейс відкине.

```bash
mkdir -p ~/DRF_project/evalforms-team-marketplace
cd ~/DRF_project/evalforms-team-marketplace
git init -b main

# перевірка імені перед створенням репо
case "evalforms-team-marketplace" in
  anthropic-*|claude-code-*|official-*) echo "FAIL: reserved prefix"; exit 1 ;;
  *) echo "OK: ім'я вільне" ;;
esac

gh repo create AndriiRuhlyuk/evalforms-team-marketplace --public --source=. --remote=origin
```

**Перевірка:** `gh repo view --json visibility,name` повертає `PUBLIC` і потрібне ім'я.

---

## Крок 2. Маніфест маркетплейсу

`.claude-plugin/marketplace.json` у корені. `owner.url` веде на репозиторій, а не на
особисту пошту: канал репорту вразливостей описаний у `SECURITY.md` і йде через GitHub
Security Advisories, тому приватний email нікуди не публікується.

```bash
mkdir -p .claude-plugin plugins scripts .github/workflows
```

```json
{
  "name": "evalforms-team-marketplace",
  "description": "Claude Code plugin marketplace for a Django/DRF team, distributing deterministic quality-gate plugins.",
  "owner": {
    "name": "Andrii Rykhliuk",
    "url": "https://github.com/AndriiRuhlyuk/evalforms-team-marketplace"
  },
  "plugins": [
    {
      "name": "django-guardrails",
      "source": "./plugins/django-guardrails",
      "description": "Deterministic quality gates for Django/DRF repos ...",
      "version": "1.2.0",
      "category": "quality-gates",
      "tags": ["django", "drf", "hooks", "testing", "secrets"],
      "author": { "name": "Andrii Rykhliuk" },
      "strict": true
    }
  ]
}
```

Сім обов'язкових полів у кожному записі: `name`, `source`, `description`, `version`,
`category`, `tags`, `strict: true`. `source` - **відносний** шлях (монорепо-кейс).

**Перевірка** - власний валідатор схеми, який ганяє й CI:

```bash
python3 scripts/validate.py        # -> OK 3 plugins
```

Він ловить не лише відсутнє поле, а й **порожнє значення** (`"name": ""` спершу проходив як
валідний) і версію з хвостовим переносом рядка. Це той випадок, де регекс із `$` бреше:
у Python `$` матчиться і перед фінальним `\n`, тому `"1.0.0\n"` вважався валідним - потрібен
`\Z`.

---

## Крок 3. Плагіни у `plugins/`, версії синхронні

```
plugins/
├── django-guardrails/
│   ├── .claude-plugin/plugin.json     # version МАЄ дорівнювати marketplace.json
│   ├── hooks/{hooks.json, *.py, *.sh, test-hooks.sh}
│   ├── commands/{gate.md, hooks-matrix.md}
│   └── skills/scaffold-tests/SKILL.md
├── drf-api-guard/
│   ├── .claude-plugin/plugin.json
│   ├── hooks/{hooks.json, guard-api-access.py, warn-serializer-writes.py, test-hooks.sh}
│   └── commands/hooks-matrix.md
└── django-deploy-checklist/
    ├── .claude-plugin/plugin.json
    ├── commands/{deploy-check.md, audit-matrix.md}
    ├── scripts/deploy-audit.py
    └── tests/test-audit.sh            # матриця під tests/, бо хуків у плагіні немає
```

Версія дублюється у двох JSON, тому інваріант винесено в окремий скрипт - **не** в
`validate.py`, щоб CI показував, що саме зламалось:

```bash
python3 scripts/check-versions.py  # -> OK 3 plugins, versions match
```

**Чому окремий файл:** зламана схема і розсинхрон версій - різні помилки з різними
виправленнями. Один скрипт на дві задачі дав би одне повідомлення на два діагнози.

---

## Крок 4. README (6 секцій) і SECURITY.md

```bash
grep -n "^## " README.md
# 3:## Що це
# 10:## Як додати у Claude Code
# 25:## Список плагінів
# 38:## Супровідники
# 45:## Як контрибʼютити
# 122:## Контакти

grep -n "^## " SECURITY.md
# 3:## Як повідомити про вразливість
# 18:## Security checklist
```

README додатково містить **правила оновлення і версіонування** - і головне попередження:
у Claude Code **немає піну діапазоном**. `enabledPlugins` - це просто
`"name@marketplace": true`, а `plugin install` не приймає версію. Тобто npm-семантика
`^1.0.0` тут не працює, і `update` дотягне навіть мажор. Це перевірено емпірично на CLI,
а не взято з аналогії з npm - у першій редакції README стверджувалося протилежне.

---

## Крок 5. CI: `.github/workflows/validate-plugins.yml`

Дві джоби. Перша - статична, без ключів. Друга - матриця по плагінах.

```yaml
jobs:
  static-validate:
    steps:
      - run: python3 scripts/validate.py
      - run: python3 scripts/check-versions.py
      - run: curl -fsSL https://claude.ai/install.sh | bash -s stable
      - run: claude plugin validate .

  plugin-validate:
    needs: static-validate
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}   # env на рівні ДЖОБИ
    strategy:
      matrix:
        plugin: [django-guardrails, drf-api-guard, django-deploy-checklist]
    steps:
      - run: claude plugin validate ./plugins/${{ matrix.plugin }}
      - run: |                                    # матриця самотестів плагіна
          ran=0
          for suite in "./plugins/${{ matrix.plugin }}/hooks/test-hooks.sh" \
                       "./plugins/${{ matrix.plugin }}/tests/test-audit.sh"; do
            [ -f "$suite" ] && { bash "$suite"; ran=$((ran + 1)); }
          done
          echo "matrices run for ${{ matrix.plugin }}: $ran"
          [ "$ran" -eq 0 ] && echo "WARNING: no self-test matrix found"
      - name: Smoke install
        if: env.ANTHROPIC_API_KEY != ''
        run: claude --plugin-dir ./plugins/${{ matrix.plugin }} --print "echo ready"
```

Три речі тут не косметичні:

1. **`env` стоїть на рівні джоби, не кроку.** `if:` кроку обчислюється **до** матеріалізації
   його власного `env`, тож при `env` на кроці умова завжди хибна і smoke-install не
   запускався **жодного разу** - при зеленому CI.
2. **Крок із самотестами.** `claude plugin validate` доводить, що маніфест валідний, а не що
   гейт досі кусається. Без цього кроку хук, який тихо перестав спрацьовувати, доїжджає до
   `main` зеленим.
3. **Лічильник `ran` друкується навмисно.** `[ -f ... ]` виходить із 0, коли нічого не
   знайдено, тому зелена джоба сама по собі не доводить, що матриця взагалі стартувала.

---

## Крок 6. Мердж у main, зелений CI, теги

```bash
git add -A && git commit -m "feat: каркас маркетплейсу і три плагіни"
git push -u origin main

gh run list --limit 1        # completed  success  Validate plugins

git tag -a django-guardrails@1.2.0      -m "release"
git tag -a drf-api-guard@1.0.0          -m "initial release"
git tag -a django-deploy-checklist@1.0.1 -m "release"
git push --tags
```

**Перевірка:** `git tag -l` показує тег на кожну опубліковану версію.
Формат `<plugin>@<version>` замість голого `v1.0.0` - обов'язковий у монорепо: голий тег не
сказав би, який із трьох плагінів випущено.

---

## Крок 7. Установка на чистій машині

```bash
/plugin marketplace add github:AndriiRuhlyuk/evalforms-team-marketplace
/plugin install django-guardrails@evalforms-team-marketplace
```

Або без інтерактиву. `--scope project` потрібен **двічі**: `marketplace add` має власний
`--scope`, і його типове значення теж `user`.

```bash
claude plugin marketplace add AndriiRuhlyuk/evalforms-team-marketplace --scope project
claude plugin install django-guardrails@evalforms-team-marketplace       --scope project
claude plugin install drf-api-guard@evalforms-team-marketplace           --scope project
claude plugin install django-deploy-checklist@evalforms-team-marketplace --scope project
```

**Перевірка - `plugin list`, і ніде більше:**

```
❯ django-deploy-checklist@evalforms-team-marketplace   Version: 1.0.1  Scope: project  ✔ enabled
❯ django-guardrails@evalforms-team-marketplace         Version: 1.2.0  Scope: project  ✔ enabled
❯ drf-api-guard@evalforms-team-marketplace             Version: 1.0.0  Scope: project  ✔ enabled
```

**Виклик через namespace** (після рестарту сесії):

```
/django-guardrails:hooks-matrix          -> 79 PASS / 0 FAIL
/drf-api-guard:hooks-matrix              -> 53 PASS / 0 FAIL
/django-deploy-checklist:audit-matrix    -> 82 PASS / 0 FAIL
/django-deploy-checklist:deploy-check    -> чекліст релізу
```

Чотири пастки цього кроку:

- **`--scope project` не типово, а обов'язково - і для `add`, і для `install`.** Без нього
  плагін лягає в `user` scope і їде за тобою у кожне стороннє репо на машині. Перевірено
  емпірично: `marketplace add` без прапорця звітує `declared in user settings` і пише в
  `$CLAUDE_CONFIG_DIR/settings.json`, тобто оголошення не їде разом із репозиторієм; із
  `--scope project` те саме лягає у `.claude/settings.json` воркспейсу і комітиться.
- **Форма адреси визначає протокол клону.** `owner/repo` записується як
  `"source": "github"` і клонується через SSH; повний `https://...git` - як `"source":
  "git"` і клонується через HTTPS. Практичного значення це не має: при недоступному SSH CLI
  друкує `SSH clone failed, retrying with HTTPS` і доводить справу до кінця. Перевірено
  прогоном із навмисно зламаним `GIT_SSH_COMMAND=/usr/bin/false` - exit 0, клон по HTTPS.
- **Оголошення ≠ установка.** У споживчому репо закомічені `extraKnownMarketplaces` і
  `enabledPlugins`, але на свіжому клоні під ізольованим `CLAUDE_CONFIG_DIR` CLI звітує
  `No plugins installed` / `No marketplaces configured` - **без жодної помилки**. Два гейти:
  реєстрація маркетплейсу потребує **довіреного** воркспейсу (недовірений мовчки ігнорує ще
  й `permissions.allow`, а `-p` пропускає діалог довіри, а не приймає його), і плагін усе
  одно треба доставити `claude plugin install`. Поки обидва не сталися, клон виглядає
  здоровим і не має жодного гейта.
- **Новий плагін вимагає `marketplace update` ПЕРЕД `install`.** Локальний каталог -
  знімок, тож щойно змерджений плагін у ньому просто відсутній і `install` падає з
  `Plugin "<name>" not found in marketplace`.

---

## Верифікація на чистій машині (протокол прогону)

Виконано 2026-08-26 у порожній директорії з ізольованим `CLAUDE_CONFIG_DIR`, щоб робочий
`~/.claude/` не впливав на результат і не постраждав.

```bash
CLEAN=/tmp/clean-machine
mkdir -p "$CLEAN/workspace" "$CLEAN/config"
cd "$CLEAN/workspace" && git init -b main .
export CLAUDE_CONFIG_DIR="$CLEAN/config"
```

**Крок A - базовий стан.** Так виглядає репозиторій у колеги до установки:

```
$ claude plugin list         -> No plugins installed. Use `claude plugin install` ...
$ claude plugin marketplace list -> No marketplaces configured
```

**Крок B - установка.** `marketplace add` + три `install --scope project`. Результат
`plugin list`:

```
❯ django-deploy-checklist@evalforms-team-marketplace  Version: 1.0.1  Scope: project  ✔ enabled
❯ django-guardrails@evalforms-team-marketplace        Version: 1.2.0  Scope: project  ✔ enabled
❯ drf-api-guard@evalforms-team-marketplace            Version: 1.0.0  Scope: project  ✔ enabled
```

Кеш ліг у `$CLAUDE_CONFIG_DIR/plugins/cache/evalforms-team-marketplace/<plugin>/<version>/` -
з директорією версії, тому шлях, скопійований із репозиторію маркетплейсу, там не резолвиться.

**Крок C - валідація маніфестів** із чистої машини: `claude plugin validate .` і по одному
на кожен плагін - `✔ Validation passed` чотири рази.

**Крок D - матриці самотестів, запущені з кешу саме цієї інсталяції.** Це і є доказ, що
приїхали робочі файли, а не лише запис у settings:

| Плагін | Матриця | Результат |
|---|---|---|
| django-guardrails 1.2.0 | `hooks/test-hooks.sh` | **79 PASS, 0 FAIL** |
| drf-api-guard 1.0.0 | `hooks/test-hooks.sh` | **53 PASS, 0 FAIL** |
| django-deploy-checklist 1.0.1 | `tests/test-audit.sh` | **82 PASS, 0 FAIL** |

**Крок E - живі гейти.** Синтетичний ввід у формі payload'а `PreToolUse`, щоб перевірити не
"чи встановилось", а "чи кусається":

| # | Сценарій | Гейт | Очікувано | Факт |
|---|---|---|---|---|
| 1 | `CandidateViewSet` без `permission_classes` | `guard-api-access.py` | блок | **exit 2** |
| 2 | `fields = "__all__"` у `Meta` | `guard-api-access.py` | блок | **exit 2** |
| 3 | той самий ViewSet **з** `permission_classes` | `guard-api-access.py` | пропуск | **exit 0** |
| 4 | `Write` у `.env` | `protect-secrets.py` | блок | **exit 2** |
| 5 | `PEOPLEFORCE_API_KEY = "pf_live_..."` у `config.py` | `protect-secrets.py` | блок | **exit 2** |
| 6 | `rm -rf working_form/migrations/0003_*.py` | `guard-migrations.sh` | блок | **exit 2** |

Рядок 3 важливий не менше за рядки 1-2: гейт, що блокує коректний код, вимикають цілком, і
тоді він не ловить нічого. Тому в матрицях негативних випадків більше, ніж позитивних.

Приклад повідомлення (сценарій 1) - гейт називає причину і дає шлях далі, включно з opt-out:

```
Заблоковано: ./api/views.py додає API-клас без явних дозволів - CandidateViewSet.
У цьому репозиторії не заданий DEFAULT_PERMISSION_CLASSES, тому клас без власних дозволів
успадковує AllowAny: ендпоінт відкритий для будь-кого, і з коду самого класу цього не видно.
Що робити далі: додай permission_classes = [...] у тіло класу, або get_permissions(), якщо
набір залежить від self.action. Якщо клас успадковує базу з іншого модуля, яка вже несе
дозволи, познач це явно коментарем # noqa: api-guard у рядку оголошення класу.
```

**Крок F - поведінка на чужому репозиторії.** `deploy-audit.py` на не-Django проєкті:

```
SKIP compose-readiness no-compose-file
    У корені немає docker-compose.yaml - перевіряти нічого.
Разом: 0 RED, 0 YELLOW, 1 SKIP
```

Один SKIP, а не чотири - і це навмисно. Скрипт розрізняє **"не застосовно"** (перевірка не
про цей репозиторій - мовчить) і **"не зміг вирішити"** (SKIP - каже вголос). Репо без
`DatabaseScheduler` не отримує SKIP по розкладу Celery, бо там немає чого пропускати; а от
нечитабельний `settings.py` дав би SKIP, бо там рішення справді не ухвалене. Різниця в тому,
чи мовчання приховує ризик.

---

## Крок 8. Опис (пункт 8 завдання)

> Найскладніше було не те, що очікувалось. Синхронізацію версій між `plugin.json` і
> `marketplace.json` закрив десятирядковий `check-versions.py` за один захід; справжня
> проблема - **мовчазні зелені стани**. Smoke-install у CI не запускався жодного разу, бо
> `env` із секретом стояв на рівні кроку, а `if:` кроку обчислюється до матеріалізації його
> env - джоба була зелена й нічого не перевіряла. Так само перелік плагінів дублюється в
> **трьох** місцях (директорія, `marketplace.json`, `matrix.plugin` у workflow), і забутий
> третій не робить CI червоним: новий плагін просто ніколи не валідується. І найтихіше -
> закомічені `extraKnownMarketplaces` оголошують маркетплейс, але не встановлюють його:
> свіжий клон під ізольованим конфігом звітує `No plugins installed` без жодної помилки,
> тобто виглядає рівно як здоровий.
>
> З чотирьох curation-критеріїв ці плагіни виправдовують **Safety guardrail** і **Capture
> knowledge**. Safety guardrail буквальний: `django-guardrails` блокує запис у `.env` і
> команди, що знищують міграції (включно з тими, що ховаються за git-аліасом або всередині
> скрипта), а `drf-api-guard` ловить DRF-клас без `permission_classes` - у проєкті не
> заданий `DEFAULT_PERMISSION_CLASSES`, тож кожен забутий ViewSet відкритий за
> замовчуванням. Capture knowledge - у тому, що ці правила раніше жили в чужих головах і в
> код-ревʼю; тепер вони виконуваний код, який кусається однаково в усіх членів команди.
>
> Release cadence - **ad-hoc**. Плагіни тут це гейти, а не продукт: реліз має статися тоді,
> коли гейт змінив поведінку, і не має статися ніколи інакше. Календарний реліз або пушив
> би порожні бампи, або тримав виправлений гейт невиданим до п'ятниці.

---

## Додаток: цикл зміни гейта (три кроки, не один)

Установка - це **кешована копія**, а не симлінк, тому зміна в маркетплейсі не доїжджає сама:

```bash
# 1. у репо маркетплейсу: правка + бамп ОБОХ версій + пуш із тегом
# 2. оновити каталог (тільки каталог!)
claude plugin marketplace update evalforms-team-marketplace
claude plugin list          # усе ще показує СТАРУ версію - це нормально

# 3. оновити сам плагін; повне name@marketplace обов'язкове
claude plugin update django-guardrails@evalforms-team-marketplace --scope project

# 4. рестарт сесії - до нього працює стара копія
```

Кеш живе в `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` - **з директорією
версії**, тому шлях, скопійований із репо маркетплейсу, там не резолвиться. `update` лишає
попередню версію поруч із новою, отже **дві директорії під одним плагіном - норма** і нічого
не означають; подвоєння гейтів дає другий зареєстрований **маркетплейс**, а не другу
кешовану версію. І рядок `✔ updated ... Restart to apply` не є доказом, що файли переїхали -
доказ це матриця, запущена **з нової директорії версії**.

Щоб спробувати зміну до публікації, взагалі без релізу:

```bash
claude --plugin-dir ~/DRF_project/evalforms-team-marketplace/plugins/django-guardrails
```
