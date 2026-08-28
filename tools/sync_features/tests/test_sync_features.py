"""Тест для `_collect_result` (fix round 2, Finding A).

Уся обгортка `sync_features.py` TDD-exempt (спец, розділ 9: виклик агента
недетермінований, мокати `query()` заради мока сенсу немає) - крім цього
одного шматка. Контролер прямо попросив тест: `_collect_result` тепер несе
одразу два guardrail (R3c - `is_error` перевіряється ДО використання
`result`, і R5 - обробка помилок доводить ненульовий exit code), і без
тесту жоден з двох не має покриття. Фейковий async-ітератор замінює лише
`sync_features.query` - решта SDK не мокається взагалі.
"""

import unittest
from unittest import mock

from claude_agent_sdk import AssistantMessage, ProcessError, ResultError, ResultMessage

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
        # мусить пережити виняток, а error_note лишитись None, бо для
        # is_error-перевірки в main_sync другий шлях помилки не потрібен.
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
        self.assertIsNone(error_note)

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
        # Санітарна перевірка: except (ResultError, ProcessError) разом не є
        # мертвим кодом навпаки - ResultError є підкласом ProcessError, тому
        # цей assert документує, чому вистачило б і одного except ProcessError,
        # а обидва названо явно для читабельності (як і просив контролер).
        self.assertTrue(issubclass(ResultError, ProcessError))


if __name__ == "__main__":
    unittest.main()
