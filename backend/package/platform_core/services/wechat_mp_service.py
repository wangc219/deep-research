"""公众号原版模块的独立运行与用户目录管理。"""

import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from functools import lru_cache

import httpx


class WechatMPUnavailable(RuntimeError):
    """公众号运行环境尚未就绪。"""


def source_root() -> Path:
    """定位随 API 镜像分发的公众号子项目。"""
    return Path(os.getenv("WECHAT_MP_SOURCE", str(Path(__file__).resolve().parents[3] / "wechat_mp")))


def frontend_asset(path: str) -> tuple[bytes, str]:
    """只读镜像内公共前端资源，按文件版本复用内容和摘要。"""
    root = (source_root() / "frontend").resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise FileNotFoundError("公众号前端资源不存在")
    stat = target.stat()
    return _read_frontend_asset(str(target), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=128)
def _read_frontend_asset(path: str, modified: int, size: int) -> tuple[bytes, str]:
    """缓存键包含文件版本，部署新文件时不复用旧资源。"""
    content = Path(path).read_bytes()
    return content, hashlib.sha256(content).hexdigest()[:20]


def frontend_document(*, can_manage_accounts: bool = False) -> str:
    """为依赖添加内容版本，并注入当前用户的共享账号管理能力。"""
    content, _ = frontend_asset("index.html")

    def versioned(match):
        """同一份镜像资源使用稳定版本 URL。"""
        _, version = frontend_asset(match[2])
        return f'{match[1]}{match[2]}?v={version}"'

    document = re.sub(
        r'((?:src|href)="/api/wechat-mp/app/)((?:js|css)/[^"?]+)"',
        versioned,
        content.decode("utf-8"),
    )
    capability = (
        "<script>window.__WECHAT_MP_CAN_MANAGE_ACCOUNTS__ = "
        f"{'true' if can_manage_accounts else 'false'};</script>"
    )
    return document.replace("</head>", capability + "\n</head>", 1)


def data_root() -> Path:
    """公众号用户状态使用持久化目录，独立于参考源码。"""
    return Path(os.getenv("WECHAT_MP_DATA_ROOT", "outputs/wechat-mp")).resolve()


def shared_account_pool_file() -> Path:
    """返回所有公众号 Worker 共用的微信读书凭据文件。"""
    directory = data_root() / "_shared"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory / "account_pool.json"


def owner_key(uid: str) -> str:
    """平台用户唯一标识映射为固定长度的私有目录名。"""
    return hashlib.sha256(str(uid).encode()).hexdigest()


def owner_directory(key: str) -> Path:
    """校验来自 RSS URL 的目录标识。"""
    if not re.fullmatch(r"[a-f0-9]{64}", key):
        raise ValueError("公众号空间不存在")
    return data_root() / key


def register_owner(uid: str) -> str:
    """保存用户归属，用于平台重启恢复 RSS 及订阅权限核验。"""
    key = owner_key(uid)
    directory = owner_directory(key)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    owner = directory / "owner.json"
    try:
        with owner.open("x") as stream:
            json.dump({"uid": str(uid)}, stream)
    except FileExistsError:
        pass
    return key


async def ensure_worker(key: str) -> str:
    """复用存活进程；跨 API worker 的 flock 避免重复调度同一用户。"""
    directory = owner_directory(key)
    if not (directory / "owner.json").exists():
        raise WechatMPUnavailable("公众号空间尚未初始化")
    sockets = Path(os.getenv("WECHAT_MP_SOCKET_ROOT", "/tmp/platform-wechat-mp"))
    sockets.mkdir(parents=True, exist_ok=True, mode=0o700)
    socket_path = str(sockets / (key[:32] + ".sock"))
    transport = httpx.AsyncHTTPTransport(uds=socket_path)
    async with httpx.AsyncClient(transport=transport, base_url="http://wechat-mp", timeout=2) as client:
        try:
            if (await client.get("/healthz")).status_code == 200:
                return socket_path
        except httpx.TransportError:
            pass
        lock = (sockets / (key + ".lock")).open("a")
        try:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass  # 另一个 API worker 已启动该用户进程，等待 readiness。
            else:
                python = os.getenv("WECHAT_MP_PYTHON", "/opt/wechat-mp/bin/python")
                if not Path(python).is_file():
                    python = sys.executable
                env = {
                    **{
                        name: value
                        for name, value in os.environ.items()
                        if name
                        in {
                            "PATH",
                            "HOME",
                            "LANG",
                            "LC_ALL",
                            "TZ",
                            "TMPDIR",
                            "PLAYWRIGHT_BROWSERS_PATH",
                            "CHROME_PATH",
                            "CHROMIUM_PATH",
                            "SSL_CERT_FILE",
                            "REQUESTS_CA_BUNDLE",
                            "CURL_CA_BUNDLE",
                            "HTTP_PROXY",
                            "HTTPS_PROXY",
                            "NO_PROXY",
                            "http_proxy",
                            "https_proxy",
                            "no_proxy",
                        }
                    },
                    "WECHAT_MP_DATA_DIR": str(directory),
                    "WECHAT_MP_ACCOUNT_POOL_FILE": str(shared_account_pool_file()),
                    "WECHAT_MP_SOCKET": socket_path,
                    "WECHAT_MP_DESKTOP": "0",
                    "PYTHONUNBUFFERED": "1",
                }
                with (directory / "runtime.log").open("a") as log:
                    subprocess.Popen(
                        [python, str(source_root() / "platform_worker.py")],
                        cwd=source_root(),
                        env=env,
                        stdout=log,
                        stderr=log,
                        pass_fds=(lock.fileno(),),
                        start_new_session=True,
                    )
            for _ in range(80):
                await asyncio.sleep(0.1)
                try:
                    if (await client.get("/healthz")).status_code == 200:
                        return socket_path
                except httpx.TransportError:
                    continue
        finally:
            lock.close()
    raise WechatMPUnavailable("公众号服务启动失败，请检查公众号运行依赖与 runtime.log 后重试")


async def restore_subscriptions():
    """平台重启后恢复已初始化用户的 RSS 定时抓取。"""
    from loguru import logger

    for owner in data_root().glob("*/owner.json"):
        try:
            await ensure_worker(owner.parent.name)
        except (ValueError, WechatMPUnavailable, OSError) as exc:
            logger.warning("公众号 RSS 恢复失败: component=wechat_mp type={}", type(exc).__name__)
