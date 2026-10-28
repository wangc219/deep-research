"""为既有 MCP 添加可选使用策略，空值保持原有全局使用行为。"""

MCP_ACCESS_SCHEMA_STATEMENTS = ("ALTER TABLE IF EXISTS mcp_servers ADD COLUMN IF NOT EXISTS access_policy JSON",)


async def main() -> None:
    """只执行 13 → 14 的新增字段迁移，不触碰历史文件与运行状态。"""
    from sqlalchemy import text

    from platform_core.storage.postgres.manager import pg_manager

    pg_manager.initialize()
    try:
        async with pg_manager.schema_migration_lock():
            versions = await pg_manager.get_schema_versions()
            if versions.get("business") not in {13, 14}:
                raise RuntimeError("请先通过标准存储迁移升级到 business=13")
            async with pg_manager.async_engine.begin() as conn:
                for statement in MCP_ACCESS_SCHEMA_STATEMENTS:
                    await conn.execute(text(statement))
                await conn.execute(
                    text(
                        "UPDATE platform_schema_migrations SET version = 14, applied_at = CURRENT_TIMESTAMP "
                        "WHERE domain = 'business'"
                    )
                )
    finally:
        await pg_manager.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
