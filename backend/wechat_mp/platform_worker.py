"""按平台用户运行公众号原版应用；仅通过私有 Unix socket 接受平台网关访问。"""

import html
import hashlib
import re
import xml.etree.ElementTree as ET
import io
import os
from pathlib import Path
import secrets
import signal
import zipfile
from urllib.parse import quote

from flask import jsonify, request, Response, send_file
from werkzeug.serving import WSGIRequestHandler, make_server

from app_mp import app
from backend.config import DATA_DIR, OUTPUT_DIR, ensure_dirs, get_settings, save_settings
from backend.waterwall import waterwall_bp

PREFIX = "/api/wechat-mp/app"
app.register_blueprint(waterwall_bp)
ensure_dirs()
settings = get_settings()
settings["download_dir"] = str(OUTPUT_DIR)
if not settings.get("rss_token"):
    settings["rss_token"] = secrets.token_urlsafe(32)
save_settings(settings)


def owned_path(raw: str = "") -> Path:
    """文件访问只允许当前用户的文章目录。"""
    path = Path(raw)
    if not path.is_absolute():
        path = OUTPUT_DIR / path
    path = path.resolve()
    if not path.is_relative_to(OUTPUT_DIR.resolve()):
        raise ValueError("只能访问当前用户的文章目录")
    return path


@app.before_request
def platform_boundary():
    """约束桌面版可配置路径，防止跨用户读取或写入。"""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify(error="请求内容必须为对象"), 400
        try:
            for key in ("path", "download_dir"):
                if data.get(key):
                    owned_path(str(data[key]))
            for key in ("account", "account_name", "nickname"):
                value = data.get(key)
                if isinstance(value, str) and ("/" in value or "\\" in value or value in {".", ".."}):
                    raise ValueError("公众号名称不能包含路径分隔符")
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        if request.path == "/api/settings":
            data["download_dir"] = str(OUTPUT_DIR)
            if "rss_token" in data and not data["rss_token"]:
                data["rss_token"] = secrets.token_urlsafe(32)
            # 返回链接始终由平台网关按实际访问地址装配。
            data["rss_base_url"] = ""


@app.after_request
def platform_response(response):
    """修正原版返回的相对 URL，并隔离下载文章中的脚本。"""
    if response.is_json:
        payload = response.get_json()
        if isinstance(payload, dict) and isinstance(payload.get("url"), str) and payload["url"].startswith("/api/"):
            payload["url"] = PREFIX + payload["url"]
            response.set_data(app.json.dumps(payload))
    if request.path.startswith("/api/articles/rss") and response.status_code == 200:
        public_base = request.headers.get("X-Platform-Public-Base", "").rstrip("/")
        token = quote(get_settings()["rss_token"], safe="")
        old_base = public_base + PREFIX + "/api/"
        new_base = public_base + "/api/wechat-mp/resources/" + DATA_DIR.name + "/"
        xml = ET.fromstring(response.get_data())
        for element in xml.iter():
            if element.text and old_base in element.text:
                element.text = re.sub(re.escape(old_base) + r"([^\s<>\"')]+)",
                                      lambda match: new_base + match[1] + ("&" if "?" in match[1] else "?") + "token=" + token,
                                      element.text)
        response.set_data(ET.tostring(xml, encoding="utf-8", xml_declaration=True))
        etag = hashlib.sha256(response.get_data()).hexdigest()
        response.set_etag(etag)
        if request.if_none_match.contains(etag):
            response.status_code = 304
            response.set_data(b"")
    if request.path.startswith("/api/articles/serve-file"):
        response.headers["Content-Security-Policy"] = "sandbox allow-same-origin; default-src 'none'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; media-src 'self' https:"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/api/platform/rss-link")
def rss_link():
    """生成只读 RSS 专用令牌链接，不携带平台登录凭据。"""
    base = request.headers["X-Platform-Public-Base"].rstrip("/")
    account = request.args.get("account", "")
    suffix = "/" + quote(account, safe="") if account else ""
    return jsonify(url=f"{base}/api/wechat-mp/feed/{DATA_DIR.name}{suffix}?token={quote(get_settings()['rss_token'], safe='')}")


@app.get("/api/platform/files")
def files():
    """浏览或打包当前用户已导出的文章和离线资源。"""
    try:
        path = owned_path(request.args.get("path", ""))
    except ValueError as exc:
        return jsonify(error=str(exc)), 403
    if not path.exists():
        return jsonify(error="文件不存在"), 404
    if path.is_file():
        return send_file(path, as_attachment=True)
    if request.args.get("zip") == "1":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for entry in path.rglob("*"):
                if entry.is_file() and entry.resolve().is_relative_to(OUTPUT_DIR.resolve()):
                    archive.write(entry, entry.relative_to(path))
        buffer.seek(0)
        return send_file(buffer, mimetype="application/zip", as_attachment=True, download_name=f"{path.name}.zip")
    rows = []
    if path != OUTPUT_DIR:
        rows.append(f'<li><a href="?path={quote(str(path.parent), safe="")}">返回上级</a></li>')
    for entry in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
        if entry.resolve().is_relative_to(OUTPUT_DIR.resolve()):
            rows.append(f'<li><a href="?path={quote(str(entry), safe="")}">{"📁" if entry.is_dir() else "📄"} {html.escape(entry.name)}</a></li>')
    return Response('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>公众号文章文件</title>'
                    '<style>body{font:16px system-ui;padding:32px;line-height:2;color:#253047}a{color:#17855b}li{list-style:none}</style>'
                    f'<h1>公众号文章文件</h1><a href="?path={quote(str(path), safe="")}&zip=1">下载此目录 ZIP</a><ul>{"".join(rows)}</ul>', mimetype="text/html")


def open_folder():
    """把原版打开目录操作转为浏览器目录页。"""
    try:
        path = owned_path((request.get_json() or {}).get("account", ""))
        path.mkdir(parents=True, exist_ok=True)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(url=f"/api/platform/files?path={quote(str(path), safe='')}", message="已打开文章文件")


original_open_file = app.view_functions["articles.open_file"]


def open_file():
    """保留原版格式选择，把目录操作映射到网页文件列表。"""
    data = request.get_json() or {}
    path = owned_path(data.get("path", ""))
    if path.is_dir() and not data.get("type"):
        return jsonify(url=f"/api/platform/files?path={quote(str(path), safe='')}")
    return original_open_file()


def open_parent():
    """浏览原版文件所在目录。"""
    path = owned_path((request.get_json() or {}).get("path", ""))
    if path.is_file():
        path = path.parent
    return jsonify(url=f"/api/platform/files?path={quote(str(path), safe='')}")


app.view_functions["articles.open_folder"] = open_folder
app.view_functions["articles.open_file"] = open_file
app.view_functions["articles.open_parent"] = open_parent


class PrivateRequestHandler(WSGIRequestHandler):
    """避免将 RSS token 或微信敏感查询参数写入访问日志。"""

    def log_request(self, code="-", size="-"):
        self.log("info", "%s %s %s", self.command, self.path.split("?", 1)[0], code)


def main():
    """持有跨 API worker 文件锁，保证每个用户只有一个 RSS/下载进程。"""
    (DATA_DIR / "worker.pid").write_text(str(os.getpid()))
    socket_path = os.environ["WECHAT_MP_SOCKET"]
    Path(socket_path).unlink(missing_ok=True)
    server = make_server("unix://" + socket_path, 0, app, threaded=True, request_handler=PrivateRequestHandler)
    os.chmod(socket_path, 0o600)
    signal.signal(signal.SIGTERM, lambda *_: exit(0))
    server.serve_forever()


if __name__ == "__main__":
    main()
