"""Guard dependency direction as the application grows."""

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "my_package"


class ArchitectureTests(unittest.TestCase):
    def test_layers_only_import_allowed_dependencies(self) -> None:
        allowed = {
            "domain": {"domain"},
            "application": {"domain", "application"},
            "infrastructure": {"domain", "infrastructure"},
        }
        for layer, dependencies in allowed.items():
            for path in (ROOT / layer).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    modules = []
                    if isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        self.assertEqual(node.level, 0, f"Use absolute imports: {path}")
                        modules = [node.module or ""]
                    for module in modules:
                        with self.subTest(path=path.name, module=module):
                            parts = module.split(".")
                            if parts[0] == "my_package":
                                self.assertGreater(len(parts), 1)
                                self.assertIn(parts[1], dependencies)
                            elif layer in {"domain", "application"}:
                                self.assertIn(parts[0], sys.stdlib_module_names)
