#!/usr/bin/env python3
# PreToolUse / Write|Edit|MultiEdit: не дати запису потрапити у файл-секрет
# і не дати секрету потрапити у трекований файл.
#
# Навіщо окремий хук: permissions.deny забороняє Read(**/.env), але не Write і
# не Edit. Тобто Claude не прочитає .env - і при цьому може його затерти.
# .env лежить у .gitignore, тож відкату немає нізвідки: ані з робочого дерева,
# ані з історії. Це та втрата, яку промпт "не чіпай .env" не страхує.
#
# Навіщо PreToolUse, а не PostToolUse: PostToolUse спрацьовує ПІСЛЯ запису.
# На той момент файл уже перезаписаний, і хуку лишається хіба надрукувати
# співчуття. Блокувати можна тільки до виклику.
#
# Контракт: exit 2 -> виклик заблоковано, stderr іде Клоду як фідбек.
# Будь-який несподіваний payload -> exit 0 (fail-open): зламаний гейт, що
# блокує все підряд, знімають цілком, і проєкт лишається взагалі без захисту.
import json
import os
import re
import sys

# Файли, вміст яких не відновити: .env у .gitignore, ключі не комітяться.
PROTECTED_NAMES = {".env", "credentials", "credentials.json", "id_rsa", "id_ed25519"}
PROTECTED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore")

# Єдиний легальний виняток серед .env.* - шаблон, який трекається у git.
ALLOWED_NAMES = {".env.sample", ".env.example", ".env.template"}

# Кожен патерн описує ФОРМУ секрету, а не слово "key" поруч із текстом.
# Ловити за назвою - значить блокувати документацію і власні коментарі.
#
# Третє поле - чи глушити збіг, що виглядає як заглушка. Категорії різні:
#   False - префікс плюс ентропія САМІ є доказом (AKIA..., ghp_..., sk-ant-...).
#           Такий рядок не буває випадковим збігом, тож послаблювати нічим.
#           Канонічний ключ AWS із доків містить слово EXAMPLE - і він
#           все одно має блокуватись, бо форма справжня.
#   True  - форма загальна і в доках чи фікстурах легальна
#           (postgres://user:password@host, PASSWORD = "...").
SECRET_PATTERNS = (
    (r"sk-ant-[A-Za-z0-9_\-]{20,}", "Anthropic API key", False),
    (r"\bsk-[A-Za-z0-9]{32,}\b", "OpenAI-подібний API key", False),
    (r"\bgh[pousr]_[A-Za-z0-9]{30,}\b", "GitHub token", False),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key id", False),
    (r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+", "JWT", False),
    (r"postgres(?:ql)?://[^:\s/]+:[^@\s]+@", "Postgres URL із паролем", True),
    (
        r"(?i)\b(?:SECRET_KEY|PEOPLEFORCE_API_KEY|API_KEY|APIKEY|PASSWORD|TOKEN)\b"
        r"\s*[:=]\s*[\"'][^\"'\n]{12,}[\"']",
        "секрет, вписаний літералом замість os.getenv()",
        True,
    ),
)

# Заглушки легальні: у .env.sample, фікстурах і доках вони і мають так виглядати.
PLACEHOLDER = re.compile(
    r"(?i)(your[_\- ]|<[^>]{1,40}>|xxx+|change[_\-]?me|dummy|example|placeholder"
    r"|fake|sample|\btest[_\-]?|\*{4,}|\.{4,})"
)

COMPILED = tuple((re.compile(p), label, soft) for p, label, soft in SECRET_PATTERNS)


def written_text(tool_name, tool_input):
    """Текст, який інструмент збирається записати. Форма поля залежить від
    інструмента, тому кожен розбирається окремо, а не через .get('content')."""
    if tool_name == "Write":
        return tool_input.get("content") or ""
    if tool_name == "Edit":
        return tool_input.get("new_string") or ""
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits")
        if not isinstance(edits, list):
            return ""
        return "\n".join(
            e.get("new_string") or "" for e in edits if isinstance(e, dict)
        )
    if tool_name == "NotebookEdit":
        return tool_input.get("new_source") or ""
    return ""


def block(message):
    sys.stderr.write(message)
    sys.exit(2)


def check_path(path):
    """Рубіж перший: цільовий файл сам по собі є секретом."""
    name = os.path.basename(path)
    if name in ALLOWED_NAMES:
        return
    if name in PROTECTED_NAMES or name.startswith(".env."):
        block(
            f"Запис у {name} заблоковано.\n"
            f"{name} у .gitignore - затертий вміст не відновиться ні з дерева, "
            f"ні з історії, і зупинить весь docker-compose.\n"
            "Що робити далі: якщо треба нова змінна оточення - додай її опис у "
            ".env.sample і попроси користувача вписати значення самому.\n"
        )
    if name.endswith(PROTECTED_SUFFIXES):
        block(
            f"Запис у {name} заблоковано: це приватний ключ або сертифікат.\n"
            "Такі файли створює власник машини, не агент.\n"
        )


def check_content(path, text):
    """Рубіж другий: секрет у тексті, що йде в трекований файл."""
    if not text:
        return
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pattern, label, soft in COMPILED:
            match = pattern.search(line)
            if not match:
                continue
            if soft and PLACEHOLDER.search(match.group(0)):
                continue
            block(
                f"Запис у {path} заблоковано: рядок {line_no} схожий на "
                f"{label}.\n"
                "Секрет у трекованому файлі лишається в історії git назавжди, "
                "навіть якщо наступний коміт його прибере.\n"
                "Що робити далі: читай значення через os.getenv(), а сам ключ "
                "хай користувач покладе у .env власноруч.\n"
            )


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

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not isinstance(path, str) or not path:
        return 0

    check_path(path)
    check_content(path, written_text(payload.get("tool_name") or "", tool_input))
    return 0


if __name__ == "__main__":
    sys.exit(main())
