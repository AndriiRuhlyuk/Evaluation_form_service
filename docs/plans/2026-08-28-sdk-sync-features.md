# sync_features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Агент на Claude Agent SDK читає git-історію, звіряє її з `Features_list.json` і пропонує правки в робочому дереві, працюючи всередині доведеної пісочниці.

**Architecture:** Python-обгортка навколо одного виклику `query()`. Уся недетермінована частина - виклик агента; усе навколо (охоронець дозволів, парсинг git, чотири інваріанти, схема, exit codes) - чисті функції, покриті юніт-тестами. Пісочниця стоїть на `PreToolUse` hook, а не на `allowed_tools`, і скрипт відмовляється стартувати, якщо не довів, що охоронець живий.

**Tech Stack:** Python 3.13, `claude-agent-sdk` 0.2.147, стандартний `unittest`, `make`. Жодних залежностей поза SDK.

**Spec:** `docs/plans/2026-08-28-sdk-sync-features-spec.md`

## Global Constraints

- Модель: `claude-haiku-4-5`, задається явно.
- Пісочниця будується **тільки** на `PreToolUse` hook. `allowed_tools` як механізм блокування не використовується взагалі - він затіняє охоронця (спец, 5.1).
- `setting_sources=[]` обов'язково: без нього allow-правила з `.claude/settings.json` затінюють охоронця невидимо.
- `ClaudeAgentOptions.stderr` обов'язково прокидається у власний stderr - інакше попередження CLI ковтаються.
- Охоронець гейтить **усі три виміри**: `Bash`, `Read`, `Edit`. Матчер не звужується до одного інструмента.
- `max_turns` задається константою в коді, не літералом у виклику.
- `is_error` перевіряється **до** будь-якого використання `result`.
- `ANTHROPIC_API_KEY` читається лише з `os.environ`, ніколи не пишеться у файл і не потрапляє в логи.
- Агент не робить `git commit` і не робить `git push`. Правки лишаються в робочому дереві.
- Жоден запис у `Features_list.json` не видаляється і не переформульовується - агенту дозволено лише перемикати `done` і додавати нові блоки (інваріант I3 зі спеки).
- Exit codes: `0` порядок, `1` зламалось, `2` відпрацювало з зауваженнями.
- Тести пишуться **перед** реалізацією (правило репозиторію `.claude/rules/workflow.md`).
- `black .` перед `flake8`; `flake8` має виходити з нулем знахідок.
- Коментарі і докстрінги українською, ідентифікатори англійською.
- Мережеві запуски (усе, що торкається `api.anthropic.com`) робляться поза Bash-пісочницею.

## File Structure

```
tools/sync_features/
├── README.md            # опис для здачі за R6
├── Makefile             # install / test / run / run-broken / clean
├── pyproject.toml       # одна залежність: claude-agent-sdk
├── guard.py             # правила дозволів + PreToolUse hook + самоперевірка пісочниці
├── gitscan.py           # читання git log, витяг id фіч, pre-check
├── verify.py            # чотири інваріанти + перевірка схеми
├── sync_features.py     # оркестрація: pre-check → agent loop → verify → persist → exit code
├── probe_sandbox.py     # уже існує: доказ, що PreToolUse hook блокує
└── tests/
    ├── test_guard.py
    ├── test_gitscan.py
    └── test_verify.py
```

---

### Task 1: Каркас пакета

**Files:**
- Create: `tools/sync_features/pyproject.toml`
- Create: `tools/sync_features/tests/__init__.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: нічого
- Produces: робочу теку пакета з власним venv, у якій `python -m unittest discover` знаходить тести

**Контекст оточення:** ця гілка створена в окремому git worktree, тому `.venv` (git-ignored) і `probe_sandbox.py` (untracked) сюди не переїхали. Обидва треба відтворити.

- [ ] **Step 0: Створити venv і встановити SDK**

`python3` у системі це 3.14.6, і `venv` на ній падає на `ensurepip`. Робочий інтерпретатор - `python3.13`.

```bash
cd tools/sync_features
python3.13 -m venv .venv
.venv/bin/pip install claude-agent-sdk
.venv/bin/python -c "import claude_agent_sdk; print(claude_agent_sdk.__name__)"
```

Expected: остання команда друкує `claude_agent_sdk`.

Якщо `python3.13` немає в PATH, шукати серед `ls /opt/homebrew/bin/python3.*`.

- [ ] **Step 0b: Перенести probe_sandbox.py**

Скопіювати з основного checkout - це доказ пісочниці, на який посилається специфікація:

```bash
cp /Users/myda2/DRF_project/evaluation_form_service/tools/sync_features/probe_sandbox.py \
   tools/sync_features/probe_sandbox.py
```

- [ ] **Step 1: Додати ігнорування venv і матеріалів лекції**

У кінець `.gitignore` додати блок:

```
# tools/sync_features має власний venv, окремий від сервісного
tools/sync_features/.venv/
tools/sync_features/sync-artifacts/

# матеріали лекції 5.7, не частина сервісу
5.7-sdk*
```

- [ ] **Step 2: Створити pyproject.toml**

```toml
[project]
name = "sync-features"
version = "0.1.0"
description = "Агент звіряє Features_list.json з git-історією"
requires-python = ">=3.11"
dependencies = ["claude-agent-sdk"]

[tool.setuptools]
py-modules = ["sync_features", "guard", "gitscan", "verify"]
```

- [ ] **Step 3: Створити порожній tests/__init__.py**

Файл порожній - потрібен лише щоб `unittest discover` бачив теку як пакет.

- [ ] **Step 4: Перевірити, що discover працює**

Run: `cd tools/sync_features && .venv/bin/python -m unittest discover tests -v`
Expected: `Ran 0 tests`, exit 0.

- [ ] **Step 5: Перевірити, що .gitignore діє**

Run: `git check-ignore -v tools/sync_features/.venv "5.7-sdk копія"`
Expected: обидва шляхи named, exit 0.

- [ ] **Step 6: Commit**

```bash
git add .gitignore tools/sync_features/pyproject.toml tools/sync_features/tests/__init__.py
git commit -m "Add: каркас tools/sync_features, ігнорування venv і матеріалів лекції"
```

---

### Task 2: Охоронець дозволів

**Files:**
- Create: `tools/sync_features/guard.py`
- Test: `tools/sync_features/tests/test_guard.py`

**Interfaces:**
- Consumes: нічого
- Produces:
  - `guard_decision(tool_name: str, tool_input: dict) -> tuple[bool, str]` - чиста синхронна функція, повертає `(дозволено, причина)`
  - `async def pre_tool_use_hook(input_data, tool_use_id, context) -> dict` - обгортка для SDK
  - `DECISIONS: list[tuple[str, str, str]]` - журнал рішень
  - `REGISTRY_PATH = "Features_list.json"` - єдиний файл, який дозволено редагувати

**Правила, які реалізує охоронець:**

| Інструмент | Дозволено | Заборонено |
|---|---|---|
| `Bash` | команда починається з `git log` і не містить `; & \| ` $( > < \n` | усе інше |
| `Read` | `Features_list.json` і будь-який `*/services.py` | усе інше, зокрема `.env`, `*.pem`, `*.key` |
| `Edit` | рівно `Features_list.json` | усе інше |
| будь-який інший | - | усе |

- [ ] **Step 1: Написати падаючі тести**

```python
"""Тести охоронця дозволів. Кожен кейс - окрема дірка в пісочниці."""

import unittest

from guard import guard_decision


class TestBashRules(unittest.TestCase):
    def test_git_log_allowed(self):
        allowed, _ = guard_decision("Bash", {"command": "git log --oneline -40"})
        self.assertTrue(allowed)

    def test_leading_whitespace_still_allowed(self):
        allowed, _ = guard_decision("Bash", {"command": "  git log -1  "})
        self.assertTrue(allowed)

    def test_echo_denied(self):
        allowed, reason = guard_decision("Bash", {"command": "echo GATE_9137"})
        self.assertFalse(allowed)
        self.assertIn("git log", reason)

    def test_chained_command_denied(self):
        # найважливіший кейс: префікс правильний, а команда шкідлива
        allowed, _ = guard_decision("Bash", {"command": "git log; rm -rf ."})
        self.assertFalse(allowed)

    def test_substitution_denied(self):
        allowed, _ = guard_decision("Bash", {"command": "git log $(whoami)"})
        self.assertFalse(allowed)

    def test_redirect_denied(self):
        allowed, _ = guard_decision("Bash", {"command": "git log > /tmp/out"})
        self.assertFalse(allowed)

    def test_missing_command_key_denied(self):
        allowed, _ = guard_decision("Bash", {})
        self.assertFalse(allowed)


class TestReadRules(unittest.TestCase):
    def test_registry_allowed(self):
        allowed, _ = guard_decision("Read", {"file_path": "Features_list.json"})
        self.assertTrue(allowed)

    def test_services_allowed(self):
        allowed, _ = guard_decision("Read", {"file_path": "working_form/services.py"})
        self.assertTrue(allowed)

    def test_env_denied(self):
        allowed, _ = guard_decision("Read", {"file_path": ".env"})
        self.assertFalse(allowed)

    def test_key_file_denied(self):
        allowed, _ = guard_decision("Read", {"file_path": "certs/server.key"})
        self.assertFalse(allowed)

    def test_traversal_to_env_denied(self):
        allowed, _ = guard_decision("Read", {"file_path": "working_form/../.env"})
        self.assertFalse(allowed)


class TestEditRules(unittest.TestCase):
    def test_registry_allowed(self):
        allowed, _ = guard_decision("Edit", {"file_path": "Features_list.json"})
        self.assertTrue(allowed)

    def test_settings_denied(self):
        allowed, _ = guard_decision(
            "Edit", {"file_path": "evaluation_form_service/settings.py"}
        )
        self.assertFalse(allowed)


class TestUnknownTools(unittest.TestCase):
    def test_write_denied(self):
        allowed, _ = guard_decision("Write", {"file_path": "Features_list.json"})
        self.assertFalse(allowed)

    def test_webfetch_denied(self):
        allowed, _ = guard_decision("WebFetch", {"url": "https://example.com"})
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Запустити тести, переконатись що падають**

Run: `cd tools/sync_features && .venv/bin/python -m unittest discover tests -v`
Expected: FAIL з `ModuleNotFoundError: No module named 'guard'`

- [ ] **Step 3: Реалізувати guard.py**

Ключові рішення реалізації:

- шлях нормалізується через `os.path.normpath` **до** перевірки, інакше `working_form/../.env` пройде як «не .env»;
- перевірка `Read` на `services.py` робиться через `fnmatch` по нормалізованому шляху;
- абсолютні шляхи і шляхи, що після нормалізації починаються з `..`, відхиляються завжди;
- журнал `DECISIONS` наповнює тільки hook, не `guard_decision` - чиста функція лишається без побічних ефектів, щоб її можна було викликати в тестах вільно.

```python
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
```

- [ ] **Step 4: Запустити тести, переконатись що зелені**

Run: `cd tools/sync_features && .venv/bin/python -m unittest discover tests -v`
Expected: PASS, усі кейси.

- [ ] **Step 5: Додати hook-обгортку і самоперевірку**

```python
async def pre_tool_use_hook(input_data, tool_use_id, context) -> dict:
    """PreToolUse hook: SDK консультує її перед КОЖНИМ викликом інструмента."""
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    allowed, reason = guard_decision(tool_name, tool_input)
    DECISIONS.append((tool_name, repr(tool_input)[:120], "ALLOW" if allowed else "DENY"))
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
```

- [ ] **Step 6: Перевірити самоперевірку вручну**

Run: `cd tools/sync_features && .venv/bin/python -c "import guard; guard.self_check(); print('self-check OK')"`
Expected: `self-check OK`

- [ ] **Step 7: Формат і лінт**

Run: `cd /Users/myda2/DRF_project/evaluation_form_service && .venv/bin/black tools/sync_features && .venv/bin/flake8 tools/sync_features`
Expected: black переформатував або нічого не змінив; flake8 без жодного рядка виводу.

- [ ] **Step 8: Commit**

```bash
git add tools/sync_features/guard.py tools/sync_features/tests/test_guard.py
git commit -m "Add: охоронець дозволів на три виміри з самоперевіркою пісочниці"
```

---

### Task 3: Читання git-історії

**Files:**
- Create: `tools/sync_features/gitscan.py`
- Test: `tools/sync_features/tests/test_gitscan.py`

**Interfaces:**
- Consumes: нічого
- Produces:
  - `ID_PATTERN` - скомпільований regex для id фіч
  - `extract_ids(text: str) -> set[str]`
  - `parse_log(raw: str) -> list[tuple[str, str]]` - `[(sha, subject), ...]`
  - `commits_since(iso_date: str) -> list[tuple[str, str]]` - викликає git, не покривається юніт-тестами
  - `coverage_line(commits, ids_in_answer) -> str` - рядок звіту

**Серії id (зі спеки):** AUTH, CORE, TPL, WF, EVAL, FORM, INT, OPS, BUG, TD, QA, AI, LD, FN, ARCH, CFG, FE.

- [ ] **Step 1: Написати падаючі тести**

```python
import unittest

from gitscan import coverage_line, extract_ids, parse_log


class TestExtractIds(unittest.TestCase):
    def test_single_id(self):
        self.assertEqual(extract_ids("Fix: ARCH-5 полагоджено"), {"ARCH-5"})

    def test_several_ids(self):
        text = "Docs: ARCH-20, CFG-1 і CFG-2"
        self.assertEqual(extract_ids(text), {"ARCH-20", "CFG-1", "CFG-2"})

    def test_no_ids(self):
        self.assertEqual(extract_ids("Update: дрібні правки"), set())

    def test_unknown_series_ignored(self):
        self.assertEqual(extract_ids("Fix: ZZZ-1"), set())

    def test_range_notation_takes_first_only(self):
        # відома межа: "ARCH-24..26" дає лише ARCH-24.
        # Діапазони не розгортаються навмисно - це здогад, а не факт.
        self.assertEqual(extract_ids("ARCH-24..26"), {"ARCH-24"})

    def test_lowercase_not_matched(self):
        self.assertEqual(extract_ids("fix: arch-5"), set())


class TestParseLog(unittest.TestCase):
    def test_two_lines(self):
        raw = "7a8598f Docs: щось\nb0086cf Fix: ARCH-5\n"
        self.assertEqual(
            parse_log(raw),
            [("7a8598f", "Docs: щось"), ("b0086cf", "Fix: ARCH-5")],
        )

    def test_empty_input(self):
        self.assertEqual(parse_log(""), [])

    def test_blank_lines_skipped(self):
        self.assertEqual(parse_log("\n\n7a8598f Subject\n\n"), [("7a8598f", "Subject")])

    def test_subject_without_space(self):
        self.assertEqual(parse_log("7a8598f"), [("7a8598f", "")])


class TestCoverageLine(unittest.TestCase):
    def test_counts(self):
        commits = [
            ("a1", "Fix: ARCH-5"),
            ("a2", "Update: без id"),
            ("a3", "Docs: CFG-1 і CFG-2"),
        ]
        line = coverage_line(commits, {"ARCH-5", "CFG-1", "CFG-2"})
        self.assertIn("3 commits in range", line)
        self.assertIn("2 reference a feature id", line)
        self.assertIn("1 do not", line)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Запустити тести, переконатись що падають**

Run: `cd tools/sync_features && .venv/bin/python -m unittest discover tests -v`
Expected: FAIL з `ModuleNotFoundError: No module named 'gitscan'`

- [ ] **Step 3: Реалізувати gitscan.py**

```python
import re
import subprocess

_SERIES = (
    "AUTH|CORE|TPL|WF|EVAL|FORM|INT|OPS|BUG|TD|QA|AI|LD|FN|ARCH|CFG|FE"
)
ID_PATTERN = re.compile(rf"\b({_SERIES})-\d+\b")


def extract_ids(text: str) -> set[str]:
    """Усі id фіч, згадані в тексті. Діапазони не розгортаються."""
    return {match.group(0) for match in ID_PATTERN.finditer(text)}


def parse_log(raw: str) -> list[tuple[str, str]]:
    """Розібрати вивід `git log --oneline` у пари (sha, subject)."""
    out: list[tuple[str, str]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition(" ")
        out.append((sha, subject))
    return out


def commits_since(iso_date: str) -> list[tuple[str, str]]:
    """Коміти після вказаної дати. Викликає git, тому без юніт-тестів."""
    result = subprocess.run(
        ["git", "log", f"--since={iso_date}", "--oneline", "--no-merges"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return parse_log(result.stdout)


def coverage_line(commits: list[tuple[str, str]], ids_in_answer: set[str]) -> str:
    """Рядок звіту про покриття. Вимірює, а не вимагає 1:1 (спец, розділ 4)."""
    with_ids = sum(1 for _, subject in commits if extract_ids(subject))
    return (
        f"{len(commits)} commits in range, {with_ids} reference a feature id, "
        f"{len(commits) - with_ids} do not; "
        f"agent answer mentions {len(ids_in_answer)} ids"
    )
```

- [ ] **Step 4: Запустити тести, переконатись що зелені**

Run: `cd tools/sync_features && .venv/bin/python -m unittest discover tests -v`
Expected: PASS

- [ ] **Step 5: Формат і лінт**

Run: `cd /Users/myda2/DRF_project/evaluation_form_service && .venv/bin/black tools/sync_features && .venv/bin/flake8 tools/sync_features`
Expected: flake8 без виводу.

- [ ] **Step 6: Commit**

```bash
git add tools/sync_features/gitscan.py tools/sync_features/tests/test_gitscan.py
git commit -m "Add: читання git-історії і витяг id фіч"
```

---

### Task 4: Чотири інваріанти верифікації

**Files:**
- Create: `tools/sync_features/verify.py`
- Test: `tools/sync_features/tests/test_verify.py`

**Interfaces:**
- Consumes: `gitscan.extract_ids`
- Produces:
  - `check_parses(text: str) -> tuple[bool, str]` - I1
  - `check_no_id_lost(before: list[dict], after: list[dict]) -> tuple[bool, str]` - I2
  - `check_descriptions_intact(before, after) -> tuple[bool, str]` - I3
  - `check_coverage(commits, payload) -> tuple[bool, str]` - I4
  - `run_all(before, after, commits, payload) -> list[str]` - список порушень, порожній = порядок

**Форма запису реєстру:** `{"id": str, "category": str, "name": str, "description": str, "done": bool}`.

- [ ] **Step 1: Написати падаючі тести**

```python
import unittest

from verify import (
    check_coverage,
    check_descriptions_intact,
    check_no_id_lost,
    check_parses,
    run_all,
)


def entry(id_, description="опис", done=False, name="назва"):
    return {
        "id": id_,
        "category": "ARCH",
        "name": name,
        "description": description,
        "done": done,
    }


class TestI1Parses(unittest.TestCase):
    def test_valid_json(self):
        ok, _ = check_parses('{"a": 1}')
        self.assertTrue(ok)

    def test_broken_json(self):
        ok, reason = check_parses('{"a": ')
        self.assertFalse(ok)
        self.assertIn("JSON", reason)


class TestI2NoIdLost(unittest.TestCase):
    def test_same_set(self):
        before = [entry("ARCH-1"), entry("ARCH-2")]
        ok, _ = check_no_id_lost(before, list(before))
        self.assertTrue(ok)

    def test_addition_allowed(self):
        before = [entry("ARCH-1")]
        after = [entry("ARCH-1"), entry("ARCH-2")]
        ok, _ = check_no_id_lost(before, after)
        self.assertTrue(ok)

    def test_removal_caught(self):
        before = [entry("ARCH-1"), entry("ARCH-2")]
        after = [entry("ARCH-1")]
        ok, reason = check_no_id_lost(before, after)
        self.assertFalse(ok)
        self.assertIn("ARCH-2", reason)


class TestI3DescriptionsIntact(unittest.TestCase):
    def test_done_flip_allowed(self):
        before = [entry("ARCH-1", done=False)]
        after = [entry("ARCH-1", done=True)]
        ok, _ = check_descriptions_intact(before, after)
        self.assertTrue(ok)

    def test_description_rewrite_caught(self):
        before = [entry("ARCH-1", description="оригінал")]
        after = [entry("ARCH-1", description="покращене формулювання")]
        ok, reason = check_descriptions_intact(before, after)
        self.assertFalse(ok)
        self.assertIn("ARCH-1", reason)

    def test_name_rewrite_caught(self):
        before = [entry("ARCH-1", name="стара назва")]
        after = [entry("ARCH-1", name="нова назва")]
        ok, _ = check_descriptions_intact(before, after)
        self.assertFalse(ok)

    def test_new_entry_ignored(self):
        before = [entry("ARCH-1")]
        after = [entry("ARCH-1"), entry("ARCH-2", description="новий")]
        ok, _ = check_descriptions_intact(before, after)
        self.assertTrue(ok)


class TestI4Coverage(unittest.TestCase):
    def test_all_covered(self):
        commits = [("a1", "Fix: ARCH-5")]
        payload = {"flipped_to_done": ["ARCH-5"], "new_entries": []}
        ok, _ = check_coverage(commits, payload)
        self.assertTrue(ok)

    def test_missing_id_caught(self):
        commits = [("a1", "Fix: ARCH-5"), ("a2", "Fix: CFG-1")]
        payload = {"flipped_to_done": ["ARCH-5"], "new_entries": []}
        ok, reason = check_coverage(commits, payload)
        self.assertFalse(ok)
        self.assertIn("CFG-1", reason)

    def test_id_in_new_entry_counts(self):
        commits = [("a1", "Fix: CFG-1")]
        payload = {"flipped_to_done": [], "new_entries": [{"id": "CFG-1"}]}
        ok, _ = check_coverage(commits, payload)
        self.assertTrue(ok)


class TestRunAll(unittest.TestCase):
    def test_clean_run_returns_empty(self):
        before = [entry("ARCH-1")]
        after = [entry("ARCH-1", done=True)]
        commits = [("a1", "Fix: ARCH-1")]
        payload = {"flipped_to_done": ["ARCH-1"], "new_entries": []}
        self.assertEqual(run_all(before, after, commits, payload), [])

    def test_violations_accumulate(self):
        before = [entry("ARCH-1", description="оригінал"), entry("ARCH-2")]
        after = [entry("ARCH-1", description="переписано")]
        commits = [("a1", "Fix: CFG-9")]
        payload = {"flipped_to_done": [], "new_entries": []}
        violations = run_all(before, after, commits, payload)
        self.assertEqual(len(violations), 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Запустити тести, переконатись що падають**

Run: `cd tools/sync_features && .venv/bin/python -m unittest discover tests -v`
Expected: FAIL з `ModuleNotFoundError: No module named 'verify'`

- [ ] **Step 3: Реалізувати verify.py**

```python
import json

from gitscan import extract_ids

# Поля, які агенту заборонено чіпати в наявних записах. `done` свідомо
# відсутнє: саме його перемикання і є роботою агента.
_IMMUTABLE_FIELDS = ("category", "name", "description")


def check_parses(text: str) -> tuple[bool, str]:
    """I1: файл після правки лишається валідним JSON."""
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        return False, f"файл не парситься як JSON: {exc}"
    return True, "JSON валідний"


def _by_id(entries: list[dict]) -> dict[str, dict]:
    return {item["id"]: item for item in entries if "id" in item}


def check_no_id_lost(before: list[dict], after: list[dict]) -> tuple[bool, str]:
    """I2: множина id до є підмножиною множини після."""
    lost = sorted(set(_by_id(before)) - set(_by_id(after)))
    if lost:
        return False, f"зникли записи: {', '.join(lost)}"
    return True, "жоден id не зник"


def check_descriptions_intact(before: list[dict], after: list[dict]) -> tuple[bool, str]:
    """I3: наявним записам дозволено міняти лише `done`.

    Найважливіший інваріант: реєстр - це накопичена вручну пам'ять, і
    "покращене формулювання" тихо знищує вимірювання, зроблене колись у
    реальному розслідуванні.
    """
    after_map = _by_id(after)
    changed: list[str] = []
    for id_, original in _by_id(before).items():
        updated = after_map.get(id_)
        if updated is None:
            continue
        for field in _IMMUTABLE_FIELDS:
            if original.get(field) != updated.get(field):
                changed.append(f"{id_}.{field}")
    if changed:
        return False, f"змінені незмінні поля: {', '.join(sorted(changed))}"
    return True, "описи наявних записів не змінені"


def check_coverage(commits: list[tuple[str, str]], payload: dict) -> tuple[bool, str]:
    """I4: кожен id із комітлогу присутній у відповіді агента."""
    mentioned = set(payload.get("flipped_to_done", []))
    mentioned |= {
        item["id"] for item in payload.get("new_entries", []) if "id" in item
    }
    from_commits: set[str] = set()
    for _, subject in commits:
        from_commits |= extract_ids(subject)
    missing = sorted(from_commits - mentioned)
    if missing:
        return False, f"id з комітів відсутні у відповіді агента: {', '.join(missing)}"
    return True, "усі id з комітів присутні у відповіді"


def run_all(
    before: list[dict],
    after: list[dict],
    commits: list[tuple[str, str]],
    payload: dict,
) -> list[str]:
    """Прогнати всі інваріанти. Порожній список = порядок."""
    violations: list[str] = []
    for ok, reason in (
        check_no_id_lost(before, after),
        check_descriptions_intact(before, after),
        check_coverage(commits, payload),
    ):
        if not ok:
            violations.append(reason)
    return violations
```

- [ ] **Step 4: Запустити тести, переконатись що зелені**

Run: `cd tools/sync_features && .venv/bin/python -m unittest discover tests -v`
Expected: PASS

- [ ] **Step 5: Формат і лінт**

Run: `cd /Users/myda2/DRF_project/evaluation_form_service && .venv/bin/black tools/sync_features && .venv/bin/flake8 tools/sync_features`
Expected: flake8 без виводу.

- [ ] **Step 6: Commit**

```bash
git add tools/sync_features/verify.py tools/sync_features/tests/test_verify.py
git commit -m "Add: чотири інваріанти верифікації відповіді агента"
```

---

### Task 5: Перевірка схеми відповіді

**Files:**
- Modify: `tools/sync_features/verify.py`
- Modify: `tools/sync_features/tests/test_verify.py`

**Interfaces:**
- Consumes: нічого
- Produces:
  - `OUTPUT_SCHEMA: dict`
  - `parse_agent_json(raw: str) -> tuple[dict | None, str]` - знімає обгортку ```json
  - `validate_schema(payload: dict) -> list[str]` - список порушень

**Схема:**

```json
{
  "flipped_to_done": ["ARCH-5"],
  "new_entries": [
    {"id": "ARCH-28", "category": "ARCH", "name": "…", "description": "…", "done": false}
  ]
}
```

- [ ] **Step 1: Дописати падаючі тести**

```python
class TestParseAgentJson(unittest.TestCase):
    def test_plain_json(self):
        payload, _ = parse_agent_json('{"flipped_to_done": [], "new_entries": []}')
        self.assertEqual(payload, {"flipped_to_done": [], "new_entries": []})

    def test_fenced_json(self):
        raw = '```json\n{"flipped_to_done": [], "new_entries": []}\n```'
        payload, _ = parse_agent_json(raw)
        self.assertIsNotNone(payload)

    def test_prose_returns_none(self):
        payload, reason = parse_agent_json("Я подивився історію і думаю, що…")
        self.assertIsNone(payload)
        self.assertIn("JSON", reason)


class TestValidateSchema(unittest.TestCase):
    def test_valid(self):
        payload = {
            "flipped_to_done": ["ARCH-5"],
            "new_entries": [
                {
                    "id": "ARCH-28",
                    "category": "ARCH",
                    "name": "н",
                    "description": "о",
                    "done": False,
                }
            ],
        }
        self.assertEqual(validate_schema(payload), [])

    def test_missing_top_level_key(self):
        self.assertTrue(validate_schema({"flipped_to_done": []}))

    def test_flipped_must_be_strings(self):
        self.assertTrue(validate_schema({"flipped_to_done": [5], "new_entries": []}))

    def test_new_entry_missing_field(self):
        payload = {"flipped_to_done": [], "new_entries": [{"id": "ARCH-28"}]}
        self.assertTrue(validate_schema(payload))

    def test_new_entry_done_must_be_bool(self):
        payload = {
            "flipped_to_done": [],
            "new_entries": [
                {
                    "id": "ARCH-28",
                    "category": "ARCH",
                    "name": "н",
                    "description": "о",
                    "done": "false",
                }
            ],
        }
        self.assertTrue(validate_schema(payload))
```

Додати `parse_agent_json` і `validate_schema` до імпорту вгорі файлу.

- [ ] **Step 2: Запустити тести, переконатись що падають**

Run: `cd tools/sync_features && .venv/bin/python -m unittest discover tests -v`
Expected: FAIL з `ImportError: cannot import name 'parse_agent_json'`

- [ ] **Step 3: Дописати verify.py**

```python
OUTPUT_SCHEMA = {
    "required": ("flipped_to_done", "new_entries"),
    "entry_fields": {
        "id": str,
        "category": str,
        "name": str,
        "description": str,
        "done": bool,
    },
}


def parse_agent_json(raw: str) -> tuple[dict | None, str]:
    """Розібрати відповідь агента, знявши можливу ```json обгортку."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```")
        text = text.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"агент повернув не JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "агент повернув JSON, але не об'єкт"
    return payload, "розібрано"


def validate_schema(payload: dict) -> list[str]:
    """Порушення схеми. Порожній список = схема дотримана."""
    problems: list[str] = []
    for key in OUTPUT_SCHEMA["required"]:
        if key not in payload:
            problems.append(f"відсутній ключ верхнього рівня: {key}")
    for value in payload.get("flipped_to_done", []):
        if not isinstance(value, str):
            problems.append(f"flipped_to_done містить не рядок: {value!r}")
    for index, item in enumerate(payload.get("new_entries", [])):
        if not isinstance(item, dict):
            problems.append(f"new_entries[{index}] не об'єкт")
            continue
        for field, expected_type in OUTPUT_SCHEMA["entry_fields"].items():
            if field not in item:
                problems.append(f"new_entries[{index}] без поля {field}")
            elif not isinstance(item[field], expected_type):
                problems.append(
                    f"new_entries[{index}].{field} має тип "
                    f"{type(item[field]).__name__}, очікували {expected_type.__name__}"
                )
    return problems
```

- [ ] **Step 4: Запустити тести, переконатись що зелені**

Run: `cd tools/sync_features && .venv/bin/python -m unittest discover tests -v`
Expected: PASS

- [ ] **Step 5: Формат, лінт, commit**

```bash
cd /Users/myda2/DRF_project/evaluation_form_service
.venv/bin/black tools/sync_features && .venv/bin/flake8 tools/sync_features
git add tools/sync_features/verify.py tools/sync_features/tests/test_verify.py
git commit -m "Add: перевірка схеми відповіді агента"
```

---

### Task 6: Оркестрація

**Files:**
- Create: `tools/sync_features/sync_features.py`

**Interfaces:**
- Consumes: `guard.pre_tool_use_hook`, `guard.self_check`, `gitscan.commits_since`, `gitscan.coverage_line`, `verify.*`
- Produces: `main() -> int`, константи `MAX_TURNS`, `PROMPT`

**TDD не застосовується:** виклик агента недетермінований, мокати `query()` заради мока сенсу немає (спец, розділ 9). Уся тестована логіка вже в Tasks 2-5.

**Реальна структура `Features_list.json`** (перевірено 2026-08-28, не вгадувати):

```json
{
  "project": "Evaluation Form Service",
  "updated": "2026-08-28",
  "legend": {"true": "implemented", "false": "planned / backlog"},
  "features": [
    {"id": "AUTH-1", "category": "auth", "name": "…", "description": "…", "done": true}
  ]
}
```

Записів рівно 80. `category` у нижньому регістрі (`"auth"`), тоді як префікс id у верхньому (`"AUTH-1"`) - не плутати. Список записів лежить під ключем `features`, не в корені.

**Шість кроків оркестрації (спец, розділ 7):**

- [ ] **Step 1: Pre-check і самоперевірка**

```python
def main_sync() -> int:
    guard.self_check()  # пісочниця вміє тихо вимикатись - не віримо на слово

    registry_text = Path(REGISTRY_PATH).read_text(encoding="utf-8")
    registry = json.loads(registry_text)
    updated = registry.get("updated", "1970-01-01")

    commits = gitscan.commits_since(updated)
    print(f"[pre-check] updated={updated}, комітів після={len(commits)}", file=sys.stderr)
    if not commits:
        print("[pre-check] нових комітів немає - модель не викликаємо", file=sys.stderr)
        return 0
```

- [ ] **Step 2: Agent loop зі streaming-прогресом**

```python
    options = ClaudeAgentOptions(
        tools=["Bash", "Read", "Edit"],
        max_turns=MAX_TURNS,
        model="claude-haiku-4-5",
        setting_sources=[],
        hooks={"PreToolUse": [HookMatcher(matcher="*", hooks=[guard.pre_tool_use_hook])]},
        stderr=lambda line: print(f"[cli] {line}", file=sys.stderr),
    )

    turn = 0
    raw_result = ""
    result_message = None
    async for message in query(prompt=PROMPT, options=options):
        if isinstance(message, AssistantMessage):
            turn += 1
            print(f"[t={turn}] {str(message.content)[:80]}", file=sys.stderr)
        elif isinstance(message, ResultMessage):
            result_message = message
            raw_result = message.result or ""
```

- [ ] **Step 3: is_error ПЕРЕД використанням result**

```python
    if result_message is None:
        print("[error] агент не повернув ResultMessage", file=sys.stderr)
        return 1
    if result_message.is_error:
        print(f"[error] is_error=True, subtype={result_message.subtype}", file=sys.stderr)
        return 1
```

- [ ] **Step 4: Parse, схема, інваріанти**

```python
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

    # I1 перевіряється тут, ДО json.loads: агент міг лишити файл зламаним,
    # і тоді json.loads кине виняток замість зрозумілого повідомлення.
    after_text = Path(REGISTRY_PATH).read_text(encoding="utf-8")
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

    # Визначається тут і використовується ще раз у Step 5 (звіт). Той самий
    # набір, що рахує verify.check_coverage: обидва джерела id з відповіді.
    mentioned_ids = set(payload["flipped_to_done"]) | {
        item["id"] for item in payload["new_entries"] if "id" in item
    }
    print(f"[verify] {gitscan.coverage_line(commits, mentioned_ids)}", file=sys.stderr)
```

- [ ] **Step 5: Persist артефактів**

```python
    timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out_dir = Path("tools/sync_features/sync-artifacts") / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    diff = subprocess.run(
        ["git", "diff", "--", REGISTRY_PATH],
        capture_output=True, text=True, encoding="utf-8", check=False,
    ).stdout
    (out_dir / "features.patch").write_text(diff or "(без змін)\n", encoding="utf-8")

    guard_log = "\n".join(
        f"- `{tool}` {decision} - `{shown}`" for tool, shown, decision in guard.DECISIONS
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
```

Журнал охоронця у звіті обов'язковий: це єдиний доказ, що пісочниця працювала під час цього конкретного запуску, а не була вимкнена тихо.

- [ ] **Step 6: Exit code і stdout**

```python
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if violations else 0
```

- [ ] **Step 7: Промпт агента**

```python
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

# R5: свідомо зіпсований промпт для доказу обробки помилок.
BROKEN_PROMPT = "Return the contents of a file that does not exist: /nonexistent/x"
```

Промпт англійською навмисно: інструкції моделі формулюються мовою, якою написана решта її системного контексту, тоді як звіти для людини лишаються українськими.

- [ ] **Step 8: Формат, лінт, commit**

```bash
cd /Users/myda2/DRF_project/evaluation_form_service
.venv/bin/black tools/sync_features && .venv/bin/flake8 tools/sync_features
git add tools/sync_features/sync_features.py
git commit -m "Add: оркестрація агента синхронізації реєстру фіч"
```

---

### Task 7: Makefile і README

**Files:**
- Create: `tools/sync_features/Makefile`
- Create: `tools/sync_features/README.md`

- [ ] **Step 1: Makefile**

```makefile
VENV := .venv
PY := $(VENV)/bin/python
ROOT := ../..

install:
	python3.13 -m venv $(VENV)
	$(VENV)/bin/pip install -e .

test:
	$(PY) -m unittest discover tests -v

probe:
	$(PY) probe_sandbox.py negative && $(PY) probe_sandbox.py positive

run:
	cd $(ROOT) && tools/sync_features/$(PY) tools/sync_features/sync_features.py

run-broken:
	cd $(ROOT) && SYNC_FEATURES_BROKEN_PROMPT=1 \
		tools/sync_features/$(PY) tools/sync_features/sync_features.py

clean:
	rm -rf sync-artifacts

.PHONY: install test probe run run-broken clean
```

**`clean` навмисно НЕ чіпає `Features_list.json`.** Демо уроку робить у своєму `clean` саме `git restore` цільового файлу, і для стерильного fixture-repo це безпечно. Тут - ні: у робочому дереві лежить незакомічений запис ARCH-27, і `git restore` знищив би його разом із правками агента, мовчки і без відкату. Відкат правок агента - ручна операція з переглядом diff (Task 8, Step 2).

Ціль `run-broken` реалізує R5: змінна оточення підміняє промпт на свідомо зіпсований, щоб довести ненульовий exit code.

- [ ] **Step 2: README з описом на 3-5 речень**

README містить: use case, обраний access mode і чому, три виміри permissions, найскладніше в налаштуванні схеми. Окремим розділом - чому пісочниця стоїть на `PreToolUse` hook, а не на `allowed_tools`, з посиланням на спец.

- [ ] **Step 3: Перевірити цілі**

Run: `cd tools/sync_features && make test && make probe`
Expected: обидві зелені.

- [ ] **Step 4: Commit**

```bash
git add tools/sync_features/Makefile tools/sync_features/README.md
git commit -m "Add: Makefile і README для sync_features"
```

---

### Task 8: Прогони на реальних даних

**Files:**
- Modify: `CLAUDE.md` (секція Project Layout)

**⚠️ Steps 1-3 виконуються в ОСНОВНОМУ checkout, після мержу гілки, не в worktree.**

Причина: у цій гілці `Features_list.json` має 79 записів. Запис ARCH-27 доданий користувачем вручну і не закомічений - він існує лише в основному дереві. Прогін на неповному реєстрі дав би агенту шанс запропонувати ARCH-27 як «новий» запис, і після мержу вийшов би дублікат id.

- [ ] **Step 1: Позитивний прогін**

Run: `cd tools/sync_features && make run`
Expected: structured JSON у stdout, `[guard]` рядки у stderr, артефакти у `sync-artifacts/<timestamp>/`, exit 0 або 2.

Зберегти повний вивід - це скріншот для здачі.

- [ ] **Step 2: Відкотити правки агента**

Run: `git diff --stat Features_list.json`, далі переглянути `git diff Features_list.json` очима.

**Увага:** `git restore Features_list.json` знищить незакомічений ARCH-27 разом із правками агента. Відкочувати наосліп заборонено. Спершу подивитись diff; якщо серед змін є і ARCH-27, і правки агента - відкочувати вибірково через `git checkout -p Features_list.json`, підтверджуючи кожен блок окремо.

- [ ] **Step 3: Негативний прогін R5**

Run: `cd tools/sync_features && make run-broken`
Expected: `is_error=True` спіймано, ненульовий exit code. Зберегти вивід.

- [ ] **Step 4: Оновити дерево в CLAUDE.md**

Додати в секцію `## Project Layout`, з дотриманням відступу 4 символи на рівень:

```
├── tools/sync_features/       # агент звіряє реєстр фіч із git-історією, пісочниця на PreToolUse hook
```

`5.7-sdk копія/` у дерево не додається - це матеріали лекції, вони в `.gitignore`.

- [ ] **Step 5: Фінальна перевірка репозиторію**

```bash
cd /Users/myda2/DRF_project/evaluation_form_service
.venv/bin/black . && .venv/bin/flake8
bash .claude/hooks/check-layout-drift.sh SessionStart
```

Expected: flake8 без виводу, хук без попереджень.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "Docs: tools/sync_features у дереві Project Layout"
```
