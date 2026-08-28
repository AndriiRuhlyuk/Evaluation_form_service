"""Тест для `_collect_result` (fix round 2, Finding A; Fix A3, Task 7).

Уся обгортка `sync_features.py` TDD-exempt (спец, розділ 9: виклик агента
недетермінований, мокати `query()` заради мока сенсу немає) - крім цього
одного шматка. Контролер прямо попросив тест: `_collect_result` тепер несе
одразу два guardrail (R3c - `is_error` перевіряється ДО використання
`result`, і R5 - обробка помилок доводить ненульовий exit code), і без
тесту жоден з двох не має покриття. Фейковий async-ітератор замінює лише
`sync_features.query` - решта SDK не мокається взагалі.

Fix A3 (Task 7): `error_note` тепер заповнюється БЕЗУМОВНО, коли виняток
стався - навіть якщо `result_message` уже заповнений (раніше `error_note`
лишався `None` у цьому випадку, і аномалія процесу губилась). Тест
`test_result_error_after_result_message_falls_through` оновлено під нову
поведінку.

`TestWriteJournal` нижче - друге виключення з TDD-exempt: `_write_journal`
не викликає `query()` взагалі, це чиста I/O-функція, тому Fix A2 (розділ
`## Покриття`), Fix A3 (розділ `## Аномалії процесу`) і Fix A4
(`errors="replace"` на биті байти) отримують покриття тут вперше.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_agent_sdk import (
    AssistantMessage,
    CLIJSONDecodeError,
    ProcessError,
    ResultError,
    ResultMessage,
)

import guard
import sync_features


def _result_message(is_error=False, subtype="success", result=None):
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="fake-session",
        result=result,
    )


class TestCollectResult(unittest.IsolatedAsyncioTestCase):
    async def test_normal_completion_returns_result_message(self):
        rm = _result_message(is_error=False, result="{}")

        async def fake_query(prompt, options):
            yield AssistantMessage(content=[], model="claude-haiku-4-5")
            yield rm

        with mock.patch.object(sync_features, "query", fake_query):
            result_message, error_note = await sync_features._collect_result("p", None)

        self.assertIs(result_message, rm)
        self.assertIsNone(error_note)

    async def test_result_error_after_result_message_falls_through(self):
        # Finding A: SDK доставляє ResultMessage(is_error=True), і ЛИШЕ на
        # НАСТУПНІЙ ітерації async for кидає ResultError - result_message
        # мусить пережити виняток. Fix A3 (Task 7): error_note тепер
        # заповнюється БЕЗУМОВНО, навіть коли result_message вже є - раніше
        # він лишався None саме в цьому випадку, і аномалія процесу
        # (виняток ПІСЛЯ success/error-фрейму) губилась без сліду.
        rm = _result_message(is_error=True, subtype="error_max_turns")

        async def fake_query(prompt, options):
            yield rm
            raise ResultError(
                "Reached maximum number of turns (1)",
                data={"subtype": "error_max_turns"},
            )
            yield  # недосяжно: лише щоб fake_query лишався async-генератором

        with mock.patch.object(sync_features, "query", fake_query):
            result_message, error_note = await sync_features._collect_result("p", None)

        self.assertIs(result_message, rm)
        self.assertTrue(result_message.is_error)
        self.assertEqual(result_message.subtype, "error_max_turns")
        self.assertIsNotNone(error_note)
        self.assertIn("ResultError", error_note)

    async def test_process_error_before_any_result_message(self):
        async def fake_query(prompt, options):
            raise ProcessError("CLI process failed", exit_code=1)
            yield  # недосяжно: лише щоб fake_query лишався async-генератором

        with mock.patch.object(sync_features, "query", fake_query):
            result_message, error_note = await sync_features._collect_result("p", None)

        self.assertIsNone(result_message)
        self.assertIsNotNone(error_note)
        self.assertIn("ProcessError", error_note)

    async def test_result_error_is_a_process_error_subclass(self):
        # Санітарна перевірка, лишена від попередньої версії except-у:
        # ResultError є підкласом ProcessError, і обидва - підкласи
        # ClaudeSDKError (Fix A3), яку зараз ловить _collect_result.
        self.assertTrue(issubclass(ResultError, ProcessError))

    async def test_cli_json_decode_error_now_caught_not_escaping(self):
        # Fix A3 (Task 7): раніше except ловив лише (ResultError,
        # ProcessError) - CLIJSONDecodeError втікав би traceback-ом до
        # самого верху, і жоден артефакт не персистувався б. Тепер спільний
        # ClaudeSDKError ловить і цей клас теж.
        async def fake_query(prompt, options):
            raise CLIJSONDecodeError("not json", ValueError("bad token"))
            yield  # недосяжно: лише щоб fake_query лишався async-генератором

        with mock.patch.object(sync_features, "query", fake_query):
            result_message, error_note = await sync_features._collect_result("p", None)

        self.assertIsNone(result_message)
        self.assertIsNotNone(error_note)
        self.assertIn("CLIJSONDecodeError", error_note)


class TestWriteJournal(unittest.TestCase):
    """`_write_journal` - чиста I/O-функція без `query()`, тому TDD-exempt
    з докстрінга модуля її не стосується. Покриває Fix A2 (Task 7,
    `## Покриття` повернуто в звіт), Fix A3 (`## Аномалії процесу`) і
    Fix A4 (`errors="replace"` на биті байти реєстру)."""

    def setUp(self):
        guard.DECISIONS.clear()
        self.addCleanup(guard.DECISIONS.clear)
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.out_dir = Path(self._tmpdir.name) / "out"
        self.registry_path = Path(self._tmpdir.name) / "Features_list.json"
        self.registry_path.write_text('{"features": []}', encoding="utf-8")

    def _report_text(self) -> str:
        return (self.out_dir / "sync-report.md").read_text(encoding="utf-8")

    def test_coverage_section_present_and_correct(self):
        # Fix A2: розділ ## Покриття мусить існувати і містити той самий
        # рядок, що рахує gitscan.coverage_line - одне джерело правди з
        # main_sync (Fix 7), тепер підтверджене з боку журналу теж.
        commits = [("abc123", "Fix: ARCH-1 щось полагоджено")]
        sync_features._write_journal(
            self.out_dir,
            self.registry_path,
            '{"features": []}',
            "2026-08-29-000000",
            "успішно",
            commits,
            payload={"flipped_to_done": ["ARCH-1"], "new_entries": []},
        )
        report = self._report_text()
        self.assertIn("## Покриття", report)
        self.assertIn("1 commits in range, 1 reference a feature id", report)
        self.assertIn("agent answer mentions 1 ids", report)

    def test_coverage_section_present_with_no_payload(self):
        # Ранні error-шляхи (payload=None) досі мають мати розділ покриття,
        # лише з "mentions 0 ids" - не мовчати про нього повністю.
        sync_features._write_journal(
            self.out_dir,
            self.registry_path,
            '{"features": []}',
            "2026-08-29-000000",
            "агент не повернув ResultMessage",
            [("abc123", "Fix: ARCH-1 щось")],
        )
        report = self._report_text()
        self.assertIn("## Покриття", report)
        self.assertIn("agent answer mentions 0 ids", report)

    def test_process_note_section_present_when_set(self):
        # Fix A3: аномалія процесу мусить бути видима в персистованому
        # звіті, не лише в скороминущому stderr.
        sync_features._write_journal(
            self.out_dir,
            self.registry_path,
            '{"features": []}',
            "2026-08-29-000000",
            "успішно",
            [],
            process_note="ProcessError: crashed after success frame",
        )
        report = self._report_text()
        self.assertIn("## Аномалії процесу", report)
        self.assertIn("ProcessError: crashed after success frame", report)

    def test_process_note_absent_shows_none_marker(self):
        sync_features._write_journal(
            self.out_dir,
            self.registry_path,
            '{"features": []}',
            "2026-08-29-000000",
            "успішно",
            [],
        )
        report = self._report_text()
        self.assertIn("## Аномалії процесу\n\n(немає)", report)

    def test_non_utf8_registry_bytes_do_not_raise(self):
        # Fix A4: агент лишив биті байти в Features_list.json - persist()
        # не повинен бути тим, що вбиває запуск traceback-ом саме на цьому
        # прогоні.
        self.registry_path.write_bytes(b'{"features": [\xff\xfe]}')
        try:
            sync_features._write_journal(
                self.out_dir,
                self.registry_path,
                '{"features": []}',
                "2026-08-29-000000",
                "інваріант I1 порушено",
                [],
            )
        except UnicodeDecodeError:
            self.fail("_write_journal підняв UnicodeDecodeError на биті байти")
        self.assertTrue((self.out_dir / "sync-report.md").exists())
        self.assertTrue((self.out_dir / "features.patch").exists())


if __name__ == "__main__":
    unittest.main()
