import unittest
from workspace_tool.mcp import tools_list, dispatch


class McpTests(unittest.TestCase):
    def test_four_bounded_tools_no_shell_or_global_approval(self):
        tools = tools_list()
        self.assertEqual({t["name"] for t in tools}, {"capabilities_find", "capabilities_describe", "capabilities_call", "ui_present"})
        for t in tools:
            self.assertFalse(t["inputSchema"].get("additionalProperties", True))

    def test_initialize_and_unknown_method(self):
        self.assertIn("protocolVersion", dispatch("initialize", {"protocolVersion": "2024-11-05"}, None))
        with self.assertRaises(ValueError): dispatch("unregistered", {}, None)
