# Team marketplace: evalforms-team-marketplace

Винести плагіни Claude Code з `evaluation_form_service` в окремий публічний GitHub-репозиторій
із маніфестом, CI-валідацією і semver-дисципліною, щоб свіжий клон проєкту отримував гейти
без ручних кроків.

**done =** на чистій машині `git clone` проєкту плюс запуск `claude` дає trust-prompt, після
якого всі три плагіни встановлені й активні; CI в маркетплейсі зелений; тег `@1.0.0` у main.

---

## Таблиця припущень

| Припущення | Наслідок, якщо хибне |
|---|---|
| `extraKnownMarketplaces` у закоміченому `.claude/settings.json` дає trust-prompt при першому запуску | Дистрибуція повертається до «інструкція в Slack»; варіант A втрачає головну перевагу, треба перезважити проти варіанта B |
| `source` типу `github:AndriiRuhlyuk/evalforms-team-marketplace` резолвиться без токена для публічного репо | Команді потрібен PAT (персональний токен доступу) у кожного; додається крок налаштування, який ми намагалися прибрати |
| `claude plugin validate ./plugins/` існує і повертає ненульовий код на невалідному маніфесті | CI-джоба стає декоративною; треба писати власний валідатор JSON-схеми |
| `strict: true` у записі `plugins[]` не ламає установку, а лише посилює валідацію | Установка падає в команди; знімаємо прапорець і покладаємося тільки на CI |
| Хуки `django-guardrails` не мають прихованої залежності від шляхів `evaluation_form_service` | Після переїзду гейти мовчать у чужому репо; потрібен аудит кожного скрипта на абсолютні шляхи |
| `version` дублюється в `plugin.json` і `marketplace.json` без механізму синхронізації | Розсинхрон версій ловиться лише людиною; CI-інваріант обов'язковий, не опційний |
| GitHub Security Advisories доступні на публічному репо особистого акаунта | `SECURITY.md` втрачає приватний канал репорту; доведеться заводити реальну розсилку |

Позначені як припущення навмисно: жодне не перевірене емпірично на цій машині, окрім
останнього рядка попереднього розділу.

---

## Зафіксовані рішення

| Питання | Рішення | Чому |
|---|---|---|
| Аудиторія | Публічне репо, споживачі - автор і команда проєкту | Знімає маркетингові доки, лишає вимогу відтворюваності установки |
| Структура | Монорепо, `django-guardrails` переїжджає | Єдиний варіант, де свіжий клон отримує гейти одним закоміченим рядком |
| Назва репо | `evalforms-team-marketplace` | Не починається з зарезервованих `anthropic-`, `claude-code-`, `official-` |
| Owner | `owner.url` на репо, без email; репорти через GitHub Security Advisories | Особистий email у публічному JSON - фішинг-вектор і bus factor = 1 |
| Скоуп v1.0.0 | Три плагіни | Усі проходять 4-критерійний фільтр мінімум на 3/4 |

---

## Прогін через 4-критерійний фільтр

Плагін гідний маркетплейсу від 2 з 4. Менше - тримати в `~/.claude/` як особистий інструмент.

| Плагін | Pain real | Standardize | Capture knowledge | Safety guardrail | Разом |
|---|:---:|:---:|:---:|:---:|:---:|
| `django-guardrails` | так | так | так | так | 4/4 |
| `drf-api-guard` | так | так | так | так | 4/4 |
| `django-deploy-checklist` | так | так | так | ні | 3/4 |

Усі три беруть щонайменше 3/4.

---

## Структура репозиторію

```
evalforms-team-marketplace/
├── .claude-plugin/marketplace.json     # єдине джерело правди: власник і перелік плагінів
├── plugins/
│   ├── django-guardrails/              # переїзд, мінус три repo-specific хуки
│   ├── drf-api-guard/                  # блокує ViewSet без permission_classes і запис у серіалайзері
│   └── django-deploy-checklist/        # не дає релізити з непримененими міграціями і неповним .env
├── .github/
│   ├── CODEOWNERS                      # маршрутизує ревʼю кожного плагіна на відповідального
│   ├── PULL_REQUEST_TEMPLATE.md        # security-checklist: hooks, MCP, bin/, env, мережа, CVE
│   └── workflows/validate-plugins.yml  # ловить поламаний маніфест до того, як його встановить команда
├── README.md                           # шість секцій: що це / як додати / перелік / супровідники / контриб / контакти
├── SECURITY.md                         # процедура репорту вразливостей і SLA
└── CHANGELOG.md                        # Keep a Changelog, секція Breaking зверху
```

### `marketplace.json`

```json
{
  "name": "evalforms-team-marketplace",
  "owner": {
    "name": "Andrii Rykhliuk",
    "url": "https://github.com/AndriiRuhlyuk/evalforms-team-marketplace"
  },
  "plugins": [
    {
      "name": "django-guardrails",
      "source": "./plugins/django-guardrails",
      "description": "Deterministic quality gates for Django/DRF repos: blocks writes to .env and secret-shaped literals, asks before commands that can destroy migrations, keeps the realtime layer out of services.py, auto-formats with black, and scaffolds tests proven to bite by an AST mutation check.",
      "version": "1.0.0",
      "category": "quality-gates",
      "tags": ["django", "drf", "hooks", "testing", "secrets"],
      "author": { "name": "Andrii Rykhliuk" },
      "strict": true
    }
  ]
}
```

**Відхилення від зразка уроку - одне і свідоме:** в `owner` немає `email`. Урок ставить туди
розсилку, ми обрали GitHub Security Advisories як канал репорту. Валідатор це пропускає -
він перевіряє наявність `name`, `owner`, `plugins`, а не вміст `owner`. Те саме в `author`
кожного запису.

`category` і `tags` не перевіряються валідатором, але лишаються обов'язковими за вимогою
завдання. `version` мусить відповідати `^\d+\.\d+\.\d+$` - саме цей регекс стоїть у CI.

---

## Скоуп кожного плагіна

### `django-guardrails` (переїзд, без нової функціональності)

Їде як є: чотири хуки (`protect-secrets.py`, `guard-layering.py`, `guard-migrations.sh`,
`check-new-migrations.sh`, `format-python.sh`), дві команди (`/gate`, `/hooks-matrix`), скіл
`scaffold-tests` із мутаційною перевіркою.

**Що не їде.** Три хуки лишаються в `evaluation_form_service`, бо знають імена його додатків:
`check-layout-drift.sh`, `InstructionsLoaded`-логер, `reinject-context.sh` після compact.
Межа проходить там, де скрипт згадує `working_form` або `template_form`.

**Що видаляється з проєкту.** Кореневі `.claude-plugin/marketplace.json` і директорія
`django-guardrails/`. Якщо кореневий маніфест лишити, у команди буде два маркетплейси з
однойменним плагіном, і резолвитиметься доданий останнім - тихий баг, який виглядає як
«чому хук не спрацював».

### `drf-api-guard` (новий)

`PreToolUse` на `Write|Edit` для `**/views.py` і `**/serializers.py`:

- `ViewSet` або `APIView` без явного `permission_classes` - блокує з exit 2, бо в проєкті не
  заданий `DEFAULT_PERMISSION_CLASSES`, тобто дефолт відкритий;
- `fields = '__all__'` у `ModelSerializer` - блокує, бо нове поле моделі мовчки протікає в API;
- виклик `.save()`, `.create()`, `.update()` у методі серіалайзера, що не є `create`/`update` -
  попереджає, бо запис належить сервісному шару.

### `django-deploy-checklist` (новий)

Слеш-команда `/deploy-check`. Кроки: `manage.py check --deploy`; `showmigrations` проти
цільового середовища; повнота змінних оточення - звірка `.env.sample` зі зверненнями до
`os.environ` і `env()` у `settings.py`; наявність healthcheck у `docker-compose.yaml`; дрейф
розкладу `django-celery-beat` між кодом і БД. Вихід: зелений/жовтий/червоний із переліком
блокерів. Читає, не виконує деструктивних дій.

---

## Дистрибуція

`.claude/settings.local.json` проєкту зараз містить робочий, але немобільний блок:

```json
"extraKnownMarketplaces": {
  "evaluation-form-service": {
    "source": { "source": "directory", "path": "/Users/myda2/DRF_project/evaluation_form_service" }
  }
}
```

Абсолютний шлях існує лише на машині автора, а сам файл не в git. Міграція: блок переїжджає в
**закомічений** `.claude/settings.json` із джерелом `github:AndriiRuhlyuk/evalforms-team-marketplace`,
поруч `enabledPlugins` із трьома записами. Дев клонує, запускає `claude`, підтверджує
trust-prompt.

Для CI і Docker, де prompt неможливий, є `forcedPlugins` через managed settings - поза скоупом
цієї задачі, зафіксовано як відомий пробіл.

---

## CI

`.github/workflows/validate-plugins.yml`, тригери - `pull_request` і `push` у `main`.
Дві джоби, друга через `needs` чекає на першу.

### Джоба 1: `static-validate`

Inline-скрипт на `python3` без залежностей і без ключів. Перевіряє:

- у `marketplace.json` присутні `name`, `owner`, `plugins`;
- кожен запис `plugins[]` має `name`, `source`, `description`, `version`;
- `version` відповідає `^\d+\.\d+\.\d+$`.

Друкує `OK <n> plugins`. Падає на першому `assert`, повідомляючи, який саме запис поламаний.

### Джоба 2: `plugin-validate`

`needs: static-validate`, `strategy.matrix.plugin` із **явним переліком** директорій.
Кроки: `actions/checkout@v4`; установка CLI через `curl -fsSL https://claude.ai/install.sh |
bash -s stable` з додаванням `$HOME/.local/bin` у `$GITHUB_PATH`; `claude --version`;
`claude plugin validate ./plugins/${{ matrix.plugin }}` - без авторизації.

Smoke-install останнім кроком і **умовно**: `if: env.ANTHROPIC_API_KEY != ''`, всередині
`claude --plugin-dir ./plugins/${{ matrix.plugin }} --print "echo ready" || exit 1`.
Форк без секрету через це не червоніє.

### Наш додаток понад урок

Третій крок у `static-validate`: `version` у `plugins/<x>/.claude-plugin/plugin.json`
дорівнює `version` запису `<x>` у `marketplace.json`. В уроці цього немає, а розсинхрон між
двома JSON названий там найтоншим місцем - тож інваріант обов'язковий, не опційний.

---

## Governance і `SECURITY.md`

`CODEOWNERS` із маршрутом на кожен плагін, required reviews не менше одного, PR-шаблон із
security-checklist. Обґрунтування: плагіни виконуються з правами користувача, ізоляції немає,
сторонні маркетплейси Anthropic не валідує - тож ревʼю не може жити лише в документації.

Чекліст (у PR-шаблоні і в `SECURITY.md`):

```markdown
## Security checklist
- [ ] Чи додає PR хуки (PreToolUse/PostToolUse/Stop)? Опишіть, що саме перехоплюємо.
- [ ] Чи додає PR MCP-сервер? Опишіть зовнішні API і потрібні permissions.
- [ ] Чи додає PR файли у `bin/` або скрипти, що виконуються через `${CLAUDE_PLUGIN_ROOT}`?
- [ ] Чи читає плагін env vars з машини користувача? Перерахуйте.
- [ ] Чи робить плагін мережеві виклики? До яких хостів?
- [ ] Чи піднімає плагін привілеї (sudo, файли поза проектом)?
- [ ] Чи переглянуто залежності `package.json` / `requirements.txt` на CVE?
```

Плюс процедура репорту: приватний канал через GitHub Security Advisories і заявлений SLA.

---

## README: шість секцій

Що це / Як додати у Claude Code / Список плагінів / Супровідники / Як контрибʼютити /
Контакти. Дві з них мусять містити конкретику нижче.

### Update flow: дві ролі, дві дороги

| Supervisor (супровідник) | User (споживач) |
|---|---|
| 1. гілка | `/plugin update django-guardrails` |
| 2. зміни в плагіні | `✓ pulled 1.3.0` |
| 3. **bump version у двох JSON** | |
| 4. PR, CI зелений | `/plugin update --all` |
| 5. merge у main | `✓ всі плагіни до останньої` |
| 6. `git tag -a django-guardrails@1.3.0` | |

Головне, що має донести цей розділ: споживач **не знає** про теги, гілки й CI. Він просто
отримує оновлення на запит. Тег - контракт між двома сторонами, semver - мова цього контракту.

### Semver: який bump під яку зміну

| Рівень | Приклад | Що саме | Ризик |
|---|---|---|---|
| PATCH | `1.3.0 → 1.3.1` | правка в промпті, одруківка, no-op | близько нуля |
| MINOR | `1.3.1 → 1.4.0` | нова команда, новий скіл | новий код, старе працює |
| MAJOR | `1.4.0 → 2.0.0` | перейменування хука, видалення команди | ламає споживачів |

Правило одним рядком: вагаєшся - це MINOR; ламає - обов'язково MAJOR.

**Виправлення після емпіричної перевірки.** Раніше в цьому розділі стояло, що причина в піні
`^1.0.0`, який дотягує найвищу `1.x.x` і не переходить на `2.x` сам. Це семантика npm, і в
Claude Code її немає: `enabledPlugins` - це просто `name@marketplace: true`, а `plugin install`
не приймає версію. `/plugin update` тягне те, що маркетплейс оголошує в HEAD, включно з
мажорною зміною.

Справжній аргумент від цього стає **сильнішим**, а не слабшим: межу мажора не стереже жоден
механізм. Єдине, що бачить споживач перед оновленням, - номер версії й секція `### Breaking`
у `CHANGELOG.md`. Тобто semver тут людська конвенція, а не бар'єр, і дисципліна bump-ів -
єдине, що стоїть між чужим breaking change і робочим днем команди.

---

## Release cadence

**Ad-hoc.** Команда мала, споживач плагінів - вона сама, тижневий ритм створював би порожні
релізи. Continuous відпадає, бо кожен реліз вимагає ручного прогону
`/django-guardrails:hooks-matrix` - мис-вайрений гейт падає мовчки, і CI цього не бачить.

Сам flow і таблиця bump-рівнів - у розділі README вище; вони є частиною документації репо,
а не лише цієї спеки. `CHANGELOG.md` у форматі Keep a Changelog, секція `### Breaking` зверху.

---

## Порядок робіт

1. Створити репо `evalforms-team-marketplace`, каркас директорій, `marketplace.json` із одним
   записом.
2. Перенести `django-guardrails`, прогнати `hooks-matrix`, переконатися що гейти живі.
3. `README.md` (шість секцій), `SECURITY.md`, `CHANGELOG.md`, `CODEOWNERS`, PR-шаблон.
4. `validate-plugins.yml`: `static-validate` плюс `plugin-validate` з matrix, довести до
   зеленого. Перевірити, що невалідний маніфест справді робить джобу червоною - зелений CI,
   який нічого не ловить, гірший за його відсутність.
5. Мердж у main, тег `django-guardrails@1.0.0`.
6. Переключити `evaluation_form_service`: блок у `settings.json`, видалити кореневий
   `.claude-plugin/` і директорію плагіна, оновити `## Project Layout` і `## Commands`
   у `CLAUDE.md`.
7. Перевірка на чистій копії: `/plugin marketplace add github:AndriiRuhlyuk/evalforms-team-marketplace`,
   `/plugin install`, виклик команди через namespace.
8. Далі по одному: `drf-api-guard`, потім `django-deploy-checklist`. Кожен - окремий PR,
   окремий тег, власна матриця PASS/FAIL. При додаванні кожного - оновити **три** місця:
   директорію, запис у `marketplace.json` і список `matrix.plugin` у workflow.

---

## Ризики і непокриті edge cases

1. **Циклічна залежність репозиторіїв.** `evaluation_form_service` тягне гейти з маркетплейсу,
   а самі гейти розроблялися під цей проєкт. Зламаний реліз плагіна блокує роботу над кодом.
   Пом'якшення: локальний `--plugin-dir` під час розробки хука. Слабше, ніж здавалося на етапі
   планування: піну діапазоном у Claude Code немає, тож «залишитись на справній версії» не
   можна оголосити - лише не викликати `/plugin update`. Повністю не знімається.
2. **Історія при переїзді.** `git filter-repo` збереже blame, але перенесе й діффи, де могли
   бути шляхи та фрагменти конфігів. Копія без історії безпечніша, але blame втрачається.
   Рішення не прийнято.
3. **Trust-prompt недоступний у CI і Docker.** `forcedPlugins` вимагає прав адміністратора
   машини. Якщо CI має ганяти ті самі гейти - окрема задача.
4. **Дрейф між плагіном і `.claude/rules/`.** Правила лишаються в проєкті, гейти їдуть у
   маркетплейс. Розходження між текстом правила і поведінкою хука ніхто не ловить.
5. **Перелік плагінів дублюється тричі.** Директорія в `plugins/`, запис у `marketplace.json`
   і список `matrix.plugin` у workflow. Забутий третій пункт не робить CI червоним - джоба
   просто не запускається для нового плагіна, і він їде в реліз неперевіреним. Це та сама
   природа помилки, що й розсинхрон версій, тільки тихіша.

---

## Найскладніший момент

Синхронізація версій між двома JSON. `version` живе і в `plugins/<x>/.claude-plugin/plugin.json`,
і в записі `plugins[]` маніфесту, без жодного механізму зв'язку. Розсинхрон не ламає установку
голосно - плагін просто ставиться не тієї версії, ніж очікує споживач, і це виявляється тижнем
пізніше. Тому CI-інваріант на рівність версій обов'язковий, а не опційний.
