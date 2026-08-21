#!/usr/bin/env python3
# SessionEnd (async: true): один JSONL-рядок на сесію - слід того, що реально
# відбувалось, а не того, що запам'яталось.
#
# Навіщо async: телеметрія нікого не блокує і нічого не вирішує. Із
# "async": true Claude не чекає на завершення хука, а decision-поля у виводі
# ігноруються. Блокуючий варіант просто додав би затримку на кожному виході.
# Правило з уроку: спочатку observability, потім політики - місяць даних, і
# видно, які гейти взагалі варто ставити.
#
# Що НЕ потрапляє в лог: жодного тексту з транскрипту. Тільки лічильники.
# Це не стиль, а вимога CLAUDE.md - у транскрипті осідають дані кандидатів
# (ПІБ, email, CV) і значення ключів PeopleForce. Рахувати виклики безпечно,
# зберігати їхні аргументи - ні. Тому агрегація тут, а не "скопіюємо і потім
# почистимо": те, чого не записали, не витече.
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

LOG_PATH = ".claude/telemetry.jsonl"

# Транскрипт довгої сесії - десятки тисяч рядків. Стеля тримає хук у межах
# мілісекунд навіть на найважчій сесії.
MAX_LINES = 50000


def parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def scan_transcript(path):
    """Лічильники з транскрипту. Жоден рядок вмісту не повертається назовні."""
    stats = {
        "tool_calls": Counter(),
        "messages": 0,
        "first_ts": None,
        "last_ts": None,
    }
    if not path or not os.path.isfile(path):
        return stats

    try:
        handle = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return stats

    with handle:
        for index, line in enumerate(handle):
            if index >= MAX_LINES:
                break
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(event, dict):
                continue

            stamp = parse_ts(event.get("timestamp"))
            if stamp is not None:
                if stats["first_ts"] is None:
                    stats["first_ts"] = stamp
                stats["last_ts"] = stamp

            if event.get("type") in ("user", "assistant"):
                stats["messages"] += 1

            message = event.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name")
                    if isinstance(name, str):
                        stats["tool_calls"][name] += 1
    return stats


def git_branch(cwd):
    """Гілка з .git/HEAD напряму: запускати git у SessionEnd-хуку дорожче,
    ніж прочитати один файл, а результат той самий."""
    head = os.path.join(cwd, ".git", "HEAD")
    try:
        with open(head, "r", encoding="utf-8") as handle:
            ref = handle.read().strip()
    except OSError:
        return None
    if ref.startswith("ref: refs/heads/"):
        return ref[len("ref: refs/heads/") :]
    return "detached"


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return 0
    if not isinstance(payload, dict):
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    stats = scan_transcript(payload.get("transcript_path"))

    duration = None
    if stats["first_ts"] and stats["last_ts"]:
        duration = round((stats["last_ts"] - stats["first_ts"]).total_seconds(), 1)

    session_id = payload.get("session_id") or ""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # Вісім символів - достатньо, щоб зшити сесію з .claude/instructions.log,
        # і замало, щоб бути ідентифікатором самим по собі.
        "sid": session_id[:8] if isinstance(session_id, str) else "",
        "reason": payload.get("reason"),
        "project": os.path.basename(cwd.rstrip("/")),
        "branch": git_branch(cwd),
        "duration_s": duration,
        "messages": stats["messages"],
        "tool_calls_total": sum(stats["tool_calls"].values()),
        "tools": dict(stats["tool_calls"].most_common(10)),
    }

    log_path = os.path.join(cwd, LOG_PATH)
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
