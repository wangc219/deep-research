"""知识治理输入边界单元测试。"""

import pytest
from fastapi import HTTPException

from platform_core.services.knowledge_governance_service import (
    _collect_source_items_with_retry,
    claim_due_source_runs,
    sanitize_source_config,
    source_governance_enabled,
    validate_source_config,
)


@pytest.mark.parametrize(
    "config",
    [
        {"password": "plaintext"},
        {"connection": {"db_password": "plaintext"}},
        {"headers": [{"authorization": "Bearer plaintext"}]},
        {"search": {"provider_api_key": "plaintext"}},
    ],
)
def test_source_config_rejects_nested_credentials(config) -> None:
    """来源配置任意层级都不能夹带连接凭据。"""
    with pytest.raises(HTTPException, match="必须放入 credential") as caught:
        sanitize_source_config(config)
    assert caught.value.status_code == 422


def test_source_config_keeps_safe_mapping() -> None:
    """表字段映射、过滤和关注主题保持原结构。"""
    config = {
        "table": "public_documents",
        "content_columns": ["title", "body"],
        "filters": [{"column": "status", "operator": "eq", "value": "published"}],
        "topics": ["无人系统", "反无人系统"],
    }
    assert sanitize_source_config(config) is config


def test_database_source_rejects_arbitrary_sql() -> None:
    with pytest.raises(HTTPException, match="不接受任意 SQL") as caught:
        validate_source_config(
            "postgresql",
            {
                "sql": "select * from secrets",
                "table": "documents",
                "primary_key": "id",
                "content_columns": ["body"],
            },
        )
    assert caught.value.status_code == 422


def test_website_source_rejects_login_state() -> None:
    with pytest.raises(HTTPException, match="不支持登录态"):
        validate_source_config(
            "website",
            {"urls": ["https://example.com"], "headers": {"X-Token": "value"}},
        )


@pytest.mark.asyncio
async def test_source_collection_retries_with_bounded_attempts(monkeypatch) -> None:
    attempts = 0

    async def collect(_source_type, _config, _credential):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("temporary")
        return [{"title": "ok"}]

    class Context:
        def __init__(self):
            self.progress = []

        async def raise_if_cancelled(self):
            return None

        async def set_progress(self, value, message):
            self.progress.append((value, message))

    context = Context()
    monkeypatch.setattr(
        "platform_core.services.knowledge_governance_service.collect_source_items",
        collect,
    )

    items, collection_attempts = await _collect_source_items_with_retry(
        "web_search",
        {"max_retries": 2, "retry_delay_seconds": 0},
        None,
        context,
    )

    assert items == [{"title": "ok"}]
    assert collection_attempts == 3
    assert len(context.progress) == 2


@pytest.mark.asyncio
async def test_cloud_disables_source_governance_scheduler_without_database_access(monkeypatch) -> None:
    """云端开关关闭后，worker 不得扫描或创建来源采集任务。"""
    monkeypatch.setenv("DEEP_RESEARCH_SOURCE_GOVERNANCE_ENABLED", "false")

    assert source_governance_enabled() is False
    assert await claim_due_source_runs() == 0
