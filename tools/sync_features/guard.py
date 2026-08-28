"""Охоронець дозволів для sync_features.

`allowed_tools` у claude-agent-sdk нічого не блокує (див. docs/plans/2026-08-28-
sdk-sync-features-spec.md, розділ 5.1) - реальна межа пісочниці це PreToolUse
hook. `guard_decision` - чиста функція без побічних ефектів, її можна вільно
викликати з тестів; журнал `DECISIONS` наповнює лише hook-обгортка.

Fix round 1: чорний список символів для `Bash` сам собою не закриває опції
програми, яку дозволено запускати (`git log --output=<file>` пише довільний
файл). Правило `Bash` двошарове: (1) заборонені символи на сирому рядку,
(2) токенізація через `shlex` + білий список опцій `git log`. Шляхи для
`Read`/`Edit` нормалізуються відносно кореня репозиторію через
`os.path.realpath`, бо інструмент `Read` завжди передає абсолютний шлях.

Fix round 2: (1) шар 2 з round 1 перевіряв лише токени, що починаються з
"-" - позиційний токен `$'\\x2d\\x2doutput=...'` (ANSI-C quoting bash, що
розкриває escape-послідовності в `--output=...` ще до запуску git) минав
перевірку мовчки. Тепер валідується КОЖЕН токен, а "$" заборонено цілком на
рівні символів. (2) `try` у hook раніше не покривав логування - падіння
`print`/`.append` вибивало виняток із hook, і SDK не отримувало жодного
рішення. (3) `.git/services.py` проходив як "рівно один /", хоча каталог
службовий.

Fix round 3 (Task 6, обов'язок 1): `DECISIONS.append` у попередній версії
відбувався ВСЕРЕДИНІ `try`, ДО `print`. Якщо `print` падав (наприклад
зламаний stderr), виняток ловився в `except`, hook повертав deny, але
журнал уже встиг записати ALLOW - до винятку. `DECISIONS` - єдиний доказ у
звіті `sync_features.py`, що пісочниця реально працювала під час запуску;
журнал, що бреше, гірший за відсутність журналу. Тепер `tool_name` і
`tool_input` читаються безпечно ДО `try` (без ризику винятку), а
`DECISIONS.append` відбувається ПІСЛЯ `try/except` - завжди з фінальним
`allowed`, яке й повертається SDK.
"""

import os
import re
import shlex
import sys

REGISTRY_PATH = "Features_list.json"

# "$" заборонено цілком (не лише "$("), бо жоден сценарій git log не
# потребує долара - це закриває $'...' (ANSI-C quoting), ${...}, $VAR одним
# рухом. Лапки заборонені так само: якщо модель формує командний рядок з
# лапками, це ознака спроби щось приховати, а не легального використання.
_FORBIDDEN_SUBSTRINGS = (";", "&", "|", "`", "$", ">", "<", "\n", "'", '"')

# Опції `git log`, дозволені як окремий токен.
_ALLOWED_EXACT_OPTS = {
    "--oneline",
    "--no-merges",
    "--name-only",
    "--no-color",
    "--reverse",
    "--",  # pathspec separator: "git log -- <file>"
    "-n",
}
_ALLOWED_OPT_PREFIXES = (
    "--since=",
    "--until=",
    "--max-count=",
    "--format=",
    "--pretty=",
    "--grep=",
)

# Безпечний позиційний токен (ref, шлях, число після "-n"): лише
# буквено-цифрові символи і вузький набір знаків, типових для git-refs і
# шляхів у цьому репозиторії. Усе поза цим - відмова.
_SAFE_POSITIONAL = re.compile(r"^[A-Za-z0-9._/~^-]+$")

# Корінь репозиторію: guard.py лежить у tools/sync_features/, тому два рівні
# вгору від його директорії - корінь (де лежить Features_list.json).
_GUARD_DIR = os.path.dirname(os.path.realpath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_GUARD_DIR))

DECISIONS: list[tuple[str, str, str]] = []


def _is_allowed_git_log_option(token: str) -> bool:
    """Токен-опція (виклик уже гарантує token.startswith("-")) - у білому списку чи ні."""
    if token in _ALLOWED_EXACT_OPTS:
        return True
    if any(token.startswith(prefix) for prefix in _ALLOWED_OPT_PREFIXES):
        return True
    # форма "-<число>", наприклад "-40"
    if token[1:].isdigit():
        return True
    return False


def _check_bash(command: str) -> tuple[bool, str]:
    """Команда дозволена лише як `git log`: кожен токен - опція з білого
    списку або безпечний ref/шлях. Нічого не проходить «за замовчуванням» -
    round 1 валідував лише токени, що починаються з "-", і позиційний токен
    з ANSI-C quoting ($'\\x2d\\x2doutput=...') минав перевірку саме тому, що
    після розкриття bash-ом не виглядав як опція."""
    # шар 1: заборонені символи на сирому рядку, до розбору
    for bad in _FORBIDDEN_SUBSTRINGS:
        if bad in command:
            return False, f"команда містить заборонений символ {bad!r}"

    # шар 2: токенізація і перевірка КОЖНОГО токена, не лише опційних
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return False, f"команду не вдалось розібрати: {exc}"

    if len(tokens) < 2 or tokens[0] != "git" or tokens[1] != "log":
        return False, f"команда {command!r} не починається з 'git log'"

    for token in tokens[2:]:
        if token.startswith("-"):
            if not _is_allowed_git_log_option(token):
                return False, f"опція {token!r} поза білим списком git log"
        elif not _SAFE_POSITIONAL.match(token):
            return False, f"аргумент {token!r} не відповідає безпечному патерну"

    return True, "git log з опціями та аргументами з білого списку"


def _normalised(tool_input: dict) -> str | None:
    """Шлях відносно REPO_ROOT, або None якщо шлях недопустимий чи поза коренем.

    Відносний шлях приєднується до REPO_ROOT, абсолютний лишається як є -
    обидва потім проганяються через `os.path.realpath` (розкриває симлінки,
    прибирає "..") і перевіряються на приналежність до REPO_ROOT через
    `os.path.commonpath`.
    """
    raw = tool_input.get("file_path", "")
    if not isinstance(raw, str) or not raw:
        return None
    candidate = raw if os.path.isabs(raw) else os.path.join(REPO_ROOT, raw)
    resolved = os.path.realpath(candidate)
    # REPO_ROOT і resolved завжди абсолютні непорожні шляхи на POSIX, тому
    # os.path.commonpath тут ValueError не кидає - перевіряти немає сенсу.
    if os.path.commonpath([REPO_ROOT, resolved]) != REPO_ROOT:
        return None
    return os.path.relpath(resolved, REPO_ROOT)


def _is_services_path(path: str) -> bool:
    """Рівно `<app>/services.py`: один рівень вкладеності, і жоден із двох
    сегментів не службовий каталог (`.git`, `.venv`, `.claude`, ...)."""
    if path.count("/") != 1 or not path.endswith("/services.py"):
        return False
    return not any(segment.startswith(".") for segment in path.split("/"))


def guard_decision(tool_name: str, tool_input: dict) -> tuple[bool, str]:
    if not isinstance(tool_input, dict):
        return False, "tool_input не є словником"

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if not isinstance(command, str):
            return False, f"command не є рядком: {command!r}"
        return _check_bash(command)

    if tool_name == "Read":
        path = _normalised(tool_input)
        if path is None:
            return False, "шлях порожній, невалідний або поза коренем репозиторію"
        if path == REGISTRY_PATH or _is_services_path(path):
            return True, f"{path} у списку читабельних"
        return False, f"{path} поза списком читабельних"

    if tool_name == "Edit":
        path = _normalised(tool_input)
        if path != REGISTRY_PATH:
            return False, f"редагувати дозволено лише {REGISTRY_PATH}, не {path!r}"
        return True, f"{REGISTRY_PATH} - єдиний дозволений до правки файл"

    return False, f"інструмент {tool_name!r} поза трьома дозволеними вимірами"


async def pre_tool_use_hook(input_data, tool_use_id, context) -> dict:
    """PreToolUse hook: SDK консультує її перед КОЖНИМ викликом інструмента.

    Fix round 2 (NEW-2): усе тіло - обчислення рішення, запис у DECISIONS,
    друк у stderr - в одному try/except. У round 1 `try` закінчувався до
    логування, тому падіння `print` чи `.append` вибивало виняток із hook
    без жодного результату: SDK ловить його сам, і CLI не отримує ні allow,
    ні deny. Тепер будь-який збій на будь-якому кроці перетворюється на deny.

    Fix round 3 (Task 6, обов'язок 1): `DECISIONS.append` перенесено ПІСЛЯ
    `try/except`, щоб журнал завжди відображав ФІНАЛЬНЕ `allowed` - те саме,
    що йде в повернене hookSpecificOutput. Раніше запис лягав у DECISIONS
    ДО print, тому падіння print лишало в журналі ALLOW, хоча SDK реально
    отримувало deny. `tool_name`/`tool_input` читаються safe-геттерами до
    try, бо сам `input_data.get(...)` може впасти, якщо input_data не dict
    (наприклад None) - це не повинно завадити журналу зафіксувати рішення.

    Fix E (Task 7, ревʼю раунд 1): `DECISIONS` зберігає ПОВНИЙ `repr(
    tool_input)`, БЕЗ обрізання. Раніше `repr(tool_input)[:120]` обрізався
    ТУТ, у місці запису - контролер виміряв живий прогін, де repr довжиною
    126 символів обрізався до 120 і губив хвіст `services.py` (лишалось
    `...working_form/service`), через що `probe_sandbox._journal_denied`
    (звіряє журнал за РІВНІСТЮ repr) не знаходив відповідного запису й
    видавав FAIL там, де денайл реально стався. Обрізання - вимога
    ВІДОБРАЖЕННЯ (рядок звіту має бути читабельним), а не зберігання;
    журнал у пам'яті нічого не виграє від короткого рядка, натомість
    програмна звірка отримує спотворені дані. Обрізання тепер лише в
    точці РЕНДЕРУ - `sync_features._write_journal` (`guard_log`) і
    `probe_sandbox._short_repr` для власних print-рядків.
    """
    tool_name = input_data.get("tool_name", "") if isinstance(input_data, dict) else ""
    tool_input = (
        input_data.get("tool_input", {}) if isinstance(input_data, dict) else {}
    )

    try:
        allowed, reason = guard_decision(tool_name, tool_input)
        print(
            f"[guard] {'ALLOW' if allowed else 'DENY '} {tool_name} - {reason}",
            file=sys.stderr,
        )
    except Exception as exc:  # межа безпеки: будь-який збій -> deny, без винятку
        allowed, reason = False, f"охоронець впав з винятком: {exc!r}"

    DECISIONS.append((tool_name, repr(tool_input), "ALLOW" if allowed else "DENY"))

    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow" if allowed else "deny",
            "permissionDecisionReason": reason,
        }
    }


def self_check() -> None:
    """Відмовитись стартувати, якщо правила охоронця зламані.

    Пісочниця вміє тихо вимикатись (спец, 5.1), тому конфігурації не
    вірять на слово: контрольні рішення перевіряються на кожному запуску.

    Fix round 2: REPO_ROOT виводиться суто з розташування guard.py, тому
    переміщення файла тихо перевело б усю нормалізацію шляхів на інше
    дерево - жоден з інших тестів цього не побачить. Перевіряємо явно, що
    REGISTRY_PATH реально існує в REPO_ROOT.
    """
    registry_full_path = os.path.join(REPO_ROOT, REGISTRY_PATH)
    if not os.path.isfile(registry_full_path):
        raise SystemExit(
            f"[guard] САМОПЕРЕВІРКА ПРОВАЛЕНА: {REGISTRY_PATH} не знайдено за "
            f"{registry_full_path!r}. REPO_ROOT обчислюється з розташування "
            "guard.py - можливо, файл перемістили. Запуск скасовано."
        )

    cases = [
        (("Bash", {"command": "echo GATE_9137"}), False),
        (("Bash", {"command": "git log --oneline -3"}), True),
        (("Bash", {"command": "git log --output=settings.py"}), False),
        (("Bash", {"command": "git log --oneline $'\\x2d\\x2doutput=/tmp/x'"}), False),
        (("Edit", {"file_path": "evaluation_form_service/settings.py"}), False),
    ]
    for (tool_name, tool_input), expected in cases:
        allowed, _ = guard_decision(tool_name, tool_input)
        if allowed is not expected:
            raise SystemExit(
                f"[guard] САМОПЕРЕВІРКА ПРОВАЛЕНА: {tool_name} {tool_input} "
                f"дало {allowed}, очікували {expected}. Запуск скасовано."
            )
