from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from platform_core.config.options import ensure_options_in_db, update_option_value
from platform_core.knowledge.parser.capabilities import PARSER_CAPABILITIES
from platform_core.knowledge.parser.result import ParsedBlock, ParsedDocument
from platform_core.services import ocr_service
from platform_core.storage.postgres.models_business import Base, ModelProvider


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await ensure_options_in_db(session)
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_task_resolution_uses_database_option(db_session):
    await update_option_value(
        db_session,
        "mineru_ocr_host_opts",
        {"server_url": "http://mineru-config:30001"},
        "tester",
    )

    resolved = await ocr_service.resolve_ocr_task_params({"ocr_engine": "mineru_ocr"}, db_session)

    assert resolved["_ocr_processor_kwargs"] == {"server_url": "http://mineru-config:30001/"}


@pytest.mark.asyncio
async def test_ocr_options_use_parser_metadata(db_session, monkeypatch):
    async def get_options(option, _db=None):
        assert option is ocr_service.system_options
        return {"default_ocr_engine": "rapid_ocr"}

    monkeypatch.setattr(type(ocr_service.system_options), "get", get_options)
    options = await ocr_service.get_ocr_options(db_session)

    assert options == {
        "default_engine": "rapid_ocr",
        "engines": [
            {
                "engine_id": engine_id,
                "service_name": capability.service_name,
                "display_name": capability.display_name,
                "supported_extensions": list(capability.supported_extensions),
            }
            for engine_id, capability in PARSER_CAPABILITIES.items()
        ],
    }
    assert options["engines"][0]["engine_id"] == "auto"
    assert options["engines"][0]["display_name"] == "智能路由（推荐）"


@pytest.mark.asyncio
async def test_auto_router_keeps_complex_documents_local_without_paddlex_configuration(
    db_session,
    monkeypatch,
):
    monkeypatch.delenv("PADDLEX_URI", raising=False)

    kwargs = await ocr_service._build_processor_kwargs(db_session, "auto")

    assert kwargs == {
        "scan_engine": "rapid_ocr",
        "complex_engines": ["docling_pdf", "rapid_ocr"],
        "engine_kwargs": {
            "rapid_ocr": {},
            "docling_pdf": {},
            "pp_structure_v3_ocr": {},
        },
    }


@pytest.mark.asyncio
async def test_auto_router_uses_configured_self_hosted_paddlex_for_complex_documents(
    db_session,
    monkeypatch,
):
    monkeypatch.delenv("PADDLEX_URI", raising=False)
    await update_option_value(
        db_session,
        "pp_structure_v3_ocr_host_opts",
        {"server_url": "http://paddlex-config:8080"},
        "tester",
    )

    kwargs = await ocr_service._build_processor_kwargs(db_session, "auto")

    assert kwargs == {
        "scan_engine": "rapid_ocr",
        "complex_engines": ["pp_structure_v3_ocr", "docling_pdf", "rapid_ocr"],
        "engine_kwargs": {
            "rapid_ocr": {},
            "docling_pdf": {},
            "pp_structure_v3_ocr": {"server_url": "http://paddlex-config:8080/"},
        },
    }


@pytest.mark.asyncio
async def test_deepseek_uses_provider_credentials_without_chat_models(db_session):
    provider = ModelProvider(
        provider_id="siliconflow-cn",
        display_name="SiliconFlow",
        provider_type="openai",
        base_url="https://provider.example/v1",
        is_enabled=True,
        api_key="provider-secret",
        api_key_env=None,
        capabilities=["embedding"],
        enabled_models=[{"id": "BAAI/bge-m3", "type": "embedding"}],
    )
    db_session.add(provider)
    await db_session.flush()

    resolved = await ocr_service.resolve_ocr_task_params({"ocr_engine": "deepseek_ocr"}, db_session)

    assert resolved["_ocr_processor_kwargs"] == {
        "api_key": "provider-secret",
        "api_url": "https://provider.example/v1/chat/completions",
    }


@pytest.mark.asyncio
async def test_health_checks_every_registered_ocr_method(db_session, monkeypatch):
    async def build_kwargs(db, engine_id):
        del db
        return {"engine": engine_id}

    monkeypatch.setattr(ocr_service, "_build_processor_kwargs", build_kwargs)
    monkeypatch.setattr(
        ocr_service.DocumentProcessorFactory,
        "check_health",
        lambda engine_id, **kwargs: {"status": "healthy", "message": kwargs["engine"]},
    )

    health = await ocr_service.check_all_ocr_health(db_session)

    assert set(health) == set(PARSER_CAPABILITIES)
    assert all(result["status"] == "healthy" for result in health.values())


@pytest.mark.asyncio
async def test_parse_boundary_replaces_postgres_invalid_nul_without_offset_drift(monkeypatch):
    parsed = ParsedDocument(
        markdown="雷达\x00抗干扰",
        parser_name="native_pdf",
        parser_version="parser-v1",
        source_metadata={"source": "local"},
        blocks=(ParsedBlock(start_char=0, end_char=6, page_number=1),),
    )

    async def parse_resolved_document_result(*, source, params):
        assert source == "/tmp/source.txt"
        assert params == {"purpose": "test"}
        return parsed

    monkeypatch.setattr(
        "platform_core.knowledge.parser.unified.parse_resolved_document_result",
        parse_resolved_document_result,
    )

    normalized = await ocr_service.parse_document_with_metadata(
        "/tmp/source.txt",
        params={"purpose": "test"},
    )

    assert normalized.markdown == "雷达�抗干扰"
    assert len(normalized.markdown) == len(parsed.markdown)
    assert normalized.blocks == parsed.blocks
    assert normalized.source_metadata == {
        "source": "local",
        "text_normalization": {
            "version": "postgres-text-v1",
            "nul_replacements": 1,
            "replacement": "U+FFFD",
            "offset_preserving": True,
        },
    }
