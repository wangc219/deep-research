"""公众号静态资源的版本缓存与文件边界。"""

import re

import pytest

from platform_core.services import wechat_mp_service as service


def test_frontend_document_changes_asset_version_after_deployment(monkeypatch, tmp_path):
    """新部署的内容必须生成新 URL，用户不能继续命中旧脚本。"""
    monkeypatch.setenv("WECHAT_MP_SOURCE", str(tmp_path))
    frontend = tmp_path / "frontend"
    (frontend / "js").mkdir(parents=True)
    script = frontend / "js/app.js"
    script.write_text("const version = 1")
    (frontend / "index.html").write_text('<script defer src="/api/wechat-mp/app/js/app.js"></script>')
    first = service.frontend_document()
    assert "?v=" in first and "defer" in first
    assert service.frontend_document() == first
    script.write_text("const version = 222")
    second = service.frontend_document()
    assert second != first
    version = re.search(r"\?v=([a-f0-9]+)", second)[1]
    assert service.frontend_asset("js/app.js")[1] == version


def test_frontend_assets_never_read_outside_image_frontend(monkeypatch, tmp_path):
    """路径跳转和目录链接都不能越过公共资源根目录。"""
    monkeypatch.setenv("WECHAT_MP_SOURCE", str(tmp_path))
    frontend = tmp_path / "frontend"
    (frontend / "js").mkdir(parents=True)
    (tmp_path / "private.json").write_text("private")
    (frontend / "js/leak.js").symlink_to(tmp_path / "private.json")
    for path in ("../private.json", "js/../../private.json", "js/leak.js"):
        with pytest.raises(FileNotFoundError):
            service.frontend_asset(path)
