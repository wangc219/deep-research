from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery import network_research  # noqa: E402


class DemandDiscoveryMainChainCleanupTests(unittest.TestCase):
    def test_network_research_module_exports_only_phase5_worker_executor(self) -> None:
        removed_names = [
            "NetworkResearchResult",
            "WhitelistExternalUrlExerciseResult",
            "run_network_research",
            "run_network_research_sync",
            "run_whitelist_external_url_exercise",
            "run_whitelist_external_url_exercise_sync",
            "format_network_research_result",
        ]

        for name in removed_names:
            self.assertFalse(hasattr(network_research, name), name)
        self.assertTrue(hasattr(network_research, "run_network_worker_round"))
        self.assertTrue(hasattr(network_research, "run_network_worker_round_sync"))

    def test_phase3_seed_url_cli_is_removed(self) -> None:
        self.assertFalse(
            (PROJECT_ROOT / "scripts" / "demand_discovery_network_research.py").exists()
        )


if __name__ == "__main__":
    unittest.main()
