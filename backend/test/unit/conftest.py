"""单元测试隔离模型统计副作用；真实写入由 integration 覆盖。"""

import pytest


@pytest.fixture(autouse=True)
def model_usage_records(monkeypatch):
    """捕获统一计量事件，防止单元测试污染部署数据库。"""
    rows = []
    monkeypatch.setattr("platform_core.repositories.model_call_repository.record_model_call", rows.append)
    return rows
