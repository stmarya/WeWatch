"""Regression tests for dynamic participant controls."""

from pathlib import Path
import re
import unittest


class ClientControlTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("templates/index.html").read_text(encoding="utf-8")

    def test_dynamic_values_are_not_interpolated_into_inline_handlers(self):
        broken = re.findall(r'onclick="[^\"]*\$\{escapeJsString', self.source)
        self.assertEqual([], broken)

    def test_tile_actions_use_delegated_dispatch(self):
        for action in ("remote", "snapshot", "pin", "mute", "kick"):
            self.assertIn(f'data-client-action="{action}"', self.source)
        self.assertIn("function handleClientControlAction", self.source)
        self.assertIn("actions?.addEventListener('click'", self.source)

    def test_annotation_setup_runs_after_tile_is_attached(self):
        append_position = self.source.index("grid.appendChild(tile);")
        interaction_position = self.source.index("attachTileRemoteInteractions(tile, clientId);")
        self.assertLess(append_position, interaction_position)


if __name__ == "__main__":
    unittest.main()
