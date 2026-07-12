# 企业交付与运行说明

## 本地开发

```bash
python3 -m uvicorn equipment_deep_research.api.app:create_app --factory --app-dir src --host 127.0.0.1 --port 8000
pnpm --dir apps/web dev --host 127.0.0.1
```

## 容器部署

```bash
docker compose build
docker compose up -d
```

Web 默认地址为 `http://127.0.0.1:8080`。真实模型凭据通过环境变量 `EQUIPMENT_DR_API_KEY` 注入，不写入镜像、配置、trace 或 session。

## 验收产物

每次完整运行至少包含 `report.md`、`capability_images.json`、`round_summary.json`、`domain.jsonl`、`trace.jsonl`、`agent_sessions/` 和 `artifacts/`。`DeliveryExporter` 生成 `delivery-manifest.json`，记录文件大小和 SHA-256，用于交付完整性复核。

## 当前部署边界

开发模式使用 SQLite 和进程内队列；生产适配接口已分离，PostgreSQL/Redis 高可用部署仍需结合甲方基础设施参数完成环境化配置。
