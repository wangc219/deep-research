from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parents[3] / "scripts" / "smoke_lightrag_innovation.py"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("smoke_lightrag_innovation", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_innovation_smoke_rejects_retired_local_models():
    module = _load_smoke_module()

    with pytest.raises(ValueError, match="禁止使用本地 LLM"):
        module._reject_local_model("local-lightrag:artifacts/qwen-7b")

    module._reject_local_model("siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash")


def test_project_model_client_uses_non_thinking_bounded_structured_extractor():
    module = _load_smoke_module()
    client = module.ProjectModelJSONClient(
        model_spec="siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash",
        timeout_seconds=120,
        max_output_tokens=4096,
    )

    assert client.extractor.options["model_spec"] == "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash"
    assert client.extractor.options["enable_thinking"] is False
    assert client.extractor.options["max_truncation_retries"] == 0
