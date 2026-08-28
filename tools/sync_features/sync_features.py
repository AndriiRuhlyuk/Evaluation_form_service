"""Оркестрація агента синхронізації `Features_list.json` із git-історією.

Один виклик `query()` з `claude_agent_sdk`, обгорнутий довкола чотирьох
production guardrails (спец, розділ 1, R3a-R3d):

- R3a: `max_turns` капнутий іменованою константою `MAX_TURNS`, не літералом
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
  `result_message.result` - дивись послідовність перевірок одразу після
  `async for`.
- R3d: `ANTHROPIC_API_KEY` цей модуль не читає, не пише і не логує взагалі -
  локальна автентифікація йде через OAuth-сесію бінарника `claude`, SDK
  успадковує її з підпроцесу (спец, розділ 8). Єдина змінна оточення, яку
  читає цей модуль - `SYNC_FEATURES_BROKEN_PROMPT`, прапорець без секрету.

`ClaudeAgentOptions.stderr` проброшено на власний stderr процесу: без цього
попередження CLI (наприклад `CanUseToolShadowedWarning`) ковтаються мовчки -
проєкт уже втратив діагностику через це один раз (спец, розділ 5.1).
"""

import asyncio
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
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
# ціль run-broken) - агент не може виконати запит, `query()` повертає
# ResultMessage з is_error=True, і скрипт мусить це впіймати й вийти
# ненульовим кодом, не впавши traceback-ом.
BROKEN_PROMPT = "Return the contents of a file that does not exist: /nonexistent/x"


async def main_sync() -> int:
    """Асинхронна оркестрація: pre-check -> agent loop -> verify -> persist.

    Повертає код виходу за конвенцією проєкту: 0 порядок, 1 зламалось,
    2 відпрацювало із зауваженнями (порушення інваріантів).
    """
    guard.self_check()  # пісочниця вміє тихо вимикатись - не віримо на слово

    registry_text = Path(guard.REGISTRY_PATH).read_text(encoding="utf-8")
    registry = json.loads(registry_text)
    updated = registry.get("updated", "1970-01-01")

    # Обов'язок 3: commits_since тепер кидає ValueError (невалідна календарна
    # дата) і RuntimeError (git завершився з ненульовим кодом). git сам НЕ
    # скаржиться на биту дату - тихо повертає нуль комітів, і без цієї
    # перевірки pre-check хибно доповів би "нових комітів немає" та вийшов
    # би 0, нічого не зробивши.
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

    # R5: прапорець з env вибирає свідомо зіпсований промпт. Це не секрет -
    # обмеження R3d стосується лише ANTHROPIC_API_KEY.
    prompt = BROKEN_PROMPT if os.environ.get("SYNC_FEATURES_BROKEN_PROMPT") else PROMPT

    options = ClaudeAgentOptions(
        # R3b, зовнішня межа: інших інструментів у моделі просто не існує.
        tools=["Bash", "Read", "Edit"],
        max_turns=MAX_TURNS,  # R3a
        model="claude-haiku-4-5",
        # Відрізає allow-правила з .claude/settings.json - інакше вони тихо
        # затінюють PreToolUse callback ще до охоронця (спец, розділ 5.1).
        setting_sources=[],
        # R3b, справжній блокувальний шар: matcher="*" гейтить УСІ три
        # виміри (Bash, Read, Edit), не лише Bash - доведено окремо
        # інтеграційною пробою в probe_sandbox.py, режим "read_edit".
        hooks={
            "PreToolUse": [HookMatcher(matcher="*", hooks=[guard.pre_tool_use_hook])]
        },
        # Без цього попередження CLI-підпроцесу ковтаються мовчки.
        stderr=lambda line: print(f"[cli] {line}", file=sys.stderr),
    )

    turn = 0
    raw_result = ""
    result_message = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            turn += 1
            print(f"[t={turn}] {str(message.content)[:80]}", file=sys.stderr)
        elif isinstance(message, ResultMessage):
            result_message = message
            raw_result = message.result or ""

    if result_message is None:
        print("[error] агент не повернув ResultMessage", file=sys.stderr)
        return 1
    # R3c: is_error перевіряється ТУТ, до будь-якого використання
    # result_message.result нижче за текстом.
    if result_message.is_error:
        print(
            f"[error] is_error=True, subtype={result_message.subtype}", file=sys.stderr
        )
        return 1

    payload, reason = verify.parse_agent_json(raw_result)
    if payload is None:
        print(f"[verify] {reason}", file=sys.stderr)
        return 1

    schema_problems = verify.validate_schema(payload)
    if schema_problems:
        for problem in schema_problems:
            print(f"[verify] схема: {problem}", file=sys.stderr)
        return 1
    print("[verify] схема OK", file=sys.stderr)

    # I1 перевіряється тут, ДО json.loads: агент міг лишити файл зламаним, і
    # тоді json.loads кине виняток замість зрозумілого повідомлення.
    after_text = Path(guard.REGISTRY_PATH).read_text(encoding="utf-8")
    parses, parse_reason = verify.check_parses(after_text)
    if not parses:
        print(f"[verify] інваріант I1: {parse_reason}", file=sys.stderr)
        return 1

    after = json.loads(after_text)
    violations = verify.run_all(
        registry["features"], after["features"], commits, payload
    )
    for violation in violations:
        print(f"[verify] інваріант: {violation}", file=sys.stderr)

    # Той самий набір, що рахує verify.check_coverage: обидва джерела id з
    # відповіді. Визначається тут і використовується ще раз у звіті нижче.
    mentioned_ids = set(payload["flipped_to_done"]) | {
        item["id"] for item in payload["new_entries"] if "id" in item
    }
    print(f"[verify] {gitscan.coverage_line(commits, mentioned_ids)}", file=sys.stderr)

    timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out_dir = Path("tools/sync_features/sync-artifacts") / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    diff = subprocess.run(
        ["git", "diff", "--", guard.REGISTRY_PATH],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    ).stdout
    (out_dir / "features.patch").write_text(diff or "(без змін)\n", encoding="utf-8")

    # Журнал охоронця у звіті обов'язковий: це єдиний доказ, що пісочниця
    # реально працювала під час цього конкретного запуску, а не була тихо
    # вимкнена (Обов'язок 1 гарантує, що записи тут відповідають рішенням,
    # які hook реально повернув SDK).
    guard_log = "\n".join(
        f"- `{tool}` {decision} - `{shown}`"
        for tool, shown, decision in guard.DECISIONS
    )
    (out_dir / "sync-report.md").write_text(
        f"# Звіт синхронізації реєстру фіч\n\n"
        f"- Час: {timestamp}\n"
        f"- Turns: {result_message.num_turns}\n"
        f"- Вартість (USD): {result_message.total_cost_usd}\n"
        f"- Тривалість (ms): {result_message.duration_ms}\n\n"
        f"## Рішення охоронця\n\n{guard_log or '(жодного виклику інструмента)'}\n\n"
        f"## Покриття\n\n{gitscan.coverage_line(commits, mentioned_ids)}\n\n"
        f"## Порушення інваріантів\n\n"
        f"{chr(10).join('- ' + v for v in violations) or '(немає)'}\n\n"
        f"## JSON агента\n\n```json\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(f"[saved] {out_dir}", file=sys.stderr)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if violations else 0


def main() -> int:
    """Синхронна тонка обгортка: `main_sync` - `async for` усередині, тому
    коротуна, а `main` лише запускає її в новому event loop і повертає код
    виходу далі до `sys.exit`."""
    return asyncio.run(main_sync())


if __name__ == "__main__":
    sys.exit(main())
