"""个人微信视频号采集端：只主动连接平台，不暴露本机网络端口。"""

import argparse
import asyncio
import contextlib
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit

import httpx

from platform_core.knowledge.wxchannels import WxChannelsMCPClient, collector_proxy_status, prepare_collector_connection
from platform_core.knowledge.video_transcriber.utils.ffmpeg import get_ffmpeg_path


async def resolve_account(client, account):
    """按完整昵称精确匹配账号，重名时要求提供 @finder ID。"""
    if account.endswith("@finder"):
        return account

    def contacts(value):
        """遍历下载器的嵌套账号响应。"""
        if isinstance(value, dict):
            yield value
            for item in value.values():
                yield from contacts(item)
        elif isinstance(value, list):
            for item in value:
                yield from contacts(item)

    matches = {
        str(item["username"]).strip()
        for item in contacts(await client.search_accounts(account))
        if item.get("nickname") == account and item.get("username")
    }
    if len(matches) != 1:
        raise RuntimeError("未找到唯一账号，请核对完整昵称或使用 @finder ID")
    return matches.pop()


async def run(config, endpoint):
    """心跳领取自己的任务，本机提取临时 WAV，云端完成识别和 Word 生成。"""
    origin = urlsplit(config["platform_url"])
    if origin.scheme != "https" and not (
        origin.scheme == "http" and origin.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("远程平台必须使用 HTTPS；本机测试可使用 http://localhost")
    if origin.username or origin.password or origin.query or origin.fragment:
        raise ValueError("平台地址应为不带凭据、查询参数和片段的站点 origin")
    local = urlsplit(endpoint)
    if local.scheme != "http" or local.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("下载器 MCP 只连接本机回环地址")
    base = urlunsplit((local.scheme, local.netloc, "", "", ""))
    headers = {"Authorization": "Bearer " + config["token"], "X-Collector-Device": config["device_id"]}
    root = config["platform_url"].rstrip("/") + "/api/knowledge/wxchannels/collector/"
    current = None
    current_id = None
    latest_job = None
    completed = set()
    announced = False
    last_reconnect = 0
    async with (
        httpx.AsyncClient(headers=headers, timeout=180, trust_env=False) as platform_client,
        httpx.AsyncClient(timeout=5, trust_env=False) as local_client,
    ):

        async def send(path, **kwargs):
            """交接重试保持相同执行 ID 与序号，服务端负责幂等。"""
            for attempt in range(3):
                for file_value in kwargs.get("files", {}).values():
                    if hasattr(file_value[1], "seek"):
                        file_value[1].seek(0)
                try:
                    response = await platform_client.post(root + path, **kwargs)
                    response.raise_for_status()
                    return response.json()
                except (httpx.TransportError, httpx.HTTPStatusError) as error:
                    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code < 500:
                        raise
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2**attempt)

        async def execute(job):
            """采集任务仅上传公开视频信息和临时音频。"""
            identity = {"task_id": job["task_id"], "execution_id": job["execution_id"]}
            sequence, skipped = 1, 0
            acknowledged = False
            kind = "video_list" if job["task_type"] == "wxchannels_discover" else "complete"
            try:
                async with WxChannelsMCPClient(endpoint, timeout=180) as source:
                    username = job.get("resolved_username") or await resolve_account(source, job["account"])
                    videos = await source.iter_account_videos(
                        username, job["max_pages"], known_oids=set(job.get("known_oids") or [])
                    )
                    if kind == "video_list":
                        if len(videos) > 202000:
                            raise RuntimeError("视频数量超过单次列表容量，请改用限定页数获取")
                        for offset in range(0, max(1, len(videos)), 2000):
                            sequence = offset // 2000 + 1
                            await send(
                                "event",
                                json={
                                    **identity,
                                    "sequence": sequence,
                                    "kind": kind,
                                    "username": username,
                                    "finished": offset + 2000 >= len(videos),
                                    "history_complete": source.history_complete,
                                    "videos": [
                                        {"oid": v.oid, "title": v.title[:20000], "published_at": v.published_at}
                                        for v in videos[offset : offset + 2000]
                                    ],
                                },
                            )
                            sequence += 1
                        acknowledged = True
                        return
                    if not videos:
                        raise RuntimeError("视频号暂无可处理的视频")
                    selected = set(job.get("video_oids") or [])
                    if selected and not selected.issubset({v.oid for v in videos}):
                        raise RuntimeError("部分选中视频已失效，请重新获取列表")
                    candidates = sorted(
                        (v for v in videos if not selected or v.oid in selected),
                        key=lambda v: v.published_at,
                        reverse=True,
                    )
                    skipped = sum(v.oid in job.get("completed_oids", []) for v in candidates)
                    pending = [v for v in candidates if v.oid not in job.get("completed_oids", [])][: job["max_videos"]]
                    for video in pending:
                        with TemporaryDirectory(prefix="platform_video_audio_") as temporary:
                            audio = await source.extract_audio_stream(video, Path(temporary) / "audio.wav", 7200)
                            with audio.open("rb") as file:
                                await send(
                                    "audio",
                                    data={
                                        **identity,
                                        "sequence": str(sequence),
                                        "oid": video.oid,
                                        "title": video.title[:20000],
                                    },
                                    files={"file": ("audio.wav", file, "audio/wav")},
                                )
                        while latest_job and latest_job.get("processed_count", 0) < sequence:
                            await asyncio.sleep(0.5)
                        sequence += 1
                    await send(
                        "event", json={**identity, "sequence": sequence, "kind": "complete", "skipped_count": skipped}
                    )
                    acknowledged = True
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # 不发送 HTTP 请求详情或 signed stream URL；登录态留在本机。
                text = (
                    str(error) if isinstance(error, RuntimeError) else "采集连接或音频提取失败，请检查本机微信和下载器"
                )
                await send("event", json={**identity, "sequence": sequence, "kind": kind, "error": text[:500]})
                acknowledged = True
            finally:
                if acknowledged:
                    completed.add((job["task_id"], job["execution_id"]))

        try:
            while True:
                state = {
                    "mcp_available": False,
                    "wechat_available": False,
                    "ffmpeg_available": bool(get_ffmpeg_path()),
                    "channels_ready": False,
                    "proxy_ready": False,
                }
                connection_error = ""
                try:
                    mcp = await local_client.get(base + "/api/mcp/status")
                    channels = await local_client.get(base + "/api/channels/status")
                    state["mcp_available"] = mcp.json().get("data", {}).get("enabled") is True
                    state["wechat_available"] = channels.json().get("data", {}).get("available") is True
                    state.update(await collector_proxy_status(local_client, base))
                except (httpx.HTTPError, ValueError, AttributeError, RuntimeError):
                    pass
                if state["mcp_available"] and not state["proxy_ready"] and time.monotonic() - last_reconnect >= 30:
                    last_reconnect = time.monotonic()
                    try:
                        state.update(await prepare_collector_connection(local_client, base))
                    except RuntimeError as error:
                        connection_error = str(error)
                    except (httpx.HTTPError, ValueError):
                        connection_error = "微信采集代理暂未响应，正在自动重连"
                state["channels_ready"] = all(
                    state[key] for key in ("mcp_available", "wechat_available", "proxy_ready")
                )
                state["message"] = connection_error or (
                    "视频号采集端已就绪"
                    if state["channels_ready"]
                    else "请启动下载器、启用 MCP，并在微信中打开视频号页面"
                )
                try:
                    response = await send("heartbeat", json=state)
                    job = response.get("job")
                    latest_job = job
                    if not announced:
                        print(
                            "[3/3] 网站已连接。返回网页查看微信连接状态并选择采集功能。请保持此窗口运行。",
                            flush=True,
                        )
                        announced = True
                    identity = (job["task_id"], job["execution_id"]) if job else None
                    if current and (identity != current_id or job.get("cancel_requested")):
                        current.cancel()
                        await asyncio.gather(current, return_exceptions=True)
                        current = None
                    if (
                        job
                        and not job.get("cancel_requested")
                        and identity not in completed
                        and state["channels_ready"]
                    ):
                        if current is None or current.done():
                            current_id = identity
                            current = asyncio.create_task(execute(job))
                    if current and current.done():
                        with contextlib.suppress(Exception):
                            current.result()
                    await asyncio.sleep(2)
                except httpx.HTTPStatusError as error:
                    if error.response.status_code in {401, 403}:
                        raise RuntimeError("设备配对已撤销或账号不可用，请重新在网站配对") from None
                    await asyncio.sleep(2)
                except httpx.TransportError:
                    if current:
                        current.cancel()
                        await asyncio.gather(current, return_exceptions=True)
                        current = None
                    print("连接平台暂时中断，正在重试；不会继续提取音频。", flush=True)
                    await asyncio.sleep(5)
        finally:
            if current:
                current.cancel()
                await asyncio.gather(current, return_exceptions=True)


def main():
    """读取网站下载的专用配对配置，不需要平台用户密码。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--mcp-url", default="http://127.0.0.1:2022/mcp")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    asyncio.run(run(config, args.mcp_url))


if __name__ == "__main__":
    main()
