import unittest

from verify import (
    check_coverage,
    check_descriptions_intact,
    check_no_id_lost,
    check_parses,
    mentioned_ids,
    parse_agent_json,
    run_all,
    validate_schema,
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

    def test_multiple_ids_in_one_commit(self):
        commits = [
            (
                "7f6861e",
                "Docs: ARCH-20..22, CFG-1, CFG-2 - знахідки з роботи над чеклістом релізу",
            )
        ]
        payload = {"flipped_to_done": ["ARCH-20", "CFG-1", "CFG-2"], "new_entries": []}
        ok, _ = check_coverage(commits, payload)
        self.assertTrue(ok)

    def test_multiple_ids_one_missing(self):
        commits = [
            (
                "7f6861e",
                "Docs: ARCH-20..22, CFG-1, CFG-2 - знахідки з роботи над чеклістом релізу",
            )
        ]
        payload = {"flipped_to_done": ["ARCH-20", "CFG-1"], "new_entries": []}
        ok, reason = check_coverage(commits, payload)
        self.assertFalse(ok)
        self.assertIn("CFG-2", reason)


class TestMentionedIds(unittest.TestCase):
    # Fix 7 (Task 6, fix round 1): єдине джерело правди для union'у
    # flipped_to_done + id нових записів - раніше рахувалось окремо у
    # check_coverage і в sync_features.py, ризик тихого розходження.

    def test_union_of_both_sources(self):
        payload = {
            "flipped_to_done": ["ARCH-5"],
            "new_entries": [{"id": "ARCH-28"}],
        }
        self.assertEqual(mentioned_ids(payload), {"ARCH-5", "ARCH-28"})

    def test_new_entry_without_id_ignored(self):
        payload = {"flipped_to_done": [], "new_entries": [{"category": "arch"}]}
        self.assertEqual(mentioned_ids(payload), set())

    def test_missing_keys_default_to_empty(self):
        self.assertEqual(mentioned_ids({}), set())

    def test_check_coverage_uses_same_union(self):
        # Регресія: check_coverage і mentioned_ids мусять погоджуватись на
        # одному й тому самому payload - інакше рядок покриття в звіті
        # суперечив би I4-порушенню з того самого запуску.
        commits = [("a1", "Fix: ARCH-5"), ("a2", "Fix: ARCH-28")]
        payload = {"flipped_to_done": ["ARCH-5"], "new_entries": [{"id": "ARCH-28"}]}
        ok, _ = check_coverage(commits, payload)
        self.assertTrue(ok)
        self.assertEqual(mentioned_ids(payload), {"ARCH-5", "ARCH-28"})


class TestParseAgentJson(unittest.TestCase):
    """Fix I2 (Task 7, ревʼю раунд 4): контролер виміряв локально (без
    мережі) шість реалістичних форм відповіді моделі - `parse_agent_json`
    раніше знімав ```-огорожу лише коли ВЕСЬ текст ПОЧИНАВСЯ з неї, тому
    прозовий вступ ламав парсинг структурно, хоча JSON у відповіді був
    правильним. Кожен тест нижче - одна з шести форм, дослівно."""

    _BARE_JSON = '{"flipped_to_done": ["ARCH-1"], "new_entries": []}'

    def test_shape_1_bare_json(self):
        payload, _ = parse_agent_json(self._BARE_JSON)
        self.assertEqual(payload, {"flipped_to_done": ["ARCH-1"], "new_entries": []})

    def test_shape_2_fenced_json(self):
        raw = f"```json\n{self._BARE_JSON}\n```"
        payload, _ = parse_agent_json(raw)
        self.assertIsNotNone(payload)

    def test_shape_3_prose_before_fence(self):
        raw = f"Here is the result:\n```json\n{self._BARE_JSON}\n```"
        payload, _ = parse_agent_json(raw)
        self.assertEqual(payload, {"flipped_to_done": ["ARCH-1"], "new_entries": []})

    def test_shape_4_prose_after_fence(self):
        raw = f"```json\n{self._BARE_JSON}\n```\nThat is my final answer."
        payload, _ = parse_agent_json(raw)
        self.assertEqual(payload, {"flipped_to_done": ["ARCH-1"], "new_entries": []})

    def test_shape_5_prose_before_bare_json_no_fence(self):
        raw = f"Here is my answer: {self._BARE_JSON}"
        payload, _ = parse_agent_json(raw)
        self.assertEqual(payload, {"flipped_to_done": ["ARCH-1"], "new_entries": []})

    def test_shape_6_pure_prose_returns_none(self):
        # Жорстка вимога брифу: чиста проза МАЄ повертати None - R5
        # (доказ обробки помилок) залежить саме від цього.
        raw = (
            "I could not find any relevant discrepancies in the commit "
            "log, so I made no changes to the registry."
        )
        payload, reason = parse_agent_json(raw)
        self.assertIsNone(payload)
        self.assertIn("JSON", reason)

    def test_agent_quotes_example_then_gives_real_answer(self):
        # Регресія для всього класу знахідки: дві огорожі, різний вміст -
        # остання МАЄ трактуватись як відповідь, не перша (приклад).
        raw = (
            "Here is the shape as an example:\n"
            '```json\n{"flipped_to_done": ["ARCH-1"], "new_entries": []}\n```\n'
            "Now here is my actual answer:\n"
            '```json\n{"flipped_to_done": ["ARCH-5"], "new_entries": []}\n```'
        )
        payload, reason = parse_agent_json(raw)
        self.assertEqual(payload, {"flipped_to_done": ["ARCH-5"], "new_entries": []})
        self.assertEqual(reason, "розібрано")

    def test_python_fenced_block_not_mistaken_for_json(self):
        # Не надто поблажливий: ```python не є ```json чи голою огорожею -
        # має провалитись через balanced-span fallback (тут - на прозі
        # без {}), не мовчки з'їсти чужий приклад коду.
        raw = "```python\nprint('not json at all')\n```"
        payload, reason = parse_agent_json(raw)
        self.assertIsNone(payload)

    def test_no_fence_prefers_first_balanced_span_documented_limit(self):
        # Задокументований компроміс _find_balanced_json: без огорожі
        # береться ПЕРШИЙ {...} - тут це навмисно приклад, не відповідь,
        # щоб компроміс був видимий у тестах, а не лише в докстрінгу.
        raw = 'Example shape: {"a": 1}. Real answer: {"flipped_to_done": [], "new_entries": []}'
        payload, _ = parse_agent_json(raw)
        self.assertEqual(payload, {"a": 1})


class TestValidateSchema(unittest.TestCase):
    def test_valid(self):
        # Task 7, fix round 5: повна відповідь має ТРИ ключі верхнього рівня.
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
            "left_unchanged": [],
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

    def test_flipped_to_done_must_be_list(self):
        payload = {"flipped_to_done": "ARCH-5", "new_entries": []}
        problems = validate_schema(payload)
        self.assertTrue(problems)
        self.assertTrue(any("flipped_to_done" in p for p in problems))

    def test_new_entries_must_be_list_not_string(self):
        payload = {"flipped_to_done": [], "new_entries": "ARCH-28"}
        problems = validate_schema(payload)
        self.assertTrue(problems)
        self.assertTrue(any("new_entries" in p for p in problems))

    def test_new_entries_must_be_list_not_dict(self):
        payload = {"flipped_to_done": [], "new_entries": {"id": "ARCH-28"}}
        problems = validate_schema(payload)
        self.assertTrue(problems)
        self.assertTrue(any("new_entries" in p for p in problems))

    def test_valid_payload_still_passes(self):
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
            "left_unchanged": [],
        }
        self.assertEqual(validate_schema(payload), [])

    def test_flipped_to_done_null_is_invalid(self):
        payload = {"flipped_to_done": None, "new_entries": []}
        problems = validate_schema(payload)
        self.assertTrue(problems)
        self.assertTrue(any("flipped_to_done" in p for p in problems))

    def test_new_entries_null_is_invalid(self):
        payload = {"flipped_to_done": [], "new_entries": None}
        problems = validate_schema(payload)
        self.assertTrue(problems)
        self.assertTrue(any("new_entries" in p for p in problems))

    def test_absent_key_reports_only_missing_key(self):
        payload = {"new_entries": [], "left_unchanged": []}
        problems = validate_schema(payload)
        self.assertTrue(problems)
        self.assertTrue(any("flipped_to_done" in p for p in problems))
        self.assertEqual(len(problems), 1)

    def test_string_flipped_to_done_still_caught(self):
        payload = {"flipped_to_done": "ARCH-5", "new_entries": []}
        problems = validate_schema(payload)
        self.assertTrue(problems)
        self.assertTrue(any("flipped_to_done" in p for p in problems))

    def test_empty_lists_are_valid(self):
        payload = {"flipped_to_done": [], "new_entries": [], "left_unchanged": []}
        self.assertEqual(validate_schema(payload), [])


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


def unchanged(id_, reason="коміт лише фіксує знахідку, не реалізує її"):
    return {"id": id_, "reason": reason}


class TestLeftUnchangedCoverage(unittest.TestCase):
    """Task 7, fix round 5: третє поле відповіді - id, які агент розглянув і
    свідомо НЕ чіпав.

    Без нього промпт ("якщо коміт неоднозначний - лиши його і НЕ згадуй") і
    I4 ("кожен id з комітів присутній у відповіді") взаємно нездійсненні:
    чесний агент повертає порожні списки і I4 спрацьовує на кожному
    реалістичному прогоні, а вердикт, який завжди негативний, несе рівно
    стільки ж інформації, скільки завжди позитивний.
    """

    def test_left_unchanged_counts_towards_coverage(self):
        commits = [("a1", "Docs: ARCH-23 - CI матриць читає лише код виходу")]
        payload = {
            "flipped_to_done": [],
            "new_entries": [],
            "left_unchanged": [unchanged("ARCH-23")],
        }
        ok, _ = check_coverage(commits, payload)
        self.assertTrue(ok)

    def test_measured_case_now_clean(self):
        # Виміряний прогін контролера: п'ять id у Docs-комітах, агент
        # правильно не змінив жодного. Раніше - I4 порушено, exit 2.
        commits = [
            ("7f6861e", "Docs: ARCH-20..22, CFG-1, CFG-2 - знахідки з чекліста"),
            ("83710aa", "Docs: ARCH-23 - CI матриць читає лише код виходу"),
            ("7a8598f", "Docs: CLAUDE.md 255 -> 166 рядків; ARCH-24..26"),
        ]
        payload = {
            "flipped_to_done": [],
            "new_entries": [],
            "left_unchanged": [
                unchanged("ARCH-20", "запис уже done: true"),
                unchanged("ARCH-21"),
                unchanged("ARCH-22"),
                unchanged("ARCH-23"),
                unchanged("ARCH-24"),
                unchanged("ARCH-25"),
                unchanged("ARCH-26"),
                unchanged("CFG-1"),
                unchanged("CFG-2"),
            ],
        }
        ok, reason = check_coverage(commits, payload)
        self.assertTrue(ok, reason)

    def test_mentioned_ids_includes_left_unchanged(self):
        payload = {
            "flipped_to_done": ["ARCH-5"],
            "new_entries": [{"id": "ARCH-28"}],
            "left_unchanged": [unchanged("CFG-1")],
        }
        self.assertEqual(mentioned_ids(payload), {"ARCH-5", "ARCH-28", "CFG-1"})

    def test_left_unchanged_entry_without_id_ignored(self):
        payload = {
            "flipped_to_done": [],
            "new_entries": [],
            "left_unchanged": [{"reason": "без id"}],
        }
        self.assertEqual(mentioned_ids(payload), set())

    def test_left_unchanged_non_dict_entry_ignored(self):
        # mentioned_ids не має падати на кривому payload - валідність форми
        # це справа validate_schema, не рахівника покриття.
        payload = {
            "flipped_to_done": [],
            "new_entries": [],
            "left_unchanged": ["CFG-1"],
        }
        self.assertEqual(mentioned_ids(payload), set())

    def test_string_flipped_to_done_yields_no_ids(self):
        # mentioned_ids викликається і з ранніх error-шляхів журналу, де
        # payload ще не бачив validate_schema. Рядок замість списку не
        # має розсипатись на символи і надути "agent answer mentions N ids".
        payload = {"flipped_to_done": "ARCH-5", "new_entries": [], "left_unchanged": []}
        self.assertEqual(mentioned_ids(payload), set())

    def test_still_missing_id_caught(self):
        # Третє поле не робить I4 беззубим: id, якого немає в ЖОДНОМУ з
        # трьох списків, і далі порушує покриття.
        commits = [("a1", "Fix: ARCH-5"), ("a2", "Docs: CFG-1")]
        payload = {
            "flipped_to_done": ["ARCH-5"],
            "new_entries": [],
            "left_unchanged": [],
        }
        ok, reason = check_coverage(commits, payload)
        self.assertFalse(ok)
        self.assertIn("CFG-1", reason)


class TestLeftUnchangedSchema(unittest.TestCase):
    def _valid(self):
        return {
            "flipped_to_done": ["ARCH-5"],
            "new_entries": [],
            "left_unchanged": [unchanged("CFG-1")],
        }

    def test_valid_three_field_payload(self):
        self.assertEqual(validate_schema(self._valid()), [])

    def test_left_unchanged_is_required(self):
        payload = {"flipped_to_done": [], "new_entries": []}
        problems = validate_schema(payload)
        self.assertTrue(any("left_unchanged" in p for p in problems))

    def test_left_unchanged_must_be_list(self):
        payload = self._valid() | {"left_unchanged": "CFG-1"}
        problems = validate_schema(payload)
        self.assertTrue(any("left_unchanged" in p for p in problems))

    def test_left_unchanged_null_is_invalid(self):
        payload = self._valid() | {"left_unchanged": None}
        problems = validate_schema(payload)
        self.assertTrue(any("left_unchanged" in p for p in problems))

    def test_left_unchanged_entry_must_be_object(self):
        payload = self._valid() | {"left_unchanged": ["CFG-1"]}
        problems = validate_schema(payload)
        self.assertTrue(any("left_unchanged[0]" in p for p in problems))

    def test_left_unchanged_entry_needs_id(self):
        payload = self._valid() | {"left_unchanged": [{"reason": "бо"}]}
        problems = validate_schema(payload)
        self.assertTrue(any("id" in p for p in problems))

    def test_left_unchanged_entry_needs_reason(self):
        payload = self._valid() | {"left_unchanged": [{"id": "CFG-1"}]}
        problems = validate_schema(payload)
        self.assertTrue(any("reason" in p for p in problems))

    def test_left_unchanged_reason_must_be_string(self):
        payload = self._valid() | {"left_unchanged": [{"id": "CFG-1", "reason": 5}]}
        problems = validate_schema(payload)
        self.assertTrue(any("reason" in p for p in problems))

    def test_empty_reason_rejected(self):
        payload = self._valid() | {"left_unchanged": [{"id": "CFG-1", "reason": ""}]}
        problems = validate_schema(payload)
        self.assertTrue(any("reason" in p for p in problems))

    def test_whitespace_only_reason_rejected(self):
        # Найдешевша форма вакуумного задоволення I4 - перелічити всі id з
        # порожньою причиною. Семантику схема перевірити не може, форму - може.
        payload = self._valid() | {
            "left_unchanged": [{"id": "CFG-1", "reason": " \n\t"}]
        }
        problems = validate_schema(payload)
        self.assertTrue(any("reason" in p for p in problems))

    def test_empty_left_unchanged_list_is_valid(self):
        payload = {"flipped_to_done": [], "new_entries": [], "left_unchanged": []}
        self.assertEqual(validate_schema(payload), [])


class TestDispositionsAreDisjoint(unittest.TestCase):
    """Три списки - три ВЗАЄМОВИКЛЮЧНІ розпорядження одним id. Той самий id
    у двох списках - самосуперечність ("я змінив і не змінив цей запис"),
    а JSON агента існує саме для того, щоб бути достовірним звітом про те,
    що реально записано у файл.
    """

    def test_flipped_and_left_unchanged_overlap_rejected(self):
        payload = {
            "flipped_to_done": ["ARCH-5"],
            "new_entries": [],
            "left_unchanged": [unchanged("ARCH-5")],
        }
        problems = validate_schema(payload)
        self.assertTrue(any("ARCH-5" in p for p in problems))

    def test_new_entries_and_left_unchanged_overlap_rejected(self):
        payload = {
            "flipped_to_done": [],
            "new_entries": [
                {
                    "id": "ARCH-28",
                    "category": "ARCH",
                    "name": "н",
                    "description": "о",
                    "done": True,
                }
            ],
            "left_unchanged": [unchanged("ARCH-28")],
        }
        problems = validate_schema(payload)
        self.assertTrue(any("ARCH-28" in p for p in problems))

    def test_flipped_and_new_entries_overlap_rejected(self):
        payload = {
            "flipped_to_done": ["ARCH-28"],
            "new_entries": [
                {
                    "id": "ARCH-28",
                    "category": "ARCH",
                    "name": "н",
                    "description": "о",
                    "done": True,
                }
            ],
            "left_unchanged": [],
        }
        problems = validate_schema(payload)
        self.assertTrue(any("ARCH-28" in p for p in problems))

    def test_no_overlap_is_clean(self):
        payload = {
            "flipped_to_done": ["ARCH-5"],
            "new_entries": [
                {
                    "id": "ARCH-28",
                    "category": "ARCH",
                    "name": "н",
                    "description": "о",
                    "done": True,
                }
            ],
            "left_unchanged": [unchanged("CFG-1")],
        }
        self.assertEqual(validate_schema(payload), [])

    def test_duplicate_inside_one_list_is_not_an_overlap(self):
        # Повтор у ОДНОМУ списку - не суперечність, лише неохайність.
        # Схема не має права це відхиляти: I4 працює з множинами.
        payload = {
            "flipped_to_done": ["ARCH-5", "ARCH-5"],
            "new_entries": [],
            "left_unchanged": [],
        }
        self.assertEqual(validate_schema(payload), [])


class TestRunAllWithLeftUnchanged(unittest.TestCase):
    def test_honest_no_op_run_is_clean(self):
        # Наскрізний доказ ruling'у: агент нічого не змінив у реєстрі,
        # але звітував про кожен id - жодного порушення інваріантів.
        before = [entry("ARCH-23"), entry("CFG-1"), entry("CFG-2")]
        after = [entry("ARCH-23"), entry("CFG-1"), entry("CFG-2")]
        commits = [("83710aa", "Docs: ARCH-23, CFG-1, CFG-2 - знахідки")]
        payload = {
            "flipped_to_done": [],
            "new_entries": [],
            "left_unchanged": [
                unchanged("ARCH-23"),
                unchanged("CFG-1"),
                unchanged("CFG-2"),
            ],
        }
        self.assertEqual(run_all(before, after, commits, payload), [])


if __name__ == "__main__":
    unittest.main()
