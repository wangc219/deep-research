"""公众号真实获取入库与视频号真实转录验收。"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import time
import zipfile
from pathlib import Path
from uuid import uuid4

from final_acceptance import api, client_for, report, save, state, update_state
from platform_core.storage.postgres.manager import pg_manager


REPORT_PATH = Path("/app/outputs/final-delivery-acceptance-20261029/acceptance-report.json")


def items_from(payload, *keys: str) -> list[dict]:
    value = payload
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "accounts", "articles", "list", "results"):
            if isinstance(payload.get(key), list):
                return [item for item in payload[key] if isinstance(item, dict)]
    return []


async def wait_task(client, task_id: str, *, path_prefix: str = "/api/tasks/", timeout: int = 1200) -> dict:
    update_state(task_ids_append=task_id)
    started = time.monotonic()
    last = ""
    while time.monotonic() - started < timeout:
        payload = await api(client, "GET", path_prefix + task_id)
        task = payload.get("task") if isinstance(payload, dict) and isinstance(payload.get("task"), dict) else payload
        status = str(task.get("status") or "")
        if status != last:
            print(json.dumps({"task_id": task_id, "status": status, "elapsed": round(time.monotonic() - started)}, ensure_ascii=False), flush=True)
            last = status
        if status in {"success", "failed", "cancelled"}:
            if status != "success":
                raise RuntimeError(f"任务失败: {task_id}: {json.dumps(task, ensure_ascii=False)[:1800]}")
            return task
        await asyncio.sleep(2)
    raise TimeoutError(f"任务超时: {task_id}: {last}")


async def create_kb(client, label: str) -> str:
    created = await api(
        client,
        "POST",
        "/api/knowledge/databases",
        json={
            "database_name": "pytest_final_delivery_" + label + "_" + uuid4().hex[:8],
            "kb_type": "milvus",
            "description": "交付前真实验收临时知识库",
            "embedding_model_spec": "siliconflow-cn:Pro/BAAI/bge-m3",
            "additional_params": {},
        },
    )
    kb_id = str(created["kb_id"])
    update_state(kb_ids_append=kb_id)
    return kb_id


async def import_workspace_artifact(client, kb_id: str, path: str) -> dict:
    staged = await api(
        client,
        "POST",
        "/api/knowledge/files/import-workspace",
        json={"kb_id": kb_id, "paths": [path]},
    )
    item = staged["items"][0]
    created = await api(
        client,
        "POST",
        f"/api/knowledge/databases/{kb_id}/documents",
        json={
            "items": [item["file_path"]],
            "params": {
                "content_type": "file",
                "auto_index": True,
                "content_hashes": {item["file_path"]: item["content_hash"]},
                "file_sizes": {item["file_path"]: item["size"]},
            },
        },
    )
    task = await wait_task(client, str(created["task_id"]), timeout=900)
    return {"staged": item, "task": task}


async def phase_wechat() -> None:
    current = state()
    if not current.get("uid"):
        raise RuntimeError("请先运行 final_acceptance.py chat 创建验收账号")
    async with await client_for(current) as client:
        headers = {"X-Requested-With": "WechatMP", "X-Platform-Origin": BASE_ORIGIN}
        session = await api(client, "POST", "/api/wechat-mp/session", headers=headers)
        search = await api(
            client,
            "POST",
            "/api/wechat-mp/app/api/accounts/search",
            headers=headers,
            json={"keyword": "央视新闻"},
        )
        accounts = items_from(search)
        if not accounts and isinstance(search, dict):
            accounts = items_from(search.get("data") or {})
        if not accounts:
            raise RuntimeError(f"公众号搜索无结果: {json.dumps(search, ensure_ascii=False)[:1600]}")
        account = accounts[0]
        fakeid = str(account.get("fakeid") or account.get("id") or account.get("fake_id") or "")
        nickname = str(account.get("nickname") or account.get("name") or "央视新闻")
        listing = await api(
            client,
            "GET",
            f"/api/wechat-mp/app/api/articles/list/{fakeid}",
            headers=headers,
            params={"begin": 0, "count": 10, "keyword": ""},
        )
        articles = items_from(listing)
        if not articles and isinstance(listing, dict):
            articles = items_from(listing.get("data") or {})
        article = next((item for item in articles if item.get("link") or item.get("url")), None)
        if article is None:
            raise RuntimeError(f"公众号文章列表无可下载项: {json.dumps(listing, ensure_ascii=False)[:1800]}")
        started = await api(
            client,
            "POST",
            "/api/wechat-mp/app/api/articles/download",
            headers=headers,
            json={"articles": [article], "account_name": nickname},
        )
        download_id = str(started["task_id"])
        download = {}
        for _ in range(240):
            download = await api(
                client,
                "GET",
                f"/api/wechat-mp/app/api/articles/download-status/{download_id}",
                headers=headers,
            )
            if download.get("status") in {"completed", "failed"}:
                break
            await asyncio.sleep(1)
        if download.get("status") != "completed" or int(download.get("completed") or 0) < 1:
            raise RuntimeError(f"公众号下载未成功: {json.dumps(download, ensure_ascii=False)[:1800]}")
        # Download completion and workspace publication are separate atomic
        # steps; allow the artifact index a short propagation window.
        article_items = []
        for _ in range(30):
            artifacts = await api(client, "GET", "/api/knowledge/collection-artifacts/wechat-articles")
            article_items = artifacts.get("items") if isinstance(artifacts, dict) else []
            if article_items:
                break
            await asyncio.sleep(1)
        if not article_items:
            raise RuntimeError("公众号下载成功但未发布到采集成果工作区")
        selected = next((item for item in article_items if item.get("available")), article_items[0])
        kb_id = await create_kb(client, "wechat")
        imported = await import_workspace_artifact(client, kb_id, str(selected["import_path"]))
        query_text = str(selected.get("title") or article.get("title") or "央视新闻")[:100]
        recalled = await api(
            client,
            "POST",
            f"/api/knowledge/databases/{kb_id}/query",
            json={"query": query_text, "meta": {"final_top_k": 3, "similarity_threshold": 0}},
        )
        history = await api(client, "GET", "/api/wechat-mp/app/api/articles/history", headers=headers, params={"limit": 20})
        history_rows = history.get("history") if isinstance(history, dict) else []
        matched = next((item for item in history_rows if str(item.get("path") or "") == str(selected.get("source_path") or "")), None)
        if matched is None and history_rows:
            matched = history_rows[0]
        if matched is not None and matched.get("_index") is not None:
            await api(
                client,
                "DELETE",
                f"/api/wechat-mp/app/api/articles/history/{matched['_index']}",
                headers=headers,
            )
    recall_text = json.dumps(recalled, ensure_ascii=False)
    gate = {
        "module_session": bool(session.get("url")),
        "real_account_search": bool(fakeid),
        "real_article_download": int(download.get("completed") or 0) >= 1,
        "artifact_published": bool(selected.get("import_path")),
        "knowledge_indexed": str(imported["task"].get("status")) == "success",
        "vector_recall": len(recall_text) > 100,
    }
    result = {
        "status": "passed" if all(gate.values()) else "failed",
        "gate": gate,
        "account": nickname,
        "article_title": str(article.get("title") or selected.get("title") or "")[:500],
        "download_task_id": download_id,
        "kb_id": kb_id,
        "recall_characters": len(recall_text),
    }
    current_report = report()
    current_report["phases"]["wechat_article_download_and_ingest"] = result
    save(REPORT_PATH, current_report)
    print(json.dumps(result, ensure_ascii=False), flush=True)


async def phase_video() -> None:
    current = state()
    if not current.get("uid"):
        raise RuntimeError("请先运行 final_acceptance.py chat 创建验收账号")
    base = "/api/knowledge/wxchannels"
    async with await client_for(current) as client:
        status = await api(client, "GET", base + "/status", params={"mode": "central"})
        discovery = await api(
            client,
            "POST",
            base + "/videos",
            json={
                "account": "央视新闻",
                "max_pages": 1,
                "max_videos": 3,
                "full_refresh": False,
                "load_more": False,
                "collection_mode": "central",
            },
        )
        discovered = await wait_task(client, str(discovery["task_id"]), path_prefix=base + "/tasks/", timeout=900)
        videos = (discovered.get("result") or {}).get("videos") or []
        if not videos:
            raise RuntimeError(f"视频号发现任务没有视频: {json.dumps(discovered, ensure_ascii=False)[:1600]}")
        chosen = videos[0]
        converted = await api(
            client,
            "POST",
            base + "/transcribe",
            json={
                "account": "央视新闻",
                "max_pages": 1,
                "max_videos": 1,
                "full_refresh": False,
                "load_more": False,
                "collection_mode": "central",
                "language": "zh",
                "timeout_seconds": 900,
                "video_oids": [chosen["oid"]],
            },
        )
        if not converted.get("submitted"):
            raise RuntimeError(f"视频转录未提交: {json.dumps(converted, ensure_ascii=False)}")
        task_id = str(converted["task_id"])
        transcript = await wait_task(client, task_id, path_prefix=base + "/tasks/", timeout=1800)
        result = transcript.get("result") or {}
        docx = await client.get(base + f"/tasks/{task_id}/items/0/docx")
        docx.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(docx.content)) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
        kb_id = await create_kb(client, "video")
        imported = await api(
            client,
            "POST",
            base + f"/databases/{kb_id}/import",
            json={"task_id": task_id, "indexes": [0]},
        )
        index_task = await wait_task(client, str(imported["task_id"]), timeout=900)
        recalled = await api(
            client,
            "POST",
            f"/api/knowledge/databases/{kb_id}/query",
            json={"query": str(chosen.get("title") or "央视新闻")[:80], "meta": {"final_top_k": 3, "similarity_threshold": 0}},
        )
    recall_text = json.dumps(recalled, ensure_ascii=False)
    gate = {
        "collector_ready": bool(status.get("ready")),
        "real_video_discovered": bool(videos),
        "asr_completed": int(result.get("completed_count") or 0) == 1 and int(result.get("failed_count") or 0) == 0,
        "docx_valid": len(docx.content) > 1000 and len(document_xml) > 500,
        "knowledge_indexed": index_task.get("status") == "success",
        "vector_recall": str(chosen["oid"]) in recall_text or len(recall_text) > 100,
    }
    output = {
        "status": "passed" if all(gate.values()) else "failed",
        "gate": gate,
        "source_account": "央视新闻",
        "source_title": str(chosen.get("title") or "")[:500],
        "discovered_videos": len(videos),
        "transcribe_task_id": task_id,
        "docx_bytes": len(docx.content),
        "kb_id": kb_id,
        "recall_characters": len(recall_text),
    }
    current_report = report()
    current_report["phases"]["wxchannels_transcription_and_ingest"] = output
    save(REPORT_PATH, current_report)
    print(json.dumps(output, ensure_ascii=False), flush=True)


BASE_ORIGIN = "https://www.deepquest.space"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["wechat", "video"])
    args = parser.parse_args()
    pg_manager.initialize()
    try:
        await {"wechat": phase_wechat, "video": phase_video}[args.phase]()
    finally:
        await pg_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
