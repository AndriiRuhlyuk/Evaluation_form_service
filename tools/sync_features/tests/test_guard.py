"""Тести охоронця дозволів. Кожен кейс - окрема дірка в пісочниці."""

import os
import unittest

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

    # --- білий список опцій git log не мусить блокувати легітимні форми ---

    def test_allowed_git_log_forms_still_pass(self):
        for command in (
            "git log --oneline -40",
            "git log --since=2026-08-01 --oneline",
            "git log --no-merges --format=%h",
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


class TestSelfCheck(unittest.TestCase):
    def test_self_check_passes_silently(self):
        self.assertIsNone(guard.self_check())


if __name__ == "__main__":
    unittest.main()
