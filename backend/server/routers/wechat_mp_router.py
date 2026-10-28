"""知识库中的公众号文章入口、平台鉴权及原版应用流式网关。"""

import hmac
import json
import mimetypes
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from starlette.responses import JSONResponse, Response, StreamingResponse

from platform_core.services import wechat_mp_service as service
from platform_core.services.enterprise_service import feature_access
from platform_core.storage.postgres.models_business import Department, User
from server.utils.auth_middleware import get_current_user, get_db, get_required_user

router = APIRouter(prefix="/wechat-mp", tags=["wechat-mp"])
COOKIE = "wechat_mp_session"


async def module_user(request: Request, db=Depends(get_db)):
    """每次请求重新检查平台身份与知识库权限，cookie 只用于嵌入页。"""
    authorization = request.headers.get("authorization")
    if not authorization:
        token = request.cookies.get(COOKIE)
        authorization = f"Bearer {token}" if token else None
        if request.method not in {"GET", "HEAD"} and request.headers.get("x-requested-with") != "WechatMP":
            raise HTTPException(403, "请通过公众号文章页面提交操作")
    user = await get_required_user(await get_current_user(authorization, db))
    access = await feature_access(db, user, "knowledge")
    write = request.method not in {"GET", "HEAD"} and not request.url.path.endswith("/session")
    if not access["can_write" if write else "can_read"]:
        raise HTTPException(403, "没有知识库操作权限")
    # 私有进程启动或下载代理期间无需继续持有权限查询的只读事务。
    await db.commit()
    return user


@router.post("/session")
async def open_session(request: Request, user=Depends(module_user)):
    """把已验证的平台凭据放入模块专用 HttpOnly cookie。"""
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "请重新登录平台")
    key = service.register_owner(user.uid)
    try:
        await service.ensure_worker(key)
    except (service.WechatMPUnavailable, OSError) as exc:
        raise HTTPException(503, "公众号运行环境未就绪，请检查服务依赖后重试") from exc
    response = JSONResponse(
        {"url": "/api/wechat-mp/app/index.html", "version": "2.3.3", "document": service.frontend_document()}
    )
    response.set_cookie(
        COOKIE,
        authorization[7:],
        httponly=True,
        samesite="strict",
        path="/api/wechat-mp",
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.delete("/session")
async def close_session():
    """退出平台时清除模块会话，后台下载和 RSS 仍保留。"""
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE, path="/api/wechat-mp")
    return response


async def subscription_owner(key: str, request: Request, db=Depends(get_db)):
    """校验 RSS 专用令牌以及订阅所有者当前权限。"""
    try:
        directory = service.owner_directory(key)
        owner = json.loads((directory / "owner.json").read_text())
        settings = json.loads((directory / "app_settings.json").read_text())
    except (ValueError, OSError):
        raise HTTPException(404, "订阅不存在") from None
    expected = settings.get("rss_token", "")
    supplied = request.query_params.get("token", "")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "RSS 访问令牌无效")
    user = await db.scalar(select(User).where(User.uid == owner["uid"], User.is_deleted == 0))
    if not user or user.is_login_locked():
        raise HTTPException(403, "订阅已停用")
    department = await db.get(Department, user.department_id)
    user.tenant_id = department.tenant_id if department else "default"
    if not (await feature_access(db, user, "knowledge"))["can_read"]:
        raise HTTPException(403, "订阅已停用")
    return key


@router.get("/feed/{key}")
@router.get("/feed/{key}/{account:path}")
async def public_feed(request: Request, account: str = "", key: str = Depends(subscription_owner)):
    """外部阅读器读取单公众号或聚合 RSS。"""
    from urllib.parse import quote

    suffix = "/" + quote(account, safe="") if account else ""
    return await forward(request, key, "/api/articles/rss" + suffix)


@router.get("/resources/{key}/{path:path}")
async def feed_resource(path: str, request: Request, key: str = Depends(subscription_owner)):
    """RSS 令牌只允许读取文章及头像资源。"""
    if not path.startswith(("articles/serve-file/", "articles/avatars/")):
        raise HTTPException(404, "订阅资源不存在")
    return await forward(request, key, "/api/" + path)


@router.api_route("/app/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
async def application(path: str, request: Request, user=Depends(module_user)):
    """页面、资源、任务进度与下载使用同一个用户身份。"""
    if path in {"", "index.html"}:
        return Response(
            service.frontend_document(), media_type="text/html", headers={"Cache-Control": "private, no-store"}
        )
    if path.startswith(("js/", "css/")):
        if request.method not in {"GET", "HEAD"}:
            raise HTTPException(405, "前端资源只允许读取")
        try:
            content, version = service.frontend_asset(path)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, "公众号前端资源不存在") from exc
        etag = f'"{version}"'
        cache = (
            "private, max-age=31536000, immutable" if request.query_params.get("v") == version else "private, no-cache"
        )
        headers = {"Cache-Control": cache, "ETag": etag}
        validators = {value.strip().removeprefix("W/") for value in request.headers.get("if-none-match", "").split(",")}
        if etag in validators or "*" in validators:
            return Response(status_code=304, headers=headers)
        headers["Content-Length"] = str(len(content))
        return Response(
            b"" if request.method == "HEAD" else content,
            media_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
            headers=headers,
        )
    if path.startswith("api/") and path.split("/")[1] not in {
        "auth",
        "account-pool",
        "accounts",
        "articles",
        "proxy",
        "settings",
        "capabilities",
        "waterwall",
        "diagnose",
        "platform",
    }:
        raise HTTPException(404, "本模块仅提供微信公众号功能")
    key = service.register_owner(user.uid)
    return await forward(request, key, "/" + path)


async def forward(request: Request, key: str, path: str):
    """流式转发 SSE 和文件，断线时关闭上游连接。"""
    try:
        socket = await service.ensure_worker(key)
    except (service.WechatMPUnavailable, OSError) as exc:
        raise HTTPException(503, "公众号服务暂不可用，请重试") from exc
    origin = urlsplit(
        request.headers.get("x-platform-origin")
        or request.headers.get("origin")
        or request.headers.get("referer")
        or str(request.base_url)
    )
    public_base = f"{origin.scheme}://{origin.netloc}"
    headers = {
        name: request.headers[name]
        for name in ("content-type", "accept", "if-none-match", "range", "if-range")
        if name in request.headers
    }
    headers["X-Platform-Public-Base"] = public_base
    headers["X-Forwarded-Host"] = origin.netloc
    headers["X-Forwarded-Proto"] = origin.scheme
    client = httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(uds=socket),
        base_url="http://wechat-mp",
        timeout=httpx.Timeout(180, connect=10),
    )
    try:
        upstream = await client.send(
            client.build_request(
                request.method,
                path,
                params=request.query_params.multi_items(),
                content=await request.body(),
                headers=headers,
            ),
            stream=True,
        )
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(502, "公众号服务连接中断，请重试") from exc
    response_headers = {
        name: value
        for name, value in upstream.headers.items()
        if name.lower()
        in {
            "content-type",
            "content-disposition",
            "content-length",
            "etag",
            "last-modified",
            "content-range",
            "accept-ranges",
            "content-security-policy",
            "x-content-type-options",
        }
    }
    if not path.startswith(("/api/articles/serve-file", "/api/platform/files")):
        response_headers.pop("content-disposition", None)
    response_headers.update(
        {"Cache-Control": "private, no-store", "X-Accel-Buffering": "no", "Referrer-Policy": "no-referrer"}
    )

    async def content():
        """消费完成、异常或取消都释放流式上游。"""
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(content(), status_code=upstream.status_code, headers=response_headers)
