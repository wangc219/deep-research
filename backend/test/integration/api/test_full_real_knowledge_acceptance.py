"""真实上传、解析、向量检索、模型抽取和图谱存储的完整验收。"""

import asyncio
import io
import json
import os
from time import monotonic
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import TaskRecord

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_FULL_REAL_ACCEPTANCE") != "1", reason="显式启用真实模型与 OCR 验收"),
]


async def test_upload_ocr_embedding_retrieval_and_graph(test_client, admin_headers, standard_user, knowledge_database):
    """不注入模型或存储替身，独立测试库完成全部真实处理后再删除。"""
    kb_id = knowledge_database["kb_id"]
    marker = "OBS_" + uuid4().hex[:12]
    body = (
        f"验收标记：{marker}。测试浮标配备温度传感器。温度传感器测量海水温度。"
        "温度传感器连接数据记录器。数据记录器保存温度数据。测试浮标使用太阳能电池供电。"
        "每月由维护人员检查电池、电缆和传感器。该说明为软件验收合成资料，不代表真实产品参数。"
    )
    image = Image.new("RGB", (1600, 500), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=48)
    draw.text((80, 80), "OCR ACCEPTANCE 20261025", font=font, fill="black")
    draw.text((80, 180), "Sensor measures water temperature.", font=font, fill="black")
    pdf = io.BytesIO()
    image.save(pdf, format="PDF", resolution=150)
    file_ids = []
    task_ids = []

    async def request(method, path, **kwargs):
        response = await test_client.request(method, path, headers=admin_headers, **kwargs)
        assert response.status_code == 200, (path, response.text)
        return response.json()

    async def finish(task_id):
        task_ids.append(task_id)
        started = monotonic()
        while monotonic() - started < 600:
            task = (await request("GET", f"/api/tasks/{task_id}"))["task"]
            if task["status"] in {"success", "failed", "cancelled"}:
                assert task["status"] == "success", task
                result = task.get("result") or {}
                assert not result.get("failed", 0), result
                print(
                    json.dumps(
                        {"task": task_id, "type": task["type"], "status": task["status"], "result": result},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                return task
            await asyncio.sleep(1)
        pytest.fail(f"真实任务超时：{task_id}")

    try:
        for filename, content, media_type in (
            ("acceptance.txt", body.encode(), "text/plain"),
            ("scan.pdf", pdf.getvalue(), "application/pdf"),
        ):
            upload = await request(
                "POST", f"/api/knowledge/files/upload?kb_id={kb_id}", files={"file": (filename, content, media_type)}
            )
            added = await request(
                "POST",
                f"/api/knowledge/databases/{kb_id}/documents/add",
                json={
                    "items": [upload["file_path"]],
                    "params": {
                        "content_hashes": {upload["file_path"]: upload["content_hash"]},
                        "file_sizes": {upload["file_path"]: upload["size"]},
                    },
                },
            )
            assert added["added"] == 1 and added["failed"] == 0, added
            file_ids.append(added["items"][0]["file_id"])
        parsed = await request(
            "POST",
            f"/api/knowledge/databases/{kb_id}/documents/parse",
            json={"file_ids": file_ids, "params": {"ocr_engine": "rapid_ocr", "prefer_pdf_text_layer": False}},
        )
        await finish(parsed["task_id"])
        scanned = await request("GET", f"/api/knowledge/databases/{kb_id}/documents/{file_ids[1]}/content")
        assert "temperature" in json.dumps(scanned).lower(), scanned
        indexed = await request(
            "POST", f"/api/knowledge/databases/{kb_id}/documents/index", json={"file_ids": file_ids}
        )
        await finish(indexed["task_id"])
        results = await request(
            "POST",
            f"/api/knowledge/databases/{kb_id}/query",
            json={"query": "测试浮标如何测量和保存海水温度？", "meta": {"final_top_k": 5, "similarity_threshold": 0}},
        )
        assert marker in json.dumps(results, ensure_ascii=False), results
        private = await test_client.post(
            f"/api/knowledge/databases/{kb_id}/query", headers=standard_user["headers"], json={"query": marker}
        )
        assert private.status_code == 403, private.text
        health = await request("GET", f"/api/knowledge/databases/{kb_id}/index-health")
        print(
            json.dumps({"kb_id": kb_id, "index_health": health, "retrieval_marker_found": True}, ensure_ascii=False),
            flush=True,
        )
        configured = await request(
            "POST",
            f"/api/knowledge/databases/{kb_id}/graph-build/config",
            json={
                "extractor_type": "llm",
                "extractor_options": {
                    "model_spec": "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash",
                    "max_output_tokens": 8192,
                    "timeout_seconds": 180,
                },
            },
        )
        assert configured["status"] == "success"
        graph_task = await request("POST", f"/api/knowledge/databases/{kb_id}/graph-build/index", json={})
        await finish(graph_task["task_id"])
        status = await request("GET", f"/api/knowledge/databases/{kb_id}/graph-build/status")
        assert status["extraction_counts"]["succeeded"] > 0, status
        assert status["extraction_counts"]["failed"] == 0, status
        graph = await request(
            "GET", "/api/graph/subgraph", params={"kb_id": kb_id, "max_nodes": 100, "exclude_chunk": True}
        )
        assert graph.get("success") is True, graph
        graph = graph["data"]
        assert graph.get("nodes") and graph.get("edges"), graph
        print(
            json.dumps(
                {
                    "kb_id": kb_id,
                    "ocr": "passed",
                    "embedding": "passed",
                    "retrieval": "passed",
                    "graph": "passed",
                    "nodes": len(graph["nodes"]),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        generated = await request(
            "POST",
            f"/api/evaluation/databases/{kb_id}/datasets/generate",
            json={
                "name": "真实评估验收",
                "count": 1,
                "neighbors_count": 0,
                "concurrency_count": 1,
                "llm_model_spec": "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash",
                "generation_mode": "graph_enhanced",
            },
        )
        dataset_id = generated["data"]["dataset_id"]
        await finish(generated["data"]["task_id"])
        download = await test_client.get(f"/api/evaluation/datasets/{dataset_id}/download", headers=admin_headers)
        assert download.status_code == 200, download.text
        dataset_items = [json.loads(line) for line in download.text.splitlines() if line.strip()]
        assert len(dataset_items) == 1 and dataset_items[0]["gold_answer"], dataset_items
        evaluated = await request(
            "POST",
            f"/api/evaluation/databases/{kb_id}/runs",
            json={
                "dataset_id": dataset_id,
                "name": "真实重排与回答评估",
                "model_config": {
                    "answer_llm": "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash",
                    "judge_llm": "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash",
                    "use_reranker": True,
                    "reranker_model": "siliconflow-cn:Pro/BAAI/bge-reranker-v2-m3",
                    "final_top_k": 5,
                    "similarity_threshold": 0,
                },
            },
        )
        run_id = evaluated["data"]["run_id"]
        async with pg_manager.get_async_session_context() as db:
            evaluation_task = await db.scalar(
                select(TaskRecord.id).where(TaskRecord.payload["run_id"].as_string() == run_id)
            )
        assert evaluation_task
        await finish(evaluation_task)
        evaluation = (await request("GET", f"/api/evaluation/databases/{kb_id}/runs/{run_id}"))["data"]
        assert evaluation["status"] == "completed", evaluation
        assert evaluation["completed_items"] == 1 and evaluation["items"], evaluation
        item = evaluation["items"][0]
        assert item.get("generated_answer") and item.get("retrieved_chunks"), item
        assert all("rerank_score" in chunk for chunk in item["retrieved_chunks"]), "重排降级不能记为通过"
        assert not item.get("metrics", {}).get("error"), item
        assert evaluation["overall_score"] is not None, evaluation
        print(
            json.dumps(
                {
                    "real_dataset_generation": "passed",
                    "real_reranker_and_answer_evaluation": "passed",
                    "dataset_id": dataset_id,
                    "run_id": run_id,
                    "overall_score": evaluation["overall_score"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    finally:
        for task_id in task_ids:
            response = await test_client.get(f"/api/tasks/{task_id}", headers=admin_headers)
            if response.status_code == 200 and response.json()["task"]["status"] not in {
                "success",
                "failed",
                "cancelled",
            }:
                await test_client.post(f"/api/tasks/{task_id}/cancel", headers=admin_headers)
                for _ in range(60):
                    state = (await test_client.get(f"/api/tasks/{task_id}", headers=admin_headers)).json()["task"]
                    if state["status"] in {"success", "failed", "cancelled"}:
                        break
                    await asyncio.sleep(1)
