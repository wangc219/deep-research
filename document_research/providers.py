"""仅用于独立文档研发入口的 HTTP 提供商；不注册共享工具。"""

import asyncio
import json
import math
import re
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx

from .contracts import ResearchError

Authorize = Callable[[], None]
ZHIPU_RETRIEVE_URL = (
    "https://open.bigmodel.cn/api/llm-application/open/knowledge/retrieve"
)
ZHIPU_WEB_SEARCH_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"
PUBLIC_DOCUMENTS = (
    (
        "Docling 官方 README",
        "https://raw.githubusercontent.com/docling-project/docling/main/README.md",
    ),
    (
        "PaddleOCR 官方 README",
        "https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/main/README.md",
    ),
    (
        "Unstructured 官方 README",
        "https://raw.githubusercontent.com/Unstructured-IO/unstructured/main/README.md",
    ),
)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PUBLIC_EXCERPT = 6000
MAX_PUBLIC_SEARCH_RESULTS = 10
PUBLIC_SEARCH_SNIPPET_WARNING = (
    "联网来源为搜索服务返回的摘要，未读取网页全文；引用仅能核对这些片段。"
)
SOURCE_CREDENTIAL_PARAMS = {
    "access_token",
    "access-token",
    "accesskey",
    "accesskeyid",
    "api_key",
    "apikey",
    "authorization",
    "awsaccesskeyid",
    "credential",
    "key-pair-id",
    "ossaccesskeyid",
    "q-ak",
    "q-key-time",
    "q-sign-algorithm",
    "q-sign-time",
    "q-signature",
    "secret",
    "sig",
    "signature",
    "token",
    "x-amz-credential",
    "x-amz-security-token",
    "x-amz-signature",
    "x-goog-credential",
    "x-goog-signature",
}


class ProviderError(RuntimeError):
    """可展示的固定错误；不得包含响应正文、凭据或私有文本。"""


class ProviderConfigurationError(ProviderError):
    """显式网络配置错误不能降级为公开资料获取失败。"""


def safe_source_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        parts = urlsplit(value)
        parameter_names = {
            key.casefold()
            for component in (parts.query, parts.fragment)
            for key, _ in parse_qsl(component.replace(";", "&"), keep_blank_values=True)
        }
        return (
            value
            if parts.scheme in {"https", "http"}
            and parts.hostname
            and not parts.username
            and not parts.password
            and not parameter_names.intersection(SOURCE_CREDENTIAL_PARAMS)
            else None
        )
    except ValueError:
        return None


def primary_public_url(value: object) -> str | None:
    """只收录本模块候选工具的官方文档/代码与论文原始发布站点。"""
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2000
        or any(char.isspace() or ord(char) < 32 for char in value)
        or "\\" in value
    ):
        return None
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or parts.username
            or parts.password
            or parts.port not in {None, 443}
            or not parts.hostname
            or "%" in parts.path
            or any(part in {".", ".."} for part in parts.path.split("/"))
        ):
            return None
        host, path = parts.hostname.lower(), parts.path
        allowed = False
        if host in {"github.com", "raw.githubusercontent.com"}:
            pieces = path.strip("/").lower().split("/")
            repositories = {
                ("docling-project", "docling"),
                ("ds4sd", "docling"),
                ("paddlepaddle", "paddleocr"),
                ("unstructured-io", "unstructured"),
            }
            allowed = tuple(pieces[:2]) in repositories and (
                host == "raw.githubusercontent.com"
                or len(pieces) == 2
                or pieces[2] in {"blob", "tree", "releases"}
            )
        elif host == "docling-project.github.io":
            allowed = path == "/docling" or path.startswith("/docling/")
        elif host == "paddlepaddle.github.io":
            allowed = path == "/PaddleOCR" or path.startswith("/PaddleOCR/")
        elif host in {"docs.unstructured.io", "www.paddleocr.ai", "paddleocr.ai"}:
            allowed = True
        elif host in {"arxiv.org", "www.arxiv.org"}:
            allowed = bool(
                re.fullmatch(
                    r"/(?:abs|pdf|html)/(?:\d{4}\.\d{4,5}|[a-z-]+/\d{7})"
                    r"(?:v\d+)?(?:\.pdf)?/?",
                    path,
                )
            )
        elif host == "aclanthology.org":
            allowed = bool(re.fullmatch(r"/\d{4}\.[A-Za-z0-9_.-]+/?", path))
        elif host == "openaccess.thecvf.com":
            allowed = path.startswith(("/content_", "/content/"))
        elif host == "proceedings.mlr.press":
            allowed = bool(re.fullmatch(r"/v\d+/[A-Za-z0-9_./-]+", path))
        if allowed:
            # 丢弃查询参数/片段，避免将跟踪或任意跳转参数作为证据链接输出。
            return urlunsplit(("https", host, path, "", ""))
    except ValueError:
        pass
    return None


def model_configured(config: dict) -> bool:
    model = config.get("model")
    if not isinstance(model, dict):
        return False
    if not all(
        isinstance(model.get(key), str) and model[key].strip()
        for key in ("base_url", "api_key", "model")
    ):
        return False
    try:
        parts = urlsplit(model["base_url"])
        return bool(
            parts.hostname
            and not parts.username
            and not parts.password
            and not parts.query
            and not parts.fragment
            and (
                parts.scheme == "https"
                or (
                    parts.scheme == "http"
                    and parts.hostname in {"127.0.0.1", "localhost", "::1"}
                )
            )
        )
    except ValueError:
        return False


def strict_json(data: bytes | str) -> object:
    """拒绝重复键与非 JSON 数值，避免解释歧义。"""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("non-finite value")

    try:
        return json.loads(
            data, object_pairs_hook=unique, parse_constant=invalid_constant
        )
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ProviderError("提供商返回无效 JSON。") from None


def public_excerpt(text: str, public_query: str) -> tuple[str, int, int]:
    """公开关键词只在本地排序段落；返回连续原文窗口，便于核验引句。"""
    terms = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2}", public_query.lower())
    terms = {
        term.removesuffix("s") if term.isascii() and len(term) > 3 else term
        for term in terms
    }
    if not terms:
        terms = {"table", "ocr", "layout", "structure", "pdf"}
    paragraphs = list(re.finditer(r"(?:[^\n]|\n(?!\s*\n))+", text))
    if not paragraphs:
        return text[:MAX_PUBLIC_EXCERPT], 0, min(len(text), MAX_PUBLIC_EXCERPT)
    best = max(
        paragraphs,
        key=lambda match: sum(term in match.group().lower() for term in terms),
    )
    # 最相关段落及上下文都保持连续；不把不同位置拼成看似连续的原文。
    start = max(0, best.start() - 1200)
    end = min(len(text), start + MAX_PUBLIC_EXCERPT)
    start = max(0, end - MAX_PUBLIC_EXCERPT)
    return text[start:end], start, end


class HttpProviders:
    """有界请求，禁止跳转和环境代理；仅使用当前独立配置的显式代理。"""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        config_loader: Callable[[], dict] | None = None,
    ):
        self.transport = transport
        self.config_loader = config_loader or dict

    def _proxy_for_request(self, url: str) -> str | None:
        """每次读取专用配置；loopback 模型地址始终直连，不读取环境代理。"""
        config = self.config_loader()
        if not isinstance(config, dict) or not isinstance(
            config.get("network", {}), dict
        ):
            raise ProviderConfigurationError(
                "独立网络代理配置无效，请检查 network.proxy_url。"
            )
        proxy_url = config.get("network", {}).get("proxy_url", "")
        if not isinstance(proxy_url, str):
            raise ProviderConfigurationError(
                "独立网络代理配置无效，请检查 network.proxy_url。"
            )
        if proxy_url:
            try:
                parts = urlsplit(proxy_url)
                if (
                    len(proxy_url) > 2048
                    or any(char.isspace() for char in proxy_url)
                    or parts.scheme not in {"http", "https"}
                    or not parts.hostname
                    or parts.query
                    or parts.fragment
                    or parts.path not in {"", "/"}
                    or (parts.port is not None and parts.port < 1)
                ):
                    raise ValueError
            except ValueError:
                raise ProviderConfigurationError(
                    "独立网络代理配置无效，请检查 network.proxy_url。"
                ) from None
        if urlsplit(url).hostname in {"127.0.0.1", "localhost", "::1"}:
            return None
        return proxy_url or None

    async def _request(
        self,
        method: str,
        url: str,
        authorize: Authorize,
        *,
        headers=None,
        payload=None,
        timeout=30,
    ) -> bytes:
        authorize()
        try:
            async with asyncio.timeout(timeout):
                async with (
                    httpx.AsyncClient(
                        transport=self.transport,
                        proxy=self._proxy_for_request(url),
                        timeout=timeout,
                        follow_redirects=False,
                        trust_env=False,
                    ) as client,
                    client.stream(
                        method, url, headers=headers, json=payload
                    ) as response,
                ):
                    if response.status_code < 200 or response.status_code >= 300:
                        raise ProviderError(
                            f"提供商 HTTP 请求失败（状态 {response.status_code}）。"
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise ProviderError("提供商响应超过大小上限。")
        except (httpx.HTTPError, TimeoutError):
            raise ProviderError("提供商连接失败或超时，请检查配置后重试。") from None
        finally:
            # 撤权优先于任何旧响应；取消任务仍由 asyncio 传播。
            authorize()
        return bytes(body)

    async def retrieve_zhipu(
        self,
        api_key: str,
        knowledge_ids: list[str],
        query: str,
        authorize: Authorize,
        top_k: int = 6,
    ) -> list[dict]:
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise ResearchError("智谱检索问题必须为 1 至 1000 字符。")
        if not knowledge_ids or any(
            not isinstance(item, str) or not item.strip() for item in knowledge_ids
        ):
            raise ResearchError("必须明确选择智谱知识库。")
        if (
            isinstance(top_k, bool)
            or not isinstance(top_k, int)
            or not 1 <= top_k <= 20
        ):
            raise ResearchError("智谱 top_k 必须为 1 至 20。")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProviderError("未配置独立的智谱知识库密钥。")
        data = strict_json(
            await self._request(
                "POST",
                ZHIPU_RETRIEVE_URL,
                authorize,
                headers={"Authorization": f"Bearer {api_key}"},
                payload={
                    "query": query,
                    "knowledge_ids": knowledge_ids,
                    "top_k": top_k,
                },
            )
        )
        if (
            not isinstance(data, dict)
            or type(data.get("code")) is not int
            or data["code"] != 200
            or not isinstance(data.get("data"), list)
        ):
            raise ProviderError("智谱知识库返回失败状态或不兼容的响应结构。")
        rows = data["data"]
        if len(rows) > 100:
            raise ProviderError("智谱返回片段数量超限。")
        sources = []
        for row in rows:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("text"), str)
                or not row["text"].strip()
                or len(row["text"]) > 100000
            ):
                raise ProviderError("智谱返回了无效的文档片段。")
            metadata = row.get("metadata")
            if not isinstance(metadata, dict):
                raise ProviderError("智谱文档片段缺少来源信息。")
            kb_id = metadata.get("knowledge_id")
            if kb_id not in knowledge_ids:
                raise PermissionError("智谱返回了所选知识库范围之外的内容。")
            if any(
                not isinstance(metadata.get(key), str) or not metadata[key]
                for key in ("_id", "doc_id", "doc_name")
            ):
                raise ProviderError("智谱文档片段缺少可追溯标识。")
            score = row.get("score")
            if type(score) not in (int, float) or not math.isfinite(score):
                raise ProviderError("智谱文档片段的相关性分数无效。")
            sources.append(
                {
                    "id": metadata["_id"],
                    "library_id": f"zhipu:{kb_id}",
                    "document_id": metadata["doc_id"],
                    "title": metadata["doc_name"],
                    "text": row["text"],
                    "score": score,
                    "source_url": safe_source_url(metadata.get("doc_url")),
                    "page": None,
                    "origin": "zhipu",
                }
            )
        return sources

    async def public_sources(
        self, public_query: str, authorize: Authorize
    ) -> tuple[list[dict], list[str]]:
        """只取三个固定官方 README；关键词不拼入 URL，更不发送私有资料。"""
        if not isinstance(public_query, str) or len(public_query) > 1000:
            raise ResearchError("公开关键词过长。")
        sources, warnings = [], []
        for title, url in PUBLIC_DOCUMENTS:
            try:
                body = await self._request("GET", url, authorize)
                text = body.decode("utf-8")
                if not text.strip() or text.lstrip().lower().startswith(
                    ("<!doctype html", "<html")
                ):
                    raise ProviderError("官方文档响应不是有效文本。")
                excerpt, start, end = public_excerpt(text, public_query)
                sources.append(
                    {
                        "id": url,
                        "title": title,
                        "text": excerpt,
                        "source_url": url,
                        "excerpt_start": start,
                        "excerpt_end": end,
                        "page": None,
                        "origin": "public",
                        "fetched_at": datetime.now(UTC).isoformat(),
                    }
                )
            except ProviderConfigurationError:
                raise
            except (ProviderError, UnicodeError):
                warnings.append(f"{title} 获取失败，未作为本次证据。")
        return sources, warnings

    async def search_public(
        self, api_key: str, public_query: str, authorize: Authorize
    ) -> tuple[list[dict], list[str]]:
        """仅发送显式公开关键词；返回搜索摘要，不跟随或抓取结果链接。"""
        if (
            not isinstance(public_query, str)
            or not public_query.strip()
            or len(public_query) > 70
        ):
            raise ResearchError("联网搜索需要单独填写 1 至 70 字符的公开关键词。")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProviderError("未配置独立的智谱联网搜索密钥。")
        data = strict_json(
            await self._request(
                "POST",
                ZHIPU_WEB_SEARCH_URL,
                authorize,
                headers={"Authorization": f"Bearer {api_key}"},
                payload={
                    "search_query": public_query,
                    "search_engine": "search_std",
                    "search_intent": False,
                    "count": MAX_PUBLIC_SEARCH_RESULTS,
                    "content_size": "medium",
                    "search_recency_filter": "noLimit",
                },
            )
        )
        if (
            not isinstance(data, dict)
            or "error" in data
            or not isinstance(data.get("search_result"), list)
        ):
            raise ProviderError("智谱联网搜索返回失败状态或不兼容的响应结构。")
        rows = data["search_result"]
        if len(rows) > 50:
            raise ProviderError("联网搜索返回结果数量超限。")
        sources, seen = [], set()
        filtered = False
        truncated = len(rows) > MAX_PUBLIC_SEARCH_RESULTS
        fetched_at = datetime.now(UTC).isoformat()
        for row in rows:
            if (
                not isinstance(row, dict)
                or any(
                    not isinstance(row.get(key), str) or not row[key].strip()
                    for key in ("title", "content", "link")
                )
                or len(row["title"]) > 2000
                or len(row["content"]) > 100000
                or len(row["link"]) > 2000
            ):
                raise ProviderError("联网搜索返回了无效的来源片段。")
            url = primary_public_url(row["link"])
            if not url:
                filtered = True
                continue
            if url in seen:
                continue
            seen.add(url)
            if len(sources) >= MAX_PUBLIC_SEARCH_RESULTS:
                continue
            text = row["content"][:MAX_PUBLIC_EXCERPT]
            truncated = truncated or len(text) < len(row["content"])
            sources.append(
                {
                    "id": url,
                    "original_id": url,
                    "library_id": "public:web_search",
                    "document_id": url,
                    "title": row["title"],
                    "text": text,
                    "source_url": url,
                    "page": None,
                    "origin": "public",
                    "content_kind": "search_excerpt",
                    "fetched_at": fetched_at,
                }
            )
        warnings = [PUBLIC_SEARCH_SNIPPET_WARNING] if sources else []
        if filtered:
            warnings.append(
                "部分搜索结果不属于本模块允许的官方文档、代码或论文来源，已排除。"
            )
        if truncated:
            warnings.append("联网搜索结果超过片段或数量上限，仅保留有界摘要。")
        return sources, warnings

    async def model_report(
        self, config: dict, messages: list[dict], authorize: Authorize
    ) -> object:
        if not model_configured({"model": config}):
            raise ProviderError("独立模型配置不完整或地址不受支持。")
        payload = {
            "model": config["model"],
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "max_tokens": 10000,
            "stream": False,
        }
        if "reasoning_effort" in config:
            reasoning_effort = config["reasoning_effort"]
            if not isinstance(reasoning_effort, str) or reasoning_effort not in {
                "low",
                "high",
                "max",
            }:
                raise ProviderConfigurationError(
                    "独立模型思考强度配置无效，reasoning_effort 仅支持 low、high 或 max。"
                )
            payload["reasoning_effort"] = reasoning_effort
        body = strict_json(
            await self._request(
                "POST",
                config["base_url"].rstrip("/") + "/chat/completions",
                authorize,
                headers={"Authorization": f"Bearer {config['api_key']}"},
                payload=payload,
                timeout=120,
            )
        )
        try:
            if (
                not isinstance(body, dict)
                or not isinstance(body["choices"], list)
                or len(body["choices"]) != 1
            ):
                raise ValueError
            choice = body["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError
            content = choice["message"]["content"]
            if not isinstance(content, str) or len(content) > 120000:
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("模型没有返回完整的 JSON 报告。") from None
        return strict_json(content)
