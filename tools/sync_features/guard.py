"""Охоронець дозволів для sync_features.

`allowed_tools` у claude-agent-sdk нічого не блокує (див. docs/plans/2026-08-28-
sdk-sync-features-spec.md, розділ 5.1) - реальна межа пісочниці це PreToolUse
hook. `guard_decision` - чиста функція без побічних ефектів, її можна вільно
викликати з тестів; журнал `DECISIONS` наповнює лише hook-обгортка.

Fix round 1 (рев'ю): чорний список символів для `Bash` сам собою не закриває
опції програми, яку дозволено запускати (`git log --output=<file>` пише
довільний файл). Правило `Bash` тепер двошарове: (1) заборонені символи на
сирому рядку, (2) токенізація через `shlex` + білий список опцій `git log`.
Шляхи для `Read`/`Edit` нормалізуються відносно кореня репозиторію через
`os.path.realpath`, а не через `os.path.normpath` від відносного рядка -
інакше довелось би або пускати абсолютні шляхи як є (діра), або відхиляти їх
геть (а інструмент `Read` у Claude Code завжди передає абсолютний шлях).
"""

import os
import shlex
import sys

REGISTRY_PATH = "Features_list.json"
_FORBIDDEN_SUBSTRINGS = (";", "&", "|", "`", "$(", ">", "<", "\n")

# Білий список опцій `git log`, дослівно з рішення рев'ю (C1). Усе інше, що
# починається з "-", відхиляється - зокрема "--output", "-p", "--ext-diff".
_ALLOWED_EXACT_OPTS = {
    "--oneline",
    "--no-merges",
    "--name-only",
    "--no-color",
    "--reverse",
}
_ALLOWED_OPT_PREFIXES = (
    "--since=",
    "--until=",
    "--max-count=",
    "--format=",
    "--pretty=",
    "--grep=",
)

# Корінь репозиторію: guard.py лежить у tools/sync_features/, тому два рівні
# вгору від його директорії - корінь (де лежить Features_list.json).
_GUARD_DIR = os.path.dirname(os.path.realpath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_GUARD_DIR))

DECISIONS: list[tuple[str, str, str]] = []


def _is_allowed_git_log_option(token: str) -> bool:
    """Один токен-опція (починається з "-") - у білому списку чи ні."""
    if token in _ALLOWED_EXACT_OPTS:
        return True
    if any(token.startswith(prefix) for prefix in _ALLOWED_OPT_PREFIXES):
        return True
    # форма "-<число>", наприклад "-40"
    if token.startswith("-") and token[1:].isdigit():
        return True
    return False


def _check_bash(command: str) -> tuple[bool, str]:
    """Команда дозволена лише як `git log` з опціями з білого списку."""
    # шар 1: заборонені символи на сирому рядку, до розбору
    for bad in _FORBIDDEN_SUBSTRINGS:
        if bad in command:
            return False, f"команда містить заборонений символ {bad!r}"

    # шар 2: токенізація і перевірка кожного токена-опції
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return False, f"команду не вдалось розібрати: {exc}"

    if len(tokens) < 2 or tokens[0] != "git" or tokens[1] != "log":
        return False, f"команда {command!r} не починається з 'git log'"

    for token in tokens[2:]:
        if token.startswith("-") and not _is_allowed_git_log_option(token):
            return False, f"опція {token!r} поза білим списком git log"

    return True, "git log з опціями з білого списку"


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
    try:
        common = os.path.commonpath([REPO_ROOT, resolved])
    except ValueError:
        return None
    if common != REPO_ROOT:
        return None
    return os.path.relpath(resolved, REPO_ROOT)


def _is_services_path(path: str) -> bool:
    """Рівно `<app>/services.py` - один рівень вкладеності, не будь-яка глибина."""
    return path.count("/") == 1 and path.endswith("/services.py")


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

    Обгорнуто в try/except (I2): SDK ловить виняток усередині hook сам і не
    надсилає жодного рішення - тобто без цього охоронець не fail-closed, а
    просто мовчки не спрацьовує. Тут будь-який збій перетворюється на deny.
    """
    tool_name = "?"
    tool_input: dict = {}
    try:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        allowed, reason = guard_decision(tool_name, tool_input)
    except Exception as exc:  # межа безпеки: будь-який збій -> deny, не виняток
        allowed, reason = False, f"охоронець впав з винятком: {exc!r}"

    DECISIONS.append(
        (tool_name, repr(tool_input)[:120], "ALLOW" if allowed else "DENY")
    )
    print(
        f"[guard] {'ALLOW' if allowed else 'DENY '} {tool_name} - {reason}",
        file=sys.stderr,
    )
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
    """
    cases = [
        (("Bash", {"command": "echo GATE_9137"}), False),
        (("Bash", {"command": "git log --oneline -3"}), True),
        (("Bash", {"command": "git log --output=settings.py"}), False),
        (("Edit", {"file_path": "evaluation_form_service/settings.py"}), False),
    ]
    for (tool_name, tool_input), expected in cases:
        allowed, _ = guard_decision(tool_name, tool_input)
        if allowed is not expected:
            raise SystemExit(
                f"[guard] САМОПЕРЕВІРКА ПРОВАЛЕНА: {tool_name} {tool_input} "
                f"дало {allowed}, очікували {expected}. Запуск скасовано."
            )
