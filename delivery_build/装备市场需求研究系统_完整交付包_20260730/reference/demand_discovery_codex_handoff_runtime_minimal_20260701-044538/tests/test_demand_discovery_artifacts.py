from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402


class DemandDiscoveryArtifactStoreTests(unittest.TestCase):
    def test_put_get_exists_and_deduplicates_by_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ArtifactStore(Path(tmp))

            first = store.put(
                "hello demand discovery",
                kind="html",
                meta={"url": "https://example.test/a"},
            )
            second = store.put(
                "hello demand discovery",
                kind="html",
                meta={"url": "https://example.test/a"},
            )

            self.assertEqual(first, second)
            self.assertTrue(store.exists(first))
            self.assertEqual(store.get_text(first), "hello demand discovery")
            self.assertEqual(store.get_meta(first)["url"], "https://example.test/a")
            self.assertEqual(first.split(":", 1)[0], "html")

    def test_missing_artifact_raises_key_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ArtifactStore(Path(tmp))

            with self.assertRaises(KeyError):
                store.get_text("text:missing00000000")


if __name__ == "__main__":
    unittest.main()
