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


def check_report_matches_file(
    before: list[dict], after: list[dict], payload: dict
) -> tuple[bool, str]:
    """I5: звіт агента збігається з тим, що реально сталося з файлом.

    Finding K (ревʼю раунд 6): жоден інваріант цього не перевіряв. I2
    дивиться лише на множину id, I3 СВІДОМО виключає `done` (його
    перемикання і є роботою агента), I4 рахує згадки. Тому агент міг
    перемкнути `done` у файлі і водночас написати "я цього не чіпав" - і
    пройти геть усе чисто, лишивши звіт, який прямо суперечить
    `features.patch` поруч із ним.

    Це ширше за прийняту межу про вакуумні причини (README, "Відомі межі"):
    там причина порожня від ЗМІСТУ, тут хибна САМА ДИСПОЗИЦІЯ. Принцип уже
    був записаний у докстрінгу `_check_dispositions_disjoint` - "єдина
    робота JSON - бути достовірним звітом про те, що записано у файл" - але
    його ніщо не забезпечувало.

    Порівнюється рівень ДИСПОЗИЦІЇ, тобто id: які записи змінили `done` і
    які додались. Значення полів нових записів (`category`, `name`,
    `description`) з файлом НЕ звіряються - це інша перевірка, за нею немає
    жодного виміряного провалу, і вигадувати гейт з n=0 - те саме
    вгадування, через яке `reason` лишився вільним текстом.
    """
    before_map = _by_id(before)
    after_map = _by_id(after)
    claimed = _ids_from_strings(payload.get("flipped_to_done"))
    reported_new = _ids_from_objects(payload.get("new_entries"))
    acknowledged = _ids_from_objects(payload.get("left_unchanged"))

    changed = {
        id_
        for id_, original in before_map.items()
        if id_ in after_map and original.get("done") != after_map[id_].get("done")
    }
    appended = set(after_map) - set(before_map)

    problems: list[str] = []
    for id_ in sorted(changed - claimed):
        where = (
            "але звіт відносить його до left_unchanged"
            if id_ in acknowledged
            else "але його немає у flipped_to_done"
        )
        problems.append(f"{id_}: done змінено у файлі, {where}")
    for id_ in sorted(claimed - changed):
        problems.append(
            f"{id_}: заявлений у flipped_to_done, але у файлі done не змінився"
        )
    for id_ in sorted(claimed & changed):
        if after_map[id_].get("done") is not True:
            problems.append(
                f"{id_}: заявлений у flipped_to_done, але у файлі done став не true"
            )
    for id_ in sorted(appended - reported_new):
        problems.append(f"{id_}: доданий у файл, але його немає у new_entries")
    for id_ in sorted(reported_new - appended):
        problems.append(f"{id_}: заявлений у new_entries, але у файлі не з'явився")

    if problems:
        return False, "звіт агента розходиться з файлом: " + "; ".join(problems)
    return True, "звіт агента збігається з файлом"


_METADATA_VALUE_TRUNCATE = 80


def _short_value(value: object) -> str:
    """repr значення метаполя, обрізаний для рядка звіту.

    `legend` - словник на кілька рядків; неврізаний repr у причині
    порушення робить і stderr, і `sync-report.md` нечитабельними, а вся
    інформація, потрібна людині тут, - ЯКИЙ ключ змінився.
    """
    text = repr(value)
    if len(text) <= _METADATA_VALUE_TRUNCATE:
        return text
    return text[: _METADATA_VALUE_TRUNCATE - 3] + "..."


def check_metadata_intact(before_doc: dict, after_doc: dict) -> tuple[bool, str]:
    """I6: усе на верхньому рівні реєстру ПОЗА `features` - незмінне.

    Ревʼю фінального раунду (Important 1): захист реєстру закінчувався на
    ключі `features`. `run_all` отримувала лише `registry["features"]`, а
    перевірка форми після правки (`sync_features.py`) стверджувала лише
    "features - це список". Живий файл несе ще `project`, `updated` і
    `legend`, і жоден інваріант їх не бачив - обидва наслідки проходили з
    усіма пʼятьма зеленими:

    - агент переписує `legend` - рукописна памʼять знищена мовчки;
    - агент піднімає `updated` на сьогодні - і КОЖЕН наступний прогін
      виходить 0 ще на pre-check ("нових комітів немає"). Інструмент тихо
      вимикає сам себе, і жодна помилка про це не скаже.

    Перевіряються ТРИ роди змін - зниклий ключ, доданий ключ і змінене
    значення. Порівняння за `!=` на розпарсеному JSON, не за текстом:
    переформатування самого файлу (відступи, порядок ключів) роботою агента
    не є і тут навмисно не судиться - його ловить `features.patch`, який
    людина й так переглядає.

    `features` виключено СУВОРО: інакше I6 дублювала б I2/I3 і сама робота
    агента (перемикання `done`, нові записи) ставала б порушенням.
    """
    before_meta = {key: value for key, value in before_doc.items() if key != "features"}
    after_meta = {key: value for key, value in after_doc.items() if key != "features"}

    problems: list[str] = []
    for key in sorted(set(before_meta) - set(after_meta)):
        problems.append(f"{key}: ключ зник")
    for key in sorted(set(after_meta) - set(before_meta)):
        problems.append(f"{key}: ключ доданий ({_short_value(after_meta[key])})")
    for key in sorted(set(before_meta) & set(after_meta)):
        if before_meta[key] != after_meta[key]:
            problems.append(
                f"{key}: {_short_value(before_meta[key])} -> "
                f"{_short_value(after_meta[key])}"
            )

    if problems:
        return False, "змінено метадані реєстру поза 'features': " + "; ".join(problems)
    return True, "метадані реєстру поза 'features' не змінені"


def check_entries_identifiable(after: list) -> tuple[bool, str]:
    """I7: КОЖЕН запис у файлі після правки має унікальний непорожній `id`.

    Ревʼю фінального раунду (Important 2): `_by_id` ВІДКИДАЄ записи без
    `id` і СХЛОПУЄ дублікати, а I2, I3 і I5 читають реєстр лише через неї.
    Виміряний ревʼю вхід - `run_all(before, before + [{"name": "ghost",
    ...}], [], {порожні списки})` - повертав `[]`: файл отримав рядок, JSON
    сказав "нічого не записано", прогін вийшов 0. Те саме для дописаного
    байт-у-байт дубліката наявного id.

    Чому саме ця вимога, а не "рядків стало `len(before) +
    len(new_entries)`": лічильник рядків звіряє файл із ЗАЯВОЮ агента, тому
    брехлива заява і спричиняє порушення, і маскує його (два `new_entries`
    з однаковим id дають 2 у довжині списку і 1 в множині id). Унікальність
    вимірюється СУВОРО з файлу і від звіту не залежить. Крім того вона
    сильніша: щойно кожен рядок `after` має унікальний id, `_by_id` стає
    без-втратною, і будь-який дописаний рядок знову ВИДИМИЙ для I5 -
    "дописав і не звітував" ловить I5, як і задумано, а не тиша.

    Судиться лише `after`. `before` - людський baseline, і перевіряти його
    тут означало б звинувачувати агента в чужій ваді; виміряний реєстр цієї
    гілки чистий (79 записів, 0 без id, 0 дублікатів), тому на здоровому
    прогоні I7 мовчить.
    """
    problems: list[str] = []
    first_seen: dict[str, int] = {}
    for index, item in enumerate(after):
        if not isinstance(item, dict):
            problems.append(f"запис #{index} не є обʼєктом ({_short_value(item)})")
            continue
        id_ = item.get("id")
        if not isinstance(id_, str) or not id_.strip():
            problems.append(
                f"запис #{index} без непорожнього рядкового 'id' "
                f"({_short_value(item.get('name'))})"
            )
            continue
        if id_ in first_seen:
            problems.append(
                f"{id_}: дублікат id у записах #{first_seen[id_]} і #{index}"
            )
        else:
            first_seen[id_] = index

    if problems:
        return False, (
            "записи реєстру не ідентифікуються однозначно: " + "; ".join(problems)
        )
    return True, f"усі {len(after)} записів мають унікальний id"


def run_all(
    before_doc: dict,
    after_doc: dict,
    commits: list[tuple[str, str]],
    payload: dict,
) -> list[str]:
    """Прогнати всі інваріанти. Порожній список = порядок.

    Приймає ПОВНІ документи реєстру, не лише списки `features` - це і є
    структурний бік фіксу Important 1: місце виклику фізично не може
    передати верифікатору менше, ніж увесь файл, тому "захист закінчується
    на `features`" не можна відтворити, забувши аргумент. Форму обох
    документів (`dict` із `features`-списком) перевіряє викликач ДО і ПІСЛЯ
    правки агента, тому індексуємо `["features"]` прямо: відсутній ключ тут
    - зламаний контракт викликача, і хай він падає гучно, а не звіряє два
    порожні списки мовчки.

    I5 (Finding K), I6 і I7 стоять ТУТ, а не поруч у `sync_features.py`,
    свідомо: `run_all` - єдина точка входу "усе, що знає верифікатор", і
    перевірку в ній неможливо забути на місці виклику. Проєкт це вже
    проходив (Fix 7, два незалежні підрахунки одного union'у в різних
    файлах). Уся потрібні дані вже є в сигнатурі.

    Порушення I5 дає код виходу 2 ("відпрацював із зауваженнями"), не 1
    ("зламалось"), з двох причин. По-перше, за змістом це той самий рід
    результату, що I2 та I3: прогін дійшов до кінця, файл цілий і
    парситься, і ми маємо ЗНАХІДКУ про те, що сталось - а не аварію
    інструмента. По-друге, `run_all` НАКОПИЧУЄ порушення, тоді як шляхи з
    кодом 1 у `main_sync` роблять ранній `return`; зробивши I5 фатальним,
    ми відібрали б у людини результати I2/I3/I4 того самого прогону саме
    тоді, коли вони найпотрібніші. Правки у файлі при цьому цілком можуть
    бути правильними - хибний тут ЗВІТ, і вирішує це ручний перегляд
    `features.patch`, який і так обовʼязковий.

    I6 та I7 отримують той самий код 2, і з тих самих причин. Спокуса дати
    I6 код 1 є ("піднятий `updated` вимикає інструмент назавжди"), але
    наслідок від коду виходу не залежить: файл на диску вже змінено в обох
    випадках, лікує це та сама ручна правка, а код 1 РОБИТЬ ГІРШЕ - він
    змусив би `main_sync` повернутись раніше і забрав би в людини результати
    решти інваріантів того самого прогону саме тоді, коли треба зрозуміти,
    що ще агент устиг зачепити. Код 1 у цьому інструменті означає "не
    відпрацював" (SDK впав, JSON не розібрався, файл не парситься), а не
    "відпрацював погано".
    """
    before = before_doc["features"]
    after = after_doc["features"]
    violations: list[str] = []
    for ok, reason in (
        check_no_id_lost(before, after),
        check_descriptions_intact(before, after),
        check_coverage(commits, payload),
        check_report_matches_file(before, after, payload),
        check_metadata_intact(before_doc, after_doc),
        check_entries_identifiable(after),
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


def _all_json_candidates(text: str) -> list[str]:
    """Усі шматки тексту, які МОЖУТЬ бути JSON-відповіддю, у порядку появи:
    вміст кожної огорожі плюс кожен збалансований `{...}` діапазон верхнього
    рівня.

    Finding L: раніше дві евристики дивились у РІЗНІ боки - огорожа бралась
    ОСТАННЯ, збалансований діапазон ПЕРШИЙ. Щоб узгодити їх, спершу треба
    мати повний список кандидатів, а не одразу вибирати по одному з кожної.
    """
    found: list[tuple[int, str]] = [
        (match.start(1), match.group(1).strip())
        for match in _FENCED_JSON_RE.finditer(text)
    ]

    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start == -1:
            break
        span = _find_balanced_json(text[start:])
        if span is None:
            break
        found.append((start, span))
        index = start + len(span)

    found.sort(key=lambda pair: pair[0])
    ordered: list[str] = []
    for _, candidate in found:
        if candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _is_schema_shaped(candidate: str) -> bool:
    """Чи має кандидат ВСІ три обовʼязкові ключі верхнього рівня.

    Саме це відрізняє відповідь від чужого `{...}`, процитованого поруч.
    Перевірка навмисно лише про НАЯВНІСТЬ ключів, не про типи всередині:
    типи - робота `validate_schema`, і кандидат зі схемними ключами, але
    поганими типами, мусить дійти до неї і бути відхиленим ГУЧНО, а не
    тихо програти іншому кандидату тут.
    """
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and all(
        key in parsed for key in OUTPUT_SCHEMA["required"]
    )


def parse_agent_json(raw: str) -> tuple[dict | None, str]:
    """Розібрати відповідь агента.

    Finding L (ревʼю раунд 6): дві евристики суперечили одна одній -
    `_find_fenced_json` брала ОСТАННЮ огорожу, `_find_balanced_json` -
    ПЕРШИЙ збалансований діапазон. Ревʼю виміряло наслідок: у тексті
    "приклад, потім відповідь" БЕЗ огорожі парсер брав ПРИКЛАД, а оскільки
    приклад із самого промпту схемно валідний, `validate_schema` пропускала
    його мовчки - і прогін звітував про flip ARCH-5 та новий ARCH-28, яких
    ніхто не писав. Промпт сам загострює це: він постачає повний валідний
    приклад і просить НЕ ставити огорожу.

    Тепер правило одне для обох джерел: серед УСІХ кандидатів (кожна
    огорожа плюс кожен збалансований діапазон) береться ОСТАННІЙ, що має всі
    три обовʼязкові ключі. "Останній" - бо підсумкова відповідь моделі йде
    після її роздумів і прикладів.

    Межа цього правила, названа прямо: коли модель дає відповідь, а ПОТІМ
    відлунює шаблон, обидва кандидати схемно валідні, і жодна структурна
    ознака їх не розрізняє - буде обрано шаблон. Це не лікується парсером.
    Лікує це I5 (`check_report_matches_file`): відлунений шаблон заявляє
    flip і новий запис, яких у файлі немає, тому прогін впаде з
    порушенням інваріанта замість тихого хибного звіту. Крім того, коли
    схемних кандидатів БІЛЬШЕ ОДНОГО, це видно в поверненій причині.

    Фолбек - стара поведінка (остання огорожа, інакше перший збалансований
    діапазон, інакше весь текст) - лишається РІВНО для випадку, коли жоден
    кандидат не має всіх трьох ключів. Чиста проза й надалі МУСИТЬ давати
    `None`: кандидатів немає, `candidate` лишається сирим текстом, і
    `json.loads` дає ту саму помилку, що раніше. R5 залежить саме від цього.
    """
    text = raw.strip()

    note = ""
    schema_shaped = [c for c in _all_json_candidates(text) if _is_schema_shaped(c)]
    if schema_shaped:
        candidate = schema_shaped[-1]
        if len(schema_shaped) > 1:
            note = (
                f" (схемних кандидатів у тексті: {len(schema_shaped)}, узято "
                f"останній - перевір, що це відповідь, а не відлунений шаблон)"
            )
    else:
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
    return payload, "розібрано" + note


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
