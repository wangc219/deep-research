"""生成已配对的一键连接包，普通用户无需手动配置运行环境。"""

import io
import json
import zipfile
from functools import lru_cache
from pathlib import Path


def build_connection_package(root: Path, config: dict) -> bytes:
    """复用已压缩的公共程序包，只为本设备追加专用配对配置。"""
    collector = root / "video_collector"
    knowledge = root / "package/platform_core/knowledge"
    target = "windows" if config["platform"] == "windows" else "darwin"
    suffix = ".exe" if target == "windows" else ""
    binaries = [collector / "bin" / f"{target}-{arch}" / ("video-downloader" + suffix) for arch in ("amd64", "arm64")]
    if any(not binary.is_file() for binary in binaries):
        raise FileNotFoundError("桌面采集程序未构建，请重新构建 API 镜像或执行 scripts/build-video-collectors.sh")
    launcher = "连接我的微信.cmd" if target == "windows" else "连接我的微信.command"
    sources = [
        *binaries,
        collector / "collector.py",
        collector / "bootstrap.py",
        collector / launcher,
        knowledge / "wxchannels.py",
        knowledge / "video_transcriber/utils/ffmpeg/__init__.py",
    ]
    version = tuple((path.stat().st_mtime_ns, path.stat().st_size) for path in sources)
    base = compressed_public_payload(str(root), target, version)
    output = io.BytesIO(base)
    with zipfile.ZipFile(output, "a", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("video-collector.json", json.dumps(config, ensure_ascii=False, indent=2))
    return output.getvalue()


@lru_cache(maxsize=2)
def compressed_public_payload(root_path: str, target: str, version: tuple) -> bytes:
    """每种系统只压缩一次公共代码和程序；缓存永不包含用户身份或令牌。"""
    root = Path(root_path)
    collector = root / "video_collector"
    knowledge = root / "package/platform_core/knowledge"
    suffix = ".exe" if target == "windows" else ""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        for name in ("collector.py", "bootstrap.py"):
            archive.write(collector / name, name)
        launcher = "连接我的微信.cmd" if target == "windows" else "连接我的微信.command"
        entry = zipfile.ZipInfo(launcher)
        entry.create_system = 3
        entry.external_attr = 0o100755 << 16
        archive.writestr(entry, (collector / launcher).read_bytes())
        archive.writestr(
            "使用说明.txt",
            "解压后双击“连接我的微信”，首次自动准备环境。\n"
            "保持连接窗口运行。看到“[3/3] 网站已连接”后返回网站；请在微信打开视频号页面。\n"
            "连接包含此电脑的专用配对凭据，请勿转发。可在网站撤销配对。\n",
        )
        for arch in ("amd64", "arm64"):
            name = f"{target}-{arch}/video-downloader{suffix}"
            archive.write(collector / "bin" / name, "bin/" + name)
        archive.write(knowledge / "wxchannels.py", "platform_core/knowledge/wxchannels.py")
        archive.write(
            knowledge / "video_transcriber/utils/ffmpeg/__init__.py",
            "platform_core/knowledge/video_transcriber/utils/ffmpeg/__init__.py",
        )
        for directory in (
            "platform_core",
            "platform_core/knowledge",
            "platform_core/knowledge/video_transcriber",
            "platform_core/knowledge/video_transcriber/utils",
        ):
            archive.writestr(directory + "/__init__.py", "")
        vendor = root / "vendor/wx_channels_download"
        if not vendor.exists():
            vendor = root.parent / "vendor/wx_channels_download"
        archive.write(vendor / "LICENSE", "采集程序许可证.txt")
    return output.getvalue()
