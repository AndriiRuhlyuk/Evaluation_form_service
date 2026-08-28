"""Охоронець дозволів для sync_features.

`allowed_tools` у claude-agent-sdk нічого не блокує (див. docs/plans/2026-08-28-
sdk-sync-features-spec.md, розділ 5.1) - реальна межа пісочниці це PreToolUse
hook. `guard_decision` - чиста функція без побічних ефектів, її можна вільно
викликати з тестів; журнал `DECISIONS` наповнює лише hook-обгортка.
"""

import os
import sys
from fnmatch import fnmatch

REGISTRY_PATH = "Features_list.json"
_FORBIDDEN_SUBSTRINGS = (";", "&", "|", "`", "$(", ">", "<", "\n")
_READABLE_GLOBS = (REGISTRY_PATH, "*/services.py")

DECISIONS: list[tuple[str, str, str]] = []


def _normalised(tool_input: dict) -> str | None:
    """Нормалізований відносний шлях, або None якщо шлях недопустимий."""
    raw = tool_input.get("file_path", "")
    if not raw:
        return None
    if os.path.isabs(raw):
        return None
    path = os.path.normpath(raw)
    if path.startswith(".."):
        return None
    return path


def guard_decision(tool_name: str, tool_input: dict) -> tuple[bool, str]:
    if tool_name == "Bash":
        command = tool_input.get("command", "").strip()
        if not command.startswith("git log"):
            return False, f"команда {command!r} не починається з 'git log'"
        for bad in _FORBIDDEN_SUBSTRINGS:
            if bad in command:
                return False, f"команда містить заборонений символ {bad!r}"
        return True, "git log без керівних символів"

    if tool_name == "Read":
        path = _normalised(tool_input)
        if path is None:
            return False, "шлях порожній, абсолютний або виходить за корінь"
        if any(fnmatch(path, pattern) for pattern in _READABLE_GLOBS):
            return True, f"{path} у списку читабельних"
        return False, f"{path} поза списком читабельних"

    if tool_name == "Edit":
        path = _normalised(tool_input)
        if path != REGISTRY_PATH:
            return False, f"редагувати дозволено лише {REGISTRY_PATH}, не {path!r}"
        return True, f"{REGISTRY_PATH} - єдиний дозволений до правки файл"

    return False, f"інструмент {tool_name!r} поза трьома дозволеними вимірами"


async def pre_tool_use_hook(input_data, tool_use_id, context) -> dict:
    """PreToolUse hook: SDK консультує її перед КОЖНИМ викликом інструмента."""
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    allowed, reason = guard_decision(tool_name, tool_input)
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
    вірять на слово: три контрольні рішення перевіряються на кожному запуску.
    """
    cases = [
        (("Bash", {"command": "echo GATE_9137"}), False),
        (("Bash", {"command": "git log --oneline -3"}), True),
        (("Edit", {"file_path": "evaluation_form_service/settings.py"}), False),
    ]
    for (tool_name, tool_input), expected in cases:
        allowed, _ = guard_decision(tool_name, tool_input)
        if allowed is not expected:
            raise SystemExit(
                f"[guard] САМОПЕРЕВІРКА ПРОВАЛЕНА: {tool_name} {tool_input} "
                f"дало {allowed}, очікували {expected}. Запуск скасовано."
            )
