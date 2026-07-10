from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class DemandDiscoveryImportTests(unittest.TestCase):
    def test_package_imports(self) -> None:
        import knowledgegraph.demand_discovery as package
        import knowledgegraph.demand_discovery.harness as harness
        import knowledgegraph.demand_discovery.llm as llm
        import knowledgegraph.demand_discovery.domain as domain
        import knowledgegraph.demand_discovery.workers as workers

        self.assertEqual(package.__all__, ["harness", "llm", "domain", "workers"])
        self.assertIn("harness", harness.__name__)
        self.assertIn("llm", llm.__name__)
        self.assertIn("domain", domain.__name__)
        self.assertIn("workers", workers.__name__)


if __name__ == "__main__":
    unittest.main()
