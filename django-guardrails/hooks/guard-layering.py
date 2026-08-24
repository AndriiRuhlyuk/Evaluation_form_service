#!/usr/bin/env python3
# PreToolUse / Write|Edit|MultiEdit по **/services.py: тримати realtime-шар
# поза сервісами.
#
# Інваріант: "services never broadcast" (README плагіна, секція Hooks).
# Мутацію робить сервіс усередині transaction.atomic(); розсилку в групу
# form_<id> робить той, хто володіє HTTP-запитом - working_form/views.py або
# consumers.py. Сьогодні grep підтверджує: жоден services.py не згадує
# channels. Гейт ставиться на зелений baseline.
#
# Чому це не косметика: group_send() усередині atomic() відправляє подію до
# COMMIT. Якщо транзакція далі відкотиться, підписники вже отримали стан,
# якого в базі немає, і WebSocket-клієнти розходяться з БД до перезавантаження
# сторінки. Баг проявляється тільки під відкат - тобто рідко і не в тестах.
#
# Чому PreToolUse: PostToolUse дав би фідбек уже після запису, і Claude пішов
# би у micro-fix loop - переписувати щойно записаний файл. Дешевше не пустити.
#
# Чому фільтр шляху живе у скрипті, а не в конфігурації: standalone-версія
# звужувала виклик полем "if" у settings.json. Плагін такої гарантії не має -
# hooks.json підключає гейт на кожен Write/Edit, і саме скрипт вирішує, що це
# не його випадок. Ціна - зайвий старт процесу; вигода - гейт не залежить від
# того, як його підключили.
import json
import os
import re
import sys

# Маркери realtime-шару. Ловимо виклик і імпорт окремо: у сервісі може
# з'явитись рядок 'group_send' і без імпорту channels - через хелпер.
REALTIME_MARKERS = (
    (r"^\s*(?:from|import)\s+channels\b", "імпорт channels"),
    (r"\bget_channel_layer\s*\(", "get_channel_layer()"),
    (r"\bgroup_send\b", "group_send()"),
    (r"\bchannel_layer\b", "channel_layer"),
    (r"\bfrom\s+asgiref\.sync\s+import\s+.*\basync_to_sync\b", "async_to_sync"),
)

COMPILED = tuple((re.compile(p), label) for p, label in REALTIME_MARKERS)

FEEDBACK = (
    "Заблоковано: {path} отримує {label}.\n"
    "Інваріант django-guardrails - сервіси не роблять broadcast "
    "(README плагіна, секція Hooks).\n"
    "Причина не стильова: group_send() усередині transaction.atomic() "
    "відправляє подію до COMMIT. Відкат транзакції лишає підписників групи "
    "form_<id> зі станом, якого в базі немає.\n"
    "Що робити далі: хай сервіс поверне результат мутації, а group_send() "
    "виклич у views.py або в consumer після виходу з atomic-блоку - там, де "
    "вже живе решта розсилок.\n"
)


def written_text(tool_name, tool_input):
    """Текст, який інструмент збирається записати; поле залежить від тулзи."""
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
    return ""


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

    path = tool_input.get("file_path") or ""
    # Друга лінія після if: гейт стосується лише сервісного шару.
    if not isinstance(path, str) or os.path.basename(path) != "services.py":
        return 0

    text = written_text(payload.get("tool_name") or "", tool_input)
    for line in text.splitlines():
        # Коментар, що згадує group_send, - не порушення, а пояснення правила.
        if line.lstrip().startswith("#"):
            continue
        for pattern, label in COMPILED:
            if pattern.search(line):
                sys.stderr.write(FEEDBACK.format(path=path, label=label))
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
