"""Тести охоронця дозволів. Кожен кейс - окрема дірка в пісочниці."""

import unittest

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


if __name__ == "__main__":
    unittest.main()
