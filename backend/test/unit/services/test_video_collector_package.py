"""验证一键连接包中的凭据隔离、平台程序和启动器权限。"""

import io
import json
import zipfile
from pathlib import Path

import pytest

from platform_core.services.video_collector_package import build_connection_package


@pytest.mark.parametrize(
    "platform,target,suffix,launcher",
    [
        ("macos", "darwin", "", "连接我的微信.command"),
        ("windows", "windows", ".exe", "连接我的微信.cmd"),
    ],
)
def test_oneclick_package_is_bound_to_one_device(tmp_path, platform, target, suffix, launcher):
    """解压后已有配置和双架构程序，不要求用户手填参数或编译。"""
    root = Path(__file__).resolve().parents[3]
    import shutil

    shutil.copytree(
        root / "video_collector", tmp_path / "video_collector", ignore=shutil.ignore_patterns("bin", "__pycache__")
    )
    shutil.copytree(
        root / "package/platform_core/knowledge/video_transcriber/utils/ffmpeg",
        tmp_path / "package/platform_core/knowledge/video_transcriber/utils/ffmpeg",
    )
    shutil.copy2(
        root / "package/platform_core/knowledge/wxchannels.py",
        tmp_path / "package/platform_core/knowledge/wxchannels.py",
    )
    for arch in ("amd64", "arm64"):
        binary = tmp_path / "video_collector/bin" / f"{target}-{arch}" / ("video-downloader" + suffix)
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"compiled-fixture")
    license_path = tmp_path / "vendor/wx_channels_download/LICENSE"
    license_path.parent.mkdir(parents=True)
    license_path.write_text("source license")
    config = {
        "device_id": "wxd_" + "a" * 32,
        "token": "b" * 64,
        "platform": platform,
        "name": "我的电脑",
        "platform_url": "https://research.example",
    }
    content = build_connection_package(tmp_path, config)
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        assert not any("wechat" in name for name in package.namelist())
        assert b"playwright" not in package.read(launcher)
        assert json.loads(package.read("video-collector.json")) == config
        assert package.getinfo(launcher).external_attr >> 16 & 0o100
        assert len([name for name in package.namelist() if name.startswith("bin/")]) == 2
        assert all(
            "data.db" not in name and ".env" not in name and "private.key" not in name for name in package.namelist()
        )
        assert b"uv" in package.read(launcher)
