"""採点器とメッセージ形式の単体テスト。モデルは呼ばない。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenario_runner import (  # noqa: E402
    build_user,
    encode_action,
    evaluate,
    first_url,
    resolve_system,
)
from compare_quants import fits_in_memory  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scenarios.catalog import SCENARIOS, SUITES  # noqa: E402


class EvaluateTest(unittest.TestCase):
    def test_include_exclude_and_regex(self):
        text = "root@demo:/app/project#\n12\n"
        self.assertEqual(
            evaluate(text, {"include": ["root@demo:/app/project#"], "regex": [r"(?m)^\s*12\s*$"]}),
            [],
        )
        self.assertTrue(evaluate(text, {"exclude": ["project#"]}))
        self.assertTrue(evaluate("nope", {"include_any": ["No such file", "not found"]}))
        self.assertEqual(evaluate("No such file", {"include_any": ["No such file", "not found"]}), [])
        self.assertTrue(evaluate("apple\n", {"exclude_regex": [r"(?m)^apple$"]}))
        self.assertEqual(evaluate("", {"allow_empty": True}), [])
        self.assertTrue(evaluate("", {}))

    def test_regex_any(self):
        self.assertEqual(
            evaluate("12 src/a.txt\n", {"regex_any": [r"(?m)^\s*12\s*$", r"(?m)^\s*12\s+src/a\.txt\s*$"]}),
            [],
        )
        self.assertTrue(evaluate("13\n", {"regex_any": [r"(?m)^\s*12\s*$"]}))

    def test_legacy_terminal_message(self):
        keys = "mkdir project && cd project\n"
        action = json.dumps([{"keystrokes": keys, "duration": 1.0}], ensure_ascii=False, indent=2)
        legacy = (
            "### Turn 1\n"
            "**Current State:**\nroot@demo:/app#\n\n"
            f"**Action:**\n```json\n{action}\n```\n"
            "**Environment Observation:**"
        )
        scenario = SCENARIOS["terminal_short"]
        body, lang = encode_action(scenario, scenario["turns"][0])
        got = build_user(scenario, scenario["turns"][0], 1, body, lang)
        self.assertEqual(got, legacy)
        second = build_user(scenario, scenario["turns"][1], 2, body, lang)
        self.assertNotIn("Current State", second)

    def test_swe_arguments_are_a_json_string(self):
        scenario = SCENARIOS["domain_swe"]
        body, lang = encode_action(scenario, scenario["turns"][0])
        payload = json.loads(body)
        self.assertEqual(lang, "json")
        self.assertIsInstance(payload["arguments"], str)
        self.assertIn("swe-token-9", json.loads(payload["arguments"])["content"])

    def test_tool_suffix_and_ui_task(self):
        mcp = SCENARIOS["domain_mcp"]
        body, lang = encode_action(mcp, mcp["turns"][0])
        message = build_user(mcp, mcp["turns"][0], 1, body, lang)
        self.assertIn("<predicted_observation>", message)
        self.assertNotIn("Current State", message)
        os_scenario = SCENARIOS["domain_os"]
        body, lang = encode_action(os_scenario, os_scenario["turns"][0])
        message = build_user(os_scenario, os_scenario["turns"][0], 2, body, lang)
        self.assertIn("**Task Instruction:**", message)
        self.assertIn("**Current State:**", message)
        self.assertIn("CalcTools.set_cell_value", message)

    def test_first_url(self):
        self.assertEqual(first_url("see https://example.com/a. and more"), "https://example.com/a")
        self.assertIsNone(first_url("no link"))

    def test_prompts_resolve(self):
        for scenario in SCENARIOS.values():
            text = resolve_system(scenario)
            self.assertNotIn("{tool_definitions}", text)
            self.assertNotIn("{demonstrations}", text)
            self.assertTrue(scenario["turns"])
            for turn in scenario["turns"]:
                self.assertIn("expect", turn)

    def test_suite_names_exist(self):
        for names in SUITES.values():
            for name in names:
                self.assertIn(name, SCENARIOS)

    def test_memory_gate(self):
        gib = 1024 ** 3
        ram = 36 * gib
        self.assertTrue(fits_in_memory(int(24.64 * gib), ram))
        self.assertFalse(fits_in_memory(int(34.37 * gib), ram))
        self.assertTrue(fits_in_memory(int(20.61 * gib), ram))


if __name__ == "__main__":
    unittest.main()
