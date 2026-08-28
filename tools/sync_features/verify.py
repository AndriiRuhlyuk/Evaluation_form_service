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
