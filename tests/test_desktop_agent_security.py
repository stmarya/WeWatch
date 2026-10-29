import unittest
from unittest.mock import Mock, patch

import desktop_agent


class DesktopAgentSecurityTests(unittest.TestCase):
    def test_remote_agent_requires_https(self):
        self.assertEqual(
            desktop_agent._validate_server_url("http://localhost:5001"),
            "http://localhost:5001",
        )
        self.assertEqual(
            desktop_agent._validate_server_url("https://rtc.example.com"),
            "https://rtc.example.com",
        )
        with self.assertRaises(ValueError):
            desktop_agent._validate_server_url("http://rtc.example.com")
        with self.assertRaises(ValueError):
            desktop_agent._validate_server_url("https://user:pass@rtc.example.com")
        with self.assertRaises(ValueError):
            desktop_agent._validate_server_url("https://rtc.example.com/socket")

    def test_keyboard_hotkeys_are_allowlisted(self):
        fake_desktop = Mock()
        with patch.object(desktop_agent, "pyautogui", fake_desktop):
            desktop_agent.execute_command(
                "key_input",
                {"type": "hotkey", "value": "ctrl+c"},
            )
            fake_desktop.hotkey.assert_called_once_with("ctrl", "c")
            with self.assertRaises(ValueError):
                desktop_agent.execute_command(
                    "key_input",
                    {"type": "hotkey", "value": "ctrl+alt+delete"},
                )

    def test_screenshot_requires_explicit_opt_in(self):
        with patch.object(desktop_agent, "ALLOW_SCREENSHOTS", False):
            with self.assertRaises(PermissionError):
                desktop_agent.execute_command(
                    "quick_action",
                    {"action": "capture_screen"},
                )


if __name__ == "__main__":
    unittest.main()