#!/usr/bin/env python3
"""
Пошук і застосування мутацій через синтаксичне дерево (AST).

Навіщо AST, а не пошук рядків за шаблоном: `return (` відкриває вираз, який
триває кілька рядків. Замінивши тільки перший рядок, ми лишаємо хвіст без
початку, файл перестає бути валідним Python, тести падають на SyntaxError -
і мутація виглядає "спійманою", хоча насправді нічого не перевірено.

AST дає точні межі конструкції (від `lineno` до `end_lineno`), тому замінюється
вона цілком. При цьому дерево використовується лише для ПОШУКУ меж; сама заміна
текстова, тож коментарі, відступи і форматування решти файлу не страждають -
на відміну від `ast.unparse()`, який переписав би файл повністю.

Два види мутацій:
  return  - `return <вираз>` -> `return None`, вузол замінюється цілком;
  compare - `a == b` -> `not (a == b)`, лише однорядкові порівняння, бо
            заміна йде за колонками всередині рядка.

Використання:
  mutate.py list  <file>            перелік кандидатів, по одному на рядок:
                                    <індекс>|<вид>|<рядок>|<фрагмент коду>
  mutate.py apply <file> <індекс>   застосувати мутацію (файл змінюється на місці)
"""

import ast
import sys

MUTATION_MARK = "  # mutation"


def _label(source_lines: list[str], node: ast.AST) -> str:
    """Короткий фрагмент вихідного коду для звіту."""
    text = source_lines[node.lineno - 1].strip()
    return text[:50]


def collect(path: str) -> list[dict]:
    """Кандидати на мутацію, впорядковані за позицією у файлі."""
    source = open(path, encoding="utf-8").read()
    source_lines = source.splitlines()
    tree = ast.parse(source)

    items: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            # `return None` мутувати немає сенсу - воно вже None
            if isinstance(node.value, ast.Constant) and node.value.value is None:
                continue
            items.append(
                {
                    "kind": "return",
                    "lineno": node.lineno,
                    "end_lineno": node.end_lineno,
                    "label": _label(source_lines, node),
                }
            )
        elif isinstance(node, ast.Compare) and node.lineno == node.end_lineno:
            # Багаторядкові порівняння пропускаємо: заміна йде за колонками,
            # а вони мають сенс лише в межах одного рядка
            items.append(
                {
                    "kind": "compare",
                    "lineno": node.lineno,
                    "end_lineno": node.end_lineno,
                    "col": node.col_offset,
                    "end_col": node.end_col_offset,
                    "label": _label(source_lines, node),
                }
            )

    items.sort(key=lambda item: (item["lineno"], item.get("col", 0)))
    return items


def apply(path: str, index: int) -> None:
    items = collect(path)
    if not 0 <= index < len(items):
        sys.exit(f"немає мутації з індексом {index} (всього {len(items)})")

    item = items[index]
    lines = open(path, encoding="utf-8").readlines()

    if item["kind"] == "return":
        first = lines[item["lineno"] - 1]
        indent = first[: len(first) - len(first.lstrip())]
        # Увесь вузол - від першого до останнього рядка - стає одним рядком
        lines[item["lineno"] - 1 : item["end_lineno"]] = [
            f"{indent}return None{MUTATION_MARK}\n"
        ]
    else:  # compare
        line = lines[item["lineno"] - 1]
        original = line[item["col"] : item["end_col"]]
        lines[item["lineno"] - 1] = (
            line[: item["col"]] + f"not ({original})" + line[item["end_col"] :]
        )

    open(path, "w", encoding="utf-8").writelines(lines)


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)

    command, path = sys.argv[1], sys.argv[2]

    if command == "list":
        for index, item in enumerate(collect(path)):
            print(f"{index}|{item['kind']}|{item['lineno']}|{item['label']}")
    elif command == "apply":
        if len(sys.argv) < 4:
            sys.exit("apply потребує індекс мутації")
        apply(path, int(sys.argv[3]))
    else:
        sys.exit(f"невідома команда: {command}")


if __name__ == "__main__":
    main()
