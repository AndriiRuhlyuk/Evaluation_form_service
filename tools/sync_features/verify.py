import itertools
import json
import re

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


def _ids_from_strings(items: object) -> set[str]:
    """id зі списку рядків, стійко до кривої форми.

    `isinstance(items, list)` тут не педантизм: `set("ARCH-5")` дає шість
    ОДНОСИМВОЛЬНИХ "id" замість нуля, і на error-шляхах журналу (де payload
    ще не бачив `validate_schema`) це надувало б рядок покриття.
    """
    if not isinstance(items, list):
        return set()
    return {value for value in items if isinstance(value, str)}


def _ids_from_objects(items: object) -> set[str]:
    """id зі списку об'єктів, стійко до кривої форми.

    `mentioned_ids` викликається і з ранніх error-шляхів `_write_journal`, де
    payload ще не проходив `validate_schema`. Рахівник покриття не має права
    падати на тому, що є роботою валідатора схеми: не список - порожньо, не
    об'єкт - пропустити, id не рядок - пропустити.
    """
    if not isinstance(items, list):
        return set()
    found: set[str] = set()
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            found.add(item["id"])
    return found


def mentioned_ids(payload: dict) -> set[str]:
    """Усі id фіч, згадані у відповіді агента: об'єднання ТРЬОХ джерел -
    `flipped_to_done`, id нових записів у `new_entries` і id у
    `left_unchanged`.

    Task 6, fix round 1, Fix 7: раніше `check_coverage` і `sync_features.py`
    рахували цей самий union кожен окремо - два копії однієї логіки в різних
    файлах, одна з яких (у обгортці) не покрита тестами і могла тихо
    розійтись із цією. Тепер обидва місця викликають цю функцію.

    Task 7, fix round 5: третє джерело. Раніше union складався лише зі ЗМІН,
    тому агент, який чесно нічого не змінив, не мав ЖОДНОГО способу згадати
    id - і I4 спрацьовував на кожному реалістичному прогоні.
    """
    mentioned = _ids_from_strings(payload.get("flipped_to_done"))
    mentioned |= _ids_from_objects(payload.get("new_entries"))
    mentioned |= _ids_from_objects(payload.get("left_unchanged"))
    return mentioned


def check_coverage(commits: list[tuple[str, str]], payload: dict) -> tuple[bool, str]:
    """I4: кожен id із комітлогу ВРАХОВАНИЙ у відповіді агента - у будь-якому
    з трьох списків.

    Task 7, fix round 5: сенс інваріанта не змінився ("не пропусти коміт
    мовчки"), змінилось те, ЧИМ агент може його задовольнити. До цього раунду
    відповідь мала місце лише для ЗМІН, а промпт вимагав від агента не чіпати
    неоднозначні коміти - дві взаємно нездійсненні вимоги, через які I4 падав
    на кожному чесному прогоні. Тепер "розглянув і свідомо лишив як є" - теж
    відповідь, і I4 знову розрізняє добрий прогін від поганого.
    """
    mentioned = mentioned_ids(payload)
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
    "required": ("flipped_to_done", "new_entries", "left_unchanged"),
    "entry_fields": {
        "id": str,
        "category": str,
        "name": str,
        "description": str,
        "done": bool,
    },
    # Task 7, fix round 5: третє поле. Форма навмисно мінімальна - id і
    # причина. Причина - ВІЛЬНИЙ ТЕКСТ, не закритий перелік кодів: закритий
    # перелік не рятує від вакуумного задоволення I4 (агент однаково обере
    # найближчий кошик для всього), зате мовчки спотворює випадок, якого
    # перелік не передбачив. Виміряна причина наразі рівно одна ("коміт
    # `Docs:` фіксує знахідку, а не реалізує її"), і проєктувати словник з
    # n=1 - вгадування. Промпт НАЗИВАЄ типові причини як підказку; схема їх
    # не заморожує.
    "unchanged_fields": {"id": str, "reason": str},
}


# Fix I2 (Task 7, ревʼю раунд 4): fenced-блок з тегом ```json АБО голий
# ``` - НЕ будь-яка інша мова (```python тощо), щоб не хапати чужий
# код-приклад, якщо модель колись покаже й такий. `[ \t]*\r?\n` після
# опційного "json" вимагає, щоб зразу за відкривними трьома зворотними
# лапками йшов ПЕРЕВІД РЯДКА (можливо з пробілами) - це і відрізняє
# "```json\n" від "```javascript\n" на рівні регулярного виразу, без
# додаткової перевірки мови вручну.
_FENCED_JSON_RE = re.compile(r"```(?:json)?[ \t]*\r?\n(.*?)```", re.DOTALL)


def _find_fenced_json(text: str) -> str | None:
    """Знайти fenced-блок (```json або гола ```) БУДЬ-ДЕ в тексті, не лише
    на початку.

    Fix I2: раніше `parse_agent_json` знімав огорожу лише коли ВЕСЬ текст
    ПОЧИНАВСЯ з неї (`text.startswith("```")`) - контролер виміряв локально
    (без мережі) шість реалістичних форм відповіді моделі і показав, що
    "проза ПЕРЕД огорожею" і "проза ПІСЛЯ огорожі" обидві ламали парсинг
    структурно, хоча JSON у відповіді був правильним. Модель, що відкриває
    відповідь реченням на кшталт "Here is the result:", - звичайна, не
    крайній випадок.

    Якщо огорож кілька - беремо ОСТАННЮ. Типовий патерн моделі: приклад чи
    чернетка раніше в тексті ("ось формат відповіді..."), підсумкова
    відповідь наприкінці ("отже, моя відповідь:..."). Це і закриває вимогу
    тесту "агент цитує приклад JSON, а потім дає іншу реальну відповідь" -
    останню огорожу трактуємо як відповідь, не приклад. Якщо огорожа лише
    одна - вибір тривіальний, ця гілка на нього не впливає.
    """
    matches = _FENCED_JSON_RE.findall(text)
    if not matches:
        return None
    return matches[-1].strip()


def _find_balanced_json(text: str) -> str | None:
    """Знайти НАЙЗОВНІШНІЙ збалансований `{...}` діапазон - від ПЕРШОЇ `{`
    до її парної `}`, ігноруючи дужки всередині рядкових літералів JSON
    (щоб `{"a": "}"}` не завершився передчасно на лапці-в-рядку).

    Fix I2: fallback ЛИШЕ коли в тексті взагалі немає жодної огорожі - НЕ
    друга спроба після невдалого парсингу знайденої огорожі. Якщо огорожа
    Є, але її вміст не парситься, `parse_agent_json` повертає помилку
    напряму - не сканує решту тексту в пошуках іншого `{...}`, бо це і є
    та поблажливість, проти якої застерігає бриф: чужий фрагмент JSON,
    процитований моделлю десь поруч (приклад, обговорення), міг би
    випадково "полагодити" зламану відповідь і замаскувати реальну
    проблему. Відомий компроміс цього ж fallback-у: якщо в ТЕКСТІ ВЗАГАЛІ
    немає огорожі, а є ДВА нефенсованих `{...}` (приклад і відповідь), ця
    функція візьме ПЕРШИЙ - не має способу відрізнити приклад від
    відповіді без огорожі-маркера. Наразі реальні прогони показують
    приклади лише всередині огорож, тому цей випадок не покритий тестом.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def parse_agent_json(raw: str) -> tuple[dict | None, str]:
    """Розібрати відповідь агента: fenced-блок БУДЬ-ДЕ в тексті (Fix I2),
    інакше найзовнішніший збалансований `{...}`, інакше - весь текст як є
    (чиста проза дасть звичайну `json.JSONDecodeError` від `json.loads`).

    Fix I2: пряма проза МУСИТЬ повертати None - R5 (доказ обробки помилок)
    залежить саме від цього, і надто поблажливий парсер, що знаходить JSON
    у будь-чому, зламав би робочий guardrail. Коли в тексті немає ЖОДНОЇ
    огорожі й ЖОДНОЇ `{`, обидва хелпери повертають `None`, і `candidate`
    лишається повним сирим текстом - `json.loads` на чистій прозі дає ту
    саму помилку (`Expecting value: line 1 column 1`), що й раніше.
    """
    text = raw.strip()

    candidate = _find_fenced_json(text)
    if candidate is None:
        candidate = _find_balanced_json(text)
    if candidate is None:
        candidate = text

    try:
        payload = json.loads(candidate)
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
    if "flipped_to_done" in payload:
        flipped_to_done = payload["flipped_to_done"]
        if not isinstance(flipped_to_done, list):
            problems.append(
                f"flipped_to_done має тип {type(flipped_to_done).__name__}, очікували list"
            )
        else:
            for value in flipped_to_done:
                if not isinstance(value, str):
                    problems.append(f"flipped_to_done містить не рядок: {value!r}")
    if "new_entries" in payload:
        new_entries = payload["new_entries"]
        if not isinstance(new_entries, list):
            problems.append(
                f"new_entries має тип {type(new_entries).__name__}, очікували list"
            )
        else:
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
    problems += _validate_left_unchanged(payload)
    problems += _check_dispositions_disjoint(payload)
    return problems


def _validate_left_unchanged(payload: dict) -> list[str]:
    """Форма третього поля: список об'єктів `{id: str, reason: str}`.

    `reason` мусить бути НЕПОРОЖНІМ після `strip()`. Це межа між структурною
    і семантичною перевіркою, і вона тут навмисна: схема не вміє відрізнити
    змістовну причину від "n/a", але вміє відхилити відсутність причини
    взагалі - найдешевшу форму того, щоб задовольнити I4, нічого не
    подумавши. Порогу на довжину немає свідомо: "не коротше 10 символів" має
    вигляд перевірки, не будучи нею ("n/a n/a n/a" проходить будь-який поріг).
    """
    if "left_unchanged" not in payload:
        return []
    problems: list[str] = []
    left_unchanged = payload["left_unchanged"]
    if not isinstance(left_unchanged, list):
        return [
            f"left_unchanged має тип {type(left_unchanged).__name__}, очікували list"
        ]
    for index, item in enumerate(left_unchanged):
        if not isinstance(item, dict):
            problems.append(f"left_unchanged[{index}] не об'єкт")
            continue
        for field, expected_type in OUTPUT_SCHEMA["unchanged_fields"].items():
            if field not in item:
                problems.append(f"left_unchanged[{index}] без поля {field}")
            elif not isinstance(item[field], expected_type):
                problems.append(
                    f"left_unchanged[{index}].{field} має тип "
                    f"{type(item[field]).__name__}, очікували {expected_type.__name__}"
                )
        reason = item.get("reason")
        if isinstance(reason, str) and not reason.strip():
            problems.append(f"left_unchanged[{index}].reason порожній")
    return problems


def _check_dispositions_disjoint(payload: dict) -> list[str]:
    """Три списки - три ВЗАЄМОВИКЛЮЧНІ розпорядження одним id.

    Той самий id у двох списках - самосуперечність: "я перемкнув цей запис і
    я його не чіпав", або "я створив новий запис і водночас перемкнув наявний
    із тим самим id". Інваріанти I2/I3 читають ФАЙЛ, а не цей JSON; єдина
    робота JSON - бути достовірним звітом про те, що записано у файл, і
    суперечливий звіт цю роботу не виконує. Побічно це закриває найгрубіший
    спосіб зловжити третім полем - висипати всі id у `left_unchanged` "про
    всяк випадок" ПОВЕРХ тих, які реально змінено.

    Повтор усередині ОДНОГО списку суперечністю не є (лише неохайність), і
    тут не перевіряється: I4 однаково працює з множинами.
    """
    lists = {
        "flipped_to_done": _ids_from_strings(payload.get("flipped_to_done")),
        "new_entries": _ids_from_objects(payload.get("new_entries")),
        "left_unchanged": _ids_from_objects(payload.get("left_unchanged")),
    }
    problems: list[str] = []
    for left, right in itertools.combinations(lists, 2):
        for id_ in sorted(lists[left] & lists[right]):
            problems.append(f"{id_} присутній і в {left}, і в {right}")
    return problems
