"""以本机已有测试身份提交深研沙盒验收；不输出认证凭据。"""

import json
import os
from datetime import timedelta

import httpx
import psycopg

from platform_core.utils.auth_utils import AuthUtils

uid = "Hitsz504"
with psycopg.connect(os.environ["POSTGRES_URL"].replace("+asyncpg", "").replace("+psycopg", "")) as conn:
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM users WHERE uid=%s AND is_deleted=0", (uid,))
        user_id = cursor.fetchone()[0]

headers = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user_id)}, expires_delta=timedelta(minutes=5))}
with httpx.Client(base_url="http://localhost:5050", headers=headers, timeout=60) as client:
    project = client.post("/api/projects/defaults/equipment")
    project.raise_for_status()
    response = client.post("/api/equipment/deep-thinking", json={
        "project_id": project.json()["id"],
        "title": "深研沙盒文件交付验收",
        "topic": "工作区文件生成与交付功能验收",
        "agent_slug": "deep-research",
        "knowledge_enabled": False,
        "subagents_enabled": False,
    })
    response.raise_for_status()
    session = response.json()
    query = (
        "这是文件功能验收，不开展装备研究、不检索、不成卡、不提问。请用 write_file 在当前项目的 "
        "outputs/深研沙盒验收-20261015/ 目录实际生成三个小文件："
        "深研验收.md（中文标题、说明读写持久化与预览下载，并注明数据为验收样例）；"
        "样例数据.csv（阶段,完成数，两行数据准备,2与交付,3）；"
        "交互图表.html（自包含中文页面，将上述样例显示为简单条形图，并有‘显示合计’按钮，点击显示合计5，使用内嵌JavaScript）。"
        "需要时读取 html-preview 技能的独立文件模式。逐个使用 read_file 核验，最后 present_artifacts 交付这三个真实文件。"
    )
    run = client.post("/api/agent/runs", json={
        "agent_slug": "deep-research", "thread_id": session["payload"]["thread_id"],
        "query": query, "meta": {"equipment_deep_session_id": session["session_id"], "equipment_create_artifact": False},
    })
    run.raise_for_status()
    print(json.dumps({"session_id": session["session_id"], "thread_id": session["payload"]["thread_id"],
        "url": "http://localhost:5173/equipment/deep-thinking/" + session["session_id"], "request": run.json()}, ensure_ascii=False))
