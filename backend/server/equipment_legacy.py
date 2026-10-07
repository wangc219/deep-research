"""把原装备 Deep Research FastAPI 挂到平台 /api/v1，供原 React 工作台一比一调用。"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def mount_legacy_equipment_api(platform_app: Any) -> None:
    """把原项目 /api/v1 路由并入当前 FastAPI 应用。失败时不影响平台其它接口。"""
    os.environ.setdefault("EQUIPMENT_DR_PROJECT_ROOT", os.environ.get("EQUIPMENT_DR_PROJECT_ROOT", "/app"))
    os.environ.setdefault("EQUIPMENT_DR_OUTPUT_ROOT", os.environ.get("EQUIPMENT_DR_OUTPUT_ROOT", "/app/outputs/runs"))
    os.environ.setdefault(
        "EQUIPMENT_DR_APP_DB",
        os.environ.get("EQUIPMENT_DR_APP_DB", "sqlite:////app/outputs/application.db"),
    )
    os.environ.setdefault(
        "EQUIPMENT_DR_QUERY_LIBRARY_DB",
        os.environ.get("EQUIPMENT_DR_QUERY_LIBRARY_DB", "sqlite:////app/outputs/query-library.db"),
    )
    mounted = 0
    included = 0
    try:
        from equipment_deep_research.api.app import create_app

        from equipment_deep_research.providers.platform_access import configure_model_resolver
        from platform_core.services.equipment_model_adapter import (
            equipment_model_profiles,
            resolve_managed_equipment_model,
        )

        configure_model_resolver(resolve_managed_equipment_model, equipment_model_profiles)
        legacy = create_app()
        platform_app.state.platform_read_run = legacy.state.platform_read_run
        for route in list(legacy.router.routes):
            path = getattr(route, "path", "") or ""
            if path.startswith("/api/v1"):
                platform_app.router.routes.append(route)
                mounted += 1
                continue
            # FastAPI 把 include_router 收成 _IncludedRouter，path 为空，不能按前缀过滤。
            original = getattr(route, "original_router", None)
            if original is None:
                continue
            if not _router_serves_v1(original):
                continue
            context = getattr(route, "include_context", None)
            extra_prefix = str(getattr(context, "prefix", "") or "")
            platform_app.include_router(original, prefix=extra_prefix)
            included += 1
        logger.info(
            "已挂载原装备研究 API：/api/v1/*（%s 条路由，%s 组 include_router）",
            mounted,
            included,
        )
    except Exception:
        logger.exception("原装备研究 /api/v1 挂载失败，工作台将无法访问完整原接口")

    if included == 0:
        _mount_query_library(platform_app)


def _router_serves_v1(router: Any) -> bool:
    prefix = str(getattr(router, "prefix", "") or "")
    if prefix.startswith("/api/v1"):
        return True
    for item in getattr(router, "routes", []) or []:
        path = getattr(item, "path", "") or ""
        if str(path).startswith("/api/v1"):
            return True
    return False


def _mount_query_library(platform_app: Any) -> None:
    """create_app 失败或 include_router 未被复制时，仍单独挂上问题库。"""
    try:
        from equipment_deep_research.query_library.api import create_router
        from equipment_deep_research.query_library.factory import build_service

        platform_app.include_router(create_router(build_service()))
        logger.info("已单独挂载问题库 /api/v1/query-library")
    except Exception:
        logger.exception("问题库 /api/v1/query-library 挂载失败")
