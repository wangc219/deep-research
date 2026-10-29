"""AMiner REST 边界：短期 JWT、业务错误与论文证据规范化。"""

from __future__ import annotations

import hashlib
from datetime import UTC
from typing import Any
from urllib.parse import quote

import httpx
import jwt

from platform_core.utils.datetime_utils import format_utc_datetime, utc_now_naive

AMINER_BASE_URL = "https://datacenter.aminer.cn/gateway/open_platform/api"
ACADEMIC_TOOL_NAMES = frozenset({"academic_search", "academic_get_papers", "academic_get_references"})
ENDPOINTS = {
    "search": ("GET", "/paper/search/pro", 1, "search"),
    "title_search": ("GET", "/paper/search", 0, "free"),
    "info": ("POST", "/paper/info", 0, "free"),
    "detail": ("GET", "/paper/detail", 1, "detail"),
    "references": ("GET", "/paper/relation", 10, "reference"),
}


def aminer_credential_scope(config: dict[str, Any]) -> str:
    """用不可逆摘要隔离凭证变更前后的检索缓存。"""
    return hashlib.sha256(f"{config.get('user_id', '')}\0{config.get('api_key', '')}".encode()).hexdigest()


def aminer_authorization_token(credentials: dict[str, Any], *, issued_at: int | None = None) -> str:
    """复用控制台 Token，或用原始 Key 签发短期鉴权 Token。"""
    credential = credentials["api_key"].strip()
    if credential.lower().startswith("bearer "):
        credential = credential[7:].strip()
    if credential.startswith("eyJ") and credential.count(".") == 2:
        return credential
    now = issued_at if issued_at is not None else int(utc_now_naive().replace(tzinfo=UTC).timestamp())
    return jwt.encode(
        {"user_id": credentials["user_id"], "exp": now + 600, "timestamp": now},
        credential,
        algorithm="HS256",
        headers={"sign_type": "SIGN"},
    )


class AMinerError(Exception):
    """只暴露稳定错误语义，避免外部响应或凭证进入日志。"""

    def __init__(self, status: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class AMinerClient:
    """执行单次请求；重试及费用预占由上层服务拥有。"""

    def __init__(self, credentials: dict[str, Any], *, transport: httpx.AsyncBaseTransport | None = None):
        self.credentials = credentials
        self.transport = transport

    async def request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """将 HTTP 与 JSON 业务错误转为可降级状态。"""
        token = aminer_authorization_token(self.credentials)
        method, path, _cost, _kind = ENDPOINTS[endpoint]
        try:
            async with httpx.AsyncClient(timeout=10.0, transport=self.transport, follow_redirects=False) as client:
                response = await client.request(
                    method,
                    f"{AMINER_BASE_URL}{path}",
                    headers={"Authorization": token},
                    **({"json": payload} if method == "POST" else {"params": payload}),
                )
        except httpx.RequestError as exc:
            raise AMinerError("unavailable", "AMiner 网络暂不可用", retryable=True) from exc

        if response.status_code in {401, 403}:
            raise AMinerError("auth_failed", "AMiner 鉴权失败，请检查用户 ID、API Key 和接口权限")
        if response.status_code == 429:
            raise AMinerError("rate_limited", "AMiner 调用频率受限，请稍后再试")
        if response.status_code != 200 and response.status_code < 500:
            raise AMinerError("invalid_request", "AMiner 未接受当前检索参数")
        try:
            data = response.json()
        except ValueError as exc:
            if response.status_code >= 500:
                raise AMinerError("unavailable", "AMiner 服务暂不可用", retryable=True) from exc
            raise AMinerError("unavailable", "AMiner 返回了无效数据", retryable=True) from exc
        if not isinstance(data, dict):
            raise AMinerError("unavailable", "AMiner 返回了无效数据")
        code = str(data.get("code", ""))
        if code in {"40301", "40302", "40307", "40308"}:
            raise AMinerError("auth_failed", "AMiner 鉴权失败，请检查用户 ID、API Key 和接口权限")
        if code == "40306":
            raise AMinerError("rate_limited", "AMiner 调用频率受限，请稍后再试")
        if code == "50001":
            raise AMinerError("unavailable", "AMiner 服务暂不可用", retryable=True)
        if code == "40001":
            raise AMinerError("invalid_request", "AMiner 未接受当前检索参数")
        # 供应商会用 HTTP 500 承载鉴权/限流等业务错误，先保留上面的稳定语义。
        if response.status_code >= 500:
            raise AMinerError("unavailable", "AMiner 服务暂不可用", retryable=True)
        if data.get("success") is True and code == "200" and "data" in data and data["data"] is None:
            # 实际服务在无命中时返回 data:null，不应把空结果熔断成供应商故障。
            data["data"] = []
        if data.get("success") is not True or code != "200" or not isinstance(data.get("data"), list):
            raise AMinerError("unavailable", "AMiner 返回了无效数据")
        return data


def normalize_paper(item: dict[str, Any], *, retrieved_at: str | None = None) -> dict[str, Any]:
    """保留真实题录与摘要层级，不将搜索命中包装成全文证据。"""
    paper_id = str(item.get("id") or item.get("_id") or "")
    doi = str(item.get("doi") or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :].strip()
            break
    abstract = item.get("abstract") or item.get("abstract_zh") or ""
    abstract = abstract.strip() if isinstance(abstract, str) else ""
    partial = item.get("abstract_slice") or ""
    partial = partial.strip() if isinstance(partial, str) else ""
    content = abstract or partial
    authors = item.get("authors") or []
    authors = authors if isinstance(authors, list) else []
    author_names = [
        str(author.get("name") or author.get("name_zh") or "") for author in authors if isinstance(author, dict)
    ]
    if not author_names and item.get("first_author"):
        author_names = [str(item["first_author"])]
    venue = item.get("venue") or {}
    venue_name = venue.get("raw") or venue.get("raw_zh") if isinstance(venue, dict) else str(venue)
    return {
        "id": paper_id,
        "doi": doi,
        "title": item.get("title") or item.get("title_zh") or "未提供标题",
        "title_zh": item.get("title_zh"),
        "authors": author_names,
        "year": item.get("year"),
        "venue": venue_name or item.get("venue_name") or "",
        "url": (
            f"https://doi.org/{quote(doi, safe='/')}"
            if doi
            else f"https://www.aminer.cn/pub/{quote(paper_id, safe='')}"
            if paper_id
            else ""
        ),
        "content": content if isinstance(content, str) else "",
        "content_level": "abstract" if abstract else "partial_abstract" if partial else "metadata",
        "citation_bucket": item.get("n_citation_bucket"),
        "source": "aminer",
        "retrieved_at": retrieved_at or format_utc_datetime(utc_now_naive()),
    }


def deduplicate_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 DOI 与论文 ID 合并同一研究，保留更完整的证据。"""
    groups: list[tuple[dict[str, Any], set[str]]] = []
    levels = {"metadata": 0, "partial_abstract": 1, "abstract": 2}
    for paper in papers:
        keys = set()
        if paper["doi"]:
            keys.add(f"doi:{paper['doi'].lower()}")
        if paper["id"]:
            keys.add(f"id:{paper['id']}")
        matches = [index for index, (_, identities) in enumerate(groups) if keys & identities]
        if not matches:
            groups.append((dict(paper), keys))
            continue
        records = [groups[index][0] for index in matches] + [paper]
        best = max(records, key=lambda record: levels[record["content_level"]])
        combined = dict(best)
        matched_queries = list(
            dict.fromkeys(query for record in records for query in record.get("matched_queries", []))
        )
        if matched_queries:
            combined["matched_queries"] = matched_queries
        for field in ("doi", "id", "authors", "year", "venue", "title_zh", "citation_bucket"):
            if not combined.get(field):
                combined[field] = next((record[field] for record in records if record.get(field)), combined.get(field))
        if combined["title"] == "未提供标题":
            combined["title"] = next(
                (record["title"] for record in records if record["title"] != "未提供标题"), combined["title"]
            )
        if combined["doi"]:
            combined["url"] = f"https://doi.org/{quote(combined['doi'], safe='/')}"
        for index in matches:
            keys.update(groups[index][1])
        groups[matches[0]] = (combined, keys)
        for index in reversed(matches[1:]):
            groups.pop(index)
    return [paper for paper, _ in groups]
