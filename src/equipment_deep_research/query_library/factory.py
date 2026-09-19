from __future__ import annotations

import os
from pathlib import Path

from equipment_deep_research.config.settings import Settings, load_settings
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.providers.registry import ProviderRegistry
from equipment_deep_research.query_library.generator import ModelQueryGenerator
from equipment_deep_research.query_library.credentials import EncryptedCredentialStore
from equipment_deep_research.query_library.persistence import QueryLibraryRepository
from equipment_deep_research.query_library.service import QueryLibraryService


def project_root() -> Path:
    return load_settings().paths.root


def default_database_url() -> str:
    return load_settings().query_library_database_url


def build_repository(
    database_url: str | None = None,
    *,
    settings: Settings | None = None,
) -> QueryLibraryRepository:
    resolved_settings = settings or load_settings()
    url = database_url or resolved_settings.query_library_database_url
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).expanduser().parent.mkdir(
            parents=True, exist_ok=True
        )
    return QueryLibraryRepository(create_database_engine(url))


def build_service(
    database_url: str | None = None,
    *,
    with_generator: bool = False,
    provider_name: str | None = None,
    settings: Settings | None = None,
) -> QueryLibraryService:
    resolved_settings = settings or load_settings()
    repository = build_repository(settings=resolved_settings, database_url=database_url)
    root = resolved_settings.paths.root
    artifact_root = Path(
        os.environ.get(
            "EQUIPMENT_DR_CODEX_HOME",
            str(root / "outputs" / "runtime" / "codex-homes"),
        )
    ).expanduser()
    registry = ProviderRegistry.load(
        root / "configs" / "equipment_deep_research" / "providers.yaml"
    )
    key_path = os.environ.get(
        "EQUIPMENT_DR_QUERY_LIBRARY_KEY_FILE",
        str(root / "outputs" / "query-library.key"),
    )
    credential_store = EncryptedCredentialStore(repository, key_path)
    model_options = registry.public_options()
    model_options["environment_defaults"] = _environment_default_status()
    if not with_generator:
        return QueryLibraryService(
            repository,
            model_options=model_options,
            credential_store=credential_store,
            artifact_root=artifact_root,
        )
    default_profile = provider_name or registry.default_provider

    def generator_factory(model_config: dict[str, str]) -> ModelQueryGenerator:
        profile = model_config.get("provider") or default_profile
        model = model_config.get("model") or None
        reasoning_effort = model_config.get("reasoning_effort") or "high"
        base_url = model_config.get("base_url") or None
        credential_id = model_config.get("credential_id") or ""
        api_key = (
            credential_store.resolve(credential_id)
            if credential_id
            else _query_library_api_key()
        )
        if base_url is None:
            base_url = _query_library_base_url()
        generation_id = str(model_config.get("_generation_id", ""))
        generation_suffix = generation_id.removeprefix("generation-")
        isolation_key = (
            f"query-gen-{generation_suffix}"
            if generation_suffix
            else "query-library-generator"
        )
        provider = registry.create(
            profile,
            model=model,
            base_url=base_url,
            api_key=api_key,
            workspace_path=root,
            isolation_key=isolation_key,
            include_default_skills=False,
        )
        snapshot = registry.profile_snapshot(profile, model=model)
        snapshot["profile"] = profile
        snapshot["reasoning_effort"] = reasoning_effort
        snapshot["custom_base_url"] = bool(model_config.get("base_url"))
        snapshot["custom_credential"] = bool(credential_id)
        snapshot["credential_source"] = (
            "request"
            if credential_id
            else _environment_default_status()["api_key_source"]
        )
        snapshot["base_url_source"] = (
            "request"
            if model_config.get("base_url")
            else _environment_default_status()["base_url_source"]
        )
        return ModelQueryGenerator(
            provider,
            provider_snapshot=snapshot,
            model_options={"reasoning_effort": reasoning_effort},
        )

    return QueryLibraryService(
        repository,
        generator_factory=generator_factory,
        model_options=model_options,
        credential_store=credential_store,
        artifact_root=artifact_root,
    )


def _query_library_api_key() -> str | None:
    value = (
        os.environ.get("EQUIPMENT_DR_QUERY_LIBRARY_API_KEY", "").strip()
        or os.environ.get("EQUIPMENT_DR_API_KEY", "").strip()
    )
    return value or None


def _query_library_base_url() -> str | None:
    value = (
        os.environ.get("EQUIPMENT_DR_QUERY_LIBRARY_BASE_URL", "").strip()
        or os.environ.get("EQUIPMENT_DR_BASE_URL", "").strip()
    )
    return value or None


def _environment_default_status() -> dict[str, object]:
    query_key = bool(os.environ.get("EQUIPMENT_DR_QUERY_LIBRARY_API_KEY", "").strip())
    project_key = bool(os.environ.get("EQUIPMENT_DR_API_KEY", "").strip())
    query_url = bool(os.environ.get("EQUIPMENT_DR_QUERY_LIBRARY_BASE_URL", "").strip())
    project_url = bool(os.environ.get("EQUIPMENT_DR_BASE_URL", "").strip())
    return {
        "api_key_configured": query_key or project_key,
        "api_key_source": (
            "EQUIPMENT_DR_QUERY_LIBRARY_API_KEY"
            if query_key
            else "EQUIPMENT_DR_API_KEY"
            if project_key
            else "EQUIPMENT_DR_API_KEY"
        ),
        "base_url_configured": query_url or project_url,
        "base_url_source": (
            "EQUIPMENT_DR_QUERY_LIBRARY_BASE_URL"
            if query_url
            else "EQUIPMENT_DR_BASE_URL"
            if project_url
            else "EQUIPMENT_DR_BASE_URL"
        ),
        "api_key_precedence": [
            "EQUIPMENT_DR_QUERY_LIBRARY_API_KEY",
            "EQUIPMENT_DR_API_KEY",
        ],
        "base_url_precedence": [
            "EQUIPMENT_DR_QUERY_LIBRARY_BASE_URL",
            "EQUIPMENT_DR_BASE_URL",
        ],
    }


def default_seed_manifest() -> Path:
    return Path(__file__).resolve().parent / "seeds" / "initial_queries.json"
