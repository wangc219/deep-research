"""文档模型请求覆盖成功、HTTP 失败和协议无效，且不记录原文。"""

from unittest.mock import Mock

import pytest

from platform_core.knowledge.parser.deepseek_ocr import DeepSeekOCRParser


@pytest.mark.parametrize(
    "status,payload,expected,error",
    [
        (200, {"choices": [{"message": {"content": "document"}}], "usage": {"total_tokens": 9}}, 9, False),
        (200, {"choices": [{"message": {"content": "document"}}]}, None, False),
        (403, {}, None, True),
        (200, {"choices": []}, None, True),
    ],
)
def test_ocr_model_call_is_accounted(monkeypatch, model_usage_records, status, payload, expected, error):
    response = Mock(status_code=status, text="unavailable")
    response.json.return_value = payload
    monkeypatch.setattr("platform_core.knowledge.parser.deepseek_ocr.requests.post", Mock(return_value=response))
    parser = DeepSeekOCRParser(api_key="test-key")
    if error:
        with pytest.raises(Exception):
            parser._call_api(b"private-image", "image/png", {})
    else:
        assert parser._call_api(b"private-image", "image/png", {}) == "document"
    assert len(model_usage_records) == 1
    row = model_usage_records[0]
    assert row["surface"] == "文档 OCR"
    assert row["model_spec"] == "siliconflow-cn:deepseek-ai/DeepSeek-OCR"
    assert row["status"] == ("failed" if error else "completed")
    assert row["total_tokens"] == expected
    assert "private-image" not in str(row)
    assert "test-key" not in str(row)
