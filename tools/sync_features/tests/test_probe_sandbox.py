"""Тести для Fix A1/E/G (Task 7): `_journal_denied`,
`_parse_journal_tool_input` і `_leak_check_note`.

`probe_sandbox.py` до цього фіксу не мав жодного тесту взагалі - обидва
`query()`-режими вимагають мережі й живого CLI, тому TDD-звільнення (спец,
розділ 9) на весь модуль поширювалось помилково широко. `_journal_denied`,
`_parse_journal_tool_input` і `_leak_check_note` - чисті функції без мережі
й без `guard.DECISIONS` як глобального стану (приймають журнал параметром),
тому покриваються тут.
"""

import unittest
from pathlib import Path

import guard
import probe_sandbox


class TestJournalDenied(unittest.TestCase):
    """`_journal_denied` - єдине джерело доказу денайлу (Fix A1). Кожен
    кейс перевіряє, що вердикт іде з журналу `decisions`, а НЕ з локального
    `guard.guard_decision`. Повертає `(denied, parse_errors)` (Fix G) -
    тести розпаковують обидва і за замовчуванням очікують `parse_errors ==
    []`, крім тестів, що явно перевіряють шлях помилки парсингу."""

    def test_targeted_call_denied_in_journal_is_true(self):
        tool_use = [("Read", {"file_path": ".env"})]
        decisions = [("Read", repr({"file_path": ".env"}), "DENY")]
        denied, errors = probe_sandbox._journal_denied(
            tool_use, decisions, "Read", ".env"
        )
        self.assertTrue(denied)
        self.assertEqual(errors, [])

    def test_targeted_call_allowed_in_journal_is_false(self):
        # Хук насправді ДОЗВОЛИВ - охоронець зламаний чи затінений.
        tool_use = [("Read", {"file_path": ".env"})]
        decisions = [("Read", repr({"file_path": ".env"}), "ALLOW")]
        denied, errors = probe_sandbox._journal_denied(
            tool_use, decisions, "Read", ".env"
        )
        self.assertFalse(denied)
        self.assertEqual(errors, [])

    def test_targeted_call_missing_from_journal_is_false(self):
        # Це і є сценарій "hook затінений для Read" з A1: tool_use стався,
        # але жодного запису про нього в журналі немає - хук не викликався.
        tool_use = [("Read", {"file_path": ".env"})]
        decisions: list[tuple[str, str, str]] = []
        denied, errors = probe_sandbox._journal_denied(
            tool_use, decisions, "Read", ".env"
        )
        self.assertFalse(denied)
        self.assertEqual(errors, [])

    def test_no_targeted_calls_is_false_not_vacuous_true(self):
        # attempted=False обробляється окремо викликачем (_verdict_for_op) -
        # ця функція сама по собі не повинна мовчки повертати True.
        tool_use: list[tuple[str, dict]] = []
        decisions: list[tuple[str, str, str]] = []
        denied, errors = probe_sandbox._journal_denied(
            tool_use, decisions, "Read", ".env"
        )
        self.assertFalse(denied)
        self.assertEqual(errors, [])

    def test_noise_call_does_not_consume_journal_entry_of_targeted_call(self):
        # Один виклик - шум (агент вигадав інший шлях), другий - цільовий.
        # Шумовий запис у журналі не повинен підмінити собою цільовий.
        noise_input = {"file_path": "nonexistent-dir/x"}
        target_input = {"file_path": ".env"}
        tool_use = [("Read", noise_input), ("Read", target_input)]
        decisions = [
            ("Read", repr(noise_input), "DENY"),
            ("Read", repr(target_input), "DENY"),
        ]
        denied, errors = probe_sandbox._journal_denied(
            tool_use, decisions, "Read", ".env"
        )
        self.assertTrue(denied)
        self.assertEqual(errors, [])

    def test_duplicate_targeted_calls_each_need_their_own_journal_entry(self):
        target_input = {"file_path": ".env"}
        tool_use = [("Read", target_input), ("Read", target_input)]
        # Лише ОДИН запис DENY у журналі на дві однакові цільові спроби -
        # другій спробі не має чим підтвердитись.
        decisions = [("Read", repr(target_input), "DENY")]
        denied, errors = probe_sandbox._journal_denied(
            tool_use, decisions, "Read", ".env"
        )
        self.assertFalse(denied)
        self.assertEqual(errors, [])

    def test_works_for_edit_dimension_too(self):
        # Той самий патерн застосований і до Edit (докстрінг Fix A1 у
        # probe_sandbox.py: "перевірити, чи той самий патерн ховається ще
        # десь у файлі" - ховався і в edit_denied).
        target_input = {"file_path": "working_form/services.py"}
        tool_use = [("Edit", target_input)]
        decisions = [("Edit", repr(target_input), "DENY")]
        denied, errors = probe_sandbox._journal_denied(
            tool_use, decisions, "Edit", "working_form/services.py"
        )
        self.assertTrue(denied)
        self.assertEqual(errors, [])

    def test_long_repr_beyond_old_120_limit_still_matches(self):
        # Fix E (Task 7, ревʼю раунд 1): раніше guard.py обрізав repr до
        # 120 символів У МОМЕНТ ЗАПИСУ в DECISIONS - контролер виміряв живий
        # прогін, де repr довжиною 126 символів обрізався і губив хвіст
        # "s.py" з "working_form/services.py". Тестовий шлях тут навмисно
        # довгий, щоб repr сам перевищував 120 символів; порядок ключів той
        # самий з обох боків, тому це кейс ЛИШЕ на обрізання, не на Fix G.
        long_path = "working_form/" + "y" * 100 + "/services.py"
        target_input = {"file_path": long_path}
        full_repr = repr(target_input)
        self.assertGreater(len(full_repr), 120)

        tool_use = [("Edit", target_input)]

        # Журнал зберігає ПОВНИЙ repr (як тепер робить guard.py) - матч є.
        denied, errors = probe_sandbox._journal_denied(
            tool_use, [("Edit", full_repr, "DENY")], "Edit", long_path
        )
        self.assertTrue(denied)
        self.assertEqual(errors, [])

    def test_real_measured_pair_read_absolute_vs_relative_path(self):
        # Fix G (Task 7, ревʼю раунд 2): РЕАЛЬНА виміряна контролером пара -
        # стрім ToolUseBlock несе ВІДНОСНИЙ шлях, який агент передав, а
        # журнал (вхід hook) несе шлях, який CLI вже РЕЗОЛЬВИЛА в абсолютний
        # ДО виклику hook. Рядкова рівність repr НІКОЛИ не могла збігтись -
        # це і було справжньою причиною FAIL, не обрізання (Fix E було
        # реальним, окремим дефектом).
        stream_input = {"file_path": ".env"}
        journal_input_repr = repr(
            {
                "file_path": "/Users/myda2/DRF_project/evaluation_form_service/"
                ".claude/worktrees/sdk-sync-features/.env"
            }
        )
        tool_use = [("Read", stream_input)]
        decisions = [("Read", journal_input_repr, "DENY")]

        denied, errors = probe_sandbox._journal_denied(
            tool_use, decisions, "Read", ".env"
        )
        self.assertTrue(denied)
        self.assertEqual(errors, [])

    def test_real_measured_pair_edit_differing_key_order(self):
        # Та сама виміряна пара, Edit-вимір: стрім і журнал несуть ОДНАКОВІ
        # ключі, але в РІЗНОМУ порядку (`replace_all` то перший, то
        # останній) - repr(dict) серіалізує в порядку вставки, тому рядки
        # відрізняються навіть коли dict-и семантично рівні.
        file_path = "working_form/services.py"
        stream_input = {
            "replace_all": False,
            "file_path": file_path,
            "old_string": "class X:",
            "new_string": "# probe\nclass X:",
        }
        journal_input = {
            "file_path": file_path,
            "old_string": "class X:",
            "new_string": "# probe\nclass X:",
            "replace_all": False,
        }
        # Санітарна перевірка передумови тесту: різний порядок ключів дає
        # різний repr, хоча dict-и рівні за ==.
        self.assertEqual(stream_input, journal_input)
        self.assertNotEqual(repr(stream_input), repr(journal_input))

        tool_use = [("Edit", stream_input)]
        decisions = [("Edit", repr(journal_input), "DENY")]

        denied, errors = probe_sandbox._journal_denied(
            tool_use, decisions, "Edit", "working_form/services.py"
        )
        self.assertTrue(denied)
        self.assertEqual(errors, [])

    def test_repr_equality_matching_would_have_failed_both_real_pairs(self):
        # Санітарна перевірка механізму (не тестує продуктовий код, лише
        # документує регресію): стара рядкова рівність на цих двох РЕАЛЬНИХ
        # парах ніколи не збіглась би - ні до Fix E (обрізання), ні після.
        journal_input_repr = repr(
            {
                "file_path": "/Users/myda2/DRF_project/evaluation_form_service/"
                ".claude/worktrees/sdk-sync-features/.env"
            }
        )
        stream_shown = repr({"file_path": ".env"})
        self.assertNotEqual(stream_shown, journal_input_repr)

    def test_unparseable_journal_entry_reported_not_silently_ignored(self):
        # Fix G, "fail loudly": запис журналу, який не вдається розпарсити
        # ast.literal_eval-ом, мусить зʼявитись у parse_errors, а не тихо
        # рахуватись як "не збіглось". Оскільки немає ІНШОГО запису для
        # цього tool_name, denied лишається False (ми не можемо ДОВЕСТИ
        # денайл) - але parse_errors НЕ порожній, і саме це відрізняє
        # "не знайшли" від "не змогли зрозуміти".
        tool_use = [("Read", {"file_path": ".env"})]
        decisions = [("Read", "{not valid python syntax:::", "DENY")]

        denied, errors = probe_sandbox._journal_denied(
            tool_use, decisions, "Read", ".env"
        )
        self.assertFalse(denied)
        self.assertEqual(len(errors), 1)
        self.assertIn("не розпарсився", errors[0])

    def test_unparseable_entry_does_not_block_match_on_another_entry(self):
        # Один запис не парситься (шум чи пошкоджені дані), другий -
        # реальний, семантично цільовий DENY. Пошук не повинен зупинятись
        # на першій невдачі парсингу.
        tool_use = [("Read", {"file_path": ".env"})]
        decisions = [
            ("Read", "{broken:::", "DENY"),
            ("Read", repr({"file_path": ".env"}), "DENY"),
        ]
        denied, errors = probe_sandbox._journal_denied(
            tool_use, decisions, "Read", ".env"
        )
        self.assertTrue(denied)
        self.assertEqual(len(errors), 1)


class TestParseJournalToolInput(unittest.TestCase):
    """`_parse_journal_tool_input` - розбір репрезентації журналу назад у
    dict (Fix G)."""

    def test_valid_dict_repr_parses(self):
        parsed, error = probe_sandbox._parse_journal_tool_input(
            repr({"file_path": ".env"})
        )
        self.assertEqual(parsed, {"file_path": ".env"})
        self.assertIsNone(error)

    def test_broken_syntax_reports_error_not_none_silently(self):
        parsed, error = probe_sandbox._parse_journal_tool_input("{not valid:::")
        self.assertIsNone(parsed)
        self.assertIsNotNone(error)
        self.assertIn("не розпарсився", error)

    def test_non_dict_literal_reports_error(self):
        parsed, error = probe_sandbox._parse_journal_tool_input("[1, 2, 3]")
        self.assertIsNone(parsed)
        self.assertIsNotNone(error)
        self.assertIn("не в dict", error)


class TestLeakCheckNote(unittest.TestCase):
    """Друга половина A1: leak-перевірка мусить називати себе вакуумною,
    коли `.env` не існує - "перевірка, що не може провалитись, не повинна
    виглядати як перевірка, що пройшла"."""

    def test_missing_env_file_is_vacuous(self):
        note = probe_sandbox._leak_check_note(Path("/nonexistent/.env"), [])
        self.assertIn("ВАКУУМНО", note)

    def test_existing_env_file_no_leak_is_ok(self):
        note = probe_sandbox._leak_check_note(Path(guard.__file__), [])
        self.assertNotIn("ВАКУУМНО", note)
        self.assertIn("OK", note)

    def test_existing_env_file_with_leak_reports_leak(self):
        note = probe_sandbox._leak_check_note(Path(guard.__file__), ["SECRET_KEY"])
        self.assertNotIn("ВАКУУМНО", note)
        self.assertIn("ВИТІК", note)


if __name__ == "__main__":
    unittest.main()


class TestVerdictForOp(unittest.TestCase):
    """Ревʼю раунд 6, minor: `_verdict_for_op` ігнорував `parse_errors`.

    Друк помилок парсингу журналу - лише половина "fail loudly"; поки
    вердикт на них не зважає, PASS може надрукуватись поруч із записами,
    яких перевірка НЕ ЗРОЗУМІЛА. Це слабша форма рівно того патерну, який
    Fix G існує щоб убити: "не зміг розібрати" не дорівнює "все гаразд".
    """

    def test_clean_pass(self):
        self.assertEqual(
            probe_sandbox._verdict_for_op(True, True, True, True, []), "PASS"
        )

    def test_parse_errors_block_pass(self):
        verdict = probe_sandbox._verdict_for_op(
            True, True, True, True, ["не розібрав рядок журналу"]
        )
        self.assertNotEqual(verdict, "PASS")

    def test_inconclusive_still_wins_over_parse_errors(self):
        # attempted=False означає, що судити нема чого взагалі - решта
        # флагів вакуумна, і помилки парсингу цього не змінюють.
        verdict = probe_sandbox._verdict_for_op(False, True, True, True, ["щось"])
        self.assertEqual(verdict, "INCONCLUSIVE")

    def test_real_fail_still_fails(self):
        self.assertEqual(
            probe_sandbox._verdict_for_op(True, False, True, True, []), "FAIL"
        )
