"""一键启动：自动定位 FFmpeg、启动采集器并读取已配对的网站配置。"""

import asyncio
import json
import os
import platform
import subprocess
import time
from pathlib import Path

import httpx


async def prepare_local_certificate(client):
    """仅在用户双击的本机连接包内完成首次证书准备，系统授权仍交给用户。"""
    base = "http://127.0.0.1:2022"

    async def request(path, body=None):
        """校验本机采集程序的 HTTP 与业务状态，不输出证书或密钥。"""
        response = (
            await client.get(base + path) if body is None else await client.post(base + path, json=body, timeout=180)
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
            raise RuntimeError("本机微信采集证书准备失败，请检查采集程序的系统授权提示")
        return payload["data"]

    cert = await request("/api/proxy/certificate/status")
    if cert.get("is_legacy") or not (cert.get("configured") or {}).get("file"):
        print("首次连接，正在为本机生成独立的微信采集证书。", flush=True)
        await request(
            "/api/proxy/certificate/generate",
            {
                "name": "wx_channels_download",
                "install": False,
                "restart": False,
                "valid_years": 10,
            },
        )
        cert = await request("/api/proxy/certificate/status")
    if not cert.get("installed") or not cert.get("trusted"):
        print("请在操作系统弹窗中完成微信采集证书授权；无需在网页填写配置。", flush=True)
        await request("/api/proxy/certificate/install", {})
        cert = await request("/api/proxy/certificate/status")
    if cert.get("is_legacy") or not cert.get("installed") or not cert.get("trusted"):
        raise RuntimeError("证书尚未获得本机信任，微信代理未启用；请完成系统授权后重新双击连接")


def acquire_connection_lock(state):
    """同一配对只运行一个连接进程，进程退出时由系统释放锁。"""
    lock = (state / "connection.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            lock.write(b"0")
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock
    except OSError:
        lock.close()
        return None


def main():
    """使用用户目录保存运行态；无需手填平台地址或复制命令。"""
    import imageio_ffmpeg
    from collector import run

    root = Path(__file__).resolve().parent
    config = json.loads((root / "video-collector.json").read_text(encoding="utf-8"))
    state = Path.home() / ".research-video-collector" / config["device_id"]
    state.mkdir(parents=True, exist_ok=True)
    lock = acquire_connection_lock(state)
    if lock is None:
        print("微信连接已在运行，无需重复启动。请返回网站使用视频号转 DOCX。", flush=True)
        return
    with lock:
        start(config, root, state, imageio_ffmpeg.get_ffmpeg_exe(), run)


def start(config, root, state, ffmpeg, run):
    """复用本机采集器，检查服务响应后启动已配对的网站连接。"""
    print("[1/3] 运行环境已就绪，正在检查本机微信采集器。", flush=True)
    os.environ["FFMPEG_PATH"] = ffmpeg
    available = False
    try:
        with httpx.Client(timeout=2, trust_env=False) as client:
            response = client.get("http://127.0.0.1:2022/api/mcp/status")
            available = response.status_code == 200 and isinstance(response.json().get("data"), dict)
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    if not available:
        system = "windows" if platform.system() == "Windows" else "darwin"
        arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "amd64"
        extension = ".exe" if system == "windows" else ""
        binary = root / "bin" / f"{system}-{arch}" / ("video-downloader" + extension)
        if not binary.is_file():
            raise RuntimeError("连接包缺少当前电脑的采集程序，请重新从网站下载对应系统的连接包")
        print("正在启动微信采集器；首次使用请完成操作系统要求的确认。", flush=True)
        subprocess.Popen(
            [str(binary), "server", "--workdir", str(state / "downloader")],
            cwd=state,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
    for _ in range(60):
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                response = client.post("http://127.0.0.1:2022/api/mcp/enable")
                if response.status_code == 200 and response.json().get("code") == 0:
                    break
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        time.sleep(1)
    else:
        raise RuntimeError("采集程序尚未启动，请查看系统权限提示后重新双击连接")
    from platform_core.knowledge.wxchannels import prepare_collector_connection

    async def prepare():
        """网站心跳前先确认微信流量能进入本机采集器。"""
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            await prepare_local_certificate(client)
            await prepare_collector_connection(client, "http://127.0.0.1:2022")

    asyncio.run(prepare())
    print("[2/3] 本机采集器已启动，正在连接网站。", flush=True)
    print(
        "请保持此窗口运行。请在微信打开视频号页面。",
        flush=True,
    )
    asyncio.run(run(config, "http://127.0.0.1:2022/mcp"))


if __name__ == "__main__":
    main()
