import json
import unittest

from argus import llm
from tests.helpers import make_cfg


def walk_objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for v in node.values():
            yield from walk_objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_objects(v)


class SchemaTests(unittest.TestCase):
    def test_schemas_are_strict_compatible(self):
        """OpenAI strict mode (codex --output-schema) needs additionalProperties=false and every key required."""
        for name in ("news", "paper_screen", "paper_read"):
            schema = llm.load_schema(name)
            self.assertNotIn("$ref", json.dumps(schema), name)
            for obj in walk_objects(schema):
                self.assertIs(obj.get("additionalProperties"), False, name)
                self.assertEqual(set(obj["required"]), set(obj["properties"]), name)

    def test_validate(self):
        schema = llm.load_schema("paper_screen")
        good = {"trend": "t", "deep_read": [{"id": "1", "reason": "r", "topic_id": ""}], "glance": []}
        self.assertEqual(llm.validate(schema, good), [])
        bad = {"trend": 3, "deep_read": [{"id": "1", "reason": "r", "extra": 1}], "glance": []}
        errors = llm.validate(schema, bad)
        self.assertTrue(any("trend" in e for e in errors))
        self.assertTrue(any("topic_id" in e for e in errors))
        self.assertTrue(any("extra" in e for e in errors))
        stars = llm.load_schema("paper_read")["properties"]["stars"]
        self.assertEqual(llm.validate(stars, 6), ["$: 6 not in [1, 2, 3, 4, 5]"])
        self.assertTrue(llm.validate(stars, True))  # bool is not an integer here


class AgentBackendTests(unittest.TestCase):
    def test_request_then_resume(self):
        cfg = make_cfg()
        backend = llm.AgentBackend(cfg)
        with self.assertRaises(llm.NeedsAgent) as ctx:
            backend.structured("paper_screen", "PROMPT BODY", "paper_screen")
        req, resp = ctx.exception.pending[0]
        self.assertIn("PROMPT BODY", req.read_text())
        self.assertIn(str(resp), req.read_text())

        resp.write_text(json.dumps({"trend": "t", "deep_read": []}))  # invalid: missing glance
        with self.assertRaises(llm.NeedsAgent):
            backend.structured("paper_screen", "PROMPT BODY", "paper_screen")
        self.assertIn("glance", resp.with_name("paper_screen.errors.txt").read_text())

        resp.write_text(json.dumps({"trend": "t", "deep_read": [], "glance": []}))
        data, cost = backend.structured("paper_screen", "PROMPT BODY", "paper_screen")
        self.assertEqual(data["trend"], "t")
        self.assertFalse(resp.with_name("paper_screen.errors.txt").exists())

    def test_per_backend_models(self):
        cfg = make_cfg({"llm": {"claude-cli": {"model": "m-default", "models": {"paper_read": "m-read"}}}})
        self.assertEqual(cfg.model_for("claude-cli", "paper_read:2610.1"), "m-read")
        self.assertEqual(cfg.model_for("claude-cli", "news"), "m-default")
        self.assertEqual(cfg.model_for("codex-cli", "news"), "")


if __name__ == "__main__":
    unittest.main()
