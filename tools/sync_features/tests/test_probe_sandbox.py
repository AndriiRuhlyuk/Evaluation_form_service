"""Тести для Fix A1 (Task 7): `_journal_denied` і `_leak_check_note`.

`probe_sandbox.py` до цього фіксу не мав жодного тесту взагалі - обидва
`query()`-режими вимагають мережі й живого CLI, тому TDD-звільнення (спец,
розділ 9) на весь модуль поширювалось помилково широко. `_journal_denied` і
`_leak_check_note` - чисті функції без мережі й без `guard.DECISIONS` як
глобального стану (приймають журнал параметром), тому покриваються тут.
"""

import unittest
from pathlib import Path

import guard
import probe_sandbox


class TestJournalDenied(unittest.TestCase):
    """`_journal_denied` - єдине джерело доказу денайлу (Fix A1). Кожен
    кейс перевіряє, що вердикт іде з журналу `decisions`, а НЕ з локального
    `guard.guard_decision`."""

    def test_targeted_call_denied_in_journal_is_true(self):
        tool_use = [("Read", {"file_path": ".env"})]
        decisions = [("Read", repr({"file_path": ".env"}), "DENY")]
        self.assertTrue(
            probe_sandbox._journal_denied(tool_use, decisions, "Read", ".env")
        )

    def test_targeted_call_allowed_in_journal_is_false(self):
        # Хук насправді ДОЗВОЛИВ - охоронець зламаний чи затінений.
        tool_use = [("Read", {"file_path": ".env"})]
        decisions = [("Read", repr({"file_path": ".env"}), "ALLOW")]
        self.assertFalse(
            probe_sandbox._journal_denied(tool_use, decisions, "Read", ".env")
        )

    def test_targeted_call_missing_from_journal_is_false(self):
        # Це і є сценарій "hook затінений для Read" з A1: tool_use стався,
        # але жодного запису про нього в журналі немає - хук не викликався.
        tool_use = [("Read", {"file_path": ".env"})]
        decisions: list[tuple[str, str, str]] = []
        self.assertFalse(
            probe_sandbox._journal_denied(tool_use, decisions, "Read", ".env")
        )

    def test_no_targeted_calls_is_false_not_vacuous_true(self):
        # attempted=False обробляється окремо викликачем (_verdict_for_op) -
        # ця функція сама по собі не повинна мовчки повертати True.
        tool_use: list[tuple[str, dict]] = []
        decisions: list[tuple[str, str, str]] = []
        self.assertFalse(
            probe_sandbox._journal_denied(tool_use, decisions, "Read", ".env")
        )

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
        self.assertTrue(
            probe_sandbox._journal_denied(tool_use, decisions, "Read", ".env")
        )

    def test_duplicate_targeted_calls_each_need_their_own_journal_entry(self):
        target_input = {"file_path": ".env"}
        tool_use = [("Read", target_input), ("Read", target_input)]
        # Лише ОДИН запис DENY у журналі на дві однакові цільові спроби -
        # другій спробі не має чим підтвердитись.
        decisions = [("Read", repr(target_input), "DENY")]
        self.assertFalse(
            probe_sandbox._journal_denied(tool_use, decisions, "Read", ".env")
        )

    def test_works_for_edit_dimension_too(self):
        # Той самий патерн застосований і до Edit (докстрінг Fix A1 у
        # probe_sandbox.py: "перевірити, чи той самий патерн ховається ще
        # десь у файлі" - ховався і в edit_denied).
        target_input = {"file_path": "working_form/services.py"}
        tool_use = [("Edit", target_input)]
        decisions = [("Edit", repr(target_input), "DENY")]
        self.assertTrue(
            probe_sandbox._journal_denied(
                tool_use, decisions, "Edit", "working_form/services.py"
            )
        )

    def test_long_repr_beyond_old_120_limit_still_matches(self):
        # Fix E (Task 7, ревʼю раунд 1): раніше guard.py обрізав repr до
        # 120 символів У МОМЕНТ ЗАПИСУ в DECISIONS - контролер виміряв живий
        # прогін, де repr довжиною 126 символів обрізався і губив хвіст
        # "s.py" з "working_form/services.py", тож ця функція (яка звіряє
        # РІВНІСТЬ рядків) не знаходила збігу і давала FAIL на реальному
        # DENY. Тестовий шлях тут навмисно довгий, щоб його repr сам
        # перевищував 120 символів.
        long_path = "working_form/" + "y" * 100 + "/services.py"
        target_input = {"file_path": long_path}
        full_repr = repr(target_input)
        self.assertGreater(len(full_repr), 120)

        tool_use = [("Edit", target_input)]

        # Журнал зберігає ПОВНИЙ repr (як тепер робить guard.py) - матч є.
        decisions_full = [("Edit", full_repr, "DENY")]
        self.assertTrue(
            probe_sandbox._journal_denied(tool_use, decisions_full, "Edit", long_path)
        )

        # Санітарна перевірка механізму: якби журнал і надалі зберігав
        # ОБРІЗАНИЙ рядок (стара поведінка guard.py до Fix E), матчу не
        # було б - саме так стара тавтологія маскувалась під "PASS", а
        # реальний денайл - під FAIL.
        decisions_truncated_old_style = [("Edit", full_repr[:120], "DENY")]
        self.assertFalse(
            probe_sandbox._journal_denied(
                tool_use, decisions_truncated_old_style, "Edit", long_path
            )
        )


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
