"""Small MCP client for the wx_channels_download Streamable HTTP endpoint.

The downloader owns WeChat login/session state, URL resolution and decryption.
This module only calls its public MCP tools and returns local media paths.
"""

from __future__ import annotations

import json
import os
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from platform_core.knowledge.video_transcriber.utils.ffmpeg import get_ffmpeg_path


class WxChannelsError(RuntimeError):
    """Raised when the downloader cannot complete a requested operation."""


@dataclass
class WxVideo:
    """Normalized video item returned by the account feed tool."""

    oid: str
    nid: str
    url: str = ""
    title: str = ""
    raw: dict[str, Any] | None = None
    published_at: int = 0


def downloader_endpoint() -> str:
    """视频号使用默认连接地址，容器自动访问宿主机微信。"""
    default = (
        "http://host.docker.internal:2022/mcp"
        if os.getenv("RUNNING_IN_DOCKER") == "true"
        else "http://127.0.0.1:2022/mcp"
    )
    return os.getenv("WX_CHANNELS_MCP_URL", default).rstrip("/")


async def collector_proxy_status(client: httpx.AsyncClient, base: str) -> dict:
    """读取实际监听、系统代理与证书状态，不用配置开关代替运行状态。"""
    response = await client.get(base + "/api/proxy/status")
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data")
    if payload.get("code") != 0 or not isinstance(data, dict):
        raise WxChannelsError("微信采集器未返回有效的连接状态，请更新采集程序")
    certificate = data.get("certificate") or {}
    certificate_ready = (
        certificate.get("installed") is True
        and certificate.get("trusted") is True
        and certificate.get("is_legacy") is False
    )
    proxy_ready = (
        certificate_ready
        and (data.get("service") or {}).get("listening") is True
        and (data.get("system_proxy") or {}).get("matched") is True
    )
    return {"proxy_ready": proxy_ready, "certificate_ready": certificate_ready}


async def prepare_collector_connection(client: httpx.AsyncClient, base: str) -> dict:
    """对齐 video_text，复用已信任的本机证书并恢复微信所需的系统代理。"""
    response = await client.post(base + "/api/mcp/enable")
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0 or (payload.get("data") or {}).get("enabled") is not True:
        raise WxChannelsError("微信采集器未确认 MCP 已启用")
    state = await collector_proxy_status(client, base)
    if not state["certificate_ready"]:
        raise WxChannelsError("微信采集证书尚未完成本机信任，请在采集程序中完成系统授权后重新连接")
    if state["proxy_ready"]:
        return state
    response = await client.post(
        base + "/api/proxy/config",
        json={
            "values": {"proxy.enabled": True, "proxy.system": True, "proxy.skipInstallRootCert": False},
            "restart": True,
        },
    )
    response.raise_for_status()
    if response.json().get("code") != 0:
        raise WxChannelsError("微信采集代理未能启动，请检查采集程序的系统授权提示")
    for _ in range(20):
        await asyncio.sleep(0.5)
        try:
            state = await collector_proxy_status(client, base)
        except httpx.TransportError:
            continue
        if state["proxy_ready"]:
            return state
    raise WxChannelsError("微信采集代理尚未生效，请检查其他代理软件是否覆盖了系统代理")


class WxChannelsMCPClient:
    """Client for wx_channels_download's stateless Streamable HTTP MCP."""

    def __init__(
        self,
        endpoint: str | None = None,
        timeout: float = 300.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.endpoint = (endpoint or downloader_endpoint()).rstrip("/")
        self.timeout = timeout
        self._client = http_client
        self._request_id = 0

    async def __aenter__(self) -> WxChannelsMCPClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, trust_env=False)
        try:
            await self.initialize()
        except BaseException:
            await self.__aexit__()
            raise
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def initialize(self) -> dict[str, Any]:
        return await self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "deep-research-video", "version": "1.0"},
            },
        )

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout, trust_env=False)
        self._request_id += 1
        payload = {"jsonrpc": "2.0", "id": self._request_id, "method": method}
        if params is not None:
            payload["params"] = params
        try:
            response = await self._client.post(
                self.endpoint,
                json=payload,
                headers={"Content-Type": "application/json", "MCP-Protocol-Version": "2025-11-25"},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WxChannelsError(f"无法连接视频号下载器 MCP: {exc}") from exc
        if data.get("error"):
            error = data["error"]
            raise WxChannelsError(str(error.get("message", error)))
        return data.get("result") or {}

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("isError"):
            message = self._result_text(result)
            if "timed out" in message.lower():
                message = "微信视频号响应超时，请重新打开视频号窗口并保持在线后重试"
            raise WxChannelsError(message)
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        text = self._result_text(result)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    @staticmethod
    def _result_text(result: dict[str, Any]) -> str:
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                return str(item.get("text", ""))
        return str(result)

    async def search_accounts(self, keyword: str) -> Any:
        return await self.call_tool("search_wxchannels_accounts", {"keyword": keyword})

    async def account_videos(self, username: str, next_marker: str = "") -> Any:
        return await self.call_tool(
            "get_wxchannels_account_videos",
            {"username": username, "next_marker": next_marker},
        )

    async def iter_account_videos(
        self,
        username: str,
        max_pages: int | None = None,
        *,
        known_oids: set[str] | None = None,
        start_marker: str = "",
        selected_oids: set[str] | None = None,
        max_videos: int | None = None,
        skip_oids: set[str] | None = None,
    ) -> list[WxVideo]:
        """按游标获取全部页（或指定页数），以发布时间降序返回去重视频。"""
        videos: list[WxVideo] = []
        marker = start_marker
        self.next_marker = marker
        seen: set[str] = set()
        markers: set[str] = set()
        page_count = 0
        known_pages = 0
        self.history_complete = False
        while max_pages is None or page_count < max_pages:
            page_count += 1
            page = await self.account_videos(username, marker)
            objects = _find_video_objects(page)
            for obj in objects:
                oid = _first_string(obj, "id", "objectId", "objectid")
                nid = _first_string(obj, "objectNonceId", "object_nonce_id", "nid")
                if not oid or not nid:
                    continue
                key = oid
                if key in seen:
                    continue
                seen.add(key)
                videos.append(
                    WxVideo(
                        oid=oid,
                        nid=nid,
                        url=_first_string(obj, "source_url", "sourceUrl", "url"),
                        title=_nested_string(obj, ("objectDesc", "description"))
                        or _first_string(obj, "title", "description"),
                        raw=obj,
                        published_at=video_publish_time(obj),
                    )
                )
            next_marker = _find_marker(page)
            self.next_marker = next_marker
            if not next_marker or not objects:
                self.history_complete = True
                break
            if selected_oids and selected_oids <= seen:
                break
            if not selected_oids and max_videos is not None and len(seen - (skip_oids or set())) >= max_videos:
                break
            if next_marker in markers:
                break
            # 连续两页均已保存才停止，避免单页置顶内容掩盖后续新增视频。
            page_oids = {_first_string(obj, "id", "objectId", "objectid") for obj in objects}
            known_pages = known_pages + 1 if known_oids and page_oids and page_oids <= known_oids else 0
            if known_pages >= 2:
                break
            markers.add(next_marker)
            marker = next_marker
        return sorted(videos, key=lambda video: video.published_at, reverse=True)

    async def extract_audio_stream(
        self,
        video: WxVideo,
        output_path: Path,
        timeout_seconds: int = 3600,
    ) -> Path:
        """Decode the remote stream through /play and save only 16 kHz mono audio.

        /play decrypts in memory and supports HTTP ranges, so FFmpeg can seek
        even when the remote MP4's metadata is at the end. No download task or
        local video file is created, and failures never fall back to MP4.
        """
        try:
            profile = await self.call_tool(
                "get_wxchannels_video_profile",
                {"oid": video.oid, "nid": video.nid},
            )
        except WxChannelsError:
            # Account feeds can already contain the complete stream metadata.
            # Use it when the detail request times out; never download a video
            # as a fallback. FFmpeg still validates that the stream is usable.
            desc = video.raw.get("objectDesc", {}) if isinstance(video.raw, dict) else {}
            media = desc.get("media", []) if isinstance(desc, dict) else []
            if not media or not isinstance(media[0], dict) or not _first_string(media[0], "url"):
                raise
            profile = {"object": video.raw}
        if isinstance(profile, dict) and isinstance(profile.get("data"), dict):
            profile = profile["data"]
        obj = profile.get("object", {}) if isinstance(profile, dict) else {}
        desc = obj.get("objectDesc", {}) if isinstance(obj, dict) else {}
        media = desc.get("media", []) if isinstance(desc, dict) else []
        if not media or not isinstance(media[0], dict):
            raise WxChannelsError("视频详情缺少可用媒体流，无法直接提取音频")
        source = _first_string(media[0], "url") + _first_string(media[0], "urlToken")
        if urlsplit(source).scheme not in {"http", "https"}:
            raise WxChannelsError("视频详情缺少有效的媒体流地址")
        params = {"url": source}
        key = _first_string(media[0], "decodeKey")
        if key:
            params["key"] = key
        endpoint = urlsplit(self.endpoint)
        stream_url = urlunsplit((endpoint.scheme, endpoint.netloc, "/play", urlencode(params), ""))
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            raise WxChannelsError("未找到 FFmpeg，无法直接提取音频")
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-rw_timeout",
            "30000000",
            "-i",
            stream_url,
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            str(output_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
            if process.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 44:
                raise WxChannelsError("视频流音频提取失败，请检查微信连接和视频是否包含音轨")
            return output_path
        except BaseException:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
            output_path.unlink(missing_ok=True)
            raise


def video_publish_time(value: dict) -> int:
    """统一微信原始和下载器字段的秒/毫秒时间戳，缺失时间排在最后。"""
    for key in ("createtime", "createTime", "create_time", "publish_time"):
        raw = value.get(key)
        if isinstance(raw, bool):
            continue
        try:
            timestamp = int(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if timestamp > 0:
            return timestamp // 1000 if timestamp >= 1_000_000_000_000 else timestamp
    return 0


def _first_string(value: Any, *keys: str) -> str:
    if not isinstance(value, dict):
        return ""
    for key in keys:
        item = value.get(key)
        if item is not None and str(item).strip():
            return str(item).strip()
    return ""


def _nested_string(value: Any, keys: tuple[str, str]) -> str:
    current = value.get(keys[0]) if isinstance(value, dict) else None
    return _first_string(current, keys[1])


def _find_video_objects(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        for key in ("object", "objects", "objectList", "feeds", "items"):
            item = value.get(key)
            if isinstance(item, list):
                return [x for x in item if isinstance(x, dict)]
        for item in value.values():
            found = _find_video_objects(item)
            if found:
                return found
    elif isinstance(value, list):
        candidates = [x for x in value if isinstance(x, dict) and (_first_string(x, "id", "objectId", "objectid"))]
        if candidates:
            return candidates
        for item in value:
            found = _find_video_objects(item)
            if found:
                return found
    return []


def _find_marker(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("lastBuffer", "lastBuff", "next_marker"):
            candidate = value.get(key)
            if candidate is not None and str(candidate).strip():
                return str(candidate).strip()
        for item in value.values():
            marker = _find_marker(item)
            if marker:
                return marker
    elif isinstance(value, list):
        for item in value:
            marker = _find_marker(item)
            if marker:
                return marker
    return ""
