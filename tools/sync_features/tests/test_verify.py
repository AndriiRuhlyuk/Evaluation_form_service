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
        payload = {"new_entries": []}
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
        payload = {"flipped_to_done": [], "new_entries": []}
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


if __name__ == "__main__":
    unittest.main()
