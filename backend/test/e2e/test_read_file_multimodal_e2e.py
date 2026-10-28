from __future__ import annotations

import asyncio
import os
import re
import uuid
from pathlib import Path

import httpx
import pytest
import asyncpg
from PIL import Image, ImageDraw, ImageFont

from e2e_helpers import delete_agent, postgres_dsn
from test.live_api_cleanup import make_test_conversation_metadata, make_test_conversation_title

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.slow]

RUN_TIMEOUT_SECONDS = int(os.getenv("E2E_RUN_TIMEOUT_SECONDS", "240"))
VISION_MODEL = os.getenv("E2E_VISION_MODEL")
NON_VISION_MODEL = os.getenv("E2E_NON_VISION_MODEL")


async def _create_agent(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    uid: str,
    model: str,
) -> str:
    slug = f"e2e-read-file-{uuid.uuid4().hex[:8]}"
    response = await client.post(
        "/api/agent",
        json={
            "name": f"E2E read_file {slug[-8:]}",
            "slug": slug,
            "backend_id": "ChatbotAgent",
            "description": "read_file 多模态真实链路测试智能体",
            "config_json": {
                "context": {
                    "model": model,
                    "system_prompt": (
                        "你是附件端到端测试智能体。附件尚未提供解析正文时，必须先调用 read_file，"
                        "不得根据文件名猜测内容。严格按用户指定格式回答。"
                    ),
                    "tools": [],
                    "knowledges": [],
                    "mcps": [],
                    "skills": [],
                    "subagents": [],
                    "model_retry_times": 0,
                }
            },
            "share_config": {
                "version": 2,
                "read_scope": {"access_level": "user", "department_ids": [], "user_uids": [uid]},
                "manage_scope": None,
            },
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return slug


async def _create_thread(client: httpx.AsyncClient, headers: dict[str, str], agent_slug: str) -> str:
    response = await client.post(
        "/api/chat/thread",
        json={
            "agent_id": agent_slug,
            "title": make_test_conversation_title("read-file-e2e"),
            "metadata": make_test_conversation_metadata("read-file-e2e", e2e=True),
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return str(payload.get("thread_id") or payload["id"])


async def _upload(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    thread_id: str,
    file_path: Path,
) -> str:
    with file_path.open("rb") as handle:
        upload_response = await client.post(
            "/api/chat/attachments/tmp",
            files={"file": (file_path.name, handle)},
            headers=headers,
        )
    assert upload_response.status_code == 200, upload_response.text
    uploaded = upload_response.json()

    confirm_response = await client.post(
        f"/api/chat/thread/{thread_id}/attachments/confirm",
        json={
            "attachments": [
                {
                    "file_type": uploaded.get("file_type"),
                    "object_name": uploaded["object_name"],
                }
            ]
        },
        headers=headers,
    )
    assert confirm_response.status_code == 200, confirm_response.text
    attachment = confirm_response.json()["attachments"][0]
    assert attachment["original_path"].endswith(file_path.name), attachment
    return str(attachment["file_id"])


async def _run(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    agent_slug: str,
    thread_id: str,
    query: str,
    attachment_file_id: str,
    require_read_file: bool = True,
) -> str:
    response = await client.post(
        "/api/agent/runs",
        json={
            "query": query,
            "agent_slug": agent_slug,
            "thread_id": thread_id,
            "meta": {
                "request_id": f"read-file-e2e-{uuid.uuid4()}",
                "attachment_file_ids": [attachment_file_id],
            },
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    run_id = str(response.json()["run_id"])

    deadline = asyncio.get_running_loop().time() + RUN_TIMEOUT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        result = await client.get(f"/api/agent/runs/{run_id}/result", headers=headers)
        assert result.status_code == 200, result.text
        payload = result.json()
        status = str(payload.get("status") or "")
        if status in {"completed", "failed", "cancelled", "interrupted"}:
            assert status == "completed", payload
            conn = await asyncpg.connect(postgres_dsn())
            try:
                read_calls = await conn.fetchval(
                    "SELECT count(*) FROM tool_calls t JOIN messages m ON m.id=t.message_id "
                    "WHERE m.run_id=$1 AND t.tool_name='read_file' AND t.status='success'",
                    run_id,
                )
            finally:
                await conn.close()
            if require_read_file:
                assert read_calls, "模型未实际成功调用 read_file，不能用文件名猜测冒充工具验收"
            output = str(payload.get("output") or "")
            if not output:
                history = await client.get(f"/api/chat/thread/{thread_id}/history", headers=headers)
                ai_messages = [
                    {key: m.get(key) for key in ("id", "content", "reasoning_content", "message_type")}
                    for m in history.json().get("history", [])
                    if m.get("type") == "ai"
                ]
                pytest.fail(f"完成任务却没有输出: {payload}; assistant_history={ai_messages}")
            return output
        await asyncio.sleep(2)
    pytest.fail(f"read_file E2E run timed out: {run_id}")


def _write_test_image(path: Path) -> None:
    image = Image.new("RGB", (128, 128), "red")
    ImageDraw.Draw(image).rectangle((40, 40, 88, 88), fill="blue")
    image.save(path, format="PNG")


def _write_ocr_test_image(path: Path) -> None:
    image = Image.new("RGB", (720, 180), "white")
    font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 56)
    ImageDraw.Draw(image).text((35, 55), "OCR FALLBACK OK", fill="black", font=font)
    image.save(path, format="PNG")


async def test_read_file_image_and_pdf_attachment_real_agent_runs(
    tmp_path: Path,
    e2e_client: httpx.AsyncClient,
    e2e_headers: dict[str, str],
    e2e_agent_context: dict[str, str],
) -> None:
    if not VISION_MODEL:
        pytest.skip("E2E_VISION_MODEL is not configured for the external vision model test.")

    slug = await _create_agent(
        e2e_client,
        e2e_headers,
        uid=e2e_agent_context["uid"],
        model=VISION_MODEL,
    )
    try:
        image_path = tmp_path / "shape.png"
        _write_test_image(image_path)
        image_thread = await _create_thread(e2e_client, e2e_headers, slug)
        image_file_id = await _upload(e2e_client, e2e_headers, thread_id=image_thread, file_path=image_path)
        image_output = await _run(
            e2e_client,
            e2e_headers,
            agent_slug=slug,
            thread_id=image_thread,
            query="调用 read_file 检查 shape.png。中心方块是什么颜色？只回答英文颜色单词。",
            attachment_file_id=image_file_id,
        )
        assert image_output.strip().lower() == "blue", image_output

        document_path = tmp_path / "sample.pdf"
        document_image = Image.new("RGB", (720, 180), "white")
        ImageDraw.Draw(document_image).text((35, 55), "PDF read_file boundary test", fill="black")
        document_image.save(document_path, format="PDF")
        document_thread = await _create_thread(e2e_client, e2e_headers, slug)
        document_file_id = await _upload(
            e2e_client,
            e2e_headers,
            thread_id=document_thread,
            file_path=document_path,
        )
        document_output = await _run(
            e2e_client,
            e2e_headers,
            agent_slug=slug,
            thread_id=document_thread,
            query="读取附件 sample.pdf，复述其中实际存在的英文文字。若附件已有解析正文，直接根据正文回答。",
            attachment_file_id=document_file_id,
            require_read_file=False,
        )
        # 有效 PDF 会在附件准备阶段实际 OCR；验收已解析文字，不能再要求旧版固定建议文案。
        assert "BOUNDARY TEST" in " ".join(re.findall(r"[A-Z]+", document_output.upper())), document_output
    finally:
        await delete_agent(e2e_client, e2e_headers, slug)


async def test_non_vision_model_uses_ocr_fallback(
    tmp_path: Path,
    e2e_client: httpx.AsyncClient,
    e2e_headers: dict[str, str],
    e2e_agent_context: dict[str, str],
) -> None:
    if not NON_VISION_MODEL:
        pytest.skip("E2E_NON_VISION_MODEL is not configured for the external capability rejection test.")

    slug = await _create_agent(
        e2e_client,
        e2e_headers,
        uid=e2e_agent_context["uid"],
        model=NON_VISION_MODEL,
    )
    try:
        image_path = tmp_path / "ocr-text.png"
        _write_ocr_test_image(image_path)
        thread_id = await _create_thread(e2e_client, e2e_headers, slug)
        image_file_id = await _upload(e2e_client, e2e_headers, thread_id=thread_id, file_path=image_path)
        output = await _run(
            e2e_client,
            e2e_headers,
            agent_slug=slug,
            thread_id=thread_id,
            query="调用 read_file 读取 ocr-text.png 中的文字，只回答图片中的英文文字。",
            attachment_file_id=image_file_id,
        )
        assert "OCR FALLBACK OK" in " ".join(re.findall(r"[A-Z]+", output.upper())), output
    finally:
        await delete_agent(e2e_client, e2e_headers, slug)
