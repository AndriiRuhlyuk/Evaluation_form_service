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


def check_descriptions_intact(
    before: list[dict], after: list[dict]
) -> tuple[bool, str]:
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
    mentioned |= {item["id"] for item in payload.get("new_entries", []) if "id" in item}
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
    flipped_to_done = payload.get("flipped_to_done")
    if flipped_to_done is not None and not isinstance(flipped_to_done, list):
        problems.append(
            f"flipped_to_done має тип {type(flipped_to_done).__name__}, очікували list"
        )
    elif isinstance(flipped_to_done, list):
        for value in flipped_to_done:
            if not isinstance(value, str):
                problems.append(f"flipped_to_done містить не рядок: {value!r}")
    new_entries = payload.get("new_entries")
    if new_entries is not None and not isinstance(new_entries, list):
        problems.append(
            f"new_entries має тип {type(new_entries).__name__}, очікували list"
        )
    elif isinstance(new_entries, list):
        for index, item in enumerate(new_entries):
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
