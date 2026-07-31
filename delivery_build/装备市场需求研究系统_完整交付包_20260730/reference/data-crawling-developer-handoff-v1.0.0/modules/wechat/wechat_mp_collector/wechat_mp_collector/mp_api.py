from __future__ import annotations

import base64
import json
import random
import time
from dataclasses import dataclass
from typing import Any

import requests


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
]


class WechatApiError(RuntimeError):
    def __init__(self, message: str, ret: int | None = None):
        super().__init__(message)
        self.ret = ret


@dataclass
class WechatMpApi:
    session_data: dict[str, Any]
    timeout: tuple[int, int] = (10, 30)
    verify_tls: bool = True

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self.token = str(self.session_data.get("token", ""))
        self.cookie = str(self.session_data.get("cookie", ""))
        self.user_agent = str(self.session_data.get("user_agent") or random.choice(USER_AGENTS))
        if not self.token:
            raise WechatApiError("missing token; run auth first")
        if not self.cookie:
            raise WechatApiError("missing cookie; run auth first")

    def search_biz(self, keyword: str, *, limit: int = 10, offset: int = 0) -> dict[str, Any]:
        url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            "action": "search_biz",
            "begin": offset,
            "count": limit,
            "query": keyword,
            "token": self.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        return self._get_json(url, params=params, referer=url)

    def list_articles(
        self,
        fakeid: str,
        *,
        pages: int = 1,
        start_page: int = 0,
        delay_range: tuple[float, float] = (3.0, 8.0),
    ) -> list[dict[str, Any]]:
        url = "https://mp.weixin.qq.com/cgi-bin/appmsgpublish"
        articles: list[dict[str, Any]] = []
        for page_no in range(start_page, start_page + pages):
            if page_no > start_page:
                _sleep_between(delay_range)
            params = {
                "sub": "list",
                "sub_action": "list_ex",
                "begin": page_no * 5,
                "count": 5,
                "fakeid": fakeid,
                "token": self.token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            }
            payload = self._get_json(url, params=params, referer=url)
            articles.extend(parse_publish_page(payload, fakeid=fakeid, page_no=page_no))
        return articles

    def _get_json(self, url: str, *, params: dict[str, Any], referer: str) -> dict[str, Any]:
        response = self.session.get(
            url,
            params=params,
            headers=self._headers(referer=referer),
            timeout=self.timeout,
            verify=self.verify_tls,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise WechatApiError(f"response is not JSON from {url}") from exc

        base_resp = payload.get("base_resp") or {}
        ret = base_resp.get("ret", 0)
        if ret == 200013:
            raise WechatApiError("frequency control from WeChat; reduce pages or delay", ret=ret)
        if ret == 200003:
            raise WechatApiError("invalid session; run auth again", ret=ret)
        if ret not in (0, "0"):
            msg = base_resp.get("err_msg") or base_resp.get("errmsg") or "unknown WeChat API error"
            raise WechatApiError(f"{msg}; ret={ret}", ret=int(ret) if str(ret).isdigit() else None)
        return payload

    def _headers(self, *, referer: str) -> dict[str, str]:
        return {
            "Cookie": self.cookie,
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Referer": referer,
        }


def parse_publish_page(payload: dict[str, Any], *, fakeid: str, page_no: int) -> list[dict[str, Any]]:
    publish_page = payload.get("publish_page")
    if not publish_page:
        return []
    if isinstance(publish_page, str):
        publish_page = json.loads(publish_page)

    rows: list[dict[str, Any]] = []
    for publish_item in publish_page.get("publish_list", []):
        publish_info = publish_item.get("publish_info") or "{}"
        if isinstance(publish_info, str):
            try:
                publish_info = json.loads(publish_info)
            except json.JSONDecodeError:
                publish_info = {}

        app_messages = publish_info.get("appmsgex") or []
        for index, item in enumerate(app_messages):
            aid = str(item.get("aid") or item.get("appmsgid") or item.get("link") or "")
            article = {
                "aid": aid,
                "id": aid,
                "fakeid": fakeid,
                "mp_id": fakeid_to_mp_id(fakeid),
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "digest": item.get("digest", ""),
                "cover": item.get("cover", ""),
                "create_time": _first_int(item.get("create_time"), publish_item.get("create_time")),
                "update_time": _first_int(item.get("update_time"), publish_item.get("update_time")),
                "copyright_stat": _first_int(item.get("copyright_stat"), publish_info.get("copyright_stat")),
                "item_show_type": _first_int(item.get("item_show_type"), publish_info.get("item_show_type")),
                "is_deleted": bool(item.get("is_deleted", False)),
                "page_no": page_no,
                "item_index": index,
                "raw": item,
                "publish_info": publish_info,
            }
            rows.append(article)
    return rows


def fakeid_to_mp_id(fakeid: str) -> str:
    try:
        decoded = base64.b64decode(fakeid + "=" * (-len(fakeid) % 4)).decode("utf-8")
    except Exception:
        return ""
    return f"MP_WXS_{decoded}" if decoded else ""


def _first_int(*values: Any) -> int:
    for value in values:
        try:
            if value not in (None, ""):
                return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _sleep_between(delay_range: tuple[float, float]) -> None:
    low, high = delay_range
    if high <= 0:
        return
    if low < 0:
        low = 0
    if high < low:
        high = low
    time.sleep(random.uniform(low, high))

