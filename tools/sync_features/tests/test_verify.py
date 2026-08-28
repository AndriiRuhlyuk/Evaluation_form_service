import unittest

from verify import (
    check_coverage,
    check_descriptions_intact,
    check_no_id_lost,
    check_parses,
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
