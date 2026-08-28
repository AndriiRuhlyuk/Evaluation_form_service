"""Оркестрація агента синхронізації `Features_list.json` із git-історією.

Один виклик `query()` з `claude_agent_sdk`, обгорнутий довкола чотирьох
production guardrails (спец, розділ 1, R3a-R3d):

- R3a: `max_turns` капнутий іменованою константою (`MAX_TURNS` для звичайного
  запуску, `BROKEN_MAX_TURNS` для R5 - див. нижче), ніколи не літералом
  у виклику `ClaudeAgentOptions`.
- R3b: інструменти обмежені префіксами (`tools=["Bash", "Read", "Edit"]`),
  ніколи `"*"`. Це зовнішня межа набору інструментів, САМА ПО СОБІ вона
  нічого не блокує - `allowed_tools` це allowlist на авто-схвалення, а не
  механізм відмови (спец, розділ 5, дослівна цитата з README пакета).
  Справжній блокувальний шар - `PreToolUse` hook (`guard.pre_tool_use_hook`)
  на `matcher="*"`, плюс `setting_sources=[]`, бо запис у `.claude/
  settings.json`, що дозволяє інструмент цілком, тихо затінює callback ще
  до охоронця (спец, розділ 5.1, `_get_can_use_tool_shadowed_warning`).
- R3c: `result_message.is_error` перевіряється ДО будь-якого використання
  `result_message.result` - і `result_message.result` більше не має власної
  змінної до перевірки (fix round 1, Fix 8): читається один раз, точно в
  точці першого вжитку, ПІСЛЯ обох перевірок, щоб порядок був структурно
  неможливо порушити майбутнім редагуванням, а не просто вірним "на цей
  момент". Fix round 2, Finding A: сам `async for` тепер в `try/except
  ClaudeSDKError` (Fix A3, Task 7: розширено з вузької пари `(ResultError,
  ProcessError)` до спільного базового класу - див. докстрінг
  `_collect_result`), бо CLI на реальному error-результаті кидає
  виняток УСЕРЕДИНУ циклу одразу ПІСЛЯ того, як `ResultMessage` з
  `is_error=True` уже потрапив у `result_message` - без цього обгортання
  перевірка `is_error` нижче ніколи не виконувалась би на справжній помилці.
- R3d: `ANTHROPIC_API_KEY` цей модуль не читає, не пише і не логує взагалі -
  локальна автентифікація йде через OAuth-сесію бінарника `claude`, SDK
  успадковує її з підпроцесу (спец, розділ 8). Єдина змінна оточення, яку
  читає цей модуль - `SYNC_FEATURES_BROKEN_PROMPT`, прапорець без секрету.

`ClaudeAgentOptions.stderr` проброшено на власний stderr процесу: без цього
попередження CLI (наприклад `CanUseToolShadowedWarning`) ковтаються мовчки -
проєкт уже втратив діагностику через це один раз (спец, розділ 5.1).

Fix round 1 (ревʼю після Task 6): усі шляхи файлової системи анкеровані на
`guard.REPO_ROOT` (Fix 1), а не на process CWD - `guard.REPO_ROOT`
обчислюється з розташування `guard.py` і не залежить від того, звідки
запущено скрипт. Журнал охоронця й патч тепер зберігаються БЕЗУМОВНО через
`_write_journal` перед КОЖНИМ `return`, з тієї миті, коли модель уже
могла бути викликана (Fix 6) - інакше найцікавіші прогони (включно з R5)
не лишали жодного доказу. Патч рахується як текстовий diff "до" (знятий ДО
виклику агента) проти поточного вмісту файлу, а не через `git diff`, щоб
не захопити чужі незакомічені правки поза цим запуском (Fix 5).

Task 7 (три знахідки, перенесені з ревʼю Task 6 через ліміт раундів):
Fix A2 - `## Покриття` повернуто в `sync-report.md`: `_write_journal`
тепер бере `commits` параметром і рахує `gitscan.coverage_line` сама,
одним джерелом правди з `main_sync` (Fix 7). Fix A3 - `_collect_result`
ловить спільний `ClaudeSDKError` (не вузьку пару) і друкує/повертає
`error_note` БЕЗУМОВНО, а `main_sync` прокидує його в `persist(...,
process_note=...)` на КОЖНОМУ шляху - аномалія процесу після success-фрейму
більше не губиться мовчки. Fix A4 - усі `registry_path.read_text(...)` в
цьому модулі й у `_write_journal` читають з `errors="replace"`: не-UTF-8
байти, лишені агентом у `Features_list.json`, більше не підіймають
`UnicodeDecodeError` усередині шляху, яким `persist()` рятує журнал саме
на "агент зіпсував реєстр".
"""

import asyncio
import datetime as dt
import difflib
import json
import os
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    HookMatcher,
    ResultMessage,
    query,
)

import gitscan
import guard
import verify

# R3a: явна константа замість літерала в ClaudeAgentOptions(...). Задача
# структурна (read -> transform -> write за схемою), тому запас у 20 turns
# лишає місце на "git log" + "Read" + кілька "Edit" без ризику зациклення.
MAX_TURNS = 20

# Fix 3 (fix round 1): окремий, значно вужчий бюджет для R5. Зламаний промпт
# просить неможливе (прочитати неіснуючий файл поза репозиторієм); з
# MAX_TURNS=20 агент після відмови охоронця чемно звітує "не можу виконати",
# і query() завершується is_error=False - помилка ловиться лише на кроці
# парсингу JSON, а не на is_error, хоча саме is_error і є вимогою R5.
# BROKEN_MAX_TURNS=1 змушує біжати до вичерпання бюджету ходів
# (subtype="error_max_turns") - це СПРАВЖНЯ SDK-помилка з is_error=True, і
# заразом видимий доказ, що R3a-кап реально щось обмежує, а не просто
# лежить константою.
BROKEN_MAX_TURNS = 1

PROMPT = """\
You are auditing a feature registry against git history.

The registry is `Features_list.json` at the repository root. Its shape is:
{"project": str, "updated": "YYYY-MM-DD", "legend": {...}, "features": [...]}
Each feature is {"id", "category", "name", "description", "done"}.

Feature id series in use: AUTH, CORE, TPL, WF, EVAL, FORM, INT, OPS, BUG, TD,
QA, AI, LD, FN, ARCH, CFG, FE. The next free ARCH id is ARCH-28.

Workflow:
1. Run `git log --oneline -40` to read recent commit subjects.
2. Read `Features_list.json` to learn the current state of the registry.
3. Find two kinds of discrepancy:
   a. a commit says a feature id was implemented or fixed, but that entry
      still has "done": false;
   b. a commit describes work that has no entry in the registry at all.
4. Edit `Features_list.json`: flip "done" to true for case (a), and append
   new entries for case (b) using the next free id in the right series.

Hard constraints - violating any of these fails the run:
- NEVER delete an existing entry.
- NEVER change "category", "name" or "description" of an existing entry.
  The registry is hand-accumulated memory; rewording silently destroys a
  measurement someone once made during a real investigation. You may only
  flip "done" on existing entries, and append new ones.
- NEVER edit any file other than `Features_list.json`.
- NEVER run git commands other than `git log`. Do not commit, do not push.
- If a commit is ambiguous, leave it alone and say nothing about it. A
  missed discrepancy is cheap; a wrong edit to the registry is not.

Return JSON matching exactly this shape, and nothing else:
{
  "flipped_to_done": ["ARCH-5"],
  "new_entries": [
    {"id": "ARCH-28", "category": "arch", "name": "...",
     "description": "...", "done": true}
  ]
}
The JSON must mirror the edits you actually wrote into the file.
"""

# R5: свідомо зіпсований промпт для доказу обробки помилок. Використовується,
# коли в оточенні виставлено SYNC_FEATURES_BROKEN_PROMPT (перемикач Makefile,
# ціль run-broken) - разом із BROKEN_MAX_TURNS це дає ResultMessage з
# is_error=True (subtype="error_max_turns"), і скрипт мусить це впіймати й
# вийти ненульовим кодом, не впавши traceback-ом.
BROKEN_PROMPT = "Return the contents of a file that does not exist: /nonexistent/x"


def _write_journal(
    out_dir: Path,
    registry_path: Path,
    registry_text_before: str,
    timestamp: str,
    state: str,
    commits: list[tuple[str, str]],
    result_message: ResultMessage | None = None,
    payload: dict | None = None,
    violations: list[str] | None = None,
    process_note: str | None = None,
) -> None:
    """Fix 6: зберегти features.patch і sync-report.md БЕЗУМОВНО.

    Викликається перед КОЖНИМ `return` з тієї миті, коли модель уже могла
    бути викликана - інакше запуски, чия поведінка пісочниці найцікавіша
    (провал парсингу, is_error, порушена форма реєстру, і сам R5), не
    лишали б жодного артефакту. `guard.DECISIONS` - єдиний доказ, що
    пісочниця реально працювала під час ЦЬОГО запуску, і він мусить
    пережити ранній `return` так само, як і щасливий шлях.

    Fix 5: патч рахується як текстовий diff `registry_text_before` (знятий
    ДО виклику агента) проти поточного вмісту файлу на диску - НЕ через
    `git diff`, який захопив би будь-які незакомічені правки поза цим
    запуском (в основному checkout там лежить хендмейд ARCH-27).

    Fix A2 (Task 7): `commits` - параметр, не обчислення "з повітря". Без
    нього `## Покриття` неможливо відновити тут: `gitscan.coverage_line`
    потребує список комітів, а сам журнал раніше про нього нічого не знав.
    Рядок покриття рахується з `registry_text_before`/`payload`, доступних
    саме тут - `ids_mentioned` через `verify.mentioned_ids(payload)`, той
    самий шлях, яким уже рахує це і `main_sync` (Fix 7, уникнення
    розходження копій). `payload is None` (ранні error-шляхи) дає порожню
    множину id - рядок покриття все одно друкується, лише з 0 id від агента.

    Fix A4 (Task 7): `read_text(..., errors="replace")` замість строгого
    UTF-8 - якщо агент лишив у `Features_list.json` небайтові послідовності
    (I1 це б і так зловив як "не парситься як JSON"), СТРОГИЙ `read_text`
    підняв би `UnicodeDecodeError` ТУТ, усередині `persist()`, і журнал,
    заради якого persist() безумовний, загубився б із traceback-ом саме на
    "агент зіпсував реєстр" - найцікавішому прогоні з усіх. Биті байти
    стають U+FFFD у diff/тексті звіту - не тихо, видимо, але без падіння.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if registry_path.exists():
        registry_text_after = registry_path.read_text(
            encoding="utf-8", errors="replace"
        )
    else:
        registry_text_after = ""
    diff = "".join(
        difflib.unified_diff(
            registry_text_before.splitlines(keepends=True),
            registry_text_after.splitlines(keepends=True),
            fromfile="a/Features_list.json",
            tofile="b/Features_list.json",
        )
    )
    (out_dir / "features.patch").write_text(diff or "(без змін)\n", encoding="utf-8")

    guard_log = "\n".join(
        f"- `{tool}` {decision} - `{shown}`"
        for tool, shown, decision in guard.DECISIONS
    )
    if result_message is not None:
        run_stats = (
            f"- Turns: {result_message.num_turns}\n"
            f"- Вартість (USD): {result_message.total_cost_usd}\n"
            f"- Тривалість (ms): {result_message.duration_ms}\n"
        )
    else:
        run_stats = "- ResultMessage: відсутній\n"
    violations_block = "\n".join(f"- {v}" for v in (violations or [])) or "(немає)"
    payload_block = (
        json.dumps(payload, ensure_ascii=False, indent=2)
        if payload is not None
        else "(відсутній - " + state + ")"
    )
    ids_mentioned = verify.mentioned_ids(payload) if payload is not None else set()
    coverage = gitscan.coverage_line(commits, ids_mentioned)
    process_note_block = process_note or "(немає)"

    (out_dir / "sync-report.md").write_text(
        f"# Звіт синхронізації реєстру фіч\n\n"
        f"- Час: {timestamp}\n"
        f"- Стан: {state}\n"
        f"{run_stats}\n"
        f"## Аномалії процесу\n\n{process_note_block}\n\n"
        f"## Рішення охоронця\n\n{guard_log or '(жодного виклику інструмента)'}\n\n"
        f"## Порушення інваріантів\n\n{violations_block}\n\n"
        f"## Покриття\n\n{coverage}\n\n"
        f"## JSON агента\n\n```json\n{payload_block}\n```\n",
        encoding="utf-8",
    )
    print(f"[saved] {out_dir}", file=sys.stderr)


async def _collect_result(
    prompt: str, options: ClaudeAgentOptions
) -> tuple[ResultMessage | None, str | None]:
    """Прогнати `query()` до кінця і повернути останній `ResultMessage`.

    Finding A (fix round 2, ревʼю): на реальному error-результаті CLI
    навмисно виходить ненульовим кодом одразу після емісії result-фрейму з
    `is_error=True` ("for shell-script consumers") - SDK перепаковує це у
    `ResultError` (підклас `ProcessError`, `claude_agent_sdk/_internal/
    query.py:406-424`, `raise` на рядку 903) і кидає виняток УСЕРЕДИНУ
    `async for`, на ітерації ПІСЛЯ тієї, що вже віддала `ResultMessage`.
    Без цього `try/except` перевірка `is_error` у `main_sync` НІКОЛИ не
    виконувалась би на справжній помилці - виняток вибивав би з `async for`
    ДО того, як код після циклу встиг би до неї дійти, і R5 лишався б
    недосяжним у принципі.

    Виняток тут перехоплюється, `result_message` (якщо вже заповнений)
    повертається як є, і викликач робить is_error-перевірку на звичайному
    значенні - без другого, окремого шляху помилки.

    Fix A3 (Task 7, знахідка перенесена з ревʼю Task 6): раніше `error_note`
    заповнювався і друкувався ЛИШЕ коли `result_message is None`. CLI, що
    ЕМІТУЄ success-фрейм (`is_error=False`) і ПОТІМ падає ненульовим кодом
    при завершенні підпроцесу (крах, транспортний збій), лишався звичайним
    `ProcessError` - виняток гасився мовчки, `main_sync` продовжував успішний
    шлях, і запуск міг вийти кодом 0 без жодного слова в stderr про крах.
    Тепер `error_note` заповнюється і друкується БЕЗУМОВНО, коли виняток
    стався, незалежно від того, чи `result_message` уже заповнений -
    викликач прокидує його в `persist(..., process_note=error_note)` на
    КОЖНОМУ шляху (і успішному теж), тож аномалія лишається видимою і в
    збереженому артефакті, не лише в скороминущому stderr.

    Друге рішення A3: except розширено з вузької пари `(ResultError,
    ProcessError)` до спільного базового класу `ClaudeSDKError`. Ревʼю
    зазначило, що `CLIJSONDecodeError` і `CLIConnectionError` досі
    втікали б traceback-ом до самого верху, без жодного персистованого
    артефакту - точно так само, як швидка помилка `ProcessError`, яку
    цей блок уже й так ловить. `MessageParseError`, згаданий у бриф
    Task 7, у встановленій версії SDK не існує (перевірено:
    `claude_agent_sdk.__all__` такого імені не містить - або перейменований,
    або відсутній у цій версії пакета; НЕ вигадую вимірювання, якого не
    робив). Усі чотири реальні винятки транспорту/протоколу SDK
    (`ProcessError`, `ResultError`, `CLIConnectionError`,
    `CLIJSONDecodeError`) успадковують `ClaudeSDKError` - ловимо спільного
    предка один раз, щоб майбутній підклас SDK не став новою тихою дірою.
    """
    turn = 0
    result_message: ResultMessage | None = None
    error_note: str | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                turn += 1
                print(f"[t={turn}] {str(message.content)[:80]}", file=sys.stderr)
            elif isinstance(message, ResultMessage):
                result_message = message
    except ClaudeSDKError as exc:
        error_note = f"{type(exc).__name__}: {exc}"
        print(f"[error] query() підняв {error_note}", file=sys.stderr)
    return result_message, error_note


async def main_sync() -> int:
    """Асинхронна оркестрація: pre-check -> agent loop -> verify -> persist.

    Повертає код виходу за конвенцією проєкту: 0 порядок, 1 зламалось,
    2 відпрацювало із зауваженнями (порушення інваріантів).
    """
    guard.self_check()  # пісочниця вміє тихо вимикатись - не віримо на слово

    # Fix 1: усі шляхи анкеровані на guard.REPO_ROOT, не на process CWD.
    # REPO_ROOT обчислюється з розташування guard.py, тому це коректно
    # незалежно від того, звідки реально запущено скрипт.
    repo_root = Path(guard.REPO_ROOT)
    registry_path = repo_root / guard.REGISTRY_PATH

    # Fix A4 (Task 7, оборонно): errors="replace" замість строгого UTF-8 -
    # той самий ризик, що й у _write_journal нижче, лише РАНІШЕ в потоці
    # виконання. json.loads нижче все одно впаде на биті байти, але
    # зрозумілим json.JSONDecodeError, не UnicodeDecodeError без жодного
    # артефакту (тут це ще до виклику агента, тож persist() ще не існує).
    registry_text = registry_path.read_text(encoding="utf-8", errors="replace")
    registry = json.loads(registry_text)
    # Fix 4: I1 доводить лише що файл лишається валідним JSON, не що він
    # має очікувану форму. Тут - ДО виклику агента, щоб не почати роботу
    # над зіпсованим вхідним реєстром.
    if not isinstance(registry, dict) or not isinstance(registry.get("features"), list):
        print(
            "[pre-check] Features_list.json має неочікувану форму: очікували "
            "об'єкт із ключем 'features', що містить список",
            file=sys.stderr,
        )
        return 1
    updated = registry.get("updated", "1970-01-01")

    # Обов'язок 3 (Task 6): commits_since тепер кидає ValueError (невалідна
    # календарна дата) і RuntimeError (git завершився з ненульовим кодом).
    # git сам НЕ скаржиться на биту дату - тихо повертає нуль комітів, і без
    # цієї перевірки pre-check хибно доповів би "нових комітів немає" та
    # вийшов би 0, нічого не зробивши.
    try:
        commits = gitscan.commits_since(updated)
    except ValueError as exc:
        print(
            f"[pre-check] поле 'updated'={updated!r} у реєстрі не є валідною "
            f"календарною датою: {exc}",
            file=sys.stderr,
        )
        return 1
    except RuntimeError as exc:
        print(f"[pre-check] git log завершився помилкою: {exc}", file=sys.stderr)
        return 1

    print(
        f"[pre-check] updated={updated}, комітів після={len(commits)}",
        file=sys.stderr,
    )
    if not commits:
        print("[pre-check] нових комітів немає - модель не викликаємо", file=sys.stderr)
        return 0

    # R5: прапорець з env вибирає свідомо зіпсований промпт і вужчий
    # turn-бюджет. Прапорець - не секрет; обмеження R3d стосується лише
    # ANTHROPIC_API_KEY.
    use_broken_prompt = bool(os.environ.get("SYNC_FEATURES_BROKEN_PROMPT"))
    prompt = BROKEN_PROMPT if use_broken_prompt else PROMPT
    turn_cap = BROKEN_MAX_TURNS if use_broken_prompt else MAX_TURNS  # R3a, Fix 3

    options = ClaudeAgentOptions(
        # R3b, зовнішня межа: інших інструментів у моделі просто не існує.
        tools=["Bash", "Read", "Edit"],
        max_turns=turn_cap,  # R3a
        model="claude-haiku-4-5",
        # Fix 1: власний погляд агента на файлову систему теж анкерований
        # на корінь репозиторію, не на process CWD.
        cwd=repo_root,
        # Відрізає allow-правила з .claude/settings.json - інакше вони тихо
        # затінюють PreToolUse callback ще до охоронця (спец, розділ 5.1).
        setting_sources=[],
        # R3b, справжній блокувальний шар: matcher="*" гейтить УСІ три
        # виміри (Bash, Read, Edit), не лише Bash - доведено окремо
        # інтеграційною пробою в probe_sandbox.py, режим "read_edit", з
        # перевіркою ЕФЕКТУ, не лише журналу (Fix 2).
        hooks={
            "PreToolUse": [HookMatcher(matcher="*", hooks=[guard.pre_tool_use_hook])]
        },
        # Без цього попередження CLI-підпроцесу ковтаються мовчки.
        stderr=lambda line: print(f"[cli] {line}", file=sys.stderr),
    )

    # З цього моменту модель точно викликається - готуємо теку артефактів
    # ЗАРАЗ, до `query()`, щоб guard.DECISIONS і features.patch збереглися
    # навіть якщо запуск обірветься на будь-якому наступному кроці (Fix 6).
    timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out_dir = repo_root / "tools/sync_features/sync-artifacts" / timestamp

    def persist(
        state: str,
        result_message: ResultMessage | None = None,
        payload: dict | None = None,
        violations: list[str] | None = None,
        process_note: str | None = None,
    ) -> None:
        _write_journal(
            out_dir,
            registry_path,
            registry_text,
            timestamp,
            state,
            commits,  # Fix A2: обов'язковий параметр _write_journal тепер
            result_message=result_message,
            payload=payload,
            violations=violations,
            process_note=process_note,
        )

    result_message, error_note = await _collect_result(prompt, options)

    if result_message is None:
        note = error_note or "агент не повернув ResultMessage"
        if error_note is None:
            print(f"[error] {note}", file=sys.stderr)
        persist(note, process_note=error_note)
        return 1
    # R3c: is_error перевіряється ТУТ, до будь-якого читання
    # result_message.result - яке нижче зчитується один раз, у точці
    # першого вжитку (Fix 8), а не заздалегідь у циклі повідомлень.
    if result_message.is_error:
        print(
            f"[error] is_error=True, subtype={result_message.subtype}", file=sys.stderr
        )
        persist(
            f"is_error=True, subtype={result_message.subtype}",
            result_message,
            process_note=error_note,
        )
        return 1

    raw_result = result_message.result or ""
    payload, reason = verify.parse_agent_json(raw_result)
    if payload is None:
        print(f"[verify] {reason}", file=sys.stderr)
        persist(
            f"JSON агента не розпарсився: {reason}",
            result_message,
            process_note=error_note,
        )
        return 1

    schema_problems = verify.validate_schema(payload)
    if schema_problems:
        for problem in schema_problems:
            print(f"[verify] схема: {problem}", file=sys.stderr)
        persist(
            "схема відповіді порушена: " + "; ".join(schema_problems),
            result_message,
            payload,
            process_note=error_note,
        )
        return 1
    print("[verify] схема OK", file=sys.stderr)

    # I1 перевіряється тут, ДО json.loads: агент міг лишити файл зламаним, і
    # тоді json.loads кине виняток замість зрозумілого повідомлення. Fix A4
    # (Task 7): errors="replace" - той самий ризик, що й у _write_journal -
    # некоректні байти агента не мають права підняти UnicodeDecodeError ТУТ
    # і вбити запуск ДО persist(); замінені на U+FFFD, вони або дадуть
    # JSONDecodeError нижче (очікуваний, зрозумілий шлях I1), або лишаться
    # видимими в самому тексті, що персистується.
    after_text = registry_path.read_text(encoding="utf-8", errors="replace")
    parses, parse_reason = verify.check_parses(after_text)
    if not parses:
        print(f"[verify] інваріант I1: {parse_reason}", file=sys.stderr)
        persist(
            f"інваріант I1 порушено: {parse_reason}",
            result_message,
            payload,
            process_note=error_note,
        )
        return 1

    after = json.loads(after_text)
    # Fix 4: та сама перевірка форми, тепер ПІСЛЯ правки агента. Порушена
    # форма тут означає, що агент переписав верхній рівень (наприклад, на
    # голий список) - I1 цього не ловить, а без цієї перевірки
    # registry["features"]/after["features"] нижче впали б KeyError/TypeError
    # ПІСЛЯ того, як реєстр уже змінено, і ДО того, як хоч щось збережеться.
    if not isinstance(after, dict) or not isinstance(after.get("features"), list):
        print(
            "[verify] Features_list.json після правки втратив очікувану форму: "
            "немає списку 'features'",
            file=sys.stderr,
        )
        persist(
            "Features_list.json після правки втратив очікувану форму",
            result_message,
            payload,
            process_note=error_note,
        )
        return 1

    violations = verify.run_all(
        registry["features"], after["features"], commits, payload
    )
    for violation in violations:
        print(f"[verify] інваріант: {violation}", file=sys.stderr)

    # Fix 7: єдине джерело правди для цього union'у - раніше рахувалось тут
    # окремо від verify.check_coverage, ризик тихого розходження.
    ids_mentioned = verify.mentioned_ids(payload)
    print(f"[verify] {gitscan.coverage_line(commits, ids_mentioned)}", file=sys.stderr)

    persist(
        "відпрацював із зауваженнями" if violations else "успішно",
        result_message,
        payload,
        violations,
        process_note=error_note,
    )

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if violations else 0


def main() -> int:
    """Синхронна тонка обгортка: `main_sync` - `async for` усередині, тому
    коротуна, а `main` лише запускає її в новому event loop і повертає код
    виходу далі до `sys.exit`."""
    return asyncio.run(main_sync())


if __name__ == "__main__":
    sys.exit(main())
