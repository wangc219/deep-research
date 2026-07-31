from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PROJECT_ROOT / "scripts" / "extraction_experiment"
sys.path.insert(0, str(SCRIPT_ROOT))

import mineru_api_batch  # noqa: E402


class MinerUArtifactExtractionTests(unittest.TestCase):
    def test_extract_mineru_result_zip_saves_structured_artifacts(self) -> None:
        zip_bytes = self._make_zip(
            {
                "full.md": "# Parsed\n\nbody",
                "content_list.json": '[{"type":"text","page_idx":0}]',
                "middle.json": '{"pages": []}',
                "model.json": '{"model": "vlm"}',
                "images/figure-1.png": b"fake-png",
                "notes.txt": "not needed",
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_dir = Path(temp_dir) / "artifact"
            result = mineru_api_batch.extract_mineru_result_zip(zip_bytes, artifact_dir)

            self.assertEqual(result["markdown_text"], "# Parsed\n\nbody")
            self.assertEqual(result["markdown_zip_name"], "full.md")
            self.assertTrue((artifact_dir / "result.zip").exists())
            self.assertEqual(
                json.loads((artifact_dir / "content_list.json").read_text(encoding="utf-8")),
                [{"type": "text", "page_idx": 0}],
            )
            self.assertTrue((artifact_dir / "middle.json").exists())
            self.assertTrue((artifact_dir / "model.json").exists())
            self.assertEqual((artifact_dir / "images" / "figure-1.png").read_bytes(), b"fake-png")
            self.assertFalse((artifact_dir / "notes.txt").exists())

            manifest = json.loads((artifact_dir / "artifact_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["markdown_artifacts"], ["full.md"])
            self.assertEqual(
                manifest["json_artifacts"],
                ["content_list.json", "middle.json", "model.json"],
            )
            self.assertEqual(manifest["image_artifacts"], ["images/figure-1.png"])

    def test_extract_mineru_result_zip_skips_unsafe_paths(self) -> None:
        zip_bytes = self._make_zip(
            {
                "full.md": "# Safe",
                "../outside.json": "{}",
                "/absolute/model.json": "{}",
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact_dir = root / "artifact"
            result = mineru_api_batch.extract_mineru_result_zip(zip_bytes, artifact_dir)

            self.assertEqual(result["markdown_text"], "# Safe")
            self.assertFalse((root / "outside.json").exists())
            self.assertFalse((artifact_dir / "absolute" / "model.json").exists())
            self.assertEqual(result["skipped_artifacts"], ["../outside.json", "/absolute/model.json"])

    def test_download_mineru_result_zip_retries_transient_connection_error(self) -> None:
        zip_bytes = self._make_zip({"full.md": "# Retried"})

        class FakeResponse:
            content = zip_bytes

            def raise_for_status(self) -> None:
                return None

        class FakeSession:
            attempts = 0

            def get(self, url: str, timeout: int):
                self.__class__.attempts += 1
                if self.__class__.attempts == 1:
                    raise mineru_api_batch.requests.ConnectionError("reset")
                return FakeResponse()

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "mineru_api_batch.requests.Session",
            return_value=FakeSession(),
        ), patch("mineru_api_batch.time.sleep", return_value=None):
            result = mineru_api_batch._download_mineru_result_zip(
                "https://example.invalid/result.zip",
                Path(temp_dir) / "artifact",
            )

        self.assertEqual(FakeSession.attempts, 2)
        self.assertEqual(result["markdown_text"], "# Retried")

    def _make_zip(self, entries: dict[str, str | bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, value in entries.items():
                archive.writestr(name, value)
        return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
