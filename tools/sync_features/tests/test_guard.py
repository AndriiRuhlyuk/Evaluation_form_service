"""Тести охоронця дозволів. Кожен кейс - окрема дірка в пісочниці."""

import os
import tempfile
import unittest
from unittest import mock

import guard
from guard import guard_decision


class TestBashRules(unittest.TestCase):
    def test_git_log_allowed(self):
        allowed, _ = guard_decision("Bash", {"command": "git log --oneline -40"})
        self.assertTrue(allowed)

    def test_leading_whitespace_still_allowed(self):
        allowed, _ = guard_decision("Bash", {"command": "  git log -1  "})
        self.assertTrue(allowed)

    def test_echo_denied(self):
        allowed, reason = guard_decision("Bash", {"command": "echo GATE_9137"})
        self.assertFalse(allowed)
        self.assertIn("git log", reason)

    def test_chained_command_denied(self):
        # найважливіший кейс: префікс правильний, а команда шкідлива
        allowed, _ = guard_decision("Bash", {"command": "git log; rm -rf ."})
        self.assertFalse(allowed)

    def test_substitution_denied(self):
        allowed, _ = guard_decision("Bash", {"command": "git log $(whoami)"})
        self.assertFalse(allowed)

    def test_redirect_denied(self):
        allowed, _ = guard_decision("Bash", {"command": "git log > /tmp/out"})
        self.assertFalse(allowed)

    def test_missing_command_key_denied(self):
        allowed, _ = guard_decision("Bash", {})
        self.assertFalse(allowed)

    # --- C1: --output та інші опції git log, що дозволяють довільний запис ---

    def test_output_option_denied(self):
        allowed, _ = guard_decision(
            "Bash", {"command": "git log --output=settings.py -1 --oneline"}
        )
        self.assertFalse(allowed)

    def test_ext_diff_denied(self):
        allowed, _ = guard_decision("Bash", {"command": "git log -p --ext-diff"})
        self.assertFalse(allowed)

    # --- I1: git loga не має пройти як git log ---

    def test_git_loga_denied(self):
        allowed, _ = guard_decision("Bash", {"command": "git loga"})
        self.assertFalse(allowed)

    # --- I2: нерядкові / не-словникові входи мусять відмовляти, а не падати ---

    def test_non_string_command_denied(self):
        for value in (None, 42, ["git", "log"]):
            allowed, _ = guard_decision("Bash", {"command": value})
            self.assertFalse(allowed)

    def test_non_dict_input_denied(self):
        allowed, _ = guard_decision("Bash", None)
        self.assertFalse(allowed)

    # --- NEW-1: обхід білого списку опцій через ANSI-C quoting bash ($'...') ---

    def test_ansi_c_quoting_denied(self):
        allowed, _ = guard_decision(
            "Bash", {"command": "git log --oneline $'\\x2d\\x2doutput=/tmp/x'"}
        )
        self.assertFalse(allowed)

    def test_dollar_forms_denied(self):
        for command in (
            "git log ${IFS}",
            "git log --oneline $HOME",
            "git log $(whoami)",
        ):
            allowed, _ = guard_decision("Bash", {"command": command})
            self.assertFalse(allowed, command)

    # --- NEW-3: "--" (pathspec separator) має лишитись прохідним ---

    def test_pathspec_separator_allowed(self):
        allowed, reason = guard_decision(
            "Bash", {"command": "git log --oneline -- Features_list.json"}
        )
        self.assertTrue(allowed, reason)

    # --- білий список опцій git log не мусить блокувати легітимні форми ---

    def test_allowed_git_log_forms_still_pass(self):
        for command in (
            "git log --oneline -40",
            "git log --since=2026-08-01 --oneline",
            "git log --no-merges --format=%h",
            "git log --oneline -3",
        ):
            allowed, reason = guard_decision("Bash", {"command": command})
            self.assertTrue(allowed, f"{command}: {reason}")


class TestReadRules(unittest.TestCase):
    def test_registry_allowed(self):
        allowed, _ = guard_decision("Read", {"file_path": "Features_list.json"})
        self.assertTrue(allowed)

    def test_services_allowed(self):
        allowed, _ = guard_decision("Read", {"file_path": "working_form/services.py"})
        self.assertTrue(allowed)

    def test_env_denied(self):
        allowed, _ = guard_decision("Read", {"file_path": ".env"})
        self.assertFalse(allowed)

    def test_key_file_denied(self):
        allowed, _ = guard_decision("Read", {"file_path": "certs/server.key"})
        self.assertFalse(allowed)

    def test_traversal_to_env_denied(self):
        allowed, _ = guard_decision("Read", {"file_path": "working_form/../.env"})
        self.assertFalse(allowed)

    # --- I3: fnmatch("*/services.py") бачив будь-яку глибину вкладеності ---

    def test_deep_services_path_denied(self):
        allowed, _ = guard_decision(
            "Read", {"file_path": ".venv/lib/python3.13/site-packages/x/services.py"}
        )
        self.assertFalse(allowed)

    # --- I4: абсолютні шляхи в межах репозиторію мусять проходити ---

    def test_absolute_registry_path_allowed(self):
        # шлях кореня підстав реальний, обчислений від guard.REPO_ROOT
        allowed, _ = guard_decision(
            "Read", {"file_path": os.path.join(guard.REPO_ROOT, "Features_list.json")}
        )
        self.assertTrue(allowed)

    def test_absolute_outside_repo_denied(self):
        allowed, _ = guard_decision("Read", {"file_path": "/etc/passwd"})
        self.assertFalse(allowed)

    def test_non_string_file_path_denied(self):
        allowed, _ = guard_decision("Read", {"file_path": 42})
        self.assertFalse(allowed)

    # --- I3, залишок: рівно один "/" виконано буквально, але .git службовий ---

    def test_dot_directory_services_denied(self):
        allowed, _ = guard_decision("Read", {"file_path": ".git/services.py"})
        self.assertFalse(allowed)


class TestEditRules(unittest.TestCase):
    def test_registry_allowed(self):
        allowed, _ = guard_decision("Edit", {"file_path": "Features_list.json"})
        self.assertTrue(allowed)

    def test_settings_denied(self):
        allowed, _ = guard_decision(
            "Edit", {"file_path": "evaluation_form_service/settings.py"}
        )
        self.assertFalse(allowed)


class TestUnknownTools(unittest.TestCase):
    def test_write_denied(self):
        allowed, _ = guard_decision("Write", {"file_path": "Features_list.json"})
        self.assertFalse(allowed)

    def test_webfetch_denied(self):
        allowed, _ = guard_decision("WebFetch", {"url": "https://example.com"})
        self.assertFalse(allowed)


class TestPreToolUseHook(unittest.IsolatedAsyncioTestCase):
    """M4: hook, DECISIONS і форма hookSpecificOutput раніше не мали тестів."""

    def setUp(self):
        guard.DECISIONS.clear()

    async def test_allowed_input_returns_allow(self):
        result = await guard.pre_tool_use_hook(
            {"tool_name": "Bash", "tool_input": {"command": "git log -1"}},
            "tool-use-1",
            {},
        )
        output = result["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "allow")

    async def test_denied_input_returns_deny(self):
        result = await guard.pre_tool_use_hook(
            {"tool_name": "Bash", "tool_input": {"command": "echo hi"}},
            "tool-use-2",
            {},
        )
        output = result["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")

    async def test_hook_fills_decisions_log(self):
        self.assertEqual(guard.DECISIONS, [])
        await guard.pre_tool_use_hook(
            {"tool_name": "Bash", "tool_input": {"command": "git log -1"}},
            "tool-use-3",
            {},
        )
        self.assertEqual(len(guard.DECISIONS), 1)
        tool_name, _, verdict = guard.DECISIONS[0]
        self.assertEqual(tool_name, "Bash")
        self.assertEqual(verdict, "ALLOW")

    async def test_hook_never_raises_on_broken_input(self):
        # input_data сам не є словником - .get() усередині впав би винятком
        result = await guard.pre_tool_use_hook(None, "tool-use-4", {})
        output = result["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")

    async def test_hook_survives_broken_stderr(self):
        # NEW-2: попередній try закінчувався до логування, тому падіння
        # print(..., file=sys.stderr) вибивало виняток із hook без жодного
        # рішення (ні allow, ні deny). Тепер вхід легітимний, але stderr
        # зламаний - hook мусить повернути deny, а не підняти виняток.
        class BrokenStderr:
            def write(self, _data):
                raise OSError("stderr зламано")

            def flush(self):
                pass

        with mock.patch("sys.stderr", BrokenStderr()):
            result = await guard.pre_tool_use_hook(
                {"tool_name": "Bash", "tool_input": {"command": "git log -1"}},
                "tool-use-5",
                {},
            )
        output = result["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")

    async def test_broken_stderr_journal_matches_returned_decision(self):
        # Обов'язок 1 (Task 6): раніше DECISIONS.append ішов ДО print у
        # тому самому try, тому падіння print лишало в журналі запис ALLOW,
        # хоча hook повернув deny. "git log -1" сам по собі був би ALLOW -
        # якщо цей тест провалюється з verdict="ALLOW", стара помилка
        # повернулась.
        class BrokenStderr:
            def write(self, _data):
                raise OSError("stderr зламано")

            def flush(self):
                pass

        with mock.patch("sys.stderr", BrokenStderr()):
            result = await guard.pre_tool_use_hook(
                {"tool_name": "Bash", "tool_input": {"command": "git log -1"}},
                "tool-use-6",
                {},
            )
        output = result["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertEqual(len(guard.DECISIONS), 1)
        tool_name, _, verdict = guard.DECISIONS[0]
        self.assertEqual(tool_name, "Bash")
        self.assertEqual(verdict, "DENY")

    async def test_decisions_log_keeps_full_repr_not_truncated(self):
        # Fix E (Task 7, ревʼю раунд 1): раніше DECISIONS.append обрізав
        # repr(tool_input) до 120 символів У МОМЕНТ ЗАПИСУ. Контролер
        # виміряв живий прогін, де repr довжиною 126 символів обрізався до
        # 120 і губив хвіст "services.py" - probe_sandbox._journal_denied
        # (звіряє журнал за рівністю repr) не знаходив збігу і давав FAIL
        # на реальному DENY. Цей тест з умисним ДОВГИМ file_path провалився
        # б під старою поведінкою (guard.DECISIONS[0][1] мав би довжину
        # 120, а не повний рядок).
        long_path = "working_form/" + "x" * 100 + "/services.py"
        tool_input = {"file_path": long_path}
        full_repr = repr(tool_input)
        self.assertGreater(
            len(full_repr), 120, "тестовий input мусить сам перевищувати старий ліміт"
        )

        await guard.pre_tool_use_hook(
            {"tool_name": "Edit", "tool_input": tool_input},
            "tool-use-7",
            {},
        )

        self.assertEqual(len(guard.DECISIONS), 1)
        _, shown, _ = guard.DECISIONS[0]
        self.assertEqual(shown, full_repr)
        self.assertIn("services.py", shown)


class TestSelfCheck(unittest.TestCase):
    def test_self_check_passes_silently(self):
        self.assertIsNone(guard.self_check())

    def test_self_check_fails_when_registry_missing(self):
        # REPO_ROOT обчислюється з розташування guard.py; якщо файл
        # перемістити, нормалізація тихо перейде на інше дерево - self_check
        # мусить це ловити явною перевіркою існування REGISTRY_PATH.
        original_root = guard.REPO_ROOT
        with tempfile.TemporaryDirectory() as tmp_dir:
            guard.REPO_ROOT = tmp_dir
            try:
                with self.assertRaises(SystemExit):
                    guard.self_check()
            finally:
                guard.REPO_ROOT = original_root


if __name__ == "__main__":
    unittest.main()
